import asyncio
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class JsonRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


async def collect_streaming_response(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk))
    return "".join(chunks)


class OperationsAndStreamingTests(unittest.TestCase):
    def test_maintenance_service_migrations_config_check_and_backup(self):
        import clawos_server as server
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            old_config = server.config
            old_maintenance = server.g_maintenance_service
            old_memory_db = server.MEMORY_DB
            db_path = Path(td) / "memory.db"
            server.g_memory_store = MemoryStore(str(db_path))
            server.MEMORY_DB = db_path
            server.config = {
                "functions_file": str(ROOT / "functions.jsonl"),
                "model_provider": {
                    "provider": "mock",
                    "model": "mock-model",
                    "api_key": "",
                    "requires_api_key": False,
                },
            }
            server.g_maintenance_service = None
            try:
                applied = json.loads(asyncio.run(server.api_system_migrations_apply()).body)
                listed = json.loads(asyncio.run(server.api_system_migrations()).body)
                checked = json.loads(asyncio.run(server.api_system_config_check()).body)
                backup = json.loads(asyncio.run(server.api_system_backup(JsonRequest({"output_dir": str(Path(td) / "backups"), "label": "test"}))).body)
                backup_exists = Path(backup["path"]).exists()
            finally:
                server.g_memory_store = old_store
                server.config = old_config
                server.g_maintenance_service = old_maintenance
                server.MEMORY_DB = old_memory_db

        self.assertTrue(applied["ok"])
        self.assertGreaterEqual(listed["count"], 1)
        self.assertTrue(checked["ok"])
        self.assertTrue(backup_exists)
        self.assertGreater(backup["bytes"], 0)

    def test_streaming_response_emits_metadata_chunks_and_cancellation(self):
        server = importlib.import_module("clawos_server")
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            old_task_service = server.g_task_service
            store = MemoryStore(str(Path(td) / "memory.db"))
            server.g_memory_store = store
            server.g_task_service = None
            try:
                task = server.create_runtime_task("s-stream", "streaming task")
                store.cancel_task(task["id"], reason="test cancel", actor_id="tester")
                response = server.sse_from_text("x" * 240, task_id=task["id"], extra={"task_id": task["id"]})
                body = asyncio.run(collect_streaming_response(response))
                detail = store.get_task(task["id"])
            finally:
                server.g_memory_store = old_store
                server.g_task_service = old_task_service

        self.assertIn("event: clawos_meta", body)
        self.assertIn("event: canceled", body)
        self.assertIn("data: [DONE]", body)
        self.assertEqual(detail["task"]["status"], "canceled")


if __name__ == "__main__":
    unittest.main()
