import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class RuntimeSecurityTests(unittest.TestCase):
    def test_path_sandbox_allows_root_and_blocks_escape(self):
        from security.policy import ToolSecurityPolicy

        with tempfile.TemporaryDirectory() as td:
            policy = ToolSecurityPolicy([td])
            allowed = policy.evaluate("file_write", {"path": str(Path(td) / "ok.txt")})
            denied = policy.evaluate(
                "file_write",
                {"path": str(Path(td).parent / "outside.txt")},
            )

        self.assertTrue(allowed["allowed"])
        self.assertEqual(allowed["decision"], "confirm")
        self.assertFalse(denied["allowed"])
        self.assertEqual(denied["decision"], "deny")

    def test_command_policy_allows_read_only_git_and_blocks_chaining(self):
        from security.policy import ToolSecurityPolicy

        policy = ToolSecurityPolicy([ROOT])
        allowed = policy.evaluate(
            "shell_exec", {"command": "git status", "workdir": str(ROOT)}
        )
        destructive = policy.evaluate(
            "shell_exec", {"command": "git status; del important.txt", "workdir": str(ROOT)}
        )
        write_git = policy.evaluate(
            "shell_exec", {"command": "git reset --hard", "workdir": str(ROOT)}
        )

        self.assertTrue(allowed["allowed"])
        self.assertFalse(destructive["allowed"])
        self.assertFalse(write_git["allowed"])

    def test_secret_manager_never_returns_secret_value_and_audits_access(self):
        from memoryos.memory_store import MemoryStore
        from security.secrets import SecretManager

        old_value = os.environ.get("CLAWOS_TEST_SECRET")
        os.environ["CLAWOS_TEST_SECRET"] = "top-secret-value"
        try:
            with tempfile.TemporaryDirectory() as td:
                store = MemoryStore(str(Path(td) / "memory.db"))
                manager = SecretManager(store)
                public = manager.register(
                    "model-api",
                    "CLAWOS_TEST_SECRET",
                    allowed_tools=["model_provider"],
                )
                value = manager.resolve("model-api", tool_name="model_provider")
                with self.assertRaises(PermissionError):
                    manager.resolve("model-api", tool_name="shell_exec")
                events = store.list_audit_events(action="secret.resolve")
        finally:
            if old_value is None:
                os.environ.pop("CLAWOS_TEST_SECRET", None)
            else:
                os.environ["CLAWOS_TEST_SECRET"] = old_value

        self.assertEqual(value, "top-secret-value")
        self.assertNotIn("top-secret-value", str(public))
        self.assertEqual({event["decision"] for event in events}, {"allow", "deny"})

    def test_server_denies_tool_before_execution_and_records_audit(self):
        import clawos_server as server
        from memoryos.memory_store import MemoryStore
        from security.policy import ToolSecurityPolicy

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            old_policy = server.g_security_policy
            old_execute = server.execute_python_tool
            called = []
            server.g_memory_store = MemoryStore(str(Path(td) / "memory.db"))
            server.g_security_policy = ToolSecurityPolicy([td])
            server.execute_python_tool = lambda name, args: called.append(name) or {"ok": True}
            try:
                result = server.execute_tool_call(
                    "file_write",
                    '{"path":"C:/Windows/System32/blocked.txt","content":"x"}',
                    "s1",
                    confirmed_tools={"file_write"},
                )
                events = server.g_memory_store.list_audit_events(action="tool.preflight")
            finally:
                server.g_memory_store = old_store
                server.g_security_policy = old_policy
                server.execute_python_tool = old_execute

        self.assertEqual(result["status"], "denied")
        self.assertEqual(called, [])
        self.assertEqual(events[0]["decision"], "deny")


if __name__ == "__main__":
    unittest.main()
