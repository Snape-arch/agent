import os
import json
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class RuntimeSecurityTests(unittest.TestCase):
    def test_file_write_is_atomic_and_conflict_safe(self):
        from scripts import tool_runner

        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "report.md"
            output = io.StringIO()
            tool_runner.input_data = {"path": str(target), "content": "first"}
            with contextlib.redirect_stdout(output):
                tool_runner.handlers["file_write"]()
            first = json.loads(output.getvalue())
            output = io.StringIO()
            tool_runner.input_data = {"path": str(target), "content": "second", "expected_sha256": first["sha256"]}
            with contextlib.redirect_stdout(output):
                tool_runner.handlers["file_write"]()
            second = json.loads(output.getvalue())

        self.assertTrue(first["atomic"])
        self.assertTrue(second["atomic"])
        self.assertNotEqual(first["sha256"], second["sha256"])
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

    def test_competition_delivery_package_is_path_scoped_and_confirmed(self):
        from security.policy import ToolSecurityPolicy

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            policy = ToolSecurityPolicy([root])
            allowed = policy.evaluate(
                "competition_delivery_package",
                {"root": str(root), "output_dir": str(root / "out")},
            )
            denied = policy.evaluate(
                "competition_delivery_package",
                {"root": str(root), "output_dir": str(root.parent / "outside")},
            )
            committee_allowed = policy.evaluate(
                "multi_agent_review_committee",
                {"root": str(root), "output_dir": str(root / "out")},
            )
            committee_denied = policy.evaluate(
                "multi_agent_review_committee",
                {"root": str(root), "output_dir": str(root.parent / "outside")},
            )

        self.assertTrue(allowed["allowed"])
        self.assertEqual(allowed["decision"], "confirm")
        self.assertEqual(allowed["risk_level"], "medium")
        self.assertFalse(denied["allowed"])
        self.assertTrue(committee_allowed["allowed"])
        self.assertEqual(committee_allowed["decision"], "confirm")
        self.assertFalse(committee_denied["allowed"])

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

    def test_permission_grants_can_allow_deny_and_expire(self):
        from security.policy import SecurityGrantStore, ToolSecurityPolicy

        with tempfile.TemporaryDirectory() as td:
            store = SecurityGrantStore(Path(td) / "security_policy.json")
            policy = ToolSecurityPolicy([td], grant_store=store)
            allow = store.add({
                "tool": "web_fetch",
                "decision": "allow",
                "scope_type": "url_host",
                "scope_value": "example.com",
                "reason": "trusted research source",
            })
            expired = store.add({
                "tool": "file_write",
                "decision": "allow",
                "scope_type": "path_prefix",
                "scope_value": str(Path(td)),
                "expires_at": "2000-01-01T00:00:00+00:00",
            })
            deny = store.add({
                "tool": "shell_exec",
                "decision": "deny",
                "scope_type": "command",
                "scope_value": "git status",
            })

            web = policy.evaluate("web_fetch", {"url": "https://example.com/paper"})
            write = policy.evaluate("file_write", {"path": str(Path(td) / "ok.txt")})
            shell = policy.evaluate("shell_exec", {"command": "git status", "workdir": str(td)})

        self.assertEqual(web["decision"], "allow")
        self.assertEqual(web["grant_id"], allow["id"])
        self.assertEqual(write["decision"], "confirm")
        self.assertNotEqual(write.get("grant_id"), expired["id"])
        self.assertEqual(shell["decision"], "deny")
        self.assertFalse(shell["allowed"])
        self.assertEqual(shell["grant_id"], deny["id"])

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

    def test_confirmed_office_tool_receives_service_level_confirmation(self):
        import clawos_server as server
        from security.policy import ToolSecurityPolicy

        with tempfile.TemporaryDirectory() as td:
            old_policy = server.g_security_policy
            old_execute = server.execute_python_tool
            captured = []
            server.g_security_policy = ToolSecurityPolicy([td])
            server.execute_python_tool = lambda name, args: captured.append(json.loads(args)) or {"path": str(Path(td) / "report.pdf")}
            try:
                result = server.execute_tool_call(
                    "office_productivity",
                    json.dumps({"action": "create", "output_path": str(Path(td) / "report.pdf")}),
                    "s1",
                    confirmed_tools={"office_productivity"},
                )
            finally:
                server.g_security_policy = old_policy
                server.execute_python_tool = old_execute

        self.assertEqual(result["status"], "success")
        self.assertTrue(captured[0]["confirmed"])


if __name__ == "__main__":
    unittest.main()
