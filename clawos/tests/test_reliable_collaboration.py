import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.reliable_collaboration import ReliableCollaborationService
from services.coding_workflow_service import CodingWorkflowService


def git(repo, *args):
    return ReliableCollaborationService.git(repo, *args).stdout.strip()


def fixture(folder, same_file=False):
    repo = folder / "source"
    repo.mkdir()
    git(repo, "init")
    (repo / ".gitignore").write_text("__pycache__/\n.clawos-sandbox/\n", encoding="utf-8")
    (repo / "a.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (repo / "b.py").write_text("def mul(a, b):\n    return a + b\n", encoding="utf-8")
    (repo / "check.py").write_text("from a import add\nfrom b import mul\nassert add(3, 2) == 5\nassert mul(3, 2) == 6\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@local", "commit", "-m", "fixture")
    return repo


def plan():
    return {"nodes": [{"id": "a", "objective": "Fix addition", "write_paths": ["a.py"], "depends_on": []},
                      {"id": "b", "objective": "Fix multiplication", "write_paths": ["b.py"], "depends_on": []}]}


def answer(role):
    if role == "planner":
        return plan()
    if role == "reviewer":
        return {"approved": True, "reasons": ["Both arithmetic requirements and actual tests pass"], "risks": []}
    return {"summary": "fix arithmetic", "changes": [{"path": role + ".py", "operation": "replace",
            "old_text": "return a - b" if role == "a" else "return a + b",
            "new_text": "return a + b" if role == "a" else "return a * b"}]}


class Provider:
    def __init__(self, role, handler=None, calls=None):
        self.role, self.handler, self.calls = role, handler, calls

    async def complete(self, messages, options):
        if self.calls is not None:
            self.calls.append(self.role)
        packet = json.loads(messages[1]["content"])
        output = self.handler(self.role, packet) if self.handler else answer(self.role)
        if asyncio.iscoroutine(output):
            output = await output
        return {"ok": True, "provider": "fixture", "model": "fixture",
                "content": json.dumps(output), "usage": {"total_tokens": 50},
                "raw": {"choices": [{"finish_reason": "stop"}]}}


class CollaborationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.repo = fixture(self.folder)
        self.root = self.folder / "runs"
        # Runtime/sandbox integration has separate real acceptance. These tests
        # execute the caller's fixture command using a native child process.
        def run_test(repo, command, timeout):
            proc = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=timeout)
            return dict(command=command, exit_code=proc.returncode, stdout=proc.stdout,
                        stderr=proc.stderr, sandbox={"backend": "test-fixture-native", "os_enforced": False})
        self.runner = patch.object(CodingWorkflowService, "_run_command", side_effect=run_test)
        self.runner.start()
        self.addCleanup(self.runner.stop)

    def service(self, handler=None, calls=None):
        return ReliableCollaborationService(lambda spec: Provider(spec.role_id, handler, calls), root=self.root, max_concurrency=2)

    def kwargs(self, **overrides):
        return dict(allowed_paths=["a.py", "b.py"], test_commands=[[sys.executable, "check.py"]], confirmed=True, **overrides)

    async def test_dynamic_parallel_plan_real_worktrees_source_preserved_and_replay(self):
        arrived = set()
        both = asyncio.Event()
        async def handler(role, packet):
            if role in {"a", "b"}:
                arrived.add(role)
                if len(arrived) == 2:
                    both.set()
                await asyncio.wait_for(both.wait(), 30)
            return answer(role)
        calls = []
        service = self.service(handler, calls)
        result = await service.run(self.repo, "Fix arithmetic", **self.kwargs())
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(arrived, {"a", "b"})
        self.assertNotEqual(result["results"]["a"]["workspace"]["workspace"], result["results"]["b"]["workspace"]["workspace"])
        self.assertIn("return a - b", (self.repo / "a.py").read_text())
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(result["integration"]["tests"][0]["exit_code"], 0)
        again = await service.run(self.repo, "Fix arithmetic", **self.kwargs(resume_run=result["run_id"]))
        self.assertEqual(again["status"], "passed")
        self.assertEqual(calls.count("a"), 1)
        self.assertEqual(calls.count("reviewer"), 1)

    async def test_dependency_receives_actual_committed_implementation(self):
        def handler(role, packet):
            if role == "planner":
                result = plan(); result["nodes"][1]["depends_on"] = ["a"]; return result
            if role == "b":
                self.assertIn("return a + b", packet["files"]["a.py"])
                self.assertEqual(set(packet["dependency_commits"]), {"a"})
            return answer(role)
        result = await self.service(handler).run(self.repo, "Fix arithmetic", **self.kwargs())
        self.assertEqual(result["status"], "passed", result)

    async def test_write_scope_failure_retried_without_running_dependents(self):
        calls = []
        def handler(role, packet):
            if role == "planner":
                result = plan(); result["nodes"][1]["depends_on"] = ["a"]; return result
            if role == "a":
                return answer("b")
            return answer(role)
        result = await self.service(handler, calls).run(self.repo, "Fix arithmetic", **self.kwargs())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(calls.count("a"), 3)
        self.assertNotIn("b", calls)
        self.assertNotIn("reviewer", calls)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")

    async def test_invalid_plan_cycle_cannot_launch_workers(self):
        calls = []
        def handler(role, packet):
            result = plan(); result["nodes"][0]["depends_on"] = ["b"]; result["nodes"][1]["depends_on"] = ["a"]; return result
        result = await self.service(handler, calls).run(self.repo, "Fix arithmetic", **self.kwargs())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(calls, ["planner","planner"])

    async def test_recovery_reuses_completed_node_after_cancellation(self):
        waiting = asyncio.Event()
        calls = []
        async def handler(role, packet):
            if role == "b":
                waiting.set()
                await asyncio.Event().wait()
            return answer(role)
        service = self.service(handler, calls)
        task = asyncio.create_task(service.run(self.repo, "Fix arithmetic", **self.kwargs()))
        await asyncio.wait_for(waiting.wait(), 30)
        checkpoint = next(self.root.glob("*/checkpoint.json"))
        for _ in range(1500):
            saved = json.loads(checkpoint.read_text())["state"]
            if saved["results"].get("a", {}).get("status") == "passed":
                break
            await asyncio.sleep(.02)
        self.assertEqual(saved["results"]["a"]["status"], "passed")
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        result = await self.service(calls=calls).run(self.repo, "Fix arithmetic", **self.kwargs(resume_run=saved["run_id"]))
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(calls.count("a"), 1)
        self.assertEqual(result["attempts"]["b"][0]["status"], "interrupted")
        self.assertEqual(len(result["attempts"]["b"]), 2)

    async def test_active_owner_cannot_be_replaced(self):
        waiting = asyncio.Event()
        async def handler(role, packet):
            if role == "a":
                waiting.set(); await asyncio.Event().wait()
            return answer(role)
        service = self.service(handler)
        task = asyncio.create_task(service.run(self.repo, "Fix arithmetic", **self.kwargs()))
        await asyncio.wait_for(waiting.wait(), 30)
        state = json.loads(next(self.root.glob("*/checkpoint.json")).read_text())["state"]
        try:
            with self.assertRaises(TimeoutError):
                await self.service().run(self.repo, "Fix arithmetic", **self.kwargs(resume_run=state["run_id"]))
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task

    async def test_changed_request_and_completed_workspace_rejected(self):
        service = self.service()
        result = await service.run(self.repo, "Fix arithmetic", **self.kwargs())
        with self.assertRaises(ValueError):
            await service.run(self.repo, "Different objective", **self.kwargs(resume_run=result["run_id"]))
        (Path(result["results"]["a"]["workspace"]["workspace"]) / "a.py").write_text("tampered", encoding="utf-8")
        with self.assertRaises(ValueError):
            await service.run(self.repo, "Fix arithmetic", **self.kwargs(resume_run=result["run_id"]))

    async def test_integrated_failure_is_repaired_using_actual_feedback(self):
        def handler(role, packet):
            if role == "b":
                result = answer("b"); result["changes"][0]["new_text"] = "return a - b"; return result
            if role == "repairer":
                self.assertNotEqual(packet["tests"][0]["exit_code"], 0)
                return {"changes": [{"path": "b.py", "operation": "replace", "old_text": "return a - b", "new_text": "return a * b"}]}
            return answer(role)
        result = await self.service(handler).run(self.repo, "Fix arithmetic", **self.kwargs())
        self.assertEqual(result["status"], "passed", result)
        rounds = result["integration"]["test_rounds"]
        self.assertNotEqual(rounds[0]["tests"][0]["exit_code"], 0)
        self.assertEqual(rounds[1]["tests"][0]["exit_code"], 0)

    async def test_failed_tests_cannot_be_overridden_by_reviewer(self):
        calls = []
        def handler(role, packet):
            if role == "b":
                result = answer("b"); result["changes"][0]["new_text"] = "return a - b"; return result
            if role == "repairer": return {"changes": []}
            return answer(role)
        result = await self.service(handler, calls).run(self.repo, "Fix arithmetic", **self.kwargs())
        self.assertEqual(result["status"], "test_failed")
        self.assertNotIn("reviewer", calls)

    async def test_reviewer_rejects_even_when_tests_pass(self):
        def handler(role, packet):
            return {"approved": False, "reasons": ["missing requirement"], "risks": []} if role == "reviewer" else answer(role)
        result = await self.service(handler).run(self.repo, "Fix arithmetic", **self.kwargs())
        self.assertEqual(result["status"], "review_rejected")

    async def test_same_file_conflict_three_way_resolution_then_tests(self):
        def handler(role, packet):
            if role == "planner":
                result = plan(); result["nodes"][1]["write_paths"] = ["a.py"]; return result
            if role == "a":
                return {"changes": [{"path": "a.py", "operation": "replace", "old_text": "return a - b", "new_text": "return a + b # add"}]}
            if role == "b":
                return {"changes": [{"path": "a.py", "operation": "replace", "old_text": "return a - b", "new_text": "return a + b # arithmetic"}]}
            if role == "conflict_resolver":
                self.assertIn("# add", packet["ours"]["a.py"])
                self.assertIn("# arithmetic", packet["theirs"]["a.py"])
                return {"changes": [{"path": "a.py", "operation": "replace", "old_text": "# add", "new_text": "# add arithmetic"}]}
            return answer(role)
        (self.repo / "b.py").write_text("def mul(a, b):\n    return a * b\n")
        result = await self.service(handler).run(self.repo, "Fix arithmetic and both comments", **self.kwargs())
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(len(result["integration"]["resolutions"]), 1)
        self.assertIn("# add arithmetic", (Path(result["integration"]["workspace"]["workspace"]) / "a.py").read_text())
        self.assertIn("return a - b", (self.repo / "a.py").read_text())

    async def test_conflict_invalid_resolution_remains_blocked(self):
        def handler(role, packet):
            if role == "planner":
                result = plan(); result["nodes"][1]["write_paths"] = ["a.py"]; return result
            if role == "b":
                return {"changes": [{"path": "a.py", "operation": "replace", "old_text": "return a - b", "new_text": "return b + a"}]}
            if role == "conflict_resolver": return answer("b")
            return answer(role)
        result = await self.service(handler).run(self.repo, "Fix arithmetic", **self.kwargs())
        self.assertEqual(result["status"], "conflict")
        self.assertNotIn("tests", result["integration"])

    async def test_hard_model_budget_and_sensitive_paths(self):
        result = await self.service().run(self.repo, "Fix arithmetic", **self.kwargs(limits={"max_model_calls": 1}))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["ledger"]["model_calls"], 1)
        for path in ["../x.py", "C:/x.py", ".git/config", "tools/model.txt", ".env", "a\\b.py"]:
            with self.assertRaises(ValueError):
                await self.service().run(self.repo, "Fix arithmetic", allowed_paths=[path], test_commands=[[sys.executable,"check.py"]],confirmed=True)
        with self.assertRaises(PermissionError):
            await self.service().run(self.repo, "Fix arithmetic", allowed_paths=["a.py"],test_commands=[[sys.executable,"check.py"]])

    async def test_real_process_death_releases_owner_and_reuses_verified_commit(self):
        child_code = '''
import asyncio, importlib.util, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
spec=importlib.util.spec_from_file_location("test_reliable_collaboration",Path(sys.argv[1])/"tests/test_reliable_collaboration.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class CrashService(module.ReliableCollaborationService):
 def event(self,state,kind,**fields):
  super().event(state,kind,**fields)
  if kind=="worker_completed": os._exit(17)
s=CrashService(lambda role: module.Provider(role.role_id),root=sys.argv[3],max_concurrency=2)
asyncio.run(s.run(sys.argv[2],"Fix arithmetic",allowed_paths=["a.py","b.py"],test_commands=[[sys.executable,"check.py"]],confirmed=True))
'''
        process = await asyncio.to_thread(subprocess.run,
            [sys.executable,"-c",child_code,str(ROOT),str(self.repo),str(self.root)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode,17,process.stderr)
        state = json.loads(next(self.root.glob("*/checkpoint.json")).read_text())["state"]
        completed = {k:v["commit"] for k,v in state["results"].items() if v["status"]=="passed"}
        self.assertEqual(len(completed),1)
        calls=[]
        result=await self.service(calls=calls).run(self.repo,"Fix arithmetic",**self.kwargs(resume_run=state["run_id"]))
        self.assertEqual(result["status"],"passed",result)
        for role,commit in completed.items():
            self.assertEqual(result["results"][role]["commit"],commit)
            self.assertNotIn(role,calls)
        self.assertEqual(result["ledger"]["reserved_tokens"],0)

    async def test_provider_drift_rejects_resume(self):
        result=await self.service().run(self.repo,"Fix arithmetic",**self.kwargs())
        def factory(spec):
            provider=Provider(spec.role_id);provider.model="changed-model";return provider
        changed=ReliableCollaborationService(factory,root=self.root)
        with self.assertRaises(ValueError):
            await changed.run(self.repo,"Fix arithmetic",**self.kwargs(resume_run=result["run_id"]))

    async def test_http_profile_confirmation_progress_and_resume(self):
        import httpx
        from fastapi import FastAPI
        import clawos_server as server
        app=FastAPI()
        app.add_api_route("/api/subagents/run",server.api_autonomous_subagents,methods=["POST"])
        app.add_api_route("/api/subagents/collaboration/{run_id}",server.api_collaboration_progress,methods=["GET"])
        body=dict(team_profile="reliable_coding",repo_path=str(self.repo),objective="Fix arithmetic",
                  allowed_paths=["a.py","b.py"],test_commands=[[sys.executable,"check.py"]])
        with patch.object(server,"get_reliable_collaboration_service",return_value=self.service()):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
                denied=await client.post("/api/subagents/run",json=body)
                self.assertEqual(denied.status_code,409)
                result=await client.post("/api/subagents/run",json=body|{"confirmed":True})
                self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(result.json()["status"],"passed")
                run_id=result.json()["run_id"]
                progress=await client.get("/api/subagents/collaboration/"+run_id)
                self.assertFalse(progress.json()["coordinator_active"])
                self.assertFalse(progress.json()["needs_recovery"])
                again=await client.post("/api/subagents/run",json=body|{"confirmed":True,"resume_run":run_id})
                self.assertEqual(again.json()["ledger"]["model_calls"],result.json()["ledger"]["model_calls"])
                self.assertEqual((await client.get("/api/subagents/collaboration/../bad")).status_code,404)

    async def test_checkpoint_corruption_fails_without_overwriting(self):
        result=await self.service().run(self.repo,"Fix arithmetic",**self.kwargs())
        checkpoint=Path(result["checkpoint"])
        checkpoint.write_text('{"broken":',encoding="utf-8")
        with self.assertRaises(ValueError):
            await self.service().run(self.repo,"Fix arithmetic",**self.kwargs(resume_run=result["run_id"]))
        self.assertEqual(checkpoint.read_text(),'{"broken":')

    async def test_source_drift_blocks_completed_replay(self):
        result=await self.service().run(self.repo,"Fix arithmetic",**self.kwargs())
        (self.repo/"b.py").write_text("external editor changed this\n",encoding="utf-8")
        with self.assertRaises(ValueError):
            await self.service().run(self.repo,"Fix arithmetic",**self.kwargs(resume_run=result["run_id"]))
        self.assertEqual((self.repo/"b.py").read_text(),"external editor changed this\n")

    async def test_invalid_review_format_is_repaired_without_overriding_rejection(self):
        count=0
        def handler(role,packet):
            nonlocal count
            if role=="reviewer":
                count+=1
                if count==1:return {"approved":True,"reasons":"invalid type","risks":[]}
                self.assertIn("previous_failure",packet)
                return {"approved":False,"reasons":["unsupported requirement"],"risks":[]}
            return answer(role)
        result=await self.service(handler).run(self.repo,"Fix arithmetic",**self.kwargs())
        self.assertEqual(result["status"],"review_rejected")
        self.assertEqual(count,2)

    async def test_identical_parallel_changes_are_deduplicated(self):
        def handler(role,packet):
            if role=="planner":
                result=plan();result["nodes"][1].update(write_paths=["a.py"],objective="Independent addition implementation")
                return result
            if role=="b":return answer("a")
            return answer(role)
        (self.repo/"b.py").write_text("def mul(a, b):\n    return a * b\n")
        result=await self.service(handler).run(self.repo,"Fix arithmetic",**self.kwargs())
        self.assertEqual(result["status"],"passed",result)
        self.assertFalse(result["integration"].get("resolutions"))

    async def test_changed_model_receipt_cannot_be_reused(self):
        result=await self.service().run(self.repo,"Fix arithmetic",**self.kwargs())
        event=next(e for e in result["events"] if e["event"]=="model_receipt")
        path=Path(result["checkpoint"]).parent/event["receipt"]
        path.write_text("{}",encoding="utf-8")
        with self.assertRaises(ValueError):
            await self.service().run(self.repo,"Fix arithmetic",**self.kwargs(resume_run=result["run_id"]))


if __name__ == "__main__":
    unittest.main()
