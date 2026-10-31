from __future__ import annotations

import json
import base64
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))
import database  # noqa: E402
import server  # noqa: E402
import security  # noqa: E402
from ai_studio import local_3d_plan  # noqa: E402
from mesh_postprocess import postprocess_to_glb  # noqa: E402
from object_store import LocalObjectStore  # noqa: E402


class ApiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); root=Path(self.temp.name)
        self.db_patch=patch.object(database,"DB_PATH",root/"api.db"); self.db_patch.start()
        self.url_patch=patch.object(database,"DATABASE_URL",f"sqlite:///{root/'api.db'}"); self.url_patch.start()
        self.env_patch=patch.dict(os.environ,{"CLAWVISION_OBJECT_DIR":str(root/"objects")}); self.env_patch.start()
        database.init_database(); server.OBJECT_STORE=LocalObjectStore()
        self.http=server.ThreadingHTTPServer(("127.0.0.1",0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True); self.thread.start()
        self.base=f"http://127.0.0.1:{self.http.server_port}"

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join(timeout=3)
        self.env_patch.stop(); self.url_patch.stop(); self.db_patch.stop(); self.temp.cleanup()

    def call(self,path,body=None,method=None):
        data=json.dumps(body).encode() if body is not None else None
        request=urllib.request.Request(self.base+path,data=data,headers={"Content-Type":"application/json"},method=method or ("POST" if body is not None else "GET"))
        with urllib.request.urlopen(request,timeout=30) as response: return json.loads(response.read())

    def call_auth(self,path,token,body=None,method=None):
        data=json.dumps(body).encode() if body is not None else None
        request=urllib.request.Request(self.base+path,data=data,headers={"Content-Type":"application/json","Authorization":"Bearer "+token},method=method or ("POST" if body is not None else "GET"))
        with urllib.request.urlopen(request,timeout=30) as response:return response.status,json.loads(response.read())

    def test_health_and_http_trace_correlation(self):
        incoming="00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
        request=urllib.request.Request(self.base+"/api/health",headers={"traceparent":incoming})
        with urllib.request.urlopen(request,timeout=30) as response:
            payload=json.loads(response.read());returned=response.headers["traceparent"]
        self.assertTrue(payload["ok"]);self.assertIn("workers",payload)
        self.assertTrue(returned.startswith("00-0123456789abcdef0123456789abcdef-"))
        self.assertEqual(response.headers["X-Trace-ID"],"0123456789abcdef0123456789abcdef")

    def test_scene_plan_http_sdk_export_and_asset_deletion_protection(self):
        import hashlib
        sys.path.insert(0, str(ROOT / "sdk"))
        from clawvision.evaluation import EvaluationClient
        client = EvaluationClient(self.base)
        run = self.call('/api/runs', {'name': 'scene provenance', 'source': 'test', 'params': {}})['data']
        test_set = client.create_test_set('scene tests', [{'id': 'bad', 'label': 'gear'}], classes=['gear', 'bolt'])
        report = client.evaluate(test_set['id'], run['id'], [{'sampleId': 'bad', 'label': 'bolt'}])
        content = b'v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n'
        asset = self.call('/api/model-assets', {'name': 'scene.obj', 'format': 'obj', 'content': base64.b64encode(content).decode()})['data']
        plan = client.create_scene_plan('scene fixture', report['id'], 'bad', asset['id'], 'gear', config={'count': 3})
        self.assertEqual(plan['digest'], client.export_scene_plan(plan['id'])['digest'])
        self.assertEqual(client.get_scene_plan(plan['id'])['manifest'], plan['manifest'])
        self.assertEqual(client.scene_plans(report['id'])['pagination']['total'], 1)
        self.assertEqual(client.verified_scene_asset(plan['id'])['sha256'], hashlib.sha256(content).hexdigest())
        next_version = client.create_scene_plan('scene fixture', report['id'], 'bad', asset['id'], 'gear', parent_id=plan['id'])
        self.assertEqual(next_version['version'], 2)
        references = self.call('/api/model-assets/' + asset['id'] + '?content=false')['data']['references']
        self.assertEqual({item['id'] for item in references if item['kind'] == 'evaluation-scenario'}, {plan['id'], next_version['id']})
        for suffix in ('', '?purge=true'):
            with self.assertRaises(urllib.error.HTTPError) as protected:
                self.call('/api/model-assets/' + asset['id'] + suffix, method='DELETE')
            self.assertEqual(protected.exception.code, 409)
            protected.exception.close()
        # Even legacy soft-deleted pinned assets are protected during GC.
        with database.connect() as db:
            db.execute("UPDATE model_assets SET deleted_at='2000-01-01T00:00:00+00:00' WHERE id=?", (asset['id'],))
        collected = self.call('/api/model-assets/garbage-collect', {'graceHours': 0})['data']
        self.assertIn(asset['id'], collected['protected'])
        self.assertEqual(collected['purged'], [])
        self.assertIn('/api/evaluation/scenarios/{scenarioId}/asset', self.call('/api/openapi.json')['paths'])

    def test_scene_plan_http_roles_and_cross_tenant_boundaries(self):
        with patch.dict(os.environ, {'CLAWVISION_AUTH_MODE': 'enabled'}):
            owner, token = security.bootstrap('scene-owner@example.com', 'scene-owner-password', 'Scene')
            member = security.create_member(owner, 'scene-viewer@example.com', 'scene-viewer-password', 'viewer')
            viewer = security.issue_token(security.Principal(member['userId'], owner.tenant_id, 'viewer', ('read',)), 'viewer')
            read_token = security.issue_token(security.Principal(owner.user_id, owner.tenant_id, 'owner', ('read',)), 'read only')
            _, run = self.call_auth('/api/runs', token, {'name': 'scene', 'source': 'test', 'params': {}})
            _, test_set = self.call_auth('/api/evaluation/test-sets', token, {'name': 'scene', 'classes': ['A', 'B'], 'samples': [{'id': 'bad', 'label': 'A'}]})
            _, report = self.call_auth('/api/evaluation/reports', token, {'testSetId': test_set['data']['id'], 'runId': run['data']['id'], 'predictions': [{'sampleId': 'bad', 'label': 'B'}]})
            _, asset = self.call_auth('/api/model-assets', token, {'name': 'part.obj', 'format': 'obj', 'content': base64.b64encode(b'v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n').decode()})
            body = {'name': 'private scene', 'reportId': report['data']['id'], 'sampleId': 'bad', 'assetId': asset['data']['id'], 'label': 'A'}
            _, plan = self.call_auth('/api/evaluation/scenarios', token, body)
            for limited in (viewer, read_token):
                self.assertEqual(self.call_auth('/api/evaluation/scenarios/' + plan['data']['id'] + '/asset', limited)[0], 200)
                with self.assertRaises(urllib.error.HTTPError) as denied: self.call_auth('/api/evaluation/scenarios', limited, body)
                self.assertEqual(denied.exception.code, 403)
                denied.exception.close()
            with database.connect() as db:
                db.execute("INSERT INTO tenants(id,name,created_at) VALUES('scene-other','other','now')")
                db.execute("INSERT INTO memberships(tenant_id,user_id,role) VALUES('scene-other',?,'owner')", (owner.user_id,))
            other = security.issue_token(security.Principal(owner.user_id, 'scene-other', 'owner', ('read', 'write')), 'other')
            for path in ('/api/evaluation/scenarios/' + plan['data']['id'], '/api/evaluation/scenarios/' + plan['data']['id'] + '/export',
                         '/api/evaluation/scenarios/' + plan['data']['id'] + '/asset', '/api/evaluation/scenarios?reportId=' + report['data']['id']):
                with self.assertRaises(urllib.error.HTTPError) as invisible: self.call_auth(path, other)
                self.assertEqual(invisible.exception.code, 404)
                invisible.exception.close()
            with self.assertRaises(urllib.error.HTTPError) as invisible: self.call_auth('/api/evaluation/scenarios', other, body)
            self.assertEqual(invisible.exception.code, 404)
            invisible.exception.close()

    def test_evaluation_http_and_python_client_use_the_same_fixed_manifest(self):
        sys.path.insert(0, str(ROOT / "sdk"))
        from clawvision.evaluation import EvaluationClient
        client = EvaluationClient(self.base)
        first = self.call('/api/runs', {'name': 'vision baseline', 'params': {}})['data']['id']
        second = self.call('/api/runs', {'name': 'vision candidate', 'params': {}})['data']['id']
        test_set = client.create_test_set('parts', [{'id': 'a', 'label': 'gear', 'conditions': {'lighting': 'reflection'}},
                                                  {'id': 'b', 'label': 'bolt', 'conditions': {'lighting': 'normal'}}])
        baseline = client.evaluate(test_set['id'], first, [{'sampleId': 'a', 'label': 'bolt'}, {'sampleId': 'b', 'label': 'bolt'}])
        candidate = client.evaluate(test_set['id'], second, [{'sampleId': 'a', 'label': 'gear'}, {'sampleId': 'b', 'label': 'gear'}])
        compared = client.compare(baseline['id'], candidate['id'])
        self.assertEqual((compared['fixed'], compared['regressed'], compared['accuracyDelta']), (1, 1, 0))
        self.assertEqual(client.export_test_set(test_set['id'])['samples'][0]['id'], 'a')
        self.assertEqual(client.get_report(candidate['id']), candidate)
        self.assertEqual(client.failures(candidate['id'], dimension='lighting', value='normal')['data'][0]['sampleId'], 'b')
        page = self.call('/api/evaluation/reports?testSetId=' + test_set['id'] + '&pageSize=1')
        self.assertEqual((page['pagination']['total'], len(page['data'])), (2, 1))
        self.assertEqual(self.call('/api/evaluation/test-sets/' + test_set['id'])['data'], test_set)
        for path in ('/api/evaluation/test-sets?page=0', '/api/evaluation/reports?pageSize=101',
                     '/api/evaluation/reports/' + candidate['id'] + '/cases?failuresOnly=invalid',
                     '/api/evaluation/reports/' + candidate['id'] + '/cases?dimension=lighting'):
            with self.assertRaises(urllib.error.HTTPError) as invalid: self.call(path)
            self.assertEqual(invalid.exception.code, 400)
        for path, method in (('/api/evaluation/test-sets/' + test_set['id'], 'PATCH'), ('/api/evaluation/reports/' + baseline['id'], 'PATCH')):
            with self.assertRaises(urllib.error.HTTPError): self.call(path, {'name': 'mutate'}, method)
        self.assertEqual(client.get_report(baseline['id']), baseline)
        spec = self.call('/api/openapi.json')
        self.assertIn('/api/evaluation/compare', spec['paths'])
        self.assertIn('CreateEvaluationReport', spec['components']['schemas'])

    def test_evaluation_http_enforces_viewer_scope_and_cross_tenant_invisibility(self):
        with patch.dict(os.environ, {'CLAWVISION_AUTH_MODE': 'enabled'}):
            owner, token = security.bootstrap('eval-owner@example.com', 'evaluation-owner-password', 'Evaluation')
            member = security.create_member(owner, 'eval-viewer@example.com', 'evaluation-viewer-password', 'viewer')
            viewer = security.issue_token(security.Principal(member['userId'], owner.tenant_id, 'viewer', ('read',)), 'view')
            write_only = security.issue_token(owner, 'read-only', ['read'])
            with database.connect() as db:
                db.execute("INSERT INTO tenants(id,name,created_at) VALUES('another-tenant','Other evaluation','now')")
                db.execute("INSERT INTO memberships(tenant_id,user_id,role) VALUES(?,?,?)", ('another-tenant', owner.user_id, 'owner'))
            other_token = security.issue_token(security.Principal(owner.user_id, 'another-tenant', 'owner', ('*',)), 'other')
            _, created = self.call_auth('/api/runs', token, {'name': 'eval run', 'params': {}})
            _, test_set = self.call_auth('/api/evaluation/test-sets', token, {'name': 'fixed', 'samples': [{'id': 'a', 'label': 'A'}]})
            body = {'testSetId': test_set['data']['id'], 'runId': created['data']['id'], 'predictions': [{'sampleId': 'a', 'label': 'A'}]}
            _, report = self.call_auth('/api/evaluation/reports', token, body)
            self.assertEqual(self.call_auth('/api/evaluation/reports/' + report['data']['id'], viewer)[0], 200)
            self.assertEqual(self.call_auth('/api/evaluation/test-sets', other_token)[1]['data'], [])
            for limited in (viewer, write_only):
                for path, payload in (('/api/evaluation/test-sets', {'name': 'denied', 'samples': [{'id': 'a', 'label': 'A'}]}), ('/api/evaluation/reports', body)):
                    with self.assertRaises(urllib.error.HTTPError) as denied: self.call_auth(path, limited, payload)
                    self.assertEqual(denied.exception.code, 403)
            for path in ('/api/evaluation/test-sets/' + test_set['data']['id'], '/api/evaluation/reports/' + report['data']['id'],
                         '/api/evaluation/reports/' + report['data']['id'] + '/cases'):
                with self.assertRaises(urllib.error.HTTPError) as invisible: self.call_auth(path, other_token)
                self.assertEqual(invisible.exception.code, 404)

    def test_task_pagination_is_not_truncated_at_one_hundred_resources(self):
        for index in range(105):
            server.enqueue_task('default', 'training', f'run-{index}', {'runId': f'run-{index}'}, f'pagination-{index}')
        server.enqueue_task('other-tenant', 'training', 'private', {}, 'private')
        first = self.call('/api/tasks?page=1&pageSize=100')
        second = self.call('/api/tasks?page=2&pageSize=100')
        self.assertEqual(first['pagination']['total'], 105)
        self.assertEqual(len(first['data']), 100)
        self.assertEqual(len(second['data']), 5)
        self.assertFalse(second['pagination']['hasNext'])
        self.assertEqual(len({row['id'] for row in first['data'] + second['data']}), 105)

    def test_asset_release_enforces_role_scope_and_authenticated_reviewer(self):
        with patch.dict(os.environ, {"CLAWVISION_AUTH_MODE": "enabled"}):
            owner, token = security.bootstrap("release@example.com", "release-owner-password", "Release")
            member = security.create_member(owner, "researcher@example.com", "researcher-password", "researcher")
            researcher = security.issue_token(security.Principal(member["userId"], owner.tenant_id, "researcher", ("read", "write")), "test")
            limited_owner = security.issue_token(owner, "write-only", ["read", "write"])
            obj = base64.b64encode(b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n").decode()
            _, payload = self.call_auth("/api/model-assets", researcher, {"name": "release.obj", "format": "obj", "content": obj})
            asset_id = payload["data"]["id"]
            _, pending = self.call_auth(f"/api/model-assets/{asset_id}/releases", researcher, {"status": "pending"})
            self.assertEqual(pending["data"]["status"], "pending")
            attempts = [(f"/api/model-assets/{asset_id}/releases", {"status": "approved"}, "POST"),
                        (f"/api/model-assets/{asset_id}", {"stage": "release"}, "PATCH"),
                        ("/api/model-assets/batch", {"ids": [asset_id], "patch": {"stage": "release"}}, "POST"),
                        ("/api/model-assets", {"name": "bypass.obj", "format": "obj", "content": obj, "metadata": {"assetStage": "release"}}, "POST")]
            for principal_token in (researcher, limited_owner):
                for path, body, method in attempts:
                    with self.assertRaises(urllib.error.HTTPError) as denied: self.call_auth(path, principal_token, body, method)
                    self.assertEqual(denied.exception.code, 403)
            _, approved = self.call_auth(f"/api/model-assets/{asset_id}/releases", token, {"status": "approved", "reviewer": "forged-user", "note": "reviewed"})
            self.assertEqual(approved["data"]["reviewer"], owner.user_id)
            detail = self.call_auth(f"/api/model-assets/{asset_id}", token)[1]["data"]
            self.assertEqual(detail["stage"], "release")
            self.assertIn(owner.user_id, [release["reviewer"] for release in detail["releases"]])

    def test_cross_tenant_resources_are_invisible(self):
        with patch.dict(os.environ,{"CLAWVISION_AUTH_MODE":"enabled"}):
            first,token_a=security.bootstrap('a@example.com','correct horse battery staple','Tenant A')
            created=security.now();tenant_b='ten_b';user_b='usr_b'
            with database.connect() as db:
                db.execute("INSERT INTO tenants(id,name,created_at) VALUES(?,?,?)",(tenant_b,'Tenant B',created))
                db.execute("INSERT INTO users(id,email,password_hash,active,created_at) VALUES(?,?,?,?,?)",(user_b,'b@example.com',security.hash_password('correct horse battery staple'),1,created))
                db.execute("INSERT INTO memberships(tenant_id,user_id,role) VALUES(?,?,?)",(tenant_b,user_b,'owner'))
                db.execute("INSERT INTO tenant_quotas(tenant_id) VALUES(?)",(tenant_b,))
            token_b=security.issue_token(security.Principal(user_b,tenant_b,'owner',('*',)),'test')
            _,run_a=self.call_auth('/api/runs',token_a,{'name':'private-a','params':{}});run_id=run_a['data']['id']
            _,dataset=self.call_auth('/api/datasets',token_a,{'name':'private-data','format':'json','content':[{'x':1}]})
            _,asset=self.call_auth('/api/model-assets',token_a,{'name':'private.obj','format':'obj','content':base64.b64encode(b'v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3').decode()})
            _,spec=self.call_auth('/api/visualization-specs',token_a,{'id':'shared-id','name':'private chart','spec':{'pluginId':'table'}})
            _,generation=self.call_auth('/api/studio/generations',token_a,{'id':'shared-generation','plan':local_3d_plan('private model')})
            self.assertEqual(len(self.call_auth('/api/runs',token_b)[1]['data']),0)
            for path in (f'/api/runs/{run_id}',f"/api/datasets/{dataset['data']['id']}",f"/api/model-assets/{asset['data']['id']}"):
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    self.call_auth(path,token_b)
                self.assertEqual(denied.exception.code,404)
            for path,body in (("/api/visualization-specs",{'id':spec['data']['id'],'spec':{'pluginId':'json'}}),
                              ("/api/studio/generations",{'id':generation['data']['id'],'plan':local_3d_plan('overwrite')}),
                              ("/api/parameter-snapshots",{'runId':run_id,'params':{'lr':.1}}),
                              ("/api/jobs",{'baselineRunId':run_id,'configs':[{'epochs':1}]})):
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    self.call_auth(path,token_b,body)
                self.assertEqual(denied.exception.code,403)
            _,own=self.call_auth('/api/runs',token_b,{'name':'private-b','params':{}})
            self.assertNotEqual(own['data']['id'],run_id)
            with self.assertRaises(urllib.error.HTTPError) as denied:
                self.call_auth(f"/api/model-assets/{asset['data']['id']}", token_b, {"name": "stolen"}, "PATCH")
            self.assertEqual(denied.exception.code, 404)
            self.assertEqual(self.call_auth(f"/api/model-assets/{asset['data']['id']}", token_a)[1]['data']['name'], 'private.obj')

    def wait(self,path,timeout=45):
        deadline=time.time()+timeout
        while time.time()<deadline:
            item=self.call(path)["data"]
            if item["status"] in {"completed","failed","cancelled"}: return item
            time.sleep(.1)
        self.fail(f"timeout waiting for {path}")

    def wait_status(self,path,statuses,timeout=45):
        deadline=time.time()+timeout
        while time.time()<deadline:
            item=self.call(path)["data"]
            if item["status"] in statuses:return item
            time.sleep(.1)
        self.fail(f"timeout waiting for {path}: {statuses}")

    def test_openapi_pagination_and_server_side_dataset_query(self):
        openapi = self.call("/api/openapi.json")
        self.assertEqual(openapi["openapi"], "3.1.0")
        for index in range(3):
            self.call("/api/runs", {"name": f"page-{index}", "params": {"index": index}})
        page = self.call("/api/runs?page=2&pageSize=2")
        self.assertEqual(len(page["data"]), 1)
        self.assertEqual(page["pagination"]["total"], 3)
        self.assertTrue(page["pagination"]["hasPrevious"])
        dataset = self.call("/api/datasets", {
            "name": "queryable",
            "format": "json",
            "content": [
                {"group": "train", "step": 1, "loss": 0.8},
                {"group": "train", "step": 2, "loss": 0.4},
                {"group": "eval", "step": 2, "loss": 0.5},
            ],
        })["data"]
        result = self.call(f"/api/datasets/{dataset['id']}/query", {
            "filters": [{"field": "step", "operator": "gte", "value": 2}],
            "groupBy": ["group"],
            "aggregates": [{"field": "loss", "op": "avg", "as": "loss"}],
            "sort": {"field": "group"},
        })["data"]
        self.assertEqual(result["rows"], [{"group": "eval", "loss": 0.5}, {"group": "train", "loss": 0.4}])
        self.assertEqual(result["stats"]["matchedRows"], 2)

    def test_dataset_catalog_versions_lineage_join_plan_and_cache(self):
        metrics = self.call("/api/datasets", {
            "name": "partitioned metrics",
            "partitionBy": ["region"],
            "files": [
                {"format": "json", "partitions": {"region": "east"}, "content": [{"run_id": 1, "region": "east", "loss": 0.2}]},
                {"format": "json", "partitions": {"region": "west"}, "content": [{"run_id": 2, "region": "west", "loss": 0.5}]},
            ],
        })["data"]
        labels = self.call("/api/datasets", {
            "name": "labels", "format": "json",
            "content": [{"run_id": 1, "label": "good"}, {"run_id": 2, "label": "check"}],
        })["data"]
        versions = self.call(f"/api/datasets/{metrics['id']}/versions")["data"]
        self.assertEqual((versions[0]["version"], len(versions[0]["manifest"]), versions[0]["partitionBy"]), (1, 2, ["region"]))
        upgraded = self.call(f"/api/datasets/{metrics['id']}/versions", {
            "files": [{"format": "json", "partitions": {"region": "west"}, "content": [{"run_id": 2, "region": "west", "loss": 0.4, "accuracy": 0.9}]}],
            "partitionBy": ["region"],
            "lineage": [{"datasetId": labels["id"], "relation": "enriched", "transform": {"kind": "join"}}],
        })["data"]
        self.assertEqual(upgraded["version"]["version"], 2)
        self.assertTrue(upgraded["version"]["changeSummary"]["compatible"])
        with self.assertRaises(urllib.error.HTTPError) as breaking:
            self.call(f"/api/datasets/{metrics['id']}/versions", {
                "files": [{"format": "json", "partitions": {"region": "west"}, "content": [{"run_id": 2}]}],
                "partitionBy": ["region"],
            })
        self.assertEqual(breaking.exception.code, 409)
        self.assertEqual(len(self.call(f"/api/datasets/{metrics['id']}/versions")["data"]), 2)
        lineage = self.call(f"/api/datasets/{metrics['id']}/lineage")["data"]
        self.assertEqual(lineage["upstream"][0]["source_dataset_id"], labels["id"])
        request = {
            "sources": [{"datasetId": metrics["id"], "alias": "m"}, {"datasetId": labels["id"], "alias": "l"}],
            "joins": [{"left": "m", "right": "l", "on": [{"leftField": "run_id", "rightField": "run_id"}]}],
            "select": [{"field": "m.loss", "as": "loss"}, {"field": "l.label", "as": "label"}],
        }
        first = self.call("/api/analysis/query", request)["data"]
        second = self.call("/api/analysis/query", request)["data"]
        self.assertEqual(first["rows"], [{"loss": 0.4, "label": "check"}])
        self.assertFalse(first["stats"]["cached"])
        self.assertTrue(second["stats"]["cached"])
        plan = self.call("/api/analysis/query", {**request, "explainOnly": True, "cache": False})["data"]
        self.assertIn("READ_PARQUET", plan["plan"])
        queued = self.call("/api/analysis/queries", {**request, "cache": False})["data"]
        completed = self.wait_status(f"/api/analysis/queries/{queued['id']}", {"completed", "failed"})
        self.assertEqual(completed["status"], "completed", completed)

    def test_analysis_query_cancel_and_timeout_states(self):
        dataset = self.call("/api/datasets", {"name": "control", "format": "json", "content": [{"x": 1}]})["data"]
        started = threading.Event()

        class Interruptible:
            def __init__(self): self.interrupted = threading.Event()
            def interrupt(self): self.interrupted.set()

        def blocking_query(*_args, **kwargs):
            connection = Interruptible()
            kwargs["on_connection"](connection)
            started.set()
            while not connection.interrupted.wait(0.01):
                if kwargs["is_cancelled"]():
                    break
            raise RuntimeError("query cancelled")

        with patch("analytics_service.query_sources", side_effect=blocking_query):
            queued = self.call("/api/analysis/queries", {"sources": [{"datasetId": dataset["id"], "alias": "d"}]})["data"]
            self.assertTrue(started.wait(2))
            self.call(f"/api/analysis/queries/{queued['id']}/cancel", {})
            cancelled = self.wait_status(f"/api/analysis/queries/{queued['id']}", {"cancelled", "failed"})
            self.assertEqual(cancelled["status"], "cancelled")
        with patch("analytics_service.query_sources", side_effect=TimeoutError("query exceeded 1 seconds")):
            queued = self.call("/api/analysis/queries", {"sources": [{"datasetId": dataset["id"], "alias": "d"}], "timeoutSeconds": 1})["data"]
            timed_out = self.wait_status(f"/api/analysis/queries/{queued['id']}", {"timed_out", "failed"})
            self.assertEqual(timed_out["status"], "timed_out")

    def test_ml_ingestion_receipts_merge_resume_and_artifact_dedup(self):
        run = self.call("/api/runs", {"name": "distributed", "params": {}})["data"]
        batch = {
            "metrics": [{"step": 1, "trainLoss": 1.0, "eventId": "metric-rank0-step1"}],
            "events": [{"message": "rank 0 epoch 1", "eventId": "event-rank0-step1"}],
            "artifacts": [{"name": "checkpoint.json", "type": "checkpoint", "content": {"step": 1}, "eventId": "checkpoint-step1"}],
        }
        with patch("server.reserve_storage") as reserve:
            first = self.call(f"/api/runs/{run['id']}/batch", batch)
            duplicate = self.call(f"/api/runs/{run['id']}/batch", batch)
        self.assertEqual((first["metrics"], duplicate["metrics"]), (1, 0))
        self.assertEqual((first["events"], duplicate["events"]), (1, 0))
        self.assertEqual(reserve.call_count, 1)
        self.call(f"/api/runs/{run['id']}/batch", {"metrics": [{"step": 1, "accuracy": .75, "eventId": "metric-rank0-step1-accuracy"}]})
        current = self.call(f"/api/runs/{run['id']}")["data"]
        self.assertEqual(len(current["metrics"]), 1)
        self.assertEqual((current["metrics"][0]["trainLoss"], current["metrics"][0]["accuracy"]), (1.0, .75))
        self.assertEqual(len([item for item in current["events"] if item["message"] == "rank 0 epoch 1"]), 1)
        self.assertEqual(len(current["artifacts"]), 1)
        self.call(f"/api/runs/{run['id']}/fail", {"error": "worker lost"})
        resumed = self.call(f"/api/runs/{run['id']}/resume", {"checkpointKey": "checkpoint-step1"})["data"]
        self.assertEqual(resumed["status"], "running")

    def test_model_asset_range_stream_and_gpu_telemetry(self):
        glb,_=server.compile_gltf(local_3d_plan("streamed animated robot"),"standard",binary=True)
        asset=self.call("/api/model-assets",{"name":"stream.glb","format":"glb","content":base64.b64encode(glb).decode()})["data"]
        manifest=self.call(f"/api/model-assets/{asset['id']}/stream-manifest")["data"]
        self.assertEqual((manifest["byteSize"],manifest["acceptRanges"]),(len(glb),True))
        request=urllib.request.Request(self.base+manifest["contentUrl"],headers={"Range":"bytes=0-3"})
        with urllib.request.urlopen(request) as response:
            self.assertEqual((response.status,response.read(),response.headers["Content-Range"]),(206,b"glTF",f"bytes 0-3/{len(glb)}"))
        telemetry={"label":"cad-model","sessionId":"browser-session-1","assetId":asset["id"],"frames":120,"averageFrameMs":8.2,"maxFrameMs":16.1,"gpuFrameMs":4.4,"gpuVendor":"NVIDIA","gpuRenderer":"RTX 5060","webglVersion":"WebGL 2.0","geometries":12,"textures":8,"drawCalls":30,"triangles":50000,"heapBytes":12000000,"transferredBytes":len(glb),"contextLosses":0}
        with patch("server.native_gpu_telemetry",return_value={"name":"NVIDIA RTX 5060","utilizationPercent":42}):
            created=self.call("/api/telemetry/3d",telemetry)["data"]
        self.assertEqual(created["nativeGpu"]["utilizationPercent"],42)
        listed=self.call("/api/telemetry/3d?page=1&pageSize=10")["data"]
        self.assertEqual((listed[0]["id"],listed[0]["gpu_renderer"],listed[0]["transferred_bytes"]),(created["id"],"RTX 5060",len(glb)))

    def test_every_persistent_collection_is_paginated_and_errors_are_problem_details(self):
        paths = [
            "/api/auth/tokens", "/api/auth/members", "/api/tasks", "/api/audit-logs",
            "/api/studio/generations", "/api/studio/agent-runs", "/api/parameter-snapshots",
            "/api/asset-projects", "/api/runs", "/api/jobs", "/api/datasets",
            "/api/analysis/queries", "/api/visualization-specs", "/api/model-assets", "/api/model-scenes",
        ]
        for path in paths:
            payload = self.call(path + "?page=1&pageSize=1")
            self.assertIn("pagination", payload, path)
            self.assertLessEqual(len(payload["data"]), 1, path)
        with self.assertRaises(urllib.error.HTTPError) as invalid:
            self.call("/api/runs?page=0")
        self.assertEqual(invalid.exception.code, 400)
        problem = json.loads(invalid.exception.read())
        self.assertEqual(problem["status"], 400)
        self.assertEqual(problem["code"], "validation_error")
        self.assertTrue(problem["requestId"].startswith("req_"))

    def test_agent_pipeline_text3d_and_glb_export(self):
        agent=self.call("/api/studio/agent-runs",{"prompt":"未来感非对称飞行器","provider":"local","maxCycles":2,"qualityThreshold":85})["data"]
        agent=self.wait(f"/api/studio/agent-runs/{agent['id']}")
        self.assertEqual(agent["status"],"completed"); self.assertGreaterEqual(len(agent["artifacts"]),5)
        job=self.call("/api/studio/text-to-3d",{"prompt":"非模板化机械海马","provider":"local-implicit","resolution":24})["data"]
        job=self.wait(f"/api/studio/text-to-3d/{job['id']}")
        self.assertEqual(job["status"],"completed",job); self.assertTrue(job["previewAssetId"]); self.assertTrue(job["assetId"])
        asset=self.call(f"/api/model-assets/{job['assetId']}")["data"]
        self.assertEqual(asset["format"],"glb"); self.assertTrue(asset["metadata"]["pbrTextureBaked"])
        exported=self.call("/api/studio/export",{"plan":local_3d_plan("开放品类量子仪器"),"quality":"standard","format":"glb"})["data"]
        self.assertEqual(exported["format"],"glb"); self.assertTrue(exported["content"]["base64"].startswith("Z2xURg"))

    def test_provider_catalog_and_cancel_endpoints(self):
        catalog=self.call("/api/studio/text-to-3d/providers")["data"]
        self.assertEqual({item["id"] for item in catalog},{"local-implicit","local-semantic","local-neural","trellis","hunyuan3d","triposr","external","meshy","tripo"})
        job=self.call("/api/studio/text-to-3d",{"prompt":"取消测试复杂生物","provider":"local-implicit","resolution":56})["data"]
        cancelled=self.call(f"/api/studio/text-to-3d/{job['id']}/cancel",{})["data"]
        self.assertTrue(cancelled["cancelRequested"])

    def test_scene_command_preview_confirm_and_history(self):
        plan=local_3d_plan("四旋翼无人机")
        target=plan["parts"][0]["name"]
        preview=self.call("/api/studio/scene-command",{"command":f"把 {target} 向上移动 10cm","plan":plan})["data"]
        self.assertIn(target,preview["affectedNodeIds"]); self.assertNotEqual(preview["previewPlan"],plan)
        applied=self.call("/api/studio/scenes/apply",{"generationId":"draft-test","command":preview["command"],"plan":plan,"operations":preview["operations"]})["data"]
        self.assertEqual(applied["version"],1); self.assertNotEqual(applied["plan"],plan)
        history=self.call("/api/studio/scenes/draft-test")["data"]
        self.assertEqual(history[0]["version"],1); self.assertEqual(history[0]["command"],preview["command"])

    def test_editable_glb_scene_command_modifiers_versions_and_export(self):
        glb,_=server.compile_gltf(local_3d_plan("工业相机"),"standard",binary=True)
        asset=self.call("/api/model-assets",{"name":"editable-camera.glb","format":"glb","content":base64.b64encode(glb).decode(),"metadata":{"test":True}})["data"]
        scene=self.call(f"/api/model-assets/{asset['id']}/scene",{"name":"Camera scene"})["data"]
        self.assertGreater(scene["scene"]["meshCount"],0); self.assertEqual(scene["version"],1)
        command=self.call(f"/api/model-scenes/{scene['id']}/command",{"command":"把最大的部件向上移动 10cm 并改成红色"})["data"]
        self.assertTrue(command["affectedNodeIds"])
        preview=self.call(f"/api/model-scenes/{scene['id']}/preview",{"operations":command["operations"]})["data"]
        self.assertTrue(preview["asset"]["base64"].startswith("Z2xURg"))
        applied=self.call(f"/api/model-scenes/{scene['id']}/operations",{"command":command["command"],"operations":command["operations"]})["data"]
        self.assertEqual(applied["version"],2); self.assertNotEqual(applied["sourceAssetId"],applied["currentAssetId"])
        target=applied["scene"]["nodes"][0]["id"]
        modifier={"id":"mod-test","type":"modifier","targetIds":[target],"payload":{"kind":"subdivision"},"enabled":True}
        modified=self.call(f"/api/model-scenes/{scene['id']}/operations",{"operations":[modifier]})["data"]
        self.assertEqual(modified["version"],3); self.assertTrue(modified["quality"]["passed"])
        restored=self.call(f"/api/model-scenes/{scene['id']}/restore",{"version":1})["data"]
        self.assertEqual(restored["version"],4); self.assertEqual(restored["operations"],[])
        exported=self.call(f"/api/model-scenes/{scene['id']}/export",{})["data"]
        self.assertTrue(exported["content"]["base64"].startswith("Z2xURg"))

    def test_scene_agent_preview_decisions_quality_and_atomic_apply(self):
        glb,_=server.compile_gltf(local_3d_plan("semantic robot"),"standard",binary=True)
        asset=self.call("/api/model-assets",{"name":"agent-robot.glb","format":"glb","content":base64.b64encode(glb).decode()})["data"]
        scene=self.call(f"/api/model-assets/{asset['id']}/scene",{})["data"]
        run=self.call(f"/api/model-scenes/{scene['id']}/agent-runs",{"command":"把最大的部件向上移动 5cm，并改成蓝色金属","maxCycles":3})["data"]
        run=self.wait_status(f"/api/scene-agent-runs/{run['id']}",{"ready","failed"})
        self.assertEqual(run["status"],"ready",run);self.assertTrue(run["preview"]["asset"]["base64"].startswith("Z2xURg"));self.assertTrue(run["decisions"])
        self.assertEqual(self.call(f"/api/model-scenes/{scene['id']}")["data"]["version"],1)
        applied=self.call(f"/api/scene-agent-runs/{run['id']}/apply",{})["data"]
        self.assertEqual(applied["status"],"completed");self.assertEqual(applied["result"]["version"],2);self.assertTrue(any(item["stage"]=="apply" for item in applied["decisions"]))
        destructive=self.call(f"/api/model-scenes/{scene['id']}/agent-runs",{"command":"删除最大的部件"})["data"]
        destructive=self.wait_status(f"/api/scene-agent-runs/{destructive['id']}",{"awaiting-confirmation","failed"})
        self.assertEqual(destructive["status"],"awaiting-confirmation");self.assertEqual(destructive["riskLevel"],"high")
        confirmed=self.call(f"/api/scene-agent-runs/{destructive['id']}/confirm",{})["data"]
        # The embedded worker can advance between enqueue and response serialization.
        self.assertIn(confirmed["status"], {"understanding", "planning", "previewing", "ready"})
        destructive=self.wait_status(f"/api/scene-agent-runs/{destructive['id']}",{"ready","failed"})
        self.assertEqual(destructive["status"],"ready",destructive)
        rejected=self.call(f"/api/scene-agent-runs/{destructive['id']}/reject",{})["data"]
        self.assertEqual(rejected["status"],"rejected");self.assertEqual(self.call(f"/api/model-scenes/{scene['id']}")["data"]["version"],2)

    def test_professional_geometry_worker_preview_checkpoint_and_replace(self):
        glb,_=server.compile_gltf(local_3d_plan("geometry worker robot"),"standard",binary=True)
        asset=self.call("/api/model-assets",{"name":"geometry-robot.glb","format":"glb","content":base64.b64encode(glb).decode()})["data"]
        scene=self.call(f"/api/model-assets/{asset['id']}/scene",{})["data"];target=next(node["id"] for node in scene["scene"]["nodes"] if node.get("meshIndex") is not None)
        with tempfile.TemporaryDirectory() as directory:
            worker=Path(directory)/"geometry_api_worker.py"
            worker.write_text("""import json,sys
request=json.loads(sys.stdin.read())
print(json.dumps({'type':'checkpoint','progress':60,'stage':'brep-fillet','checkpoint':{'phase':'solid-complete'}}),flush=True)
print(json.dumps({'type':'result','format':'glb','content':request['source']['content'],'stats':{'kernel':'contract-opencascade'}}),flush=True)
""",encoding="utf-8")
            with patch.dict(os.environ,{"GEOMETRY_OPENCASCADE_COMMAND":f'"{sys.executable}" "{worker}"'}):
                catalog=self.call("/api/geometry/providers")["data"];self.assertTrue(next(item for item in catalog if item["id"]=="opencascade")["configured"])
                job=self.call(f"/api/model-scenes/{scene['id']}/geometry-jobs",{"provider":"opencascade","operation":{"kind":"fillet","targetIds":[target],"radius":.02,"outputFormat":"glb"}})["data"]
                job=self.wait(f"/api/geometry-jobs/{job['id']}")
        self.assertEqual(job["status"],"completed",job);self.assertTrue(job["previewAssetId"]);self.assertTrue(job["checkpointKey"]);self.assertEqual(job["stage"],"high-quality-replaced")
        self.assertEqual(job["result"]["scene"]["version"],2);self.assertEqual(job["result"]["stats"]["kernel"],"contract-opencascade")

    def test_model_scene_twenty_cycle_acceptance_has_no_pending_tasks(self):
        obj,_=server.compile_obj(local_3d_plan("20-cycle acceptance object"),"standard");glb,_=postprocess_to_glb(obj,"obj","20-cycle acceptance object")
        asset=self.call("/api/model-assets",{"name":"twenty-cycle.glb","format":"glb","content":base64.b64encode(glb).decode()})["data"]
        scene=self.call(f"/api/model-assets/{asset['id']}/scene",{})["data"];target=next(node["id"] for node in scene["scene"]["nodes"] if node.get("meshIndex") is not None)
        for cycle in range(20):
            edit={"id":f"cycle-{cycle}","type":"transform","targetIds":[target],"payload":{"translation":[cycle/100,0,0]},"enabled":True}
            scene=self.call(f"/api/model-scenes/{scene['id']}/operations",{"command":f"acceptance cycle {cycle+1}","operations":[edit]})["data"]
        self.assertEqual(scene["version"],21);self.assertEqual(len(scene["versions"]),21);self.assertTrue(scene["quality"]["passed"])
        exported=self.call(f"/api/model-scenes/{scene['id']}/export",{})["data"]
        self.assertTrue(exported["content"]["base64"].startswith("Z2xURg"))
        with database.connect() as db: active=db.execute("SELECT COUNT(*) FROM text3d_jobs WHERE status IN ('queued','running')").fetchone()[0]
        self.assertEqual(active,0)

    def test_obj_and_external_gltf_become_self_contained_editable_assets(self):
        obj=b"v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 3 2\nf 1 2 4\nf 2 3 4\nf 3 1 4\n"
        raw=self.call("/api/model-assets",{"name":"tetra.obj","format":"obj","content":base64.b64encode(obj).decode()})["data"]
        scene=self.call(f"/api/model-assets/{raw['id']}/scene",{})["data"];canonical=self.call(f"/api/model-assets/{scene['currentAssetId']}")["data"]
        self.assertEqual(canonical["format"],"glb");self.assertEqual(canonical["metadata"]["originalFormat"],"obj");self.assertEqual(scene["scene"]["nodes"][0]["faceCount"],4)
        target=scene["scene"]["nodes"][0]["id"];job=self.call(f"/api/model-scenes/{scene['id']}/operations/async",{"operations":[{"id":"async-bevel","type":"modifier","targetIds":[target],"payload":{"kind":"bevel","amount":.01}}]})["data"]
        job=self.wait(f"/api/model-operation-jobs/{job['id']}");self.assertEqual(job["status"],"completed",job);self.assertEqual(job["result"]["version"],2)

        gltf,_=server.compile_gltf(local_3d_plan("external gltf"),"standard",binary=False);document=json.loads(gltf);uri=document["buffers"][0].pop("uri");binary=base64.b64decode(uri.split(",",1)[1]);document["buffers"][0]["uri"]="mesh.bin"
        asset=self.call("/api/model-assets",{"name":"external.gltf","format":"gltf","content":base64.b64encode(json.dumps(document).encode()).decode(),"resources":[{"name":"mesh.bin","mimeType":"application/octet-stream","base64":base64.b64encode(binary).decode()}]})["data"]
        gltf_scene=self.call(f"/api/model-assets/{asset['id']}/scene",{})["data"];target=gltf_scene["scene"]["nodes"][0]["id"]
        edited=self.call(f"/api/model-scenes/{gltf_scene['id']}/operations",{"operations":[{"id":"repair","type":"modifier","targetIds":[target],"payload":{"kind":"normal-repair"}}]})["data"]
        exported=self.call(f"/api/model-scenes/{edited['id']}/export",{})["data"];exported_document=json.loads(base64.b64decode(exported["content"]["base64"]))
        self.assertTrue(exported_document["buffers"][0]["uri"].startswith("data:application/octet-stream;base64,"))

    def test_run_3d_timeline_and_asset_catalog_lifecycle(self):
        project=self.call("/api/asset-projects",{"name":"vision-assets","description":"integration"})["data"]
        run=self.call("/api/runs",{"name":"asset-linked-run","params":{"epochs":2},"source":"test"})["data"]
        content=base64.b64encode(b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n").decode()
        asset=self.call("/api/model-assets",{"name":"linked.obj","format":"obj","content":content,"metadata":{"projectId":project["id"],"folder":"/checkpoints","assetStage":"edit","tags":["vision","checkpoint"]}})["data"]
        self.assertEqual(asset["projectId"],project["id"]);self.assertEqual(asset["tags"],["vision","checkpoint"])
        self.call(f"/api/runs/{run['id']}/metrics",{"step":2,"accuracy":.91})
        self.call(f"/api/runs/{run['id']}/assets",{"assetId":asset["id"],"role":"checkpoint","step":2})
        timeline=self.call(f"/api/runs/{run['id']}/timeline")["data"]
        self.assertEqual(timeline["frames"][-1]["assets"][0]["asset"]["id"],asset["id"]);self.assertEqual(timeline["frames"][-1]["metrics"]["accuracy"],.91)
        updated=self.call(f"/api/model-assets/{asset['id']}",{"folder":"/release","stage":"lod","tags":["approved"]},"PATCH")["data"]
        self.assertEqual(updated["folder"],"/release");self.assertEqual(updated["stage"],"lod")
        component=self.call(f"/api/model-assets/{asset['id']}/components",{"type":"material","content":{"roughness":.4}})["data"]
        self.assertEqual(component["version"],1)
        self.call(f"/api/model-assets/{asset['id']}/releases",{"status":"approved","reviewer":"qa"})
        detail=self.call(f"/api/model-assets/{asset['id']}")["data"]
        self.assertEqual(detail["stage"],"release");self.assertEqual(len(detail["references"]),1);self.assertEqual(len(detail["components"]),1)
        with self.assertRaises(urllib.error.HTTPError) as protected:
            self.call(f"/api/model-assets/{asset['id']}",method="DELETE")
        self.assertEqual(protected.exception.code,409)
        protected.exception.close()
        filtered=self.call(f"/api/model-assets?projectId={project['id']}&stage=release&tag=approved")["data"]
        self.assertEqual([item["id"] for item in filtered],[asset["id"]])


class MigrationTests(unittest.TestCase):
    def test_existing_database_is_versioned_and_upgraded(self):
        # Windows/CPython 3.14 can retain a SQLite cursor handle until the next GC
        # cycle; cleanup errors are irrelevant to the migration assertions.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory, patch.object(database,"DB_PATH",Path(directory)/"old.db"), patch.object(database,"DATABASE_URL",f"sqlite:///{Path(directory)/'old.db'}"):
            with database.connect() as db:
                db.executescript("""CREATE TABLE text3d_jobs(id TEXT PRIMARY KEY,prompt TEXT,status TEXT,progress INTEGER,stage TEXT,asset_id TEXT,stats TEXT,error TEXT,created_at TEXT,updated_at TEXT);
                CREATE TABLE agent_runs(id TEXT PRIMARY KEY,prompt TEXT,provider TEXT,model TEXT,status TEXT,cycle INTEGER,max_cycles INTEGER,total_tokens INTEGER,total_cost REAL,duration_ms INTEGER,result TEXT,error TEXT,created_at TEXT,updated_at TEXT);
                CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,applied_at TEXT);
                INSERT INTO schema_migrations VALUES(1,'baseline','now');""")
            database.init_database()
            with database.connect() as db:
                versions={row[0] for row in db.execute("SELECT version FROM schema_migrations")}
                text3d={row[1] for row in db.execute("PRAGMA table_info(text3d_jobs)")}
                agents={row[1] for row in db.execute("PRAGMA table_info(agent_runs)")}
                db.execute("INSERT INTO model_scenes(id,name,source_asset_id,current_asset_id,version,operations,scene_json,quality,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",("orphan-scene","orphan","source","current",1,"[]","{}","{}","now","now"))
                db.execute("INSERT INTO model_operation_jobs(id,scene_id,status,progress,stage,operations,result,error,cancel_requested,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",("orphan-job","orphan-scene","running",50,"voxelizing","{}",None,None,0,"now","now"))
                tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(versions,set(range(1,23))); self.assertIn("provider",text3d); self.assertIn("cancel_requested",agents)
            self.assertTrue({"training_jobs","tenants","users","api_tokens","tenant_quotas","audit_logs","credential_refs","durable_tasks","training_lineage"}.issubset(tables))
            self.assertEqual(server.recover_model_operation_jobs(),1)
            with database.connect() as db: orphan=db.execute("SELECT status,error FROM model_operation_jobs WHERE id='orphan-job'").fetchone()
            self.assertEqual(orphan["status"],"failed");self.assertIn("source scene is unchanged",orphan["error"])


if __name__=="__main__": unittest.main()
