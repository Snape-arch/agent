import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from memoryos.memory_store import MemoryStore
from memoryos.document_ingestion import ingest_file
from services.academy_materials import AcademyMaterials
from services.academy_documents import AcademyDocuments
from services.maintenance_service import MaintenanceService
from services.recovery_bundle import RecoveryBundle,sha
from memoryos.services.vector_store import MemoryVectorStore

class RecoveryBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.db=self.root/'live.db';self.store=MemoryStore(str(self.db))
        self.ops=MaintenanceService(store=self.store,db_path=self.db,base_dir=self.root,config={})
        self.s=AcademyMaterials(self.store,self.root/'output'/'academy-materials')
        self.m=self.s.upload('chapter.md',b'# Source\nEvidence supports conclusions.')
        path=self.root/'raw.txt';path.write_text('A source with recoverable evidence.')
        self.doc=ingest_file(self.store,self.root/'uploads',path)
        self.note=AcademyDocuments(self.store).save(dict(title='Note',blocks=[dict(id='p',type='paragraph',text='Actual saved note')]))
        self.bundle=RecoveryBundle(self.ops)
    def test_recover_without_originals_and_rebuild_stale_vectors(self):
        report=self.root/'report.md';report.write_text('Recoverable report.',encoding='utf-8')
        self.store.save_run_record(dict(run_id='report',run_type='report',title='Report',status='completed',
            outputs={'report':{'markdown_path':str(report)},'description':'Original prose '+str(report)},
            artifacts=[dict(artifact_id='report-md',kind='markdown',title='Report',uri=str(report))]))
        out=self.bundle.backup();original_sha=sha(self.db)
        report.unlink()
        Path(self.doc['file_path']).unlink()
        (self.s.root/self.m['document']['id']/'chapter.md').unlink()
        restored=self.bundle.restore_isolated(out['path'])
        self.assertTrue(restored['ok']);self.assertTrue(restored['vector']['consistent'])
        self.assertEqual(sha(self.db),original_sha)
        s=MemoryStore(restored['database']);fresh=AcademyMaterials(s,restored['material_root'])
        self.assertTrue((fresh.root/self.m['document']['id']/'chapter.md').is_file())
        self.assertEqual(AcademyDocuments(s).get(self.note['id'])['blocks'][0]['text'],'Actual saved note')
        run=s.get_run_record('report');path=run['outputs']['report']['markdown_path']
        self.assertEqual(path,run['artifacts'][0]['uri']);self.assertTrue(Path(path).is_file())
        self.assertEqual(run['outputs']['description'],'Original prose '+str(report))
        v=MemoryVectorStore(restored['database'],provider='lightweight',embedding_provider='hash')
        self.assertTrue(v.search('recoverable evidence',min_score=0));v.close()
    def test_corruption_rejected_before_destination_creation(self):
        out=self.bundle.backup();folder=Path(out['path'])
        manifest=json.loads((folder/'manifest.json').read_text())
        (folder/manifest['files'][0]['bundle_path']).write_bytes(b'corrupt')
        target=self.root/'backups'/'must-not-exist'
        with self.assertRaises(ValueError):self.bundle.restore_isolated(folder,target)
        self.assertFalse(target.exists())
    def test_manifest_omission_and_traversal(self):
        out=self.bundle.backup();folder=Path(out['path']);path=folder/'manifest.json';manifest=json.loads(path.read_text())
        manifest['files'].pop();path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):self.bundle.verify(folder)
        manifest['database']['path']='../live.db';path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):self.bundle.verify(folder)
    def test_missing_source_fails_complete_backup(self):
        Path(self.doc['file_path']).unlink()
        with self.assertRaises(ValueError):self.bundle.backup()
        self.assertTrue(list((self.root/'backups').glob('*/INCOMPLETE.txt')))
    def test_restore_cannot_overwrite_or_escape(self):
        out=self.bundle.backup()
        with self.assertRaises(ValueError):self.bundle.restore_isolated(out['path'],self.root)
        target=self.root/'backups'/'existing';target.mkdir()
        with self.assertRaises(ValueError):self.bundle.restore_isolated(out['path'],target)
    def test_tools_and_weights_excluded(self):
        tools=self.root/'tools';tools.mkdir();weight=tools/'model.gguf';weight.write_bytes(b'weights')
        with self.store._conn() as c:c.execute('UPDATE documents SET file_path=? WHERE id=?',(str(weight),self.doc['id']))
        with self.assertRaises(ValueError):self.bundle.backup()
    def test_lost_optional_artifact_is_declared(self):
        with self.store._conn() as c:
            c.execute("INSERT INTO run_records(run_id,run_type,title,status) VALUES ('lost','test','fixture','completed')")
            c.execute("INSERT INTO run_artifacts(run_id,artifact_id,uri) VALUES ('lost','artifact',?)",(str(self.root/'gone.md'),))
        out=self.bundle.backup();self.assertEqual(out['status'],'degraded');self.assertEqual(out['missing_artifacts'],1)
        restored=self.bundle.restore_isolated(out['path']);self.assertEqual(restored['missing_artifacts'],1)

    def test_delivery_registry_and_task_checkpoint_survive_clean_restore(self):
        from services.artifact_delivery_service import ArtifactDeliveryService
        report=self.root/'download.md';report.write_text('Download survives a clean recovery.')
        delivery=ArtifactDeliveryService(self.bundle.registry_path,[self.root])
        artifact=delivery.register(report)
        checkpoint=self.root/'checkpoint.json';checkpoint.write_text('{"completed":2}')
        task=self.store.start_task('recovery','Durable task',metadata={'checkpoint_path':str(checkpoint),'latest_checkpoint':{'uri':str(checkpoint),'digest':sha(checkpoint)}})
        out=self.bundle.backup();report.unlink();checkpoint.unlink();self.bundle.registry_path.unlink()
        restored=self.bundle.restore_isolated(out['path'])
        self.assertEqual(restored['delivery_items'],1);self.assertEqual(restored['checkpoint_files'],2)
        item,path=ArtifactDeliveryService(restored['delivery_registry'],[Path(restored['target'])]).resolve(artifact['id'])
        self.assertEqual(path.read_text(),'Download survives a clean recovery.')
        store=MemoryStore(restored['database']);metadata=store.get_task(task['id'])['task']['metadata']
        self.assertTrue(Path(metadata['checkpoint_path']).is_file())
        self.assertEqual(metadata['checkpoint_path'],metadata['latest_checkpoint']['uri'])
        self.assertEqual(sha(metadata['checkpoint_path']),metadata['latest_checkpoint']['digest'])

    def test_manifest_cannot_rebind_original_to_other_valid_file(self):
        out=self.bundle.backup();folder=Path(out['path']);mp=folder/'manifest.json';manifest=json.loads(mp.read_text())
        material=next(r for r in manifest['files'] if r['kind']=='material')
        other=next(r for r in manifest['files'] if r['kind']=='document')
        material.update(bundle_path=other['bundle_path'],sha256=other['sha256'],bytes=other['bytes'])
        mp.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'原始引用'):self.bundle.verify(folder)
if __name__=='__main__':unittest.main()
