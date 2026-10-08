"""Replayed, immutable handoff packets for passed coding collaboration runs.

Approval acknowledges one exact packet; it does not write, commit, or push the
source checkout. The source may be dirty, so exported patches use its captured
baseline, never a claim that the entire task branch is safe to merge.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from .coding_workflow_service import CodingWorkflowService
from .file_transactions import _file_lock, write_text
from .runtime_records import now_iso
from .coding_contracts import CodingContracts


class CollaborationDelivery:
    def __init__(self, collaboration):
        self.service = collaboration

    def verify_run(self, state):
        svc = self.service
        if (state['status'] != 'passed' or state['integration'].get('status') != 'passed'
                or state['review'].get('approved') is not True or state['review'].get('risks')
                or not state['integration'].get('tests')
                or any(t.get('exit_code') != 0 for t in state['integration']['tests'])):
            raise ValueError('only a passed, tested and reviewed collaboration can be delivered')
        svc.verify_receipts(state)
        requirements = state['request'].get('requirements', [])
        if requirements:
            expected = CodingContracts.results(requirements, state['integration']['tests'], svc.digest,
                repo=svc.owned_workspace(state, state['integration']['workspace']))
            if (state.get('requirement_results') != expected or not all(r['passed'] for r in expected)
                    or state.get('requirement_owners') != CodingContracts.bind_plan(requirements, state['nodes'])):
                raise ValueError('caller requirement verification or task ownership changed')
        base = svc.owned_workspace(state, state['baseline'])
        if (svc.git(base, 'rev-parse', 'HEAD').stdout.strip() != state['baseline']['baseline_commit']
                or svc.git(base, 'status', '--porcelain').stdout.strip()):
            raise ValueError('captured baseline changed')
        for item in state['results'].values():
            if item['status'] == 'passed':
                svc.verify_commit(state, item)
        svc.verify_commit(state, state['integration'])
        if svc.source_stamp(state['request']['repo'], state['request']['paths']) != state['source_stamp']:
            raise ValueError('source checkout changed; delivery requires a new run')
        repo = svc.owned_workspace(state, state['integration']['workspace'])
        baseline = state['baseline']['baseline_commit']
        diff = svc.git(repo, 'diff', '--binary', baseline, state['integration']['commit']).stdout
        if svc.digest(diff) != state['integration']['diff_digest']:
            raise ValueError('integrated difference changed')
        paths = svc.git(repo, 'diff', '--name-only', '-z', baseline, 'HEAD').stdout.split('\0')
        paths = sorted(p for p in paths if p)
        if not paths or not set(paths) <= set(state['request']['paths']):
            raise ValueError('delivery difference is empty or exceeds authorized paths')
        for path in paths:
            svc.safe_path(path)
            # No deletes, renames, executable-mode changes, links or submodules.
            before = svc.git(repo, 'ls-tree', baseline, '--', path).stdout
            after = svc.git(repo, 'ls-tree', 'HEAD', '--', path).stdout
            if not after.startswith('100644 blob ') or (before and not before.startswith('100644 blob ')):
                raise ValueError('delivery requires ordinary text files without mode changes')
        svc.read_files(repo, paths)
        return diff, paths

    def verify_packet(self, state):
        svc = self.service
        diff, paths = self.verify_run(state)
        record = state.get('delivery') or {}
        if record.get('status') not in {'ready', 'approved'}:
            raise ValueError('no verified delivery packet is ready')
        folder = svc.root / state['run_id'] / 'deliveries' / record['id']
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        patch = (folder / 'changes.patch').read_bytes()
        if (svc.digest(manifest) != record['manifest_digest']
                or hashlib.sha256(patch).hexdigest() != manifest['patch_sha256']
                or patch != diff.encode('utf-8') or manifest['changed_paths'] != paths
                or manifest['run_id'] != state['run_id']
                or manifest['integrated_commit'] != state['integration']['commit']
                or manifest['baseline_commit'] != state['baseline']['baseline_commit']
                or manifest['test_commands'] != state['request']['test_commands']
                or manifest['evidence_digest'] != svc.digest({'nodes':state['nodes'], 'results':state['results'],
                       'receipts':[e for e in state['events'] if e['event']=='model_receipt']})):
            raise ValueError('delivery packet evidence changed')
        requirements = state['request'].get('requirements', [])
        if requirements and (manifest.get('requirements') != requirements
                or manifest.get('requirements_digest') != svc.digest(requirements)
                or manifest.get('requirement_results') != CodingContracts.results(requirements, manifest['tests'], svc.digest,
                    repo=svc.owned_workspace(state, manifest['replay']['workspace']))):
            raise ValueError('delivery requirement bindings changed')
        if state.get('context_policy') and (manifest.get('context_policy') != state['context_policy']
                or manifest.get('contexts') != state.get('contexts', {})):
            raise ValueError('delivery execution context evidence changed')
        svc.verify_commit(state, manifest['replay'])
        repo = svc.owned_workspace(state, manifest['replay']['workspace'])
        replay_diff = svc.git(repo, 'diff', '--binary', manifest['baseline_commit'], 'HEAD').stdout
        if replay_diff != diff or not manifest['tests'] or any(t['exit_code'] != 0 for t in manifest['tests']):
            raise ValueError('replayed delivery does not match the accepted difference')
        if record.get('status') == 'approved':
            approval = json.loads((folder / 'approval.json').read_text(encoding='utf-8'))
            if svc.digest(approval) != record.get('approval_digest') or approval['manifest_digest'] != record['manifest_digest']:
                raise ValueError('delivery approval evidence changed')
        return manifest, diff

    def inspect(self, run_id):
        svc = self.service
        state = svc.load(run_id)
        with _file_lock(svc.root / run_id / 'coordinator', timeout=0):
            state = svc.load(run_id)
            manifest, diff = self.verify_packet(state)
            return self.public(state, manifest) | {'diff': diff}

    def public(self, state, manifest):
        record = state['delivery']
        folder = self.service.root / state['run_id'] / 'deliveries' / record['id']
        return dict(status=record['status'], run_id=state['run_id'], delivery_id=record['id'],
                    manifest_digest=record['manifest_digest'], manifest=manifest,
                    patch_path=str(folder / 'changes.patch'), manifest_path=str(folder / 'manifest.json'),
                    source_mutated=False, source_application_required=True,
                    human_release_required=record['status'] != 'approved',
                    approval=record.get('approval'))

    async def prepare(self, run_id, *, confirmed=False):
        if confirmed is not True:
            raise PermissionError('confirmed=true is required for isolated delivery replay and tests')
        svc = self.service
        state = svc.load(run_id)
        with _file_lock(svc.root / run_id / 'coordinator', timeout=0):
            state = svc.load(run_id)
            previous_started = state.pop('delivery_active_since', None)
            if previous_started is not None:
                state['ledger']['elapsed_seconds'] += max(0, time.time() - previous_started)
                for item in state.get('delivery_attempts', []):
                    item.pop('active_since', None)
                    if item['status'] == 'preparing':
                        item.update(status='interrupted', error='previous delivery coordinator exited', completed_at=now_iso())
                    if state['delivery']['id'] == item['id']:
                        state['delivery'] = dict(item)
                svc.event(state, 'delivery_coordinator_recovered')
            # Idempotence never bypasses re-verification.
            if (state.get('delivery') or {}).get('status') in {'ready', 'approved'}:
                manifest, _ = await asyncio.to_thread(self.verify_packet, state)
                svc.persist(state)
                return self.public(state, manifest)
            diff, paths = await asyncio.to_thread(self.verify_run, state)
            history = state.setdefault('delivery_attempts', [])
            if len(history) >= 3:
                raise ValueError('delivery replay attempt budget exhausted')
            remaining = state['request']['limits']['max_wall_seconds'] - state['ledger']['elapsed_seconds']
            if remaining <= 0:
                svc.save(state)
                raise TimeoutError('cumulative collaboration wall budget exhausted')
            record = dict(id='delivery-' + uuid.uuid4().hex, status='preparing', started_at=now_iso())
            history.append(record)
            state['delivery'] = record
            record['active_since'] = state['delivery_active_since'] = time.time()
            started = time.monotonic()
            svc.event(state, 'delivery_replay_started', delivery_id=record['id'])
            tasks = []
            try:
                # Shield owned native operations; don't release the coordinator
                # lock while a cancelled thread still writes/tests its worktree.
                async def native(fn, *args, **kwargs):
                    task = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
                    tasks.append(task)
                    return await asyncio.shield(task)
                meta = await native(svc.workspaces.create_task, state['baseline']['workspace'],
                                    svc.root / run_id / 'workspaces', record['id'], confirmed=True)
                record['workspace'] = meta
                svc.save(state)
                repo = svc.owned_workspace(state, meta)
                await native(self.apply_patch, repo, diff)
                commit = svc.git(repo, 'rev-parse', 'HEAD').stdout.strip()
                replay = dict(commit=commit, workspace=meta,
                              patch_digest=svc.digest(svc.git(repo, 'show', '--format=', '--binary', commit).stdout))
                before = await native(svc.source_stamp, repo, state['request']['paths'])
                tests = []
                for command in state['request']['test_commands']:
                    test_timeout = min(state['request']['limits']['timeout_seconds'],
                                       remaining - (time.monotonic() - started))
                    if test_timeout <= 0:
                        raise TimeoutError('cumulative collaboration wall budget exhausted')
                    test = await native(CodingWorkflowService._run_command, repo, command,
                                        test_timeout)
                    tests.append(test)
                    record['tests'] = tests
                    svc.event(state, 'delivery_test', delivery_id=record['id'], exit_code=test['exit_code'])
                if any(t['exit_code'] != 0 for t in tests):
                    raise ValueError('fresh delivery tests failed; original run evidence is retained')
                if before != await native(svc.source_stamp, repo, state['request']['paths']):
                    raise ValueError('delivery test mutated replayed source or index')
                await native(self.verify_run, state)
                if time.monotonic() - started > remaining:
                    raise TimeoutError('cumulative collaboration wall budget exhausted')
                manifest = dict(schema='clawos.collaboration-delivery.v1', run_id=run_id,
                    delivery_id=record['id'], objective=state['request']['objective'],
                    baseline_commit=state['baseline']['baseline_commit'],
                    source_head=state['baseline']['source_head'], source_stamp=state['source_stamp'],
                    includes_caller_dirty_baseline=state['baseline']['source_dirty'],
                    patch_base='captured baseline, including caller dirty state', changed_paths=paths,
                    patch_sha256=hashlib.sha256(diff.encode('utf-8')).hexdigest(),
                    integrated_commit=state['integration']['commit'], replay=replay,
                    test_commands=state['request']['test_commands'], tests=tests, review=state['review'],
                    requirements=state['request'].get('requirements', []),
                    requirements_digest=svc.digest(state['request'].get('requirements', [])),
                    requirement_results=CodingContracts.results(state['request'].get('requirements', []), tests, svc.digest, repo=repo),
                    context_policy=state.get('context_policy'), contexts=state.get('contexts', {}),
                    evidence_digest=svc.digest({'nodes':state['nodes'], 'results':state['results'],
                                                'receipts':[e for e in state['events'] if e['event']=='model_receipt']}),
                    created_at=now_iso(), source_mutated=False, remote_mutation=False,
                    scope='single-host replayed task patch; no model-quality or strict-sandbox claim')
                folder = svc.root / run_id / 'deliveries' / record['id']
                write_text(folder / 'changes.patch', diff, create_only=True)
                write_text(folder / 'manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2), create_only=True)
                record.update(status='ready', manifest_digest=svc.digest(manifest), completed_at=now_iso())
                svc.event(state, 'delivery_ready', delivery_id=record['id'], manifest_digest=record['manifest_digest'])
                return self.public(state, manifest)
            except BaseException as exc:
                drain = asyncio.gather(*tasks, return_exceptions=True)
                while not drain.done():
                    try:
                        await asyncio.shield(drain)
                    except asyncio.CancelledError:
                        continue
                record.update(status='interrupted' if isinstance(exc, asyncio.CancelledError) else 'failed',
                              error=f'{type(exc).__name__}: {exc}', completed_at=now_iso())
                svc.event(state, 'delivery_failed', delivery_id=record['id'], error=record['error'])
                raise
            finally:
                state.pop('delivery_active_since', None)
                record.pop('active_since', None)
                state['ledger']['elapsed_seconds'] += round(time.monotonic() - started, 3)
                svc.save(state)
                svc.persist(state)

    def approve(self, run_id, *, manifest_digest, actor, confirmed=False):
        if confirmed is not True:
            raise PermissionError('confirmed=true is required to acknowledge the exact delivery packet')
        svc = self.service
        state = svc.load(run_id)
        with _file_lock(svc.root / run_id / 'coordinator', timeout=0):
            state = svc.load(run_id)
            if actor != state['request']['actor']:
                raise PermissionError('delivery actor must match the frozen run owner')
            manifest, _ = self.verify_packet(state)
            record = state['delivery']
            if not isinstance(manifest_digest, str) or manifest_digest != record['manifest_digest']:
                raise ValueError('exact reviewed manifest_digest is required')
            if record['status'] == 'approved':
                svc.persist(state)
                return self.public(state, manifest)
            approval = dict(run_id=run_id, delivery_id=record['id'], actor=actor,
                            manifest_digest=manifest_digest, approved_at=now_iso(),
                            meaning='exact packet acknowledged; source application is a separate action')
            path = svc.root / run_id / 'deliveries' / record['id'] / 'approval.json'
            if path.exists():
                # A crash after the immutable receipt but before checkpoint must
                # not manufacture a different approval or overwrite the receipt.
                previous = json.loads(path.read_text(encoding='utf-8'))
                if any(previous.get(k) != approval[k] for k in ('run_id','delivery_id','actor','manifest_digest','meaning')):
                    raise ValueError('existing approval does not match this packet')
                approval = previous
            else:
                write_text(path, json.dumps(approval, ensure_ascii=False, indent=2), create_only=True)
            record.update(status='approved', approval=approval, approval_digest=svc.digest(approval))
            svc.event(state, 'delivery_approved', delivery_id=record['id'], manifest_digest=manifest_digest)
            svc.persist(state)
            return self.public(state, manifest)

    def apply_patch(self, repo, diff):
        for options in (['--check'], []):
            result = subprocess.run(['git', '-c', 'core.hooksPath=' + os.devnull, 'apply',
                                     '--index', '--whitespace=nowarn', *options, '-'], cwd=repo,
                                    input=diff.encode('utf-8'), capture_output=True, timeout=60)
            if result.returncode:
                raise ValueError('delivery patch replay failed: ' + result.stderr.decode('utf-8',errors='replace')[-1000:])
        self.service.git(repo, '-c', 'user.name=ClawOS Delivery', '-c',
                         'user.email=delivery@clawos.local', 'commit', '-m', 'collaboration: replayed delivery')
