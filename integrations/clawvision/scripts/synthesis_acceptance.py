"""Isolated ASGI + standalone worker + authenticated synthetic ZIP acceptance."""
import base64
import hashlib
import io
import json
import sys
import time
import zipfile
from pathlib import Path

from acceptance_support import local_api, local_worker, authenticate, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk"))
from clawvision.evaluation import EvaluationClient

CUBE = b"v -1 -1 -1\nv 1 -1 -1\nv 1 1 -1\nv -1 1 -1\nv -1 -1 1\nv 1 -1 1\nv 1 1 1\nv -1 1 1\nf 1 4 3 2\nf 5 6 7 8\nf 1 2 6 5\nf 4 8 7 3\nf 1 5 8 4\nf 2 3 7 6\n"

def seed(url, token):
    client = EvaluationClient(url, token)
    run = request(url,"/api/runs",{"name":"synthesis process fixture", "source":"test", "params":{}},token)["data"]
    suite = client.create_test_set("Process fixture (not industrial evidence)",[{"id":"failure","label":"gear"}],classes=["gear","bolt"])
    report = client.evaluate(suite["id"],run["id"],[{"sampleId":"failure","label":"bolt"}])
    asset = request(url,"/api/model-assets",{"name":"process cube.obj","format":"obj","content":base64.b64encode(CUBE).decode()},token)["data"]
    plan = client.create_scene_plan("CPU synthesis process fixture",report["id"],"failure",asset["id"],"gear",config={"count":3,
        "ranges":{"cameraAzimuth":[0,0],"cameraElevation":[0,0],"cameraDistance":[3,3],"occluderSize":[.6,.6]}})
    return client, plan, report

def wait(client, job):
    deadline = time.monotonic()+30
    while time.monotonic()<deadline:
        result = client.get_synthesis_job(job["id"])
        if result["status"] in {"completed","failed"}:
            assert result["status"] == "completed", result
            return result
        time.sleep(.1)
    raise RuntimeError("synthesis worker timeout")

def main():
    with local_api() as (url, root):
        token = authenticate(url,use_environment=False)
        client, plan, _ = seed(url,token)
        job = client.render_scene(plan["id"])
        assert client.cancel_synthesis(job["id"])["status"] == "cancelled"
        assert client.retry_synthesis(job["id"])["status"] == "queued"
        with local_worker(root):
            done = wait(client,job)
            rejected = wait(client,client.render_scene(plan["id"],min_visible_pixels=262144))
        assert done["accepted"] == 3 and rejected["accepted"] == 0
        package = client.download_synthesis_package(job["id"])
        assert package == client.download_synthesis_package(job["id"])
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            coco = json.loads(archive.read("annotations.json"))
            assert len(coco["images"]) == 3
            assert manifest["digest"] == done["digest"]
            frame = manifest["manifest"]["frames"][0]
            assert hashlib.sha256(archive.read("accepted/images/0000.png")).hexdigest() == frame["artifacts"]["image"]["sha256"]
            assert 0 < frame["annotation"]["visibleFraction"] < 1
        with zipfile.ZipFile(io.BytesIO(client.download_synthesis_package(rejected["id"]))) as archive:
            assert json.loads(archive.read("annotations.json"))["images"] == []
            assert "rejected/masks/0000.png" in archive.namelist()
        print(json.dumps({"ok":True,"transport":"ASGI","worker":"standalone","accepted":done["accepted"],"rejected":rejected["rejected"],"zipSha256":hashlib.sha256(package).hexdigest()}))

if __name__ == "__main__": main()
