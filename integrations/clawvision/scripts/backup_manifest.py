"""Content/count evidence for all database tables and object-store files."""
from __future__ import annotations

import hashlib
import argparse
import json
import re
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from database import connect  # noqa: E402
from object_store import create_object_store  # noqa: E402


def snapshot(db, store) -> dict:
    if getattr(db, 'kind', 'sqlite') == 'postgresql':
        rows = db.execute("SELECT table_name AS name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'").fetchall()
    else:
        rows = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    tables = {}
    for table in sorted(row['name'] for row in rows):
        if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', table): raise ValueError('unsupported table identifier')
        # Row digests avoid exposing credential or application contents in reports.
        hashes = sorted(hashlib.sha256(json.dumps(dict(row), sort_keys=True, default=str).encode()).hexdigest()
                        for row in db.execute(f'SELECT * FROM "{table}"').fetchall())
        tables[table] = {'rows': len(hashes), 'sha256': hashlib.sha256(''.join(hashes).encode()).hexdigest()}
    if store.kind == 'local':
        keys = sorted(path.relative_to(store.root).as_posix() for path in store.root.rglob('*') if path.is_file())
    else:
        pages = store.client.get_paginator('list_objects_v2').paginate(Bucket=store.bucket)
        keys = sorted(item['Key'] for page in pages for item in page.get('Contents', []))
    objects = {}
    for key in keys:
        payload = store.get_bytes(key)
        objects[key] = {'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
    return {'tables': tables, 'objects': objects}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--verify-run'); parser.add_argument('--digest')
    args = parser.parse_args()
    store = create_object_store()
    if args.verify_run:
        from run_service import RunService
        service = RunService(connect, store, threading.RLock())
        run = service.get(args.verify_run)
        material = {key: run[key] for key in ('status', 'metrics', 'events', 'artifacts', 'cursor')}
        verified = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest() == args.digest
        writable = False
        if verified:
            with connect() as db:
                tenant = db.execute('SELECT tenant_id FROM runs WHERE id=?', (args.verify_run,)).fetchone()['tenant_id']
            step = max((point['step'] for point in run['metrics']), default=0) + 1
            service.mutate(args.verify_run, tenant, 'metrics', {'step': step, 'accuracy': .9})
            updated = service.get(args.verify_run)
            key = 'restore-verification/probe.bin'
            try:
                store.put_bytes(key, b'restore-proof')
                writable = updated['cursor'] > run['cursor'] and updated['metrics'][-1]['step'] == step and store.get_bytes(key) == b'restore-proof'
            finally: store.delete(key)
        print(json.dumps({'runReadVerified': verified, 'restoredWritesVerified': writable}))
        raise SystemExit(0 if verified and writable else 1)
    with connect() as db: result = snapshot(db, store)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__': main()
