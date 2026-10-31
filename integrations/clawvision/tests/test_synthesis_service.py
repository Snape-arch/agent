"""Immutable packages, tenant isolation, checkpoints and lease fencing."""
import hashlib
import io
import json
import unittest
import zipfile
from unittest.mock import patch

import test_scenario_service as scene_tests
from test_synthetic_renderer import CUBE, decode_png, fixed_config
import database
import durable_queue
import synthetic_renderer as renderer
from api_contract import Pagination
from errors import ConflictError, NotFoundError, ValidationError
from synthesis_service import SynthesisService, LeaseLost

class SynthesisServiceTests(unittest.TestCase):
    setUpScene = scene_tests.ScenarioServiceTests.setUp
    tearDown = scene_tests.ScenarioServiceTests.tearDown
    asset = scene_tests.ScenarioServiceTests.asset

    def setUp(self):
        self.setUpScene()
        self.store.put_bytes("asset-scene.obj", CUBE)
        self.plan = self.service.create("default", {**self.request, "config": fixed_config()})
        self.service = SynthesisService(database.connect, self.store, self.lock)

    def job(self, **options):
        return self.service.create("default", self.plan["id"], options)

    def execute(self, job, owner="test-worker"):
        self.assertTrue(durable_queue.lease(job["taskId"], owner))
        result = self.service.execute("default", job["id"], owner)
        self.assertTrue(durable_queue.finish(job["taskId"], owner, result))
        return self.service.get("default", job["id"])

    def test_completed_package_is_reproducible_pixel_verified_and_training_only(self):
        job = self.job()
        self.assertEqual(job["id"], self.job()["id"])
        self.assertEqual(self.service.list("default", Pagination(1,1), self.plan["id"])["pagination"]["total"], 1)
        with self.assertRaises(ConflictError): self.service.manifest("default", job["id"])
        done = self.execute(job)
        self.assertEqual((done["status"], done["completed"], done["accepted"]), ("completed", 3, 3))
        frames = self.service.frames("default", job["id"], Pagination(1,2))
        self.assertEqual(len(frames["data"]), 2)
        self.assertTrue(frames["pagination"]["hasNext"])
        self.assertNotIn("key", frames["data"][0]["artifacts"]["image"])
        package = self.service.package("default", job["id"])
        self.assertEqual(package, self.service.package("default", job["id"]))
        manifest = self.service.manifest("default", job["id"])
        self.assertEqual(manifest["manifest"]["usage"], "synthetic-training-only")
        self.assertEqual(manifest["manifest"]["source"]["reportDigest"], self.report["digest"])
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            coco = json.loads(archive.read("annotations.json"))
            self.assertEqual(len(coco["images"]), 3)
            self.assertEqual(coco["categories"], [{"id": 1, "name": "gear"}])
            self.assertEqual(len(json.loads(archive.read("classification.json"))), 3)
            mask = decode_png(archive.read("accepted/masks/0000.png")) > 0
            self.assertEqual(coco["annotations"][0]["area"], int(mask.sum()))
            self.assertEqual(coco["annotations"][0]["bbox"], renderer.bbox(mask))
            self.assertEqual(hashlib.sha256(archive.read("accepted/images/0000.png")).hexdigest(), frames["data"][0]["artifacts"]["image"]["sha256"])
        for action in ("cancel", "retry"):
            with self.assertRaises(ConflictError): self.service.action("default", job["id"], action)
        # A worker crash between dataset commit and queue completion is harmless.
        self.assertEqual(self.service.execute("default", job["id"], "old-owner")["digest"], done["digest"])

    def test_rejected_samples_are_audited_but_excluded_from_training_annotations(self):
        job = self.job(minVisiblePixels=262144)
        done = self.execute(job)
        self.assertEqual((done["accepted"], done["rejected"]), (0, 3))
        result = self.service.manifest("default", job["id"])["manifest"]
        self.assertEqual(result["coco"]["images"], [])
        self.assertEqual(result["coco"]["annotations"], [])
        self.assertIn("insufficient-visible-pixels", result["frames"][0]["annotation"]["rejectionReasons"])
        with zipfile.ZipFile(io.BytesIO(self.service.package("default", job["id"]))) as archive:
            self.assertIn("rejected/images/0000.png", archive.namelist())
            self.assertFalse(any(name.startswith("accepted/") for name in archive.namelist()))

    def test_cancelled_worker_cannot_commit_and_retry_retains_saved_frames(self):
        job = self.job()
        durable_queue.lease(job["taskId"], "old")
        real_render, calls = renderer.render, []
        def cancelled_render(*args, **kwargs):
            result = real_render(*args, **kwargs)
            calls.append(1)
            if len(calls) == 2: self.service.action("default", job["id"], "cancel")
            return result
        with patch.object(renderer, "render", cancelled_render), self.assertRaises(LeaseLost):
            self.service.execute("default", job["id"], "old")
        cancelled = self.service.get("default", job["id"])
        self.assertEqual((cancelled["status"], cancelled["completed"]), ("cancelled", 1))
        saved = self.service.frames("default", job["id"], Pagination(1,25))["data"][0]
        self.service.action("default", job["id"], "retry")
        durable_queue.lease(job["taskId"], "new")
        with self.assertRaises(LeaseLost): self.service.execute("default", job["id"], "old")
        with patch.object(renderer, "render", wraps=real_render) as render:
            self.service.execute("default", job["id"], "new")
            self.assertEqual(render.call_count, 2)
        self.assertEqual(self.service.frames("default", job["id"], Pagination(1,25))["data"][0], saved)
        self.assertEqual(self.service.get("default", job["id"])["completed"], 3)

    def test_expired_lease_is_fenced_and_reaped_without_touching_other_kinds(self):
        job = self.job()
        durable_queue.lease(job["taskId"], "expired")
        other = durable_queue.enqueue("default", "test", "unused", {}, "other-job")
        durable_queue.lease(other["id"], "other")
        with database.connect() as db:
            db.execute("UPDATE durable_tasks SET lease_expires_at='2000-01-01' WHERE id IN (?,?)", (job["taskId"],other["id"]))
        with self.assertRaises(LeaseLost): self.service.execute("default", job["id"], "expired")
        self.assertEqual(durable_queue.reap_expired(kind="synthesis"), 1)
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM durable_tasks WHERE id=?", (other["id"],)).fetchone()["status"], "leased")
        self.assertEqual(self.execute(job)["status"], "completed")

    def test_invalid_requests_never_enqueue_and_tenants_cannot_read_any_artifact(self):
        invalid = [None, [], {"unknown": 1}, {"variantIndices": []}, {"variantIndices": [True]}, {"variantIndices": [3]},
                   {"variantIndices": [0,0]}, {"minVisiblePixels": 0}, {"minVisiblePixels": True}, {"minVisibleFraction": float("nan")},
                   {"minVisibleFraction": True}, {"minVisibleFraction": 2}, {"rejectClipped": "true"}]
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(ValidationError): self.service.create("default", self.plan["id"], request)
        with database.connect() as db: self.assertEqual(db.execute("SELECT COUNT(*) AS n FROM synthesis_jobs").fetchone()["n"], 0)
        job = self.job(variantIndices=[1])
        self.execute(job)
        calls = [(self.service.get, (job["id"],)), (self.service.frames, (job["id"], Pagination(1,25))),
                 (self.service.manifest, (job["id"],)), (self.service.package, (job["id"],)),
                 (self.service.artifact, (job["id"],1,"mask")), (self.service.action, (job["id"],"cancel")),
                 (self.service.list, (Pagination(1,25),self.plan["id"])), (self.service.create, (self.plan["id"],{}))]
        for function, args in calls:
            with self.subTest(function=function.__name__), self.assertRaises(NotFoundError): function("other", *args)
        for index, kind in ((0,"image"),(1,"unknown")):
            with self.assertRaises(NotFoundError): self.service.artifact("default", job["id"], index, kind)

    def test_hash_tamper_missing_output_and_limits_are_reported(self):
        job = self.job(variantIndices=[0])
        self.execute(job)
        manifest = self.service.manifest("default", job["id"])["manifest"]
        info = manifest["frames"][0]["artifacts"]["image"]
        original = self.store.get_bytes(info["key"])
        self.store.put_bytes(info["key"], b"x"*len(original))
        with self.assertRaisesRegex(ConflictError,"hash changed"): self.service.package("default", job["id"])
        self.store.put_bytes(info["key"], b"x")
        with self.assertRaisesRegex(ConflictError,"size changed"): self.service.artifact("default", job["id"],0,"image")
        self.store.delete(info["key"])
        with self.assertRaisesRegex(ConflictError,"missing"): self.service.artifact("default", job["id"],0,"image")
        self.store.put_bytes(info["key"], original)
        with patch("synthesis_service.MAX_OUTPUT", 1), self.assertRaises(ConflictError): self.service.package("default", job["id"])
        with database.connect() as db: key = db.execute("SELECT manifest_key FROM synthesis_jobs WHERE id=?", (job["id"],)).fetchone()["manifest_key"]
        self.store.put_bytes(key,b"tampered")
        with self.assertRaises(ConflictError): self.service.manifest("default", job["id"])

    def test_environment_asset_quota_and_budget_fail_without_fabricating_success(self):
        job = self.job(variantIndices=[0])
        durable_queue.lease(job["taskId"], "test")
        with patch.object(renderer,"source_digest", return_value="changed"), self.assertRaises(ConflictError):
            self.service.execute("default", job["id"], "test")
        durable_queue.fail(job["taskId"],"test","environment changed",retry=False)
        self.assertEqual(self.service.get("default",job["id"])["status"],"failed")
        self.service.action("default",job["id"],"retry")
        durable_queue.lease(job["taskId"],"test")
        with patch("synthesis_service.reserve_storage",side_effect=ValidationError("quota exceeded")), self.assertRaisesRegex(ValidationError,"quota"):
            self.service.execute("default",job["id"],"test")
        self.assertEqual(self.service.get("default",job["id"])["completed"],0)
        self.store.put_bytes("asset-scene.obj",b"changed")
        with self.assertRaises(ConflictError): self.service.execute("default",job["id"],"test")
        self.store.put_bytes("asset-scene.obj", CUBE)
        with patch("synthesis_service.MAX_OUTPUT",1), self.assertRaises(ValidationError): self.service.execute("default",job["id"],"test")
        with self.assertRaises(ValidationError): self.service.action("default",job["id"],"unknown")
        with self.assertRaises(ConflictError): self.service.action("default",job["id"],"retry")
