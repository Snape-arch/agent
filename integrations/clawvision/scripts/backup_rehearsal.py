"""Timed restore into a fresh target, with row/object digests and API evidence."""
from __future__ import annotations

import argparse
import json
import hashlib
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from contextlib import closing

from acceptance_support import ROOT, authenticate, local_api, request, write_report
from disposable_compose import DisposableCompose


def seed(url: str, token: str) -> dict:
    run = request(url, '/api/runs', {'name': 'backup-rehearsal', 'params': {'seed': 7}}, token)['data']
    request(url, f"/api/runs/{run['id']}/batch", {'metrics': [{'eventId': 'backup-metric', 'step': 1, 'accuracy': .75}],
            'events': [{'eventId': 'backup-event', 'message': 'backup-seed', 'level': 'info'}]}, token)
    request(url, f"/api/runs/{run['id']}/artifacts", {'name': 'backup-proof', 'type': 'json', 'content': {'proof': [1, 2, 3]}}, token)
    request(url, f"/api/runs/{run['id']}/finish", {'message': 'backup ready'}, token)
    request(url, '/api/datasets', {'name': 'backup-rehearsal', 'format': 'json', 'content': [{'value': 1}, {'value': 2}]}, token)
    return request(url, f"/api/runs/{run['id']}", token=token)['data']


def local_manifest(root: Path) -> dict:
    env = {**os.environ, 'DATABASE_URL': '', 'ARTIFACT_STORE': 'local', 'CLAWVISION_DATA_DIR': str(root),
           'CLAWVISION_OBJECT_DIR': str(root / 'objects'), 'PYTHONPATH': str(ROOT / 'backend')}
    result = subprocess.run([sys.executable, 'scripts/backup_manifest.py'], cwd=ROOT, env=env,
                            check=True, capture_output=True, text=True, timeout=60)
    return json.loads(result.stdout)


def assess(before: dict, after: dict, seconds: float, limit: float) -> dict:
    nonempty = before.get('tables', {}).get('runs', {}).get('rows', 0) > 0 and bool(before.get('objects'))
    return {'tableCountsAndDigestsMatch': before.get('tables') == after.get('tables'),
            'objectCountsAndDigestsMatch': before.get('objects') == after.get('objects'), 'nonemptyEvidence': nonempty,
            'tables': len(before.get('tables', {})), 'objects': len(before.get('objects', {})),
            'restoreSeconds': round(seconds, 3), 'maxRestoreSeconds': limit, 'rpoValidated': False,
            'passed': nonempty and before == after and seconds <= limit}


def local_rehearsal(limit: float) -> dict:
    with local_api() as (url, root):
        token = authenticate(url, use_environment=False); expected = seed(url, token)
        before = local_manifest(root)
        backup_started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix='clawvision-backup-') as backup_folder, tempfile.TemporaryDirectory(prefix='clawvision-restore-') as restore_folder:
            backup, target = Path(backup_folder), Path(restore_folder)
            # Own fixture is quiescent; sqlite backup includes committed WAL rows.
            with closing(sqlite3.connect(root / 'clawvision.db')) as source, closing(sqlite3.connect(backup / 'clawvision.db')) as destination:
                source.backup(destination)
            shutil.copytree(root / 'objects', backup / 'objects')
            backup_seconds = time.perf_counter() - backup_started
            restore_started = time.perf_counter()
            shutil.copy2(backup / 'clawvision.db', target / 'clawvision.db')
            shutil.copytree(backup / 'objects', target / 'objects')
            after = local_manifest(target)
            with local_api(data_directory=target) as (restored_url, _):
                restored = request(restored_url, f"/api/runs/{expected['id']}", token=token)['data']
                api_verified = all(restored[key] == expected[key] for key in ('status', 'metrics', 'events', 'artifacts', 'cursor'))
                request(restored_url, f"/api/runs/{expected['id']}/metrics", {'step': 2, 'accuracy': .9}, token)
                updated = request(restored_url, f"/api/runs/{expected['id']}", token=token)['data']
                request(restored_url, f"/api/runs/{expected['id']}/artifacts", {'name': 'restore-write', 'type': 'json', 'content': {'writable': True}}, token)
                writes_verified = updated['cursor'] > expected['cursor'] and updated['metrics'][-1]['step'] == 2
            report = assess(before, after, time.perf_counter() - restore_started, limit)
            report.update({'mode': 'sqlite-local-isolated', 'backupSeconds': round(backup_seconds, 3), 'apiVerified': api_verified,
                           'restoredWritesVerified': writes_verified, 'passed': report['passed'] and api_verified and writes_verified})
            return report


