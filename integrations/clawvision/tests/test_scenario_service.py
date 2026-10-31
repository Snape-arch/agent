"""Scene lineage, bounded plans, real byte hashes and tenant boundaries."""
import base64
import copy
import hashlib
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import database
from api_contract import Pagination
from errors import ConflictError, NotFoundError, ValidationError
from evaluation_service import EvaluationService, digest
from object_store import LocalObjectStore
from run_service import RunService
from scenario_service import ScenarioService, normalize_config, variants


class ScenarioServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [patch.object(database, "DB_PATH", root / "scene.db"),
                        patch.object(database, "DATABASE_URL", f"sqlite:///{root / 'scene.db'}"),
                        patch.dict(os.environ, {"CLAWVISION_OBJECT_DIR": str(root / "objects")})]
        for item in self.patches:
            item.start()
        database.init_database()
        self.store, self.lock = LocalObjectStore(), threading.RLock()
        self.service = ScenarioService(database.connect, self.store, self.lock)
        RunService(database.connect, self.store, self.lock).create("default", {"id": "run-scene", "name": "scene", "params": {}, "source": "test"})
        evaluation = EvaluationService(database.connect)
        suite = evaluation.create_test_set("default", {"name": "parts", "classes": ["gear", "bolt"], "samples": [
            {"id": "bad", "label": "gear", "conditions": {"angle": "side"}}, {"id": "good", "label": "bolt"}]})
        self.report = evaluation.create_evaluation("default", {"testSetId": suite["id"], "runId": "run-scene", "predictions": [
            {"sampleId": "bad", "label": "bolt"}, {"sampleId": "good", "label": "bolt"}]})
        self.content = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
        self.asset("asset-scene", self.content)
        self.request = {"name": "side scene", "reportId": self.report["id"], "sampleId": "bad", "assetId": "asset-scene", "label": "gear", "config": {"seed": 42, "count": 12}}

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def asset(self, asset_id, content, *, tenant="default", version=1, format="obj", stored=None):
        binary_key = f"{asset_id}.{format}"
        self.store.put_bytes(binary_key, content)
        key = self.store.put_json(f"{asset_id}.json", stored if stored is not None else {"base64": base64.b64encode(content).decode(), "binaryKey": binary_key})
        with database.connect() as db:
            db.execute("INSERT INTO model_assets(id,name,format,version,object_key,metadata,created_at,tenant_id) VALUES(?,?,?,?,?,?,?,?)",
                       (asset_id, asset_id, format, version, key, "{}", "now", tenant))

    def test_plan_pins_actual_bytes_and_failure_and_replays_identically(self):
        plan = self.service.create("default", self.request)
        same = self.service.create("default", {**self.request, "name": "renamed"})
        self.assertNotEqual(plan["id"], same["id"])
        self.assertEqual(plan["digest"], same["digest"])
        self.assertEqual(plan["digest"], digest(plan["manifest"]))
        self.assertEqual(plan["asset"]["sha256"], hashlib.sha256(self.content).hexdigest())
        self.assertEqual(plan["manifest"]["source"]["reportDigest"], self.report["digest"])
        self.assertEqual(plan["manifest"]["source"]["conditions"], {"angle": "side"})
        self.assertEqual(plan["manifest"]["variants"], variants(normalize_config(self.request["config"])))
        self.assertEqual(plan["manifest"]["kind"], "unrendered-scene-plan")
        preview = self.service.preview_asset("default", plan["id"])
        self.assertEqual(base64.b64decode(preview["base64"]), self.content)
        self.assertEqual(self.service.get("default", plan["id"]), plan)

    def test_hash_counter_protocol_has_known_values_and_fixed_ranges(self):
        config = normalize_config({"seed": 42, "count": 2, "ranges": {"cameraDistance": [3, 3]}})
        generated = variants(config)
        self.assertEqual(generated[0]["parameters"]["cameraDistance"], 3)
        unit = int.from_bytes(hashlib.sha256(b"42:0:cameraAzimuth").digest()[:8], "big") / 2**64
        self.assertEqual(generated[0]["parameters"]["cameraAzimuth"], round(-40 + 80 * unit, 6))
        changed = variants(normalize_config({**config, "seed": 43}))
        self.assertNotEqual(changed, generated)
        self.assertEqual(variants(normalize_config({**config, "count": 4}))[:2], generated)

    def test_new_versions_keep_prior_manifest_and_pinned_asset_version(self):
        first = self.service.create("default", self.request)
        self.asset("asset-next", self.content + b"# next\n", version=2)
        second = self.service.create("default", {**self.request, "parentId": first["id"], "assetId": "asset-next", "config": {"seed": 43, "count": 3}})
        self.assertEqual(second["version"], 2)
        self.assertEqual(second["parentId"], first["id"])
        self.assertEqual(second["asset"]["version"], 2)
        self.assertNotEqual(second["digest"], first["digest"])
        self.assertEqual(self.service.get("default", first["id"]), first)
        # The parent cannot be used for another report, even for the same sample.
        another = EvaluationService(database.connect).create_evaluation("default", {"testSetId": self.report["testSetId"], "runId": "run-scene", "predictions": [
            {"sampleId": "bad", "label": "bolt"}, {"sampleId": "good", "label": "bolt"}]})
        with self.assertRaises(ValidationError):
            self.service.create("default", {**self.request, "reportId": another["id"], "parentId": first["id"]})

    def test_tenant_report_asset_parent_and_preview_isolation(self):
        plan = self.service.create("default", self.request)
        for method in (self.service.get, self.service.preview_asset):
            with self.assertRaises(NotFoundError): method("other", plan["id"])
        with self.assertRaises(NotFoundError): self.service.create("other", self.request)
        self.asset("foreign", self.content, tenant="other")
        with self.assertRaises(NotFoundError): self.service.create("default", {**self.request, "assetId": "foreign"})
        with self.assertRaises(NotFoundError): self.service.create("default", {**self.request, "parentId": "missing"})
        self.assertEqual(self.service.list("other", Pagination(1, 25))["data"], [])
        with self.assertRaises(NotFoundError): self.service.list("other", Pagination(1, 25), self.report["id"])

    def test_correct_missing_and_mislabelled_samples_are_rejected(self):
        for sample in ("good", "missing"):
            with self.assertRaises(NotFoundError): self.service.create("default", {**self.request, "sampleId": sample})
        with self.assertRaises(ValidationError): self.service.create("default", {**self.request, "label": "bolt"})
        with self.assertRaises(NotFoundError): self.service.create("default", {**self.request, "assetId": "missing"})
        with database.connect() as db:
            db.execute("UPDATE model_assets SET deleted_at='now' WHERE id='asset-scene'")
        with self.assertRaises(NotFoundError): self.service.create("default", self.request)

    def test_invalid_and_unbounded_parameters_fail_before_writing(self):
        invalid = [None, [], {"unknown": 1}, {"ranges": []}, {"ranges": {"unknown": [0, 1]}},
                   {"count": 0}, {"count": 257}, {"count": True}, {"seed": -1}, {"seed": 2**32}, {"seed": 1.5},
                   {"background": "red"}, {"materialColor": None}]
        for values in ([float("nan"), 1], [0, float("inf")], [True, 1], [0, 10**1000], [-1, 1], [1, 0], [0], "0,1"):
            invalid.append({"ranges": {"roughness": values}})
        for config in invalid:
            with self.subTest(config=str(config)[:120]), self.assertRaises(ValidationError):
                self.service.create("default", {**self.request, "config": config})
        for request in ([], {**self.request, "typo": 1}):
            with self.assertRaises(ValidationError): self.service.create("default", request)
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) AS n FROM evaluation_scenarios").fetchone()["n"], 0)

    def test_asset_content_change_is_detected_but_export_remains_frozen(self):
        plan = self.service.create("default", self.request)
        self.store.put_bytes("asset-scene.obj", b"mutated")
        with self.assertRaises(ConflictError): self.service.preview_asset("default", plan["id"])
        self.assertEqual(self.service.get("default", plan["id"]), plan)
        self.store.put_bytes("asset-scene.obj", self.content)
        with database.connect() as db:
            db.execute("UPDATE model_assets SET version=2 WHERE id='asset-scene'")
        with self.assertRaises(ConflictError): self.service.preview_asset("default", plan["id"])
        with database.connect() as db:
            db.execute("UPDATE model_assets SET deleted_at='now' WHERE id='asset-scene'")
        with self.assertRaises(NotFoundError): self.service.preview_asset("default", plan["id"])

    def test_legacy_content_formats_sidecars_and_asset_bounds(self):
        self.asset("legacy", self.content, stored={"base64": base64.b64encode(self.content).decode()})
        plan = self.service.create("default", {**self.request, "assetId": "legacy"})
        self.assertEqual(plan["asset"]["sha256"], hashlib.sha256(self.content).hexdigest())
        self.asset("cad", self.content, format="step")
        with self.assertRaises(ValidationError): self.service.create("default", {**self.request, "assetId": "cad"})
        for stored in ({"base64": "!invalid"}, {}, [], {"base64": ""}):
            self.store.put_json("legacy.json", stored)
            with self.assertRaises((ConflictError, ValidationError)): self.service.create("default", {**self.request, "assetId": "legacy"})
        self.store.put_json("legacy.json", {"resources": [{"name": "a.bin"}]})
        with self.assertRaises(ValidationError): self.service.create("default", {**self.request, "assetId": "legacy"})
        with patch.object(self.store, "byte_size", return_value=25 * 1024 * 1024):
            with self.assertRaises(ValidationError): self.service.create("default", self.request)
        original = self.store.byte_size
        with patch.object(self.store, "byte_size", side_effect=lambda key: 17 * 1024 * 1024 if key.endswith(".obj") else original(key)):
            with self.assertRaises(ValidationError): self.service.create("default", self.request)
        self.store.delete("asset-scene.json")
        with self.assertRaises(ConflictError): self.service.create("default", self.request)

    def test_pagination_is_complete_and_asset_fk_prevents_purge(self):
        for index in range(27):
            self.service.create("default", {**self.request, "name": str(index), "config": {"count": 1}})
        first = self.service.list("default", Pagination(1, 25), self.report["id"])
        second = self.service.list("default", Pagination(2, 25), self.report["id"])
        self.assertEqual((first["pagination"]["total"], len(second["data"])), (27, 2))
        self.assertEqual(len({item["id"] for item in first["data"] + second["data"]}), 27)
        self.assertNotIn("manifest", first["data"][0])
        with self.assertRaises(Exception) as error, database.connect() as db:
            db.execute("DELETE FROM model_assets WHERE id='asset-scene'")
        self.assertTrue(database.is_integrity_error(error.exception))
        database.init_database()
        self.assertEqual(self.service.list("default", Pagination(1, 25))["pagination"]["total"], 27)


if __name__ == "__main__":
    unittest.main()
