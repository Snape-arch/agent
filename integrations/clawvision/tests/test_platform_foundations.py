from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "sdk"))

from api_contract import openapi_document, page_meta, parse_pagination  # noqa: E402
from data_engine import query_rows  # noqa: E402
from mesh_generator import compile_gltf  # noqa: E402
from mesh_quality import assess_mesh, validate_gltf_contract  # noqa: E402
from cad_fidelity import compare_round_trip  # noqa: E402
from columnar_engine import query_parquet, query_sources, rows_to_parquet  # noqa: E402
from analytics_service import schema_diff  # noqa: E402
from errors import problem_details  # noqa: E402
from clawvision.importers import export_mlflow, export_wandb, import_jsonl_history, import_mlflow, import_wandb  # noqa: E402


class PlatformFoundationTests(unittest.TestCase):
    def test_pagination_is_bounded_and_has_stable_metadata(self):
        pagination = parse_pagination({"page": ["2"], "pageSize": ["25"]})
        self.assertEqual(pagination.offset, 25)
        self.assertEqual(page_meta(pagination, 51), {"page": 2, "pageSize": 25, "total": 51, "pages": 3, "hasNext": True, "hasPrevious": True})
        with self.assertRaises(ValueError):
            parse_pagination({"pageSize": ["501"]})

    def test_openapi_exposes_core_workflows(self):
        document = openapi_document("test")
        self.assertEqual(document["openapi"], "3.1.0")
        self.assertIn("/api/datasets/{datasetId}/query", document["paths"])
        self.assertIn("/api/studio/text-to-3d", document["paths"])

    def test_data_engine_filters_groups_aggregates_and_sorts(self):
        rows = [
            {"model": "a", "step": 1, "loss": 0.8},
            {"model": "a", "step": 2, "loss": 0.4},
            {"model": "b", "step": 1, "loss": 0.9},
            {"model": "b", "step": 2, "loss": 0.5},
        ]
        result = query_rows(rows, {
            "filters": [{"field": "step", "operator": "gte", "value": 1}],
            "groupBy": ["model"],
            "aggregates": [{"field": "loss", "op": "avg", "as": "meanLoss"}, {"op": "count", "as": "points"}],
            "sort": [{"field": "meanLoss", "direction": "asc"}],
        })
        self.assertEqual(result["rows"], [{"model": "a", "meanLoss": 0.6000000000000001, "points": 2}, {"model": "b", "meanLoss": 0.7, "points": 2}])
        self.assertEqual(result["stats"]["scannedRows"], 4)

    def test_gltf_contract_rejects_broken_references(self):
        self.assertFalse(validate_gltf_contract({"buffers": [], "bufferViews": [{"buffer": 3}]})["valid"])
        payload, _ = compile_gltf({"name": "quality", "parts": [{"name": "body", "shape": "box", "size": [1, 1, 1], "position": [0, 0, 0], "color": "#ffffff"}]}, "standard", binary=True)
        report = assess_mesh(payload, "glb")
        self.assertTrue(report["contract"]["valid"], report)
        self.assertGreater(report["metrics"]["vertices"], 0)

    def test_large_parametric_asset_supports_250_nodes(self):
        plan = {"name": "large", "parts": [
            {"name": f"node-{index}", "shape": "box", "size": [.1, .1, .1], "position": [index % 25, index // 25, 0]}
            for index in range(250)
        ]}
        payload, stats = compile_gltf(plan, "standard", binary=True)
        self.assertGreater(stats["faces"], 2500)
        self.assertTrue(assess_mesh(payload, "glb")["contract"]["valid"])

    def test_cad_round_trip_tolerance_and_problem_contract(self):
        source = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 3 2\nf 1 2 4\nf 2 3 4\nf 3 1 4\n"
        report = compare_round_trip(source, source)
        self.assertTrue(report["passed"], report)
        changed = source.replace(b"v 1 0 0", b"v 2 0 0")
        self.assertFalse(compare_round_trip(source, changed)["passed"])
        problem = problem_details("bad input", 400, "req_test", code="validation_error")
        self.assertEqual((problem["status"], problem["requestId"], problem["code"]), (400, "req_test", "validation_error"))

    @unittest.skipUnless(__import__("importlib").util.find_spec("duckdb") and __import__("importlib").util.find_spec("pyarrow"), "DuckDB/Arrow optional dependencies are not installed")
    def test_duckdb_parquet_pushdown(self):
        payload = rows_to_parquet([{"group": "a", "value": 1.0}, {"group": "a", "value": 3.0}, {"group": "b", "value": 8.0}])
        self.assertIsNotNone(payload)
        result = query_parquet(payload or b"", {"filters": [{"field": "value", "operator": "gte", "value": 2}], "groupBy": ["group"], "aggregates": [{"field": "value", "op": "avg", "as": "mean"}], "sort": {"field": "group"}})
        self.assertEqual(result["rows"], [{"group": "a", "mean": 3.0}, {"group": "b", "mean": 8.0}])
        self.assertEqual(result["stats"]["provider"], "duckdb-parquet")

    @unittest.skipUnless(__import__("importlib").util.find_spec("duckdb") and __import__("importlib").util.find_spec("pyarrow"), "DuckDB/Arrow optional dependencies are not installed")
    def test_multifile_partition_and_cross_dataset_join(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = []
            for index, region in enumerate(("east", "west")):
                folder = root / f"region={region}"
                folder.mkdir()
                path = folder / f"part-{index}.parquet"
                path.write_bytes(rows_to_parquet([{"run_id": index + 1, "loss": 0.2 + index}]) or b"")
                files.append(str(path))
            labels = root / "labels.parquet"
            labels.write_bytes(rows_to_parquet([{"run_id": 1, "label": "good"}, {"run_id": 2, "label": "check"}]) or b"")
            result = query_sources(
                {"metrics": files, "labels": [str(labels)]},
                {
                    "joins": [{"left": "metrics", "right": "labels", "on": [{"leftField": "run_id", "rightField": "run_id"}]}],
                    "select": [
                        {"field": "metrics.region", "as": "region"},
                        {"field": "metrics.loss", "as": "loss"},
                        {"field": "labels.label", "as": "label"},
                    ],
                    "filters": [{"field": "metrics.region", "operator": "eq", "value": "west"}],
                },
            )
        self.assertEqual(result["rows"], [{"region": "west", "loss": 1.2, "label": "check"}])
        self.assertEqual(result["stats"]["sourceFiles"], 3)
        self.assertIn("READ_PARQUET", result["plan"])

    def test_schema_evolution_compatibility(self):
        compatible = schema_diff([{"name": "step", "type": "integer"}], [{"name": "step", "type": "integer"}, {"name": "loss", "type": "number"}])
        breaking = schema_diff([{"name": "step", "type": "integer"}], [{"name": "step", "type": "string"}])
        self.assertTrue(compatible["compatible"])
        self.assertFalse(breaking["compatible"])

    @patch("clawvision.importers.start_run")
    def test_jsonl_and_mlflow_importers_emit_runs(self, start_run_mock):
        class FakeRun:
            id = "run_import"
            def __init__(self): self.metrics = []; self.params = None; self.finished = False
            def log_metrics(self, step, **metrics): self.metrics.append((step, metrics))
            def log_artifact(self, *args, **kwargs): return self
            def finish(self, message): self.finished = True
        fake = FakeRun()
        start_run_mock.return_value = fake
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = root / "history.jsonl"
            history.write_text('{"_step": 2, "loss": 0.4, "_runtime": 1}\n', encoding="utf-8")
            self.assertEqual(import_jsonl_history(history, "demo"), "run_import")
            mlflow = root / "mlflow"
            (mlflow / "params").mkdir(parents=True)
            (mlflow / "metrics").mkdir()
            (mlflow / "artifacts").mkdir()
            (mlflow / "params" / "lr").write_text("0.001", encoding="utf-8")
            (mlflow / "metrics" / "accuracy").write_text("122 0.81 6\n123 0.91 7\n", encoding="utf-8")
            self.assertEqual(import_mlflow(mlflow, "demo"), "run_import")
            wandb = root / "wandb" / "files"; wandb.mkdir(parents=True)
            (wandb / "config.yaml").write_text('{"lr":{"value":0.01}}', encoding="utf-8")
            (wandb / "wandb-history.jsonl").write_text('{"_step":0,"loss":1.0}\n{"_step":1,"loss":0.5}\n', encoding="utf-8")
            self.assertEqual(import_wandb(wandb.parent, "demo"), "run_import")
            portable = {"id": "run_export", "name": "export", "params": {"lr": .1}, "metrics": [{"step": 0, "trainLoss": 1.0}, {"step": 1, "trainLoss": .5}], "artifacts": []}
            mlflow_export = export_mlflow(portable, root / "mlflow-export")
            wandb_export = export_wandb(portable, root / "wandb-export")
            self.assertEqual(len((mlflow_export / "metrics" / "loss").read_text().splitlines()), 2)
            self.assertEqual(len((wandb_export / "files" / "wandb-history.jsonl").read_text().splitlines()), 2)
        self.assertTrue(fake.finished)
        self.assertIn((6, {"accuracy": 0.81}), fake.metrics)
        self.assertIn((7, {"accuracy": 0.91}), fake.metrics)
