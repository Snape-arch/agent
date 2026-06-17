import asyncio
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


class RuntimeTaskControlTests(unittest.TestCase):
    def test_task_idempotency_returns_existing_task(self):
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            first = store.start_task(
                "s1", "Generate report", metadata={"x": 1},
                idempotency_key="idem-1",
            )
            second = store.start_task(
                "s1", "Generate report duplicate", metadata={"x": 2},
                idempotency_key="idem-1",
            )

        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(second["metadata"], {"x": 1})

    def test_cancel_retry_recover_and_event_cursor(self):
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            running = store.start_task("s1", "Long task", metadata={"user_text": "do work"})
            canceled = store.cancel_task(running["id"], reason="user stop", actor_id="tester")
            retry = store.retry_task(running["id"], actor_id="tester", reason="try again")
            interrupted = store.start_task("s1", "Interrupted", status="running")
            recovered = store.recover_interrupted_tasks(actor_id="startup")
            events = store.list_task_events(session_id="s1", after_id=0, limit=50)
            later = store.list_task_events(session_id="s1", after_id=events[0]["id"], limit=50)

        self.assertTrue(canceled["cancellation_requested"])
        self.assertEqual(canceled["status"], "cancel_requested")
        self.assertEqual(retry["retry_of"], running["id"])
        self.assertEqual(retry["attempt"], 2)
        self.assertIn(interrupted["id"], recovered["recovered"])
        self.assertGreater(len(later), 0)
        self.assertTrue(any(e["event_type"] == "task_cancel_requested" for e in events))
        self.assertTrue(any(e["event_type"] == "task_recovered" for e in later))

    def test_recover_interrupted_tasks_can_create_replay_retry(self):
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            interrupted = store.start_task(
                "s1", "Generate report",
                metadata={"user_text": "make report", "tool": "research_pdf"},
                status="running",
            )
            canceled = store.start_task("s1", "Canceled task", status="cancel_requested")
            recovered = store.recover_interrupted_tasks(
                actor_id="startup",
                create_retries=True,
            )
            original = store.get_task(interrupted["id"])["task"]
            retry = store.get_task(recovered["retry_tasks"][0]["id"])["task"]
            canceled_after = store.get_task(canceled["id"])["task"]

        self.assertEqual(recovered["created_retry_count"], 1)
        self.assertEqual(original["status"], "interrupted")
        self.assertEqual(original["resume_state"], "needs_retry")
        self.assertEqual(retry["status"], "pending_retry")
        self.assertEqual(retry["retry_of"], interrupted["id"])
        self.assertEqual(retry["attempt"], 2)
        self.assertEqual(retry["resume_state"], "ready_to_replay")
        self.assertEqual(retry["metadata"]["user_text"], "make report")
        self.assertEqual(canceled_after["status"], "canceled")
        self.assertEqual(canceled_after["resume_state"], "needs_retry")

    def test_recover_api_can_create_replay_retry(self):
        import clawos_server as server
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            server.g_memory_store = MemoryStore(str(Path(td) / "memory.db"))
            try:
                task = server.g_memory_store.start_task(
                    "s-api", "Interrupted API task",
                    metadata={"user_text": "resume me"},
                    status="running",
                )
                response = asyncio.run(server.api_tasks_recover(
                    JsonRequest({"actor_id": "startup", "create_retries": True})
                ))
                payload = response.body.decode("utf-8")
                recovered = json.loads(payload)
                self.assertEqual(recovered["created_retry_count"], 1)
                retry = server.g_memory_store.get_task(recovered["retry_tasks"][0]["id"])["task"]
            finally:
                server.g_memory_store = old_store

        self.assertEqual(retry["retry_of"], task["id"])
        self.assertEqual(retry["status"], "pending_retry")

    def test_server_helpers_expose_cancel_and_retry(self):
        import clawos_server as server
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            server.g_memory_store = MemoryStore(str(Path(td) / "memory.db"))
            try:
                task = server.create_runtime_task(
                    "s1", "Task", metadata={"idempotency_key": "idem-server"}
                )
                duplicate = server.create_runtime_task(
                    "s1", "Task copy", metadata={"idempotency_key": "idem-server"}
                )
                canceled = server.cancel_runtime_task(task["id"], "stop", "tester")
                retry = server.retry_runtime_task(task["id"], "again", "tester")
            finally:
                server.g_memory_store = old_store

        self.assertEqual(task["id"], duplicate["id"])
        self.assertTrue(duplicate["idempotent_replay"])
        self.assertEqual(canceled["status"], "cancel_requested")
        self.assertEqual(retry["retry_of"], task["id"])


if __name__ == "__main__":
    unittest.main()
