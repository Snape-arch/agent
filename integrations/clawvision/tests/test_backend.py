from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ai_studio import local_3d_plan, local_experiment_plan, provider_plan, validate_plan  # noqa: E402
import database  # noqa: E402
from agent_pipeline import _run_stage, create_agent_run, execute_agent_pipeline, serialize_agent_run  # noqa: E402
from database import ASSET_CATALOG_SCHEMA, INTELLIGENT_GEOMETRY_SCHEMA, POSTGRES_SCHEMA, SQLITE_SCHEMA, PostgresConnection  # noqa: E402
from geometry_worker import provider_catalog as geometry_provider_catalog, run_provider as run_geometry_provider  # noqa: E402
from implicit_geometry import marching_tetrahedra  # noqa: E402
from mesh_generator import compile_gltf, compile_obj  # noqa: E402
from object_store import LocalObjectStore, S3ObjectStore  # noqa: E402
from text_to_3d_worker import semantic_field  # noqa: E402
from text3d_providers import run_provider  # noqa: E402
from mesh_postprocess import postprocess_to_glb  # noqa: E402
from mesh_quality import assess_mesh  # noqa: E402
from scene_operations import apply_operations, interpret_scene_command  # noqa: E402
from asset_scene import apply_asset_operations, canonicalize_mesh_asset, interpret_asset_command, pack_glb, parse_asset, quality_report, scene_manifest  # noqa: E402


