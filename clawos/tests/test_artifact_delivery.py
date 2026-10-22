import tempfile
import unittest
import sys
import asyncio
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.artifact_delivery_service import ArtifactDeliveryService


class ArtifactDeliveryTests(unittest.TestCase):
    def test_generated_file_is_registered_without_exposing_local_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "report.md"
            report.write_text("# Verified report\n", encoding="utf-8")
            service = ArtifactDeliveryService(root / "registry.json", [root])
            artifacts = service.collect([{
                "name": "file_write",
                "result": {"ok": True, "data": {"written": True, "path": str(report), "size_bytes": report.stat().st_size}},
            }], task_id=7)

            self.assertEqual(len(artifacts), 1)
            item = artifacts[0]
            self.assertNotIn("path", item)
            self.assertEqual(item["name"], "report.md")
            self.assertTrue(item["preview_url"].endswith("/preview"))
            self.assertTrue(item["download_url"].endswith("/download"))
            stored, resolved = service.resolve(item["id"])
            self.assertEqual(resolved, report.resolve())
            self.assertEqual(stored["sha256"], item["sha256"])

    def test_task_patch_is_a_previewable_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            patch = root / "task-changes.diff"
            patch.write_text("diff --git a/a.py b/a.py\n", encoding="utf-8")
            service = ArtifactDeliveryService(root / "registry.json", [root])
            artifacts = service.collect([{
                "name": "coding_agent",
                "result": {"data": {"workspace_changes": {
                    "patch_path": str(patch), "patch_sha256": "evidence",
                }}},
            }], task_id=9)
            self.assertEqual(len(artifacts), 1)
            self.assertEqual(artifacts[0]["format"], "diff")
            self.assertTrue(artifacts[0]["preview_url"])

    def test_changed_or_outside_file_is_not_silently_served(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            root = Path(td)
            report = root / "report.pdf"
            report.write_bytes(b"%PDF-1.4\n%%EOF")
            service = ArtifactDeliveryService(root / "registry.json", [root])
            item = service.register(report, source_tool="office_productivity")
            self.assertIsNotNone(item)
            self.assertIsNone(service.register(Path(outside) / "missing.pdf"))
            report.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                service.resolve(item["id"])

    def test_server_exposes_metadata_preview_and_download_by_opaque_id(self):
        import clawos_server as server

        with tempfile.TemporaryDirectory() as td:
            old_output = server.OUTPUT_ROOT
            server.OUTPUT_ROOT = Path(td)
            try:
                report = Path(td) / "report.md"
                report.write_text("# Ready\n", encoding="utf-8")
                item = server.get_artifact_delivery_service().register(report, source_tool="file_write")
                metadata = asyncio.run(server.api_artifact_metadata(item["id"]))
                preview = asyncio.run(server.api_artifact_preview(item["id"]))
                download = asyncio.run(server.api_artifact_download(item["id"]))
            finally:
                server.OUTPUT_ROOT = old_output

        payload = json.loads(metadata.body.decode("utf-8"))
        self.assertNotIn("path", payload)
        self.assertEqual(payload["name"], "report.md")
        self.assertTrue(str(preview.path).endswith("report.md"))
        self.assertTrue(str(download.path).endswith("report.md"))


if __name__ == "__main__":
    unittest.main()
