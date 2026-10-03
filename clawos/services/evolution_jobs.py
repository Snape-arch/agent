"""Fenced, checkpointed experiment attempts and workspace-wide exposure ledger."""
from __future__ import annotations

import hashlib
import json
import time
import unicodedata
import uuid


class ExperimentLeaseLost(ValueError):
    pass


def input_key(case):
    # Detect normalized lexical duplicates, not semantic equivalence. IDs,
    # labels, target keys and cohort names cannot disguise the same input.
    text = ' '.join(unicodedata.normalize('NFKC', case['query']).casefold().split())
    route = case.get('route')
    if route:
        route = {key: sorted(set(value)) for key, value in route.items()}
    value = json.dumps({'query': text, 'route': route}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(value.encode()).hexdigest()


class EvolutionJobStore:
    LEASE_SECONDS = 90

    def __init__(self, store):
        self.store = store

    def summary(self, experiment_id, *, conn):
        attempts = [dict(row) for row in conn.execute(
            'SELECT * FROM evolution_attempts WHERE experiment_id=? ORDER BY started_at,token', (experiment_id,))]
        count = conn.execute('SELECT count(*) FROM evolution_case_results WHERE experiment_id=?', (experiment_id,)).fetchone()[0]
        last = attempts[-1] if attempts else None
        return {'attempts': attempts, 'checkpoint_count': count,
                'recoverable': bool(last and last['status'] == 'running' and last['lease_until'] <= time.time()),
                'lease_seconds': self.LEASE_SECONDS,
                'scope': 'saved function outcomes; paused or expired time is not successful load'}

    def check_exposures(self, definition, experiment_id=None, *, reserve=False, conn=None):
        if conn is None:
            with self.store.transaction() as active:
                return self.check_exposures(definition, experiment_id, reserve=reserve, conn=active)
        # Backfill pre-ledger attempts conservatively, including failures which
        # may have exposed labels. Never erase exposures on pause/cancel/failure.
        for row in conn.execute("SELECT id,definition FROM evolution_experiments WHERE status!='frozen'"):
            previous = json.loads(row['definition'])
            conn.executemany('INSERT OR IGNORE INTO evolution_exposures VALUES (?,?,?)',
                [(input_key(case), row['id'], case['split']) for case in previous['cases']])
        for case in definition['cases']:
            key = input_key(case)
            conflict = conn.execute('SELECT split FROM evolution_exposures WHERE input_key=? AND experiment_id!=?',
                                    (key, experiment_id or -1)).fetchall()
            if any(row['split'] == 'holdout' or case['split'] == 'holdout' for row in conflict):
                raise ValueError('holdout exposure reused across experiments; supply fresh independent task inputs')
        if reserve:
            conn.executemany('INSERT OR IGNORE INTO evolution_exposures VALUES (?,?,?)',
                [(input_key(case), experiment_id, case['split']) for case in definition['cases']])

    def claim(self, experiment_id):
        now = time.time()
        with self.store.transaction() as conn:
            experiment = self.store.get_evolution_experiment(experiment_id)
            if not experiment:
                raise ValueError('experiment not found')
            status = experiment['status']
            if status not in {'frozen', 'paused', 'running'}:
                raise ValueError('experiment already claimed; completed or terminal evidence is immutable')
            if status == 'running':
                active = conn.execute("SELECT * FROM evolution_attempts WHERE experiment_id=? AND status='running'",
                                      (experiment_id,)).fetchone()
                if active and active['lease_until'] > now:
                    raise ValueError('experiment already claimed by a live lease')
                conn.execute("UPDATE evolution_attempts SET status='abandoned',finished_at=?,reason='lease expired; explicit recovery' WHERE experiment_id=? AND status='running'",
                             (now, experiment_id))
            self.check_exposures(experiment['definition'], experiment_id, reserve=True, conn=conn)
            token = uuid.uuid4().hex
            conn.execute("INSERT INTO evolution_attempts(token,experiment_id,status,lease_until,started_at) VALUES (?,?,'running',?,?)",
                         (token, experiment_id, now + self.LEASE_SECONDS, now))
            conn.execute("UPDATE evolution_experiments SET status='running' WHERE id=?", (experiment_id,))
            result = self.store.get_evolution_experiment(experiment_id)
            result['attempt_token'] = token
            return result

    def _fence(self, conn, experiment_id, token):
        active = conn.execute("SELECT a.lease_until FROM evolution_attempts a JOIN evolution_experiments e ON e.id=a.experiment_id WHERE a.token=? AND a.experiment_id=? AND a.status='running' AND e.status='running'",
                              (token, experiment_id)).fetchone()
        if not active or active['lease_until'] <= time.time():
            raise ExperimentLeaseLost('experiment paused, cancelled or lease lost; old worker cannot write')

    def heartbeat(self, experiment_id, token):
        with self.store.transaction() as conn:
            self._fence(conn, experiment_id, token)
            conn.execute('UPDATE evolution_attempts SET lease_until=? WHERE token=?', (time.time() + self.LEASE_SECONDS, token))

    def outcomes(self, experiment_id):
        from services.evolution_experiments import digest
        with self.store._conn() as conn:
            rows = conn.execute('SELECT * FROM evolution_case_results WHERE experiment_id=?', (experiment_id,)).fetchall()
        result = {}
        for row in rows:
            outcome = json.loads(row['outcome'])
            if digest(outcome) != row['outcome_digest']:
                raise ValueError('saved checkpoint digest mismatch; cannot reuse evidence')
            result[(row['case_id'], row['candidate_id'])] = outcome
        return result

    def save(self, experiment_id, token, case_id, candidate_id, outcome):
        from services.evolution_experiments import digest
        with self.store.transaction() as conn:
            self._fence(conn, experiment_id, token)
            conn.execute('INSERT INTO evolution_case_results VALUES (?,?,?,?,?,?)',
                         (experiment_id, case_id, candidate_id, json.dumps(outcome, ensure_ascii=False, allow_nan=False), digest(outcome), token))
            conn.execute('UPDATE evolution_attempts SET lease_until=? WHERE token=?', (time.time() + self.LEASE_SECONDS, token))

    def control(self, experiment_id, action):
        if action not in {'pause', 'cancel'}:
            raise ValueError('action must be pause or cancel')
        status = 'paused' if action == 'pause' else 'cancelled'
        with self.store.transaction() as conn:
            row = conn.execute('SELECT status FROM evolution_experiments WHERE id=?', (experiment_id,)).fetchone()
            if not row or row['status'] not in {'frozen', 'running', 'paused'}:
                raise ValueError('only a pending experiment can be paused or cancelled')
            conn.execute('UPDATE evolution_experiments SET status=? WHERE id=?', (status, experiment_id))
            conn.execute("UPDATE evolution_attempts SET status=?,finished_at=?,reason=? WHERE experiment_id=? AND status='running'",
                         (status, time.time(), 'owner requested ' + action, experiment_id))
            return self.store.get_evolution_experiment(experiment_id)

    def finish(self, experiment_id, token, report, *, failed=False):
        with self.store.transaction() as conn:
            self._fence(conn, experiment_id, token)
            status = 'failed' if failed else 'completed'
            conn.execute('UPDATE evolution_experiments SET status=?,report=? WHERE id=?',
                         (status, json.dumps(report, ensure_ascii=False, allow_nan=False), experiment_id))
            conn.execute('UPDATE evolution_attempts SET status=?,finished_at=? WHERE token=?', (status, time.time(), token))
            return self.store.get_evolution_experiment(experiment_id)
