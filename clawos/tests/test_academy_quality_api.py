import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from services.academy_material_api import materials_router
import test_academy_teaching_quality as fixture_module

class TeachingQualityApiTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_module.TeachingQualityTests();self.fixture.setUp();self.addCleanup(self.fixture.tmp.cleanup)
        self.s=self.fixture.s;self.mid=self.fixture.mid;self.q=self.fixture.q
        self.model=AsyncMock();self.app=FastAPI();self.app.include_router(materials_router(lambda:self.s,self.model))
    def test_calibration_roles_and_actual_calls(self):
        bank=self.fixture.bank();self.q.import_bank(self.mid,bank)
        self.model.side_effect=[dict(choices=[dict(message=dict(content=json.dumps(p)))]) for p in self.fixture.predictions(bank)]
        with TestClient(self.app) as client:r=client.post('/api/academy/learning/materials/'+self.mid+'/calibration-run',json={})
        self.assertEqual(r.status_code,200);self.assertEqual(self.model.await_count,12)
        run=self.s.store.get_run_record(r.json()['run_id'])
        self.assertEqual(run['status'],'passed');self.assertEqual(run['metrics']['model_calls'],12)
        self.assertTrue(self.q.status(self.mid)['validated'])
    def test_calibration_failure_no_pass(self):
        self.q.import_bank(self.mid,self.fixture.bank());self.model.side_effect=RuntimeError('provider offline')
        with TestClient(self.app) as client:r=client.post('/api/academy/learning/materials/'+self.mid+'/calibration-run',json={})
        self.assertEqual(r.status_code,502);self.assertFalse(self.q.status(self.mid)['validated'])
        self.assertEqual(self.s.state(self.mid)['events'][0]['data']['status'],'failed')
    def test_bank_change_during_request(self):
        bank=self.fixture.bank();self.q.import_bank(self.mid,bank);predictions=iter(self.fixture.predictions(bank));changed=False
        async def model(messages,tools):
            nonlocal changed
            if not changed:self.q.import_bank(self.mid,bank);changed=True
            return dict(choices=[dict(message=dict(content=json.dumps(next(predictions))))])
        app=FastAPI();app.include_router(materials_router(lambda:self.s,model))
        with TestClient(app) as client:r=client.post('/api/academy/learning/materials/'+self.mid+'/calibration-run',json={})
        self.assertEqual(r.status_code,400);self.assertFalse(self.q.status(self.mid)['validated'])
    def test_missing_bank_no_call(self):
        with TestClient(self.app) as client:r=client.post('/api/academy/learning/materials/'+self.mid+'/calibration-run',json={})
        self.assertEqual(r.status_code,400);self.model.assert_not_awaited()
if __name__=='__main__':unittest.main()
