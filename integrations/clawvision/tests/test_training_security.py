import importlib.util, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import database, security, training_runner, durable_queue

class TrainingAndSecurityTests(unittest.TestCase):
    def test_local_python_jsonl_contract(self):
        if importlib.util.find_spec('torch') is None: self.skipTest('PyTorch is optional in system Python')
        events=[]
        result=training_runner.run('contract','local-python',{'epochs':1,'learningRate':.001,'batchSize':16,'dropout':.1,'optimizer':'AdamW','seed':1},events.append,60)
        self.assertEqual(result['status'],'completed');self.assertTrue(any(item['type']=='metric' for item in events))

    def test_pytorch_resumes_from_the_final_checkpoint_without_repeating_epochs(self):
        if importlib.util.find_spec('torch') is None: self.skipTest('PyTorch is optional in system Python')
        events=[];params={'epochs':1,'batchSize':64,'seed':7}
        with patch.dict(os.environ, {'CLAWVISION_TRAINING_SCRIPT': ''}):
            first=training_runner.run('checkpoint-first','local-python',params,events.append,60)
            checkpoint=next(item['content'] for item in events if item['type']=='checkpoint')
            resumed=[]
            result=training_runner.run('checkpoint-resume','local-python',{**params,'_checkpoint':checkpoint},resumed.append,60)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['finalAccuracy'],first['finalAccuracy'])
        self.assertFalse(any(item['type']=='metric' for item in resumed))
        self.assertTrue(any(item['type']=='artifact' for item in resumed))

    def test_pytorch_checkpoint_preserves_rng_and_remaining_epoch_metrics(self):
        if importlib.util.find_spec('torch') is None: self.skipTest('PyTorch is optional in system Python')
        params={'epochs':2,'batchSize':256,'seed':7,'dropout':.3};events=[]
        with patch.dict(os.environ, {'CLAWVISION_TRAINING_SCRIPT': ''}):
            training_runner.run('continuous','local-python',params,events.append,60)
            checkpoint=next(item['content'] for item in events if item['type']=='checkpoint')
            resumed=[]
            training_runner.run('remaining','local-python',{**params,'_checkpoint':checkpoint},resumed.append,60)
        expected=next(item for item in events if item['type']=='metric' and item['step']==2)
        actual=[item for item in resumed if item['type']=='metric']
        self.assertEqual([item['step'] for item in actual],[2])
        for key in ('trainLoss','valLoss','accuracy'):
            self.assertAlmostEqual(actual[0][key],expected[key],places=7)

    def test_password_tokens_roles_and_quota_schema(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(database,'DB_PATH',Path(folder)/'security.db'):
                database.init_database()
                with patch.object(security,'connect',database.connect):
                    principal,token=security.bootstrap('owner@example.com','correct horse battery staple','Lab')
                    self.assertTrue(principal.permits('admin'));self.assertTrue(token.startswith('cv_'))
                    with patch.dict(os.environ,{'CLAWVISION_AUTH_MODE':'enabled'}):
                        authenticated=security.authenticate('Bearer '+token)
                    self.assertEqual(authenticated.tenant_id,principal.tenant_id)
                    logged,second=security.login('owner@example.com','correct horse battery staple')
                    self.assertEqual(logged.role,'owner');self.assertNotEqual(token,second)
                    from cryptography.fernet import Fernet
                    with patch.dict(os.environ,{'CLAWVISION_MASTER_KEY':Fernet.generate_key().decode()}):
                        credential=security.save_credential(principal,'deepseek','training','secret-value')
                        self.assertEqual(security.resolve_credential(principal,credential),'secret-value')

    def test_durable_queue_idempotent_lease_retry_and_dead_letter(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(database,'DB_PATH',Path(folder)/'queue.db'):
                database.init_database()
                first=durable_queue.enqueue('tenant-a','training','run-a',{'runId':'run-a'},'same-key',max_attempts=2)
                second=durable_queue.enqueue('tenant-a','training','run-a',{},'same-key')
                self.assertEqual(first['id'],second['id'])
                self.assertTrue(durable_queue.lease(first['id'],'worker-a',5))
                self.assertTrue(durable_queue.heartbeat(first['id'],'worker-a',5))
                self.assertEqual(durable_queue.fail(first['id'],'worker-a','temporary'),'queued')
                self.assertTrue(durable_queue.lease(first['id'],'worker-b',5))
                self.assertEqual(durable_queue.fail(first['id'],'worker-b','permanent'),'dead-letter')
                self.assertEqual(durable_queue.list_tasks('tenant-a')[0]['status'],'dead-letter')

    def test_framework_callbacks_are_dependency_free_on_nonzero_rank(self):
        sys.path.insert(0,str(ROOT/'sdk'))
        from clawvision import HuggingFaceCallback, KerasCallback, LightningCallback, TrainingCallback
        for callback in (TrainingCallback('x',rank=1),LightningCallback('x',rank=1),HuggingFaceCallback('x',rank=1),KerasCallback('x',rank=1)):
            callback.metrics(1,{'loss':1.0});callback.close()

if __name__=='__main__':unittest.main()
