"""Reserve coding holdouts before execution, even if the first attempt fails."""

import json

from .coding_comparison_service import digest


def tree_scope(case):
    return {digest(['tree-path', case['tracked_tree'], path.casefold()]) for path in case['paths']}


def scope_keys(runner, case):
    runner.check_case(case)
    tree = runner.svc.git(case['repo'], '--literal-pathspecs', 'ls-tree', '-lz', case['source_head'], '--', *case['paths']).stdout
    # Match base blobs across copies, renames, unrelated
    # commits and reworded objectives. Do not store source text in the ledger.
    keys = tree_scope(case)
    for entry in tree.split('\0'):
        if entry:
            _, kind, blob, size = entry.split('\t', 1)[0].split()
            if kind == 'blob' and int(size) > 0:
                keys.add(digest(['git-blob', blob]))
    return sorted(keys)


def bound_plan(evidence, folder, expected_digest):
    path = evidence.path('plan.json', base=evidence.path(folder))
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('prior coding plan exceeds read limit')
    plan = json.loads(path.read_text(encoding='utf-8'))
    if (plan.get('plan_digest') != expected_digest or
            digest({k: v for k, v in plan.items() if k != 'plan_digest'}) != expected_digest):
        raise ValueError('prior coding plan changed')
    return plan


def reject_held_out_import(conn, evidence, folder, plan_digest):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='coding_task_exposures' AND type='table'").fetchone():
        return
    plan = bound_plan(evidence, folder, plan_digest)
    for case in plan['cases']:
        keys = sorted(tree_scope(case))
        predicates = ','.join('?' for _ in keys)
        if conn.execute(f"SELECT 1 FROM coding_task_exposures WHERE campaign<>'' AND (task_group=? OR scope_key IN ({predicates})) LIMIT 1",
                        (case['task_group_digest'], *keys)).fetchone():
            raise ValueError('import overlaps reserved coding holdout')


class CodingTaskExposure:
    def __init__(self, store, evidence):
        self.store = store
        self.evidence = evidence
        with store.transaction() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS coding_task_exposures (
                scope_key TEXT PRIMARY KEY, campaign TEXT NOT NULL, task_group TEXT NOT NULL
            )''')

    def _check_legacy(self, conn, claims):
        """Reject previously recorded tasks, including pre-ledger frozen trees."""
        keys = {key for claim in claims for key in claim['keys']}
        groups = {claim['task_group'] for claim in claims}
        for row in conn.execute('SELECT folder,payload,payload_digest FROM coding_evidence'):
            payload = json.loads(row['payload'])
            if digest(payload) != row['payload_digest']:
                raise ValueError('prior coding evidence changed')
            plan = bound_plan(self.evidence, row['folder'], payload['plan_digest'])
            if any(case['task_group_digest'] in groups or tree_scope(case) & keys for case in plan['cases']):
                raise ValueError('coding holdout overlaps previously observed evidence')

    def reserve(self, runner, cases, campaign=''):
        claims = [dict(task_group=case['task_group_digest'], keys=scope_keys(runner, case)) for case in cases]
        keys = [key for claim in claims for key in claim['keys']]
        if campaign and len(keys) != len(set(keys)):
            raise ValueError('coding holdout scopes overlap within the frozen batch')
        new_claims = []
        with self.store.transaction() as conn:
            for claim in claims:
                group = claim['task_group']
                for key in claim['keys']:
                    old = conn.execute('SELECT campaign,task_group FROM coding_task_exposures WHERE scope_key=?', (key,)).fetchone()
                    if old:
                        if old['campaign'] != campaign or (campaign and old['task_group'] != group):
                            raise ValueError('coding task scope already exposed in another task or campaign')
                    else:
                        new_claims.append(claim)
                        conn.execute('INSERT INTO coding_task_exposures VALUES (?,?,?)', (key, campaign, group))
            if campaign and new_claims:
                # The reservation and checks share a write transaction. A
                # concurrent development run cannot race a holdout claim.
                unique = {claim['task_group']: claim for claim in new_claims}
                self._check_legacy(conn, unique.values())
        return claims

    def verify(self, claims, cases, campaign):
        groups = [case['task_group_digest'] for case in cases]
        if not isinstance(claims, list) or [c['task_group'] for c in claims] != groups:
            raise ValueError('coding holdout reservation does not bind frozen tasks')
        keys_seen = set()
        with self.store._conn() as conn:
            for claim, case in zip(claims, cases):
                keys = set(claim['keys'])
                if not tree_scope(case) <= keys or keys_seen & keys:
                    raise ValueError('coding holdout scope overlaps or is incomplete')
                keys_seen.update(keys)
                for key in keys:
                    row = conn.execute('SELECT campaign,task_group FROM coding_task_exposures WHERE scope_key=?', (key,)).fetchone()
                    if row is None or tuple(row) != (campaign, claim['task_group']):
                        raise ValueError('coding holdout reservation missing or changed')