class AiStudioTests(unittest.TestCase):
    def test_chinese_experiment_command_changes_params_and_runs(self):
        plan = local_experiment_plan("把学习率改成 0.0005，Batch Size 改成 128，显示损失曲线并运行")
        self.assertEqual(plan["patch"]["learningRate"], 0.0005)
        self.assertEqual(plan["patch"]["batchSize"], 128)
        self.assertTrue(plan["execute"])
        self.assertEqual(plan["visualization"]["pluginId"], "core.time-series")

    def test_sweep_and_grid_expand_real_configs(self):
        sweep = local_experiment_plan("学习率从 0.0001 到 0.01 扫描 5 个点并运行")
        grid = local_experiment_plan("二维网格：学习率从 0.0001 到 0.001 3 个点，batch size 32,64,128")
        self.assertEqual(sweep["jobKind"], "sweep")
        self.assertEqual(len(sweep["configs"]), 5)
        self.assertEqual(grid["jobKind"], "grid")
        self.assertEqual(len(grid["configs"]), 9)

    def test_parametric_models_cover_reference_categories(self):
        categories = {local_3d_plan(prompt)["template"] for prompt in ("无人机", "机器人", "工业相机", "概念汽车", "复古收音机", "涡轮引擎")}
        self.assertEqual(categories, {"drone", "robot", "camera", "vehicle", "radio", "engine"})
        plan = local_3d_plan("蓝色无人机，复杂度 8，曲面 0.7，连接密度 0.8")
        self.assertGreater(len(plan["parts"]), 8)
        self.assertTrue(validate_plan(plan)["valid"])
        self.assertEqual(len(plan["agents"]), 5)

    def test_all_reference_and_open_product_categories(self):
        prompts = ("跑车", "腕表", "项链", "建筑塔楼", "固定翼飞机", "椅子", "科幻信标", "智能镜子", "头戴耳机", "球鞋", "背包", "咖啡机", "水杯容器", "控制面板", "未知量子设备")
        categories = {local_3d_plan(prompt)["template"] for prompt in prompts}
        self.assertEqual(categories, {"vehicle", "watch", "jewelry", "architecture", "aircraft", "furniture", "prop", "mirror", "headphones", "shoe", "backpack", "appliance", "container", "panel", "product"})

    def test_plan_compiles_to_versionable_high_resolution_obj(self):
        plan = local_3d_plan("高精度四旋翼无人机，复杂度 9")
        payload, stats = compile_obj(plan, "ultra")
        self.assertTrue(payload.startswith(b"# ClawVision"))
        self.assertIn(b"\nv ", payload)
        self.assertIn(b"\nf ", payload)
        self.assertGreater(stats["vertices"], 10_000)
        self.assertGreater(stats["faces"], 15_000)
        self.assertLessEqual(stats["faces"], 500_000)

    def test_gltf_glb_and_csg_exports(self):
        plan = local_3d_plan("未知量子设备")
        plan["parts"][0]["booleanOperation"] = "base"
        plan["parts"][1]["booleanOperation"] = "subtract"
        obj, obj_stats = compile_obj(plan, "standard")
        gltf, _ = compile_gltf(plan, "standard", binary=False)
        glb, _ = compile_gltf(plan, "standard", binary=True)
        self.assertIn(b"clawvision watertight sdf/csg", obj.lower())
        gltf_document = json.loads(gltf)
        self.assertTrue(gltf_document["asset"]["version"] == "2.0")
        self.assertIn("TEXCOORD_0", gltf_document["meshes"][0]["primitives"][0]["attributes"])
        self.assertEqual(glb[:4], b"glTF")
        self.assertGreater(obj_stats["faces"], 100)

    def test_non_parametric_text_mesh_field(self):
        vertices, faces = marching_tetrahedra(semantic_field("一只未来机械龙生物"), ((-3, -3, -3), (3, 3, 3)), 16)
        self.assertGreater(len(vertices), 100)
        self.assertGreater(len(faces), 100)

    def test_command_gpu_provider_contract_and_pbr_postprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            worker=Path(directory)/"provider.py"
            worker.write_text("""import base64,json,sys
json.loads(sys.stdin.read())
obj=b'v 0 0 0\\nv 1 0 0\\nv 0 1 0\\nv 0 0 1\\nf 1 2 3\\nf 1 4 2\\nf 1 3 4\\nf 2 4 3\\n'
print(json.dumps({'type':'progress','progress':50,'stage':'gpu-inference'}),flush=True)
print(json.dumps({'type':'result','format':'obj','content':base64.b64encode(obj).decode(),'stats':{'model':'fake-trellis'}}),flush=True)
""",encoding="utf-8")
            command=f'"{sys.executable}" "{worker}"'
            with patch.dict(os.environ,{"TEXT3D_TRELLIS_COMMAND":command}):
                progress=[]; result=run_provider("trellis",{"prompt":"test","imageBase64":None},30,lambda p,s:progress.append((p,s)),lambda:False)
            glb,stats=postprocess_to_glb(result.content,result.format,"test")
            document,_=parse_asset(glb,"glb")
            self.assertEqual(glb[:4],b"glTF"); self.assertTrue(stats["pbrTextureBaked"]); self.assertTrue(stats["rigged"]);self.assertEqual((len(document["images"]),len(document["skins"]),len(document["animations"])),(3,1,1));self.assertEqual(progress[0][0],50)

    def test_managed_meshy_and_tripo_api_contracts(self):
        obj=b'v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 2 3\nf 1 4 2\nf 1 3 4\nf 2 4 3\n'
        glb,_=postprocess_to_glb(obj,"obj","managed-api-test")
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_): pass
            def _json(self,payload):
                encoded=json.dumps(payload).encode(); self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
            def do_POST(self):
                length=int(self.headers.get("Content-Length","0")); self.rfile.read(length)
                if self.path.endswith("/meshy/text-to-3d"): self._json({"result":"refine-1" if getattr(self.server,"meshy_posts",0) else "preview-1"}); self.server.meshy_posts=getattr(self.server,"meshy_posts",0)+1
                elif self.path.endswith("/tripo/generation/text-to-model"): self._json({"data":{"task_id":"tripo-1"}})
                else: self.send_error(404)
            def do_GET(self):
                base=f"http://127.0.0.1:{self.server.server_port}"
                if self.path.endswith("/meshy/text-to-3d/preview-1"): self._json({"status":"SUCCEEDED","progress":100})
                elif self.path.endswith("/meshy/text-to-3d/refine-1"): self._json({"status":"SUCCEEDED","progress":100,"model_urls":{"glb":base+"/asset.glb"}})
                elif self.path.endswith("/tripo/tasks/tripo-1"): self._json({"data":{"status":"SUCCESS","progress":100,"output":{"model_url":base+"/asset.glb"}}})
                elif self.path=="/asset.glb": self.send_response(200); self.send_header("Content-Length",str(len(glb))); self.end_headers(); self.wfile.write(glb)
                else: self.send_error(404)
        http=ThreadingHTTPServer(("127.0.0.1",0),Handler); thread=threading.Thread(target=http.serve_forever,daemon=True); thread.start(); base=f"http://127.0.0.1:{http.server_port}"
        try:
            with patch.dict(os.environ,{"TEXT3D_MESHY_API_KEY":"test","TEXT3D_MESHY_BASE_URL":base+"/meshy","TEXT3D_TRIPO_API_KEY":"test","TEXT3D_TRIPO_BASE_URL":base+"/tripo","TEXT3D_API_POLL_SECONDS":"0.01"}):
                meshy=run_provider("meshy",{"prompt":"robot"},10,lambda *_:None,lambda:False)
                tripo=run_provider("tripo",{"prompt":"robot"},10,lambda *_:None,lambda:False)
            self.assertEqual(meshy.content[:4],b"glTF"); self.assertEqual(meshy.stats["provider"],"meshy")
            self.assertEqual(tripo.content[:4],b"glTF"); self.assertEqual(tripo.stats["provider"],"tripo")
        finally: http.shutdown(); http.server_close(); thread.join(timeout=3)

    def test_mesh_quality_gate_and_non_destructive_scene_commands(self):
        plan=local_3d_plan("四旋翼无人机"); target=plan["parts"][0]["name"]
        preview=interpret_scene_command(f"把 {target} 向上移动 10cm",plan)
        self.assertEqual(plan["parts"][0]["position"],local_3d_plan("四旋翼无人机")["parts"][0]["position"])
        self.assertNotEqual(preview["previewPlan"]["parts"][0]["position"],plan["parts"][0]["position"])
        duplicate=apply_operations(plan,[{"type":"duplicate","targetIds":[target],"payload":{"offset":[1,0,0]}}])
        self.assertEqual(len(duplicate["parts"]),len(plan["parts"])+1)
        obj,_=compile_obj(plan,"standard"); glb,_=postprocess_to_glb(obj,"obj","quality")
        report=assess_mesh(glb,"glb",75); self.assertTrue(report["passed"],report); self.assertGreaterEqual(report["metrics"]["vertices"],100)
        numbered=interpret_scene_command("把 Arm 1 向上移动 10cm",plan)
        self.assertAlmostEqual(numbered["operations"][0]["payload"]["position"][1],.1)

    def test_glb_scene_manifest_actual_modifiers_and_semantic_selection(self):
        source,_=compile_gltf(local_3d_plan("工业相机"),"standard",binary=True); document,binary=parse_asset(source,"glb"); original_document=json.dumps(document,sort_keys=True); manifest=scene_manifest(document)
        embedded_gltf,_=compile_gltf(local_3d_plan("工业相机"),"standard",binary=False);_,embedded_binary=parse_asset(embedded_gltf,"gltf");self.assertGreater(len(embedded_binary),100)
        self.assertGreater(manifest["meshCount"],0); command=interpret_asset_command("把最大的部件向上移动 10cm",manifest); self.assertTrue(command["affectedNodeIds"])
        target=command["affectedNodeIds"][0]; operations=command["operations"]+[
            {"id":"material","type":"material","targetIds":[target],"payload":{"color":"#ef4444","metallic":.9}},
            {"id":"subdivide","type":"modifier","targetIds":[target],"payload":{"kind":"subdivision"},"enabled":True},
        ]
        changed,next_binary,stats=apply_asset_operations(document,binary,operations); output=pack_glb(changed,next_binary); changed_manifest=scene_manifest(changed); report=quality_report(output,changed_manifest,70)
        self.assertTrue(report["passed"],report); self.assertTrue(stats); self.assertGreater(stats[0]["facesAfter"],stats[0]["facesBefore"])
        self.assertEqual(json.dumps(document,sort_keys=True),original_document)

        mesh_nodes=[node["id"] for node in manifest["nodes"] if node.get("meshIndex") is not None];source_node=mesh_nodes[0]
        boolean_document,boolean_binary,boolean_stats=apply_asset_operations(document,binary,[{"id":"copy","type":"duplicate","targetIds":[source_node],"payload":{"offset":[.1,0,0]}},{"id":"boolean","type":"modifier","targetIds":[source_node,f"node_{len(document['nodes'])}"],"payload":{"kind":"boolean","operator":"union","resolution":16},"enabled":True}])
        boolean_output=pack_glb(boolean_document,boolean_binary);boolean_quality=quality_report(boolean_output,scene_manifest(boolean_document),60)
        self.assertEqual(boolean_stats[0]["kernel"],"voxel-watertight");self.assertEqual(boolean_quality["metrics"]["nonManifoldEdges"],0);self.assertGreater(len(boolean_output),len(source))
        for operator in ("subtract","intersect"):
            result_document,result_binary,result_stats=apply_asset_operations(document,binary,[{"id":"copy","type":"duplicate","targetIds":[source_node],"payload":{"offset":[.1,0,0]}},{"id":operator,"type":"modifier","targetIds":[source_node,f"node_{len(document['nodes'])}"],"payload":{"kind":"boolean","operator":operator,"resolution":16},"enabled":True}])
            topology=quality_report(pack_glb(result_document,result_binary),scene_manifest(result_document),50)["metrics"];self.assertEqual(result_stats[0]["operator"],operator);self.assertEqual(topology["boundaryEdges"],0);self.assertEqual(topology["nonManifoldEdges"],0)

        obj=b"v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 3 2\nf 1 2 4\nf 2 3 4\nf 3 1 4\n";obj_document,obj_binary=canonicalize_mesh_asset(obj,"obj","tetra")
        self.assertEqual(scene_manifest(obj_document)["nodes"][0]["faceCount"],4);self.assertTrue(pack_glb(obj_document,obj_binary).startswith(b"glTF"))

        ply=b"ply\nformat ascii 1.0\nelement vertex 4\nproperty float x\nproperty float y\nproperty float z\nelement face 4\nproperty list uchar int vertex_indices\nend_header\n0 0 0\n1 0 0\n0 1 0\n0 0 1\n3 0 2 1\n3 0 1 3\n3 1 2 3\n3 2 0 3\n"
        ply_document,ply_binary=canonicalize_mesh_asset(ply,"ply","tetra-point-cloud")
        self.assertEqual(scene_manifest(ply_document)["nodes"][0]["faceCount"],4);self.assertTrue(pack_glb(ply_document,ply_binary).startswith(b"glTF"))

        points=b"ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n0 0 0 255 0 0\n1 0 0 0 255 0\n0 1 0 0 0 255\n"
        points_document,_=canonicalize_mesh_asset(points,"ply","colored-points")
        primitive=points_document["meshes"][0]["primitives"][0]
        self.assertEqual(primitive["mode"],0);self.assertIn("COLOR_0",primitive["attributes"])

    def test_geometry_worker_contract_checkpoint_and_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            worker=Path(directory)/"geometry_provider.py"
            worker.write_text("""import json,sys
request=json.loads(sys.stdin.read())
print(json.dumps({'type':'checkpoint','progress':55,'stage':'exact-kernel','checkpoint':{'phase':'brep-done'}}),flush=True)
print(json.dumps({'type':'result','format':request['source']['format'],'content':request['source']['content'],'stats':{'kernel':'fake-opencascade'}}),flush=True)
""",encoding="utf-8")
            command=f'"{sys.executable}" "{worker}"';progress=[]
            with patch.dict(os.environ,{"GEOMETRY_OPENCASCADE_COMMAND":command}):
                provider=next(item for item in geometry_provider_catalog() if item["id"]=="opencascade")
                result=run_geometry_provider("opencascade",{"source":{"format":"glb","content":"Z2xURg=="}},10,lambda p,s,c:progress.append((p,s,c)),lambda:False)
            self.assertTrue(provider["configured"]);self.assertTrue(provider["exact"]);self.assertEqual(result.content,b"glTF");self.assertEqual(progress[0][2]["phase"],"brep-done")

    def test_agent_pipeline_quality_rework_and_retry(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(database, "DB_PATH", Path(directory) / "test.db"), patch.object(database, "DATABASE_URL", f"sqlite:///{Path(directory) / 'test.db'}"):
            database.init_database()
            previous = os.environ.get("CLAWVISION_OBJECT_DIR"); os.environ["CLAWVISION_OBJECT_DIR"] = str(Path(directory) / "objects")
            try:
                store = LocalObjectStore(); run_id = create_agent_run("未知量子设备", "local", "local", 2)
                execute_agent_pipeline(run_id, {"prompt": "未知量子设备", "provider": "local", "model": "local", "maxCycles": 2, "qualityThreshold": 100}, store)
                run = serialize_agent_run(run_id, store)
                self.assertEqual(run["status"], "completed")
                self.assertEqual(run["cycle"], 1)
                self.assertGreaterEqual(len(run["artifacts"]), 9)
                attempts = {"count": 0}
                def flaky():
                    attempts["count"] += 1
                    if attempts["count"] == 1: raise RuntimeError("transient")
                    return {"ok": True}, {"provider": "local", "total_tokens": 1}
                _run_stage(run_id, 2, "surface", None, flaky, store, max_attempts=2)
                run = serialize_agent_run(run_id, store)
                self.assertTrue(any(stage["status"] == "failed" and stage["attempt"] == 1 for stage in run["stages"]))
            finally:
                if previous is None: os.environ.pop("CLAWVISION_OBJECT_DIR", None)
                else: os.environ["CLAWVISION_OBJECT_DIR"] = previous

    def test_online_experiment_plan_rebuilds_safe_patch(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def read(self):
                content = {**local_experiment_plan("show embedding"), "params": {**local_experiment_plan("show embedding")["params"], "learningRate": .0003}}
                return json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode()
        with patch("ai_studio.urlopen", return_value=Response()):
            plan = provider_plan("deepseek", "test-key", "test-model", "change learning rate", "experiment")
        self.assertEqual(plan["patch"], {"learningRate": .0003})
        self.assertEqual(plan["configs"][0]["learningRate"], .0003)


class AdapterTests(unittest.TestCase):
    def test_schemas_have_feature_tables(self):
        for schema in (SQLITE_SCHEMA, POSTGRES_SCHEMA):
            for table in ("studio_generations", "studio_feedback", "parameter_snapshots", "model_assets", "visualization_specs", "studio_scene_versions", "model_scenes", "model_scene_versions", "model_operation_jobs"):
                self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", schema)
        for table in ("asset_projects","run_asset_links","asset_components","asset_releases"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}",ASSET_CATALOG_SCHEMA)
        for table in ("scene_agent_runs","scene_agent_decisions","geometry_jobs"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}",INTELLIGENT_GEOMETRY_SCHEMA)

    def test_postgres_wrapper_rewrites_parameters_and_commits(self):
        class FakeConnection:
            def __init__(self): self.statement = None; self.params = None; self.committed = False; self.closed = False
            def execute(self, statement, params): self.statement, self.params = statement, params; return self
            def commit(self): self.committed = True
            def rollback(self): pass
            def close(self): self.closed = True
        raw = FakeConnection()
        with PostgresConnection(raw) as db:
            db.execute("SELECT * FROM runs WHERE id=?", ("run_1",))
        self.assertEqual(raw.statement, "SELECT * FROM runs WHERE id=%s")
        self.assertTrue(raw.committed and raw.closed)

    def test_local_store_health_and_traversal_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = os.environ.get("CLAWVISION_OBJECT_DIR")
            os.environ["CLAWVISION_OBJECT_DIR"] = directory
            try:
                store = LocalObjectStore()
                key = store.put_json("runs/a.json", {"ok": True})
                self.assertEqual(store.get_json(key), {"ok": True})
                binary_key = store.put_bytes("datasets/a.parquet", b"PAR1", "application/vnd.apache.parquet")
                self.assertEqual(store.get_bytes(binary_key), b"PAR1")
                self.assertTrue(store.health_check()["ok"])
                with self.assertRaises(ValueError): store.put_json("../escape.json", {})
                with self.assertRaises(ValueError): store.get_json("../escape.json")
                with self.assertRaises(ValueError): store.put_bytes("../escape.parquet", b"PAR1")
                with self.assertRaises(ValueError): store.get_bytes("../escape.parquet")
            finally:
                if previous is None: os.environ.pop("CLAWVISION_OBJECT_DIR", None)
                else: os.environ["CLAWVISION_OBJECT_DIR"] = previous

    def test_s3_contract_with_fake_client(self):
        class Body:
            def __init__(self, payload): self.payload = payload
            def read(self): return self.payload
        class Client:
            def __init__(self): self.objects = {}
            def put_object(self, **kwargs): self.objects[kwargs["Key"]] = kwargs["Body"]
            def get_object(self, **kwargs): return {"Body": Body(self.objects[kwargs["Key"]])}
            def head_bucket(self, **kwargs): return {"ResponseMetadata": {"HTTPStatusCode": 200}}
        store = object.__new__(S3ObjectStore)
        store.bucket = "test"; store.client = Client()
        store.endpoint_url = "http://minio:9000"; store.access_key = "access"; store.secret_key = "secret"; store.region = "us-east-1"
        self.assertEqual(store.put_json("a.json", {"ok": True}), "a.json")
        self.assertEqual(store.get_json("a.json"), {"ok": True})
        self.assertEqual(store.put_bytes("a.parquet", b"PAR1"), "a.parquet")
        self.assertEqual(store.get_bytes("a.parquet"), b"PAR1")
        self.assertEqual(store.query_uri("datasets/a.parquet"), "s3://test/datasets/a.parquet")
        class DuckConnection:
            def __init__(self): self.statements = []
            def execute(self, statement): self.statements.append(statement)
        connection = DuckConnection()
        store.configure_duckdb(connection)
        statements = "\n".join(connection.statements)
        self.assertIn("LOAD httpfs", statements)
        self.assertIn("s3_endpoint", statements)
        self.assertIn("s3_url_style='path'", statements)
        self.assertTrue(store.health_check()["ok"])


if __name__ == "__main__":
    unittest.main()
