"""Actual authenticated HTTP/SDK training and catalog integration."""
import json
import os
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import test_synthesis_http as synth_http
from test_vision_training import samples, TRAIN, TEST
import database
import security
import server
from clawvision.evaluation import EvaluationClient
from clawvision import ClawVisionError

class VisionHTTPTests(unittest.TestCase):
    setUp = synth_http.SynthesisHTTPTests.setUp
    tearDown = synth_http.SynthesisHTTPTests.tearDown
    call = synth_http.SynthesisHTTPTests.call
    call_auth = synth_http.SynthesisHTTPTests.call_auth
    plan = synth_http.SynthesisHTTPTests.plan

    def complete(self, client, job, get):
        for _ in range(200):
            done = get(job["id"])
            if done["status"] in {"completed","failed"}: break
            time.sleep(.025)
        self.assertEqual(done["status"],"completed",done)
        for _ in range(100):
            with database.connect() as db: status = db.execute("SELECT status FROM durable_tasks WHERE id=?",(job["taskId"],)).fetchone()["status"]
            if status=="completed": break
            time.sleep(.01)
        self.assertEqual(status,"completed")
        return done

    def test_authenticated_sdk_real_comparison_catalog_and_viewer_boundaries(self):
        server._SYNTHESIS_STOP.clear()
        with patch.dict(os.environ,{"CLAWVISION_AUTH_MODE":"enabled"}),patch.object(server,"EMBEDDED_WORKERS",True):
            owner, token = security.bootstrap("vision-owner@example.com","vision-owner-password","Vision")
            client, plan = self.plan(token)
            job = client.render_scene(plan["id"],variant_indices=[0]); self.complete(client,job,client.get_synthesis_job)
            synth = client.register_synthesis_dataset(job["id"],name="registered synthetic")
            self.assertEqual(client.register_synthesis_dataset(job["id"])['id'],synth['id'])
            real = client.create_image_dataset("training",samples(TRAIN),purpose="train")
            test = client.create_image_dataset("testing",samples(TEST),purpose="test")
            newer = client.create_image_dataset("training v2",samples(TRAIN+[("gear",[10,190,125])]),purpose="train",dataset_id=real["datasetId"])
            self.assertEqual(newer["version"],2)
            self.assertEqual(client.get_image_version(real["id"])["sampleCount"],4)
            self.assertEqual(client.image_versions()["pagination"]["total"],4)
            self.assertEqual(self.call_auth('/api/datasets/'+real['datasetId']+'/versions',token)[1]['data'][0]['id'],newer['id'])
            experiment = client.create_training_comparison(real["id"],synth["id"],test["id"],config={"epochs":8})
            done = self.complete(client,experiment,client.get_training_comparison)
            self.assertEqual(done["result"]["trainingSamples"],{"baseline":4,"candidate":5})
            self.assertEqual(done["result"]["baseline"]["provenance"]["kind"],"cpu-rgb-softmax/1")
            self.assertEqual(client.training_comparisons()["pagination"]["total"],1)
            member = security.create_member(owner,"vision-viewer@example.com","vision-viewer-password","viewer")
            viewer = security.issue_token(security.Principal(member['userId'],owner.tenant_id,'viewer',('read',)),"viewer")
            self.assertEqual(EvaluationClient(self.base,viewer).get_training_comparison(experiment["id"])["status"],"completed")
            prefix='/api/evaluation/image-versions/'+real['id']
            with urllib.request.urlopen(urllib.request.Request(self.base+prefix+'/images/0',headers={'Authorization':'Bearer '+viewer})) as response:
                self.assertEqual(response.headers.get_content_type(),'image/png'); self.assertTrue(response.read().startswith(b'\x89PNG'))
            for path,body in (('/api/evaluation/image-datasets',{'name':'denied','purpose':'train','samples':samples(TRAIN)}),
                              ('/api/evaluation/synthesis/'+job['id']+'/dataset-version',{}),('/api/evaluation/experiments',{}),
                              ('/api/evaluation/experiments/'+experiment['id']+'/cancel',{}),('/api/evaluation/experiments/'+experiment['id']+'/retry',{})):
                with self.assertRaises(urllib.error.HTTPError) as denied:self.call_auth(path,viewer,body)
                self.assertEqual(denied.exception.code,403);denied.exception.close()
            with database.connect() as db:
                db.execute("INSERT INTO tenants(id,name,created_at) VALUES('vision-other','other','now')")
                db.execute("INSERT INTO memberships(tenant_id,user_id,role) VALUES('vision-other',?,'owner')",(owner.user_id,))
            other=security.issue_token(security.Principal(owner.user_id,'vision-other','owner',('read','write')),'other')
            for path in (prefix,prefix+'/images/0','/api/evaluation/experiments/'+experiment['id']):
                with self.assertRaises(urllib.error.HTTPError) as hidden:self.call_auth(path,other)
                self.assertEqual(hidden.exception.code,404);hidden.exception.close()
            with self.assertRaises(ClawVisionError): EvaluationClient(self.base,other).create_training_comparison(real['id'],synth['id'],test['id'])
            self.assertIn('/api/evaluation/experiments',self.call('/api/openapi.json')['paths'])
            self.assertEqual(server.Handler._metric_path('/api/evaluation/experiments/'+experiment['id']),'/api/evaluation/experiments/vexp_:id')
            self.assertEqual(server.Handler._metric_path(prefix+'/images/0'),'/api/evaluation/image-versions/dsv_:id/images/0')
            with patch.object(server,'EMBEDDED_WORKERS',False):
                pending=client.create_training_comparison(real['id'],synth['id'],test['id'],config={'epochs':9})
                self.assertEqual(client.cancel_training_comparison(pending['id'])['status'],'cancelled')
                self.assertEqual(client.retry_training_comparison(pending['id'])['status'],'queued')
                client.cancel_training_comparison(pending['id'])
