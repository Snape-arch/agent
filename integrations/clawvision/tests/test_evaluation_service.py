"""Evaluation correctness, bounded reads, provenance and tenant isolation."""
import copy
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
from errors import NotFoundError, ValidationError
from evaluation_service import EvaluationService
from object_store import LocalObjectStore
from run_service import RunService


class EvaluationServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.patches = [patch.object(database, "DB_PATH", root / "eval.db"), patch.object(database, "DATABASE_URL", f"sqlite:///{root / 'eval.db'}"),
                        patch.dict(os.environ, {"CLAWVISION_OBJECT_DIR": str(root / "objects")})]
        for item in self.patches:
            item.start()
        database.init_database()
        self.service = EvaluationService(database.connect)
        self.runs = RunService(database.connect, LocalObjectStore(), threading.RLock())
        for run_id in ("base", "candidate"):
            self.runs.create("default", {"id": run_id, "name": run_id, "params": {"seed": 42}, "source": "sdk"})
        self.manifest = {"name": "fixed parts", "classes": ["A", "B", "unused"], "samples": [
            {"id": "1", "label": "A", "conditions": {"lighting": "reflection", "angle": "side"}},
            {"id": "2", "label": "A", "conditions": {"lighting": "reflection", "angle": "front"}},
            {"id": "3", "label": "B", "conditions": {"lighting": "normal", "angle": "side"}},
            {"id": "4", "label": "B", "conditions": {"lighting": "normal", "angle": "front"}},
        ]}
        self.test_set = self.service.create_test_set("default", self.manifest)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def evaluation(self, run_id="base", labels=("B", "A", "A", "B"), set_id=None):
        return self.service.create_evaluation("default", {"runId": run_id, "testSetId": set_id or self.test_set["id"],
                                                        "predictions": [{"sampleId": str(index + 1), "label": label} for index, label in enumerate(labels)]})

    def test_paired_comparison_exposes_regression_despite_overall_improvement(self):
        baseline, candidate = self.evaluation(), self.evaluation("candidate", ("A", "B", "B", "B"))
        result = self.service.compare("default", baseline["id"], candidate["id"])
        self.assertEqual((result["fixed"], result["regressed"], result["bothCorrect"], result["bothWrong"]), (2, 1, 1, 0))
        self.assertEqual((result["accuracyDelta"], result["errorRateDelta"]), (.25, -.25))
        groups = {(row["dimension"], row["value"]): row for row in result["groups"]}
        self.assertEqual(groups["angle", "front"]["errorRateDelta"], .5)
        self.assertEqual(groups["angle", "side"]["errorRateDelta"], -1)
        self.assertAlmostEqual(candidate["summary"]["macroF1"], (.6666666666666666 + .8) / 2)
        self.assertIsNone(candidate["summary"]["classMetrics"][2]["recall"])

    def test_missing_duplicate_extra_unknown_and_nonfinite_predictions_are_rejected_atomically(self):
        valid = {"testSetId": self.test_set["id"], "runId": "base", "predictions": [{"sampleId": str(i), "label": "A"} for i in range(1, 5)]}
        invalid = []
        item = copy.deepcopy(valid); item["predictions"].pop(); invalid.append(item)
        for field, value in (("sampleId", "1"), ("sampleId", "foreign"), ("label", "unknown"), ("confidence", float("nan")), ("confidence", float("inf")), ("confidence", True), ("confidence", 1.01), ("confidence", "0.5")):
            item = copy.deepcopy(valid); item["predictions"][1][field] = value; invalid.append(item)
        item = copy.deepcopy(valid); item["predictions"][0] = None; invalid.append(item)
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValidationError):
                self.service.create_evaluation("default", item)
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) AS n FROM evaluations").fetchone()["n"], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) AS n FROM evaluation_predictions").fetchone()["n"], 0)

    def test_fixed_manifest_digest_is_order_independent_and_label_sensitive(self):
        reordered = copy.deepcopy(self.manifest); reordered["name"] = "another name"; reordered["samples"].reverse(); reordered["classes"].reverse()
        second = self.service.create_test_set("default", reordered)
        self.assertEqual(second["digest"], self.test_set["digest"])
        reordered["samples"][0]["label"] = "A"
        changed = self.service.create_test_set("default", reordered)
        self.assertNotEqual(changed["digest"], self.test_set["digest"])
        exported = self.service.export_test_set("default", self.test_set["id"])
        self.assertEqual([sample["label"] for sample in exported["samples"]], ["A", "A", "B", "B"])
        # Even byte-identical copies are distinct test-set versions.
        baseline = self.evaluation()
        candidate = self.evaluation("candidate", set_id=second["id"])
        with self.assertRaises(ValidationError): self.service.compare("default", baseline["id"], candidate["id"])
        with self.assertRaises(ValidationError): self.service.compare("default", baseline["id"], baseline["id"])

    def test_failure_pages_and_condition_filters_are_exact(self):
        report = self.evaluation()
        first = self.service.cases("default", report["id"], Pagination(1, 1))
        second = self.service.cases("default", report["id"], Pagination(2, 1))
        self.assertEqual(first["data"][0]["sampleId"], "1")
        self.assertEqual(second["data"][0]["sampleId"], "3")
        self.assertEqual(first["pagination"]["total"], 2)
        group = self.service.cases("default", report["id"], Pagination(1, 25), dimension="lighting", value="reflection")
        self.assertEqual([sample["sampleId"] for sample in group["data"]], ["1"])
        empty = self.service.cases("default", report["id"], Pagination(1, 25), dimension="angle", value="front")
        self.assertEqual(empty["data"], [])
        all_cases = self.service.cases("default", report["id"], Pagination(1, 25), failures_only=False)
        self.assertEqual(all_cases["pagination"]["total"], 4)
        with self.assertRaises(ValidationError): self.service.cases("default", report["id"], Pagination(1, 25), dimension="lighting")

    def test_provenance_and_model_link_survive_run_updates(self):
        artifact = self.runs.mutate("base", "default", "artifacts", {"name": "checkpoint", "content": {"hash": "abc"}})
        report = self.service.create_evaluation("default", {"testSetId": self.test_set["id"], "runId": "base", "modelArtifactId": artifact["id"],
                                                          "predictions": [{"sampleId": str(i), "label": "A", "confidence": .5} for i in range(1, 5)]})
        self.runs.mutate("base", "default", "params", {"seed": 99})
        read = EvaluationService(database.connect).get_evaluation("default", report["id"])
        self.assertEqual(read, report)
        self.assertEqual(read["provenance"]["run"]["params"]["seed"], 42)
        self.assertEqual(read["provenance"]["modelArtifact"]["id"], artifact["id"])
        with self.assertRaises(NotFoundError):
            self.service.create_evaluation("default", {"testSetId": self.test_set["id"], "runId": "candidate", "modelArtifactId": artifact["id"],
                                                       "predictions": [{"sampleId": str(i), "label": "A"} for i in range(1, 5)]})

    def test_tenant_boundaries_apply_to_every_read_write_and_comparison(self):
        with database.connect() as db:
            db.execute("INSERT INTO tenants(id,name,created_at) VALUES('other','Other','now')")
        self.runs.create("other", {"id": "private", "params": {}})
        other_set = self.service.create_test_set("other", self.manifest)
        report = self.evaluation()
        actions = [lambda: self.service.get_test_set("other", self.test_set["id"]), lambda: self.service.export_test_set("other", self.test_set["id"]),
                   lambda: self.service.get_evaluation("other", report["id"]), lambda: self.service.cases("other", report["id"], Pagination(1, 25)),
                   lambda: self.service.compare("other", report["id"], report["id"]), lambda: self.service.list_evaluations("other", Pagination(1, 25), self.test_set["id"])]
        predictions = [{"sampleId": str(i), "label": "A"} for i in range(1, 5)]
        actions += [lambda: self.service.create_evaluation("other", {"testSetId": self.test_set["id"], "runId": "private", "predictions": predictions}),
                    lambda: self.service.create_evaluation("other", {"testSetId": other_set["id"], "runId": "base", "predictions": predictions}),
                    lambda: self.service.create_test_set("other", {**self.manifest, "datasetVersionId": "foreign"})]
        for action in actions:
            with self.assertRaises(NotFoundError): action()
        self.assertEqual(self.service.list_test_sets("other", Pagination(1, 25))["pagination"]["total"], 1)
        self.assertEqual(self.service.list_evaluations("other", Pagination(1, 25))["data"], [])

    def test_manifest_bounds_and_invalid_records_are_rejected(self):
        cases = [{**self.manifest, "task": "detection"}, {**self.manifest, "samples": []}, {**self.manifest, "samples": [None]},
                 {**self.manifest, "classes": ["A"]}, {**self.manifest, "classes": ["A", "A", "B"]}]
        for field, value in (("id", ""), ("conditions", {" lighting": "x", "lighting ": "y"}), ("conditions", {str(i): "x" for i in range(9)}),
                             ("conditions", {"angle": 45}), ("contentHash", "invalid"), ("imageUri", 3)):
            item = copy.deepcopy(self.manifest); item["samples"][0][field] = value; cases.append(item)
        item = copy.deepcopy(self.manifest); item["samples"][1]["id"] = "1"; cases.append(item)
        item = {**self.manifest, "samples": [{"id": str(i), "label": "A", "conditions": {"unique": str(i)}} for i in range(201)]}; cases.append(item)
        for item in cases:
            with self.subTest(item=item), self.assertRaises(ValidationError): self.service.create_test_set("default", item)
        self.assertEqual(self.service.list_test_sets("default", Pagination(1, 25))["pagination"]["total"], 1)

    def test_large_failure_collection_is_paginated_and_migrations_are_idempotent(self):
        large = self.service.create_test_set("default", {"name": "large", "classes": ["A", "B"], "samples": [{"id": f"sample-{i:03}", "label": "A"} for i in range(105)]})
        report = self.service.create_evaluation("default", {"testSetId": large["id"], "runId": "base", "predictions": [{"sampleId": f"sample-{i:03}", "label": "B"} for i in range(105)]})
        database.init_database()
        first, second = [self.service.cases("default", report["id"], Pagination(page, 100)) for page in (1, 2)]
        self.assertEqual((len(first["data"]), len(second["data"])), (100, 5))
        self.assertEqual(len({case["sampleId"] for case in first["data"] + second["data"]}), 105)
        self.assertFalse(second["pagination"]["hasNext"])
        self.assertEqual(self.service.get_evaluation("default", report["id"]), report)


if __name__ == "__main__":
    unittest.main()
