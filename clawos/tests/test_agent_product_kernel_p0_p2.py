from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.agent_product import create_agent_product_router
from memoryos.memory_store import MemoryStore
from services.agent_product_kernel import AgentProductKernel, TaskRunContract
from services.execution_governance import PolicyHookRegistry
from services.agent_sdk import AgentSDKRegistry, ExtensionSpec


REPOSITORY_ROOT = ROOT.parent


class AgentProductKernelP0P2Tests(unittest.TestCase):
    def test_task_run_state_events_checkpoint_and_terminal_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(str(Path(tmp) / "memory.db"))
            task = store.start_task(
                "session-1", "Implement feature", status="pending",
                metadata={"surface": "vscode"},
            )
            store.transition_task(task["id"], "running", actor_id="ide")
            store.transition_task(
                task["id"], "waiting_confirmation", actor_id="ide"
            )
            store.transition_task(task["id"], "running", actor_id="user")
            store.transition_task(
                task["id"], "succeeded", actor_id="ide",
                checkpoint={"uri": "output/checkpoint.json", "digest": "abc"},
            )
            detail = store.get_task(task["id"])
            envelope = TaskRunContract.envelope(detail)
            with self.assertRaises(ValueError):
                store.transition_task(task["id"], "running")

        self.assertEqual(envelope["schema"], "clawos.task-run.v2")
        self.assertEqual(envelope["status"], "succeeded")
        self.assertEqual(
            envelope["checkpoint_graph"]["latest"]["event_type"],
            "run.checkpoint",
        )
        self.assertTrue(any(
            event["event_type"] == "run.transitioned"
            for event in envelope["events"]
        ))

    def test_event_bus_v2_supports_scope_type_matcher_and_denial(self):
        hooks = PolicyHookRegistry()
        hooks.register(
            "before_tool", "deny-shell",
            lambda payload: {"decision": "deny", "reason": "managed policy"},
            matcher="shell_*", scope="managed", handler_type="command",
        )
        allowed = hooks.run("before_tool", {"tool_name": "file_read"})
        denied = hooks.run("before_tool", {"tool_name": "shell_exec"})
        description = hooks.describe()

        self.assertTrue(allowed["allowed"])
        self.assertFalse(denied["allowed"])
        self.assertEqual(denied["evidence"][0]["scope"], "managed")
        self.assertIn("checkpoint_created", description["events"])
        self.assertIn("agent", description["handler_types"])

    def test_plugin_agent_graph_and_sandbox_are_fail_closed(self):
        plugin = {
            "name": "research.adapter",
            "version": "1.0.0",
            "entrypoint": "plugin/main.py",
            "capabilities": ["context.read", "workspace.read"],
        }
        valid = AgentProductKernel.validate_plugin(
            plugin, ["context.read", "workspace.read"]
        )
        denied = AgentProductKernel.validate_plugin(plugin, ["context.read"])
        graph = AgentProductKernel.validate_agent_graph({
            "agents": [
                {
                    "id": "planner", "role": "planner", "depends_on": [],
                    "permissions": ["workspace.read"], "budget": {"tokens": 1000},
                },
                {
                    "id": "builder", "role": "builder",
                    "depends_on": ["planner"],
                    "permissions": ["workspace.write"], "budget": {"tokens": 2000},
                    "worktree": "worktrees/builder",
                },
            ]
        })
        sandbox = AgentProductKernel.sandbox_plan({
            "workspace_roots": [str(REPOSITORY_ROOT)],
            "network_default": "deny",
            "secret_refs": ["github-token"],
            "limits": {"wall_seconds": 300, "processes": 8, "memory_mb": 1024},
        })

        self.assertTrue(valid["valid"])
        self.assertFalse(denied["valid"])
        self.assertEqual(denied["ungranted_capabilities"], ["workspace.read"])
        self.assertTrue(graph["valid"])
        self.assertTrue(sandbox["plan_valid"])
        self.assertFalse(sandbox["os_enforced"])

    def test_sdk_denies_ungranted_extensions_and_describes_registry(self):
        registry = AgentSDKRegistry(["context.read"])
        registry.register(ExtensionSpec(
            name="repo-context",
            kind="context_provider",
            handler=lambda: {},
            capabilities=("context.read",),
        ))
        with self.assertRaises(PermissionError):
            registry.register(ExtensionSpec(
                name="writer", kind="tool", handler=lambda: {},
                capabilities=("workspace.write",),
            ))
        self.assertEqual(
            registry.describe()["extensions"][0]["name"], "repo-context"
        )

    def test_context_and_memory_explanations_are_user_controllable(self):
        manifest = {
            "objective": "fix task runtime",
            "context_digest": "ctx",
            "budget": {"requested_tokens": 100, "estimated_tokens": 80, "truncated": True},
            "sources": [
                {"path": "AGENTS.md", "kind": "instruction", "priority": 100},
                {"path": "runtime.py", "kind": "code", "priority": 90},
            ],
            "repo_map": {"digest": "map"},
            "trust_policy": {"instruction_precedence": ["managed", "project"]},
        }
        explanation = AgentProductKernel.explain_context(manifest)
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(str(Path(tmp) / "memory.db"))
            memory = store.upsert_memory(
                "preference", "response_style", "concise",
                source="explicit_user", confidence=0.95,
                evidence=[{"evidence_type": "manual", "source_ref": "user"}],
            )
            memory_explanation = AgentProductKernel.explain_memory(
                store, memory["id"]
            )
            disabled = store.set_memory_enabled(
                memory["id"], False, actor_id="user", change_reason="forget"
            )

        self.assertTrue(explanation["selection_policy"]["truncated"])
        self.assertEqual(explanation["sources"][0]["reason"],
                         "applicable instruction by precedence and path scope")
        self.assertEqual(memory_explanation["why_available"]["source"], "explicit_user")
        self.assertIn("disable", memory_explanation["controls"])
        self.assertFalse(disabled["enabled"])

    def test_modular_router_and_vscode_expose_product_loop(self):
        router = create_agent_product_router(lambda: None, REPOSITORY_ROOT)
        paths = {route.path for route in router.routes}
        extension = (
            ROOT / "integrations" / "vscode" / "extension.js"
        ).read_text(encoding="utf-8")
        package = json.loads((
            ROOT / "integrations" / "vscode" / "package.json"
        ).read_text(encoding="utf-8"))

        self.assertIn("/api/agent-product/contracts", paths)
        self.assertIn("/api/agent-product/task-runs/{task_id}/transition", paths)
        self.assertIn("/api/agent-product/context/explain", paths)
        self.assertIn("git.openChange", extension)
        self.assertIn(
            "onCommand:clawos.rewindLastTask", package["activationEvents"]
        )


if __name__ == "__main__":
    unittest.main()
