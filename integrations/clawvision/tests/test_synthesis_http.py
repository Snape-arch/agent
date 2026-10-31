"""Authenticated binary transport and SDK over the actual HTTP handler."""
import base64
import io
import json
import os
import sys
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch

import test_api_integration as api_tests
from test_synthetic_renderer import CUBE, fixed_config
import database
import security
import server
from durable_queue import lease, finish
from synthesis_service import SynthesisService

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk"))
from clawvision import ClawVisionError
from clawvision.evaluation import EvaluationClient

class SynthesisHTTPTests(unittest.TestCase):
    setUp = api_tests.ApiIntegrationTests.setUp
    tearDown = api_tests.ApiIntegrationTests.tearDown
    call = api_tests.ApiIntegrationTests.call
    call_auth = api_tests.ApiIntegrationTests.call_auth

    def plan(self, token=None):
        client = EvaluationClient(self.base, token)
        call = (lambda path, body: self.call_auth(path, token, body)[1]) if token else self.call
        run = call("/api/runs", {"name":"synthesis HTTP", "source":"test", "params":{}})["data"]
        suite = client.create_test_set("parts", [{"id":"bad","label":"gear"}], classes=["gear","bolt"])
        report = client.evaluate(suite["id"],run["id"],[{"sampleId":"bad","label":"bolt"}])
        asset = call("/api/model-assets", {"name":"cube.obj","format":"obj","content":base64.b64encode(CUBE).decode()})["data"]
        return client, client.create_scene_plan("HTTP scene",report["id"],"bad",asset["id"],"gear",config=fixed_config())

    def test_embedded_sdk_pipeline_and_binary_download(self):
        server._SYNTHESIS_STOP.clear()
        with patch.object(server,"EMBEDDED_WORKERS",True):
            client, plan = self.plan()
            job = client.render_scene(plan["id"],variant_indices=[0,1])
            for _ in range(100):
                done = client.get_synthesis_job(job["id"])
                if done["status"] in {"completed","failed"}: break
                time.sleep(.05)
            self.assertEqual(done["status"],"completed",done)
            self.assertEqual(client.synthesis_jobs(plan["id"])["pagination"]["total"],1)
            self.assertEqual(client.synthesis_frames(job["id"],page_size=1)["pagination"]["total"],2)
            self.assertEqual(client.synthesis_manifest(job["id"])["digest"],done["digest"])
            with zipfile.ZipFile(io.BytesIO(client.download_synthesis_package(job["id"]))) as archive:
                self.assertEqual(len(json.loads(archive.read("annotations.json"))["images"]),2)
            with urllib.request.urlopen(self.base+f'/api/evaluation/synthesis/{job["id"]}/frames/0/mask') as response:
                self.assertEqual(response.headers.get_content_type(),"image/png")
                self.assertTrue(response.read().startswith(b"\x89PNG"))
            # Wait for queue completion before the temporary database is removed.
            for _ in range(100):
                with database.connect() as db:
                    status = db.execute("SELECT status FROM durable_tasks WHERE id=?",(job["taskId"],)).fetchone()["status"]
                if status == "completed": break
                time.sleep(.02)
            self.assertEqual(status,"completed")

    def test_viewer_binary_reads_and_cross_tenant_writes_are_protected(self):
        with patch.dict(os.environ,{"CLAWVISION_AUTH_MODE":"enabled"}), patch.object(server,"EMBEDDED_WORKERS",False):
            owner, token = security.bootstrap("synth-owner@example.com","synth-owner-password","Synthesis")
            member = security.create_member(owner,"synth-viewer@example.com","synth-viewer-password","viewer")
            viewer = security.issue_token(security.Principal(member["userId"],owner.tenant_id,"viewer",("read",)),"viewer")
            client, plan = self.plan(token)
            job = client.render_scene(plan["id"],variant_indices=[0])
            self.assertEqual(client.cancel_synthesis(job["id"])["status"],"cancelled")
            self.assertEqual(client.retry_synthesis(job["id"])["status"],"queued")
            self.assertTrue(lease(job["taskId"],"http-worker"))
            result = SynthesisService(database.connect,server.OBJECT_STORE,server.DB_LOCK).execute(owner.tenant_id,job["id"],"http-worker")
            finish(job["taskId"],"http-worker",result)
            read_client = EvaluationClient(self.base,viewer)
            self.assertEqual(read_client.download_synthesis_package(job["id"])[:2],b"PK")
            prefix = f'/api/evaluation/synthesis/{job["id"]}'
            request = urllib.request.Request(self.base+prefix+"/frames/0/image",headers={"Authorization":"Bearer "+viewer})
            with urllib.request.urlopen(request) as response: self.assertEqual(response.headers.get_content_type(),"image/png")
            for path, body in ((f'/api/evaluation/scenarios/{plan["id"]}/renders',{}),(prefix+"/cancel",{}),(prefix+"/retry",{})):
                with self.assertRaises(urllib.error.HTTPError) as denied: self.call_auth(path,viewer,body)
                self.assertEqual(denied.exception.code,403); denied.exception.close()
            with database.connect() as db:
                db.execute("INSERT INTO tenants(id,name,created_at) VALUES('synth-other','other','now')")
                db.execute("INSERT INTO memberships(tenant_id,user_id,role) VALUES('synth-other',?,'owner')",(owner.user_id,))
            other = security.issue_token(security.Principal(owner.user_id,"synth-other","owner",("read","write")),"other")
            for suffix in ("","/frames","/manifest","/export","/frames/0/image","/frames/0/mask","/frames/0/amodalMask"):
                with self.assertRaises(urllib.error.HTTPError) as invisible: self.call_auth(prefix+suffix,other)
                self.assertEqual(invisible.exception.code,404); invisible.exception.close()
            with self.assertRaises(ClawVisionError): EvaluationClient(self.base,other).download_synthesis_package(job["id"])
            with self.assertRaises(urllib.error.HTTPError) as missing:
                self.call_auth(f'/api/evaluation/scenarios/{plan["id"]}/renders',other)
            self.assertEqual(missing.exception.code,404); missing.exception.close()
            with database.connect() as db: db.execute("UPDATE tenant_quotas SET max_concurrent_jobs=0 WHERE tenant_id=?",(owner.tenant_id,))
            self.assertEqual(client.render_scene(plan["id"],variant_indices=[0])["id"],job["id"])
            with self.assertRaises(ClawVisionError): client.render_scene(plan["id"],variant_indices=[1])

    def test_embedded_recovery_and_retry_exhaustion_are_bounded(self):
        server._SYNTHESIS_STOP.clear()
        with patch.object(server,"EMBEDDED_WORKERS",False):
            client, plan = self.plan()
            job = client.render_scene(plan["id"],variant_indices=[0])
        with patch.object(server,"EMBEDDED_WORKERS",True), patch.object(server,"execute_synthesis_job",side_effect=RuntimeError("provider unavailable")) as execute:
            self.assertEqual(server.recover_synthesis_once(),1)
            for _ in range(150):
                current = client.get_synthesis_job(job["id"])
                if current["status"] == "failed" and current["attempts"] == 3: break
                time.sleep(.02)
            self.assertEqual((current["status"],current["attempts"]),("failed",3))
            self.assertEqual(execute.call_count,3)
        self.assertIn("provider unavailable",current["error"])

    def test_sdk_rejects_non_zip_binary_response(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"error":"wrong endpoint"}'
        response.headers.get_content_type.return_value = "application/json"
        with patch("urllib.request.urlopen",return_value=response), self.assertRaises(ClawVisionError):
            EvaluationClient(self.base).download_synthesis_package("job")
