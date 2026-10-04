"""Real loopback-provider acceptance on an isolated, synthetic Git repository.

Requires --live. --exercise-recovery crashes only its owned child after a real
worker commit is checkpointed. No environment credentials or daily DB are read.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE_FILES=[ROOT/"services/reliable_collaboration.py",ROOT/"services/autonomous_subagent_service.py",
              ROOT/"clawos_server.py",Path(__file__)]
LOADED_FINGERPRINTS={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE_FILES}
from providers.qwen import QwenProvider
from services.reliable_collaboration import ReliableCollaborationService


OBJECTIVE = (
    "Fix addition and multiplication in their separate modules as independent tasks. "
    "After those tasks, fix report.py to import both functions and return "
    "{'sum': add(a,b), 'product': mul(a,b)} from summarize(a,b). "
    "Use a third task depending on the first two for the report. Preserve public signatures."
)
CONFLICT_OBJECTIVE = (
    "Create exactly two independent tasks with no dependencies for two specialists editing labels.py. "
    "Task A must only change normalize_label(value) to strip leading and trailing whitespace. "
    "Task B must only change normalize_label(value) to return 'Untitled' for an empty string. "
    "Both start from the same original function. Integrate both requirements: strip whitespace, "
    "and return 'Untitled' when the stripped string is empty. Preserve nonempty Unicode labels."
)


def seed(folder, scenario="arithmetic"):
    repo = folder / "source"
    if repo.exists():
        return repo
    repo.mkdir(parents=True)
    files = {
        ".gitignore": "__pycache__/\n.clawos-sandbox/\n",
        "addition.py": "def add(a, b):\n    return a - b\n",
        "multiplication.py": "def mul(a, b):\n    return a + b\n",
        "report.py": "def summarize(a, b):\n    return {'sum': 0, 'product': 0}\n",
        "check.py": (
            "from addition import add\nfrom multiplication import mul\nfrom report import summarize\n"
            "for a,b in [(3,2),(0,7),(-4,3),(2.5,4),(-3,-2)]:\n"
            "    assert add(a,b)==a+b\n    assert mul(a,b)==a*b\n"
            "    assert summarize(a,b)=={'sum':a+b,'product':a*b}\n"
            "print('15 independent fixture assertions passed')\n"),
    }
    if scenario=="conflict":
        files={".gitignore":"__pycache__/\n.clawos-sandbox/\n",
            "labels.py":"def normalize_label(value):\n    return value\n",
            "check.py":"from labels import normalize_label\nfor value,want in [('  report  ','report'),('', 'Untitled'),('   ','Untitled'),('论文','论文'),(' 数据 ','数据')]:\n    assert normalize_label(value)==want,(value,normalize_label(value))\nprint('5 independent label assertions passed')\n"}
    for path, text in files.items():
        (repo / path).write_text(text, encoding="utf-8")
    ReliableCollaborationService.git(repo, "init")
    ReliableCollaborationService.git(repo, "add", ".")
    ReliableCollaborationService.git(repo, "-c", "user.name=Acceptance", "-c",
        "user.email=acceptance@local", "commit", "-m", "synthetic fixture")
    return repo


def service(args):
    class FaultService(ReliableCollaborationService):
        def event(self, state, kind, **fields):
            super().event(state, kind, **fields)
            if args.crash_after_worker and kind == "worker_completed":
                os._exit(17)
    return FaultService(lambda spec: QwenProvider({"base_url": args.url,
        "model": args.model, "timeout_s": 120, "api_key": "", "requires_api_key": False}),
        root=args.out / "runs", max_concurrency=2)


async def execute(args, resume=""):
    repo = seed(args.out,args.scenario)
    svc = service(args)
    objective=CONFLICT_OBJECTIVE if args.scenario=="conflict" else OBJECTIVE
    paths=["labels.py"] if args.scenario=="conflict" else ["addition.py", "multiplication.py", "report.py"]
    return await svc.run(repo, objective, allowed_paths=paths,
        test_commands=[[sys.executable, "check.py"]], confirmed=True, resume_run=resume,
        actor="isolated-live-acceptance", limits={"max_wall_seconds": 900, "max_tokens": 50000})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--model", default="Qwen3.5-9B-Q4_K_M")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--exercise-recovery", action="store_true")
    parser.add_argument("--scenario",choices=["arithmetic","conflict"],default="arithmetic")
    parser.add_argument("--crash-after-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    parsed = urlparse(args.url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("acceptance requires an explicit loopback HTTP provider")
    args.out = args.out.resolve()
    args.out.relative_to(ROOT / "output")
    args.out.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    repo = seed(args.out,args.scenario)
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in repo.iterdir() if p.is_file()}
    recovery = {}
    if args.exercise_recovery:
        with (args.out / "child.log").open("w", encoding="utf-8") as log:
            child = subprocess.run([sys.executable, __file__, "--live", "--url", args.url,
                "--model", args.model, "--out", str(args.out), "--scenario",args.scenario,"--crash-after-worker"],
                stdout=log, stderr=log, timeout=900)
        recovery["exit_code"] = child.returncode
        if child.returncode != 17:
            raise RuntimeError("owned crash child did not reach a real accepted worker")
        checkpoint = next((args.out / "runs").glob("*/checkpoint.json"))
        state = json.loads(checkpoint.read_text(encoding="utf-8"))["state"]
        recovery["completed_before_crash"] = {k: v["commit"] for k,v in state["results"].items() if v["status"]=="passed"}
        result = asyncio.run(execute(args, state["run_id"]))
        recovery["reused_completed_commits"] = all(result["results"].get(k,{}).get("commit")==c
            for k,c in recovery["completed_before_crash"].items())
        recovery["fresh_interrupted_attempts"] = any(len(v)>1 and v[0]["status"]=="interrupted" for v in result["attempts"].values())
    else:
        result = asyncio.run(execute(args))
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in repo.iterdir() if p.is_file()}
    active = set(); peak = 0
    for event in result["events"]:
        if event["event"] == "model_started" and event["role"] in {n["id"] for n in result["nodes"]}:
            active.add(event["role"]); peak = max(peak,len(active))
        if event["event"] in {"model_completed", "worker_failed", "coordinator_recovered"}:
            if event["event"]=="coordinator_recovered": active.clear()
            else: active.discard(event.get("role",event.get("node")))
    checks = {"actual_integrated_pass": result["status"]=="passed", "source_preserved":before==after,
              "dynamic_task_plan":len(result["nodes"])==(2 if args.scenario=="conflict" else 3),
              "parallel_worker_requests":peak>=2,
              "real_provider_receipts":bool([e for e in result["events"] if e["event"]=="model_completed"]) and
                  all(e.get("provider")=="qwen" for e in result["events"] if e["event"]=="model_completed"),
              "independent_tests_pass":bool(result["integration"].get("tests")) and
                  all(t["exit_code"]==0 for t in result["integration"].get("tests",[])),
              "review_approved":result["review"].get("approved") is True}
    if recovery:
        checks["crash_recovery"] = bool(recovery["completed_before_crash"]) and recovery["reused_completed_commits"] and recovery["fresh_interrupted_attempts"]
    if args.scenario=="conflict":
        checks["actual_conflict_resolved"] = bool(result["integration"].get("resolutions"))
    checks["loaded_sources_unchanged"] = LOADED_FINGERPRINTS=={
        str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE_FILES}
    report = {"live_model":True,"scenario":args.scenario,"synthetic_repository":True,"independent_quality_benchmark":False,
        "passed":all(checks.values()),"checks":checks,"recovery":recovery,"peak_worker_requests":peak,
        "duration_seconds":round(time.monotonic()-start,3),"result":result,
        "source_fingerprints":LOADED_FINGERPRINTS}
    (args.out / "report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("passed","checks","recovery","duration_seconds","peak_worker_requests")},ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