def mirror(stack: DisposableCompose, folder: Path, restore: bool = False):
    command = 'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && '
    command += 'mc mirror --overwrite /backup/objects local/clawvision' if restore else 'mc mirror --overwrite local/clawvision /backup/objects'
    user = ['--user', f'{os.getuid()}:{os.getgid()}'] if hasattr(os, 'getuid') else []
    stack.run('run', '--rm', '--no-deps', *user, '-e', 'HOME=/tmp', '-v', f'{folder.resolve()}:/backup', '--entrypoint', '/bin/sh', 'minio-init', '-c', command,
              stdout=subprocess.DEVNULL)


def compose_manifest(stack: DisposableCompose) -> dict:
    result = stack.run('run', '--rm', '--no-deps', 'api', 'python', 'scripts/backup_manifest.py', capture_output=True, text=True)
    return json.loads(result.stdout)


def compose_rehearsal(source: DisposableCompose, target: DisposableCompose, url: str, token: str | None, limit: float) -> dict:
    if source.project == target.project: raise ValueError('restore target must differ from source')
    target.require_fresh()
    expected = seed(url, authenticate(url, token))
    # This script can only operate on explicitly named disposable projects.
    # Quiesce writers before capturing either side of the DB/object snapshot.
    report = None; target_started = False
    try:
        source.run('stop', 'web', 'api', 'worker', stdout=subprocess.DEVNULL)
        before = compose_manifest(source)
        backup_started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix='clawvision-backup-') as folder:
            backup = Path(folder); dump = backup / 'postgres.dump'
            with dump.open('wb') as stream:
                source.run('exec', '-T', 'postgres', 'pg_dump', '-U', 'clawvision', '-Fc', 'clawvision', stdout=stream)
            mirror(source, backup)
            backup_seconds = time.perf_counter() - backup_started
            restore_started = time.perf_counter(); target_started = True
            target.run('up', '-d', '--wait', 'postgres', 'minio', stdout=subprocess.DEVNULL)
            target.run('run', '--rm', '--no-deps', 'minio-init', stdout=subprocess.DEVNULL)
            with dump.open('rb') as stream:
                target.run('exec', '-T', 'postgres', 'pg_restore', '-U', 'clawvision', '-d', 'clawvision', '--clean', '--if-exists', '--exit-on-error', stdin=stream)
            mirror(target, backup, restore=True)
            after = compose_manifest(target)
            material = {key: expected[key] for key in ('status', 'metrics', 'events', 'artifacts', 'cursor')}
            digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
            proof = target.run('run', '--rm', '--no-deps', 'api', 'python', 'scripts/backup_manifest.py',
                               '--verify-run', expected['id'], '--digest', digest, capture_output=True, text=True)
            read_proof = json.loads(proof.stdout)
            read_verified = read_proof['runReadVerified'] and read_proof['restoredWritesVerified']
            report = assess(before, after, time.perf_counter() - restore_started, limit)
            report.update({'mode': 'postgresql-minio-disposable', 'backupSeconds': round(backup_seconds, 3),
                           'sourceProject': source.project, 'targetProject': target.project, **read_proof,
                           'passed': report['passed'] and read_verified})
    finally:
        # Restart source even when backup/import/checks fail; remove only our
        # newly created restore project after freshness was verified.
        try: source.run('start', 'api', 'worker', 'web', stdout=subprocess.DEVNULL)
        finally:
            if target_started: target.run('down', '--volumes', '--remove-orphans', stdout=subprocess.DEVNULL)
    return report


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--project'); parser.add_argument('--restore-project')
    parser.add_argument('--compose-file', action='append'); parser.add_argument('--url', default='http://127.0.0.1:8080')
    parser.add_argument('--token'); parser.add_argument('--max-rto-seconds', type=float, default=3600); parser.add_argument('--output')
    args = parser.parse_args()
    if not math.isfinite(args.max_rto_seconds) or args.max_rto_seconds <= 0: parser.error('RTO limit must be finite and positive')
    if args.project and not args.restore_project: parser.error('an explicit fresh restore project is required')
    report = compose_rehearsal(DisposableCompose(args.project, args.compose_file), DisposableCompose(args.restore_project, args.compose_file),
                              args.url, args.token, args.max_rto_seconds) if args.project else local_rehearsal(args.max_rto_seconds)
    report['schemaVersion'] = 1
    write_report(report, args.output)
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__': main()
