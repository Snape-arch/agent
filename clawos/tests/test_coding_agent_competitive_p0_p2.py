from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from memoryos.context_builder import ContextBuilder
from memoryos.memory_store import MemoryStore
from providers.base import model_result
from services.agentic_coding_loop_service import AgenticCodingLoopService
from services.coding_context_service import CodingContextService
from services.coding_trace_service import CodingTraceService
from services.coding_workflow_service import CodingWorkflowService
from services.lsp_bridge_service import LanguageServerManager


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "AGENTS.md").write_text("Preserve evidence.", encoding="utf-8")
    (repo / "maths.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )
    (repo / "test_maths.py").write_text(
        "import unittest\nfrom maths import add\n\n"
        "class MathsTest(unittest.TestCase):\n"
        "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "fixture")
    return repo


class ScriptedProvider:
    def __init__(self):
        self.index = 0
        self.actions = [
            {
                "action": "read", "path": "maths.py",
                "start_line": 1, "end_line": 20,
            },
            {
                "action": "propose_patch",
                "changes": [{
                    "path": "maths.py", "operation": "replace",
                    "old_text": "return a - b", "new_text": "return a + b",
                }],
                "test_commands": [
                    [sys.executable, "-m", "unittest", "-q", "test_maths"]
                ],
                "explanation": "Fix addition.",
            },
            {"action": "finish", "summary": "Addition fixed and verified."},
        ]

    async def complete(self, messages, options=None, **kwargs):
        action = self.actions[min(self.index, len(self.actions) - 1)]
        self.index += 1
        return model_result(
            ok=True, provider="scripted", model="test",
            content=json.dumps(action), usage={"total_tokens": 10},
        )


class CompetitiveClosureTests(unittest.TestCase):
    def test_agentic_loop_observes_edits_tests_and_records_bound_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            trace = CodingTraceService(root / "traces.json")
            service = AgenticCodingLoopService(
                ScriptedProvider(),
                workflow=CodingWorkflowService(artifact_root=root / "runs"),
                trace=trace,
            )
            result = asyncio.run(service.run(
                repo, "fix add", confirmed=True,
                task_id="task-1", session_id="session-1",
            ))
            record = trace.get(result["trajectory_id"])

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["turns"], 3)
        self.assertEqual(result["observations"][1]["type"], "read")
        self.assertEqual(record["task_id"], "task-1")
        self.assertEqual(record["session_id"], "session-1")
        self.assertTrue(
            {"context", "model", "tool", "edit", "test", "review"}
            <= {item["type"] for item in record["steps"]}
        )
        self.assertTrue(result["human_review_required"])
        self.assertFalse(result["commit_created"])
        self.assertFalse(result["online_rl_claimed"])

    def test_context_auto_compacts_and_applies_only_matching_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            rules = repo / ".claude" / "rules"
            rules.mkdir(parents=True)
            (rules / "python.md").write_text(
                "---\npaths: ['*.py']\n---\nUse Python evidence.\n",
                encoding="utf-8",
            )
            (rules / "javascript.md").write_text(
                "---\npaths: ['*.js']\n---\nUse JavaScript evidence.\n",
                encoding="utf-8",
            )
            manifest = CodingContextService().build(
                repo, "fix maths", focus_paths=["maths.py"]
            )
            paths = {
                item["path"] for item in manifest["instruction_hierarchy"]
            }
            store = MemoryStore(str(root / "memory.db"))
            for index in range(50):
                store.add_message("s1", "user", f"message {index}")
            ContextBuilder(store).build_messages("s1", "continue")
            self.assertIn(".claude/rules/python.md", paths)
            self.assertNotIn(".claude/rules/javascript.md", paths)
            self.assertLessEqual(len(store.get_session_messages("s1", 100)), 24)
            self.assertIn("message 0", store.get_session_summary("s1"))

    def test_language_server_manager_reuses_process_and_supports_rich_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            server = root / "fake_lsp.py"
            server.write_text(
                "import json,sys\n"
                "def send(x):\n"
                " b=json.dumps(x,separators=(',',':')).encode();"
                " sys.stdout.buffer.write(f'Content-Length: {len(b)}\\r\\n\\r\\n'.encode()+b);"
                " sys.stdout.buffer.flush()\n"
                "while True:\n"
                " h={}\n"
                " while True:\n"
                "  line=sys.stdin.buffer.readline()\n"
                "  if not line: raise SystemExit\n"
                "  if line in (b'\\r\\n',b'\\n'): break\n"
                "  k,_,v=line.decode().partition(':');h[k.lower().strip()]=v.strip()\n"
                " m=json.loads(sys.stdin.buffer.read(int(h['content-length'])))\n"
                " method=m.get('method'); rid=m.get('id')\n"
                " if method=='initialize': send({'jsonrpc':'2.0','id':rid,'result':{'capabilities':{'documentSymbolProvider':True,'definitionProvider':True,'referencesProvider':True,'hoverProvider':True,'renameProvider':True,'diagnosticProvider':True}}})\n"
                " elif method=='textDocument/documentSymbol': send({'jsonrpc':'2.0','id':rid,'result':[{'name':'add','kind':12}]})\n"
                " elif method=='textDocument/definition': send({'jsonrpc':'2.0','id':rid,'result':{'uri':'file:///maths.py'}})\n"
                " elif method=='textDocument/references': send({'jsonrpc':'2.0','id':rid,'result':[{'uri':'file:///test_maths.py'}]})\n"
                " elif method=='textDocument/hover': send({'jsonrpc':'2.0','id':rid,'result':{'contents':'add'}})\n"
                " elif method=='textDocument/rename': send({'jsonrpc':'2.0','id':rid,'result':{'changes':{}}})\n"
                " elif method=='textDocument/diagnostic': send({'jsonrpc':'2.0','id':rid,'result':{'items':[{'message':'sample'}]}})\n"
                " elif method=='shutdown': send({'jsonrpc':'2.0','id':rid,'result':None})\n"
                " elif method=='exit': raise SystemExit\n",
                encoding="utf-8",
            )
            command = [sys.executable, str(server)]
            manager = LanguageServerManager()
            first = manager.get(repo, command)
            second = manager.get(repo, command)
            path = repo / "maths.py"
            self.assertIs(first, second)
            self.assertEqual(first.document_symbols(path)[0]["name"], "add")
            self.assertIn("uri", first.definition(path, 0, 0))
            self.assertEqual(len(first.references(path, 0, 0)), 1)
            self.assertEqual(first.hover(path, 0, 0)["contents"], "add")
            self.assertEqual(first.rename(path, 0, 0, "sum")["changes"], {})
            self.assertEqual(first.diagnostics(path)[0]["message"], "sample")
            self.assertTrue(manager.stop(repo, command))

    def test_production_entrypoints_enforce_trace_identity_and_signatures(self):
        root = Path(__file__).resolve().parents[1]
        server = (root / "clawos_server.py").read_text(encoding="utf-8")
        extension = (
            root / "integrations" / "vscode" / "extension.js"
        ).read_text(encoding="utf-8")
        cli = (root / "scripts" / "clawos_coding_cli.py").read_text(
            encoding="utf-8"
        )
        package = json.loads((
            root / "integrations" / "vscode" / "package.json"
        ).read_text(encoding="utf-8"))

        self.assertIn("AgenticCodingLoopService", server)
        self.assertIn("CodingTraceService", server)
        self.assertIn("task_id and session_id are required", server)
        self.assertIn("CLAWOS_REVIEW_SIGNING_KEY", server)
        self.assertIn("/api/workspace/coding/ide-context", server)
        self.assertIn("/api/workspace/coding/ide-context", extension)
        self.assertIn("stream-json", cli)
        self.assertIn(
            "onCommand:clawos.runCodingTask", package["activationEvents"]
        )


if __name__ == "__main__":
    unittest.main()
