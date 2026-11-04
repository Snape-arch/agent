"""Actual offline import, unpublished failures, source preservation and runtime receipts."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from scripts.migrate_vision_store import migrate,sha
from services.vision_runtime import VisionRuntime,SOURCE_ROOT

class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'old';self.target=self.root/'new'
        (self.source/'data/objects').mkdir(parents=True);self.db=self.source/'data/clawvision.db'
        with closing(sqlite3.connect(self.db)) as c, c:
            c.executescript('''CREATE TABLE runs(id TEXT,name TEXT,status TEXT,source TEXT,params TEXT,created_at TEXT,updated_at TEXT,error_message TEXT);
              CREATE TABLE datasets(id TEXT,name TEXT,format TEXT,schema_json TEXT,object_key TEXT,row_count INTEGER,created_at TEXT);
              CREATE TABLE visualization_specs(id TEXT,name TEXT,dataset_id TEXT,spec TEXT,share_token TEXT,is_public INTEGER,version INTEGER,created_at TEXT,updated_at TEXT);
              CREATE TABLE users(id TEXT,password_hash TEXT);''')
            c.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)',('old-run','Synthetic history','running','simulator',json.dumps({'api_key':'synthetic-not-real','epochs':2}),'2026-01-01','2026-01-01',None))
            c.execute('INSERT INTO datasets VALUES(?,?,?,?,?,?,?)',('old-data','Synthetic data','csv','[]','datasets/rows.json',2,'2026-01-01'))
            c.execute('INSERT INTO visualization_specs VALUES(?,?,?,?,?,?,?,?,?)',('old-chart','Synthetic chart','old-data','{}','synthetic-old-share',1,1,'2026-01-01','2026-01-01'))
            c.execute('INSERT INTO users VALUES(?,?)',('excluded-user','synthetic-password-hash'))
        (self.source/'data/objects/datasets').mkdir()
        (self.source/'data/objects/datasets/rows.json').write_text(json.dumps({'rows':[{'x':1},{'x':2}]}),encoding='utf-8')
        self.before=sha(self.db)
    def run_import(self):return migrate(self.source,self.target,SOURCE_ROOT/'backend')
    def test_upgrade_objects_privacy_and_no_resumed_work(self):
        r=self.run_import();self.assertTrue(r['passed']);self.assertEqual(sha(self.db),self.before)
        with closing(sqlite3.connect(self.target/'data/clawvision.db')) as c, c:
            status,params=c.execute('SELECT status,params FROM runs').fetchone()
            self.assertEqual(status,'cancelled');self.assertNotIn('synthetic-not-real',params)
            share,public=c.execute('SELECT share_token,is_public FROM visualization_specs').fetchone()
            self.assertNotEqual(share,'synthetic-old-share');self.assertEqual(public,0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM users').fetchone()[0],0)
            self.assertGreaterEqual(c.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0],22)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertEqual(json.loads((self.target/'objects/datasets/rows.json').read_text())['rows'],[{'x':1},{'x':2}])
        self.assertEqual(r['objects']['datasets/rows.json']['destination_sha256'],sha(self.target/'objects/datasets/rows.json'))
    def test_existing_destination_is_never_overwritten(self):
        self.target.mkdir();marker=self.target/'keep.txt';marker.write_text('user data')
        with self.assertRaises(ValueError):self.run_import()
        self.assertEqual(marker.read_text(),'user data');self.assertEqual(sha(self.db),self.before)
    def test_missing_object_prevents_publishing(self):
        (self.source/'data/objects/datasets/rows.json').unlink()
        with self.assertRaises(FileNotFoundError):self.run_import()
        self.assertFalse(self.target.exists());self.assertEqual(sha(self.db),self.before)
    def test_traversal_object_prevents_publishing(self):
        with closing(sqlite3.connect(self.db)) as c, c:c.execute("UPDATE datasets SET object_key='../outside.json'")
        with self.assertRaises(ValueError):self.run_import()
        self.assertFalse(self.target.exists())
    def test_unmapped_nonempty_business_table_prevents_partial_import(self):
        with closing(sqlite3.connect(self.db)) as c, c:c.executescript('CREATE TABLE unknown_business(id TEXT);INSERT INTO unknown_business VALUES(1);')
        with self.assertRaises(ValueError):self.run_import()
        self.assertFalse(self.target.exists())
    def test_receipt_visible_without_start_and_corruption_is_explicit(self):
        self.run_import();runtime=VisionRuntime(self.target);self.addCleanup(runtime.close)
        self.assertEqual(runtime.status()['migration']['counts']['datasets'],1);self.assertIsNone(runtime.process)
        (self.target/'migration-receipt.json').write_text('{bad receipt')
        self.assertEqual(runtime.status()['migration']['state'],'invalid_receipt')

if __name__=='__main__':unittest.main()
