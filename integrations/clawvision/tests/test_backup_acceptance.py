"""Restore integrity and scoped fault cleanup regression tests."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts')); sys.path.insert(0, str(ROOT / 'backend'))
import backup_manifest
import backup_rehearsal
import container_fault_injection
from disposable_compose import DisposableCompose
from object_store import LocalObjectStore


class RestoreAcceptanceTests(unittest.TestCase):
    def test_row_order_is_irrelevant_but_missing_rows_and_corrupt_objects_fail(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'CLAWVISION_OBJECT_DIR': folder}):
            db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
            try:
                db.execute('CREATE TABLE runs(id TEXT,value INTEGER)')
                db.executemany('INSERT INTO runs VALUES(?,?)', [('b', 2), ('a', 1)])
                store = LocalObjectStore(); store.put_bytes('proof.bin', b'original')
                store.put_bytes('.hidden-proof', b'also-backed-up')
                before = backup_manifest.snapshot(db, store)
                self.assertIn('.hidden-proof', before['objects'])
                db.execute('DELETE FROM runs'); db.executemany('INSERT INTO runs VALUES(?,?)', [('a', 1), ('b', 2)])
                self.assertEqual(before, backup_manifest.snapshot(db, store))
                self.assertTrue(backup_rehearsal.assess(before, before, 1, 60)['passed'])
                store.put_bytes('proof.bin', b'corrupted')
                self.assertFalse(backup_rehearsal.assess(before, backup_manifest.snapshot(db, store), 1, 60)['passed'])
                store.put_bytes('proof.bin', b'original'); db.execute("DELETE FROM runs WHERE id='a'")
                self.assertFalse(backup_rehearsal.assess(before, backup_manifest.snapshot(db, store), 1, 60)['passed'])
                self.assertFalse(backup_rehearsal.assess(before, before, 61, 60)['passed'])
            finally: db.close()

    def test_empty_backups_do_not_qualify_as_recovery_evidence(self):
        empty = {'tables': {}, 'objects': {}}
        self.assertFalse(backup_rehearsal.assess(empty, empty, 1, 60)['passed'])

    def test_compose_operations_reject_unscoped_or_existing_restore_targets(self):
        for project in ('production', 'clawvision', '', '../../restore'):
            with self.assertRaises(ValueError): DisposableCompose(project)
        stack = DisposableCompose('clawvision-restore-test', [str(ROOT / 'docker-compose.yml')])
        with patch('disposable_compose.subprocess.run', return_value=SimpleNamespace(stdout='existing')):
            with self.assertRaises(ValueError): stack.require_fresh()

    def test_source_restart_and_target_cleanup_survive_failed_restore(self):
        source, target = Mock(), Mock(); source.project = 'clawvision-chaos'; target.project = 'clawvision-restore-test'
        before = {'tables': {'runs': {'rows': 1}}, 'objects': {'one': {}}}
        calls = []

        def run(*args, **kwargs):
            calls.append(args)
            if 'pg_restore' in args: raise RuntimeError('broken import')
            return SimpleNamespace(stdout=json.dumps(before))

        target.run.side_effect = run
        with patch.object(backup_rehearsal, 'seed', return_value={'id': 'run'}), patch.object(backup_rehearsal, 'authenticate', return_value='token'), patch.object(backup_rehearsal, 'compose_manifest', return_value=before), patch.object(backup_rehearsal, 'mirror'):
            with self.assertRaises(RuntimeError): backup_rehearsal.compose_rehearsal(source, target, 'http://fixture', 'token', 60)
        source.run.assert_any_call('start', 'api', 'worker', 'web', stdout=backup_rehearsal.subprocess.DEVNULL)
        self.assertIn(('down', '--volumes', '--remove-orphans'), calls)

    def test_fault_assertion_failure_still_starts_the_stopped_service(self):
        stack = Mock(); stack.project = 'clawvision-chaos'
        payloads = [{'data': {'id': 'run'}}, {'data': {'id': 'artifact'}}]
        with patch.object(container_fault_injection, 'request', side_effect=payloads), patch.object(container_fault_injection, 'health', side_effect=[True, RuntimeError('probe failed')]):
            result = container_fault_injection.exercise(stack, 'http://fixture', 'token')
        stack.run.assert_any_call('start', 'postgres')
        self.assertFalse(result['passed'])


if __name__ == '__main__': unittest.main()
