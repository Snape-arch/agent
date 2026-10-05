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
              ROOT/"services/collaboration_delivery.py",ROOT/"clawos_server.py",Path(__file__)]
LOADED_FINGERPRINTS={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE_FILES}
from providers.qwen import QwenProvider
from services.reliable_collaboration import ReliableCollaborationService
from services.collaboration_delivery import CollaborationDelivery


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
PIPELINE_OBJECTIVE = (
    'Implement a working CSV quantity report across the four supplied modules. '
    'cleaning.clean_rows(rows) returns a new list of dictionaries, preserving input dictionaries: '
    'label is str(row.get("label", "")).strip() or "Untitled"; quantity is a finite, nonnegative '
    'float converted from row["quantity"]. Invalid, missing, negative, NaN or infinite quantities '
    'raise ValueError. aggregation.group_quantities(rows) accepts cleaned rows and returns '
    'a list of {"label":label,"quantity":total} sorted by label, grouping identical labels. '
    'rendering.render_report(groups) returns JSON with key "groups", retains Unicode with '
    'ensure_ascii=False, and must not mutate groups. pipeline.report_csv(text) parses the CSV '
    'with csv.DictReader and composes these three functions to return the JSON text. '
    'Empty CSV with a header returns {"groups":[]}. Keep supplied signatures. '
    'Use independent specialist tasks for independent modules and actual dependency tasks '
    'for composition; determine the DAG from the module contracts.'
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
    if scenario=='pipeline':
        files={'.gitignore':'__pycache__/\n.clawos-sandbox/\n',
            'cleaning.py':'def clean_rows(rows):\n    return rows\n',
            'aggregation.py':'def group_quantities(rows):\n    return []\n',
            'rendering.py':'def render_report(groups):\n    return "{}"\n',
            'pipeline.py':'def report_csv(text):\n    return "{}"\n',
            'check.py':'''import copy,json,unittest
from cleaning import clean_rows
from aggregation import group_quantities
from rendering import render_report
from pipeline import report_csv
cases=[([],[]),([{'label':' 数据 ','quantity':'2.5'},{'label':'数据','quantity':'1.5'}],[{'label':'数据','quantity':4.0}]),([{'label':' ','quantity':'0'}],[{'label':'Untitled','quantity':0.0}]),([{'label':'B','quantity':'3'},{'label':'A','quantity':'1'}],[{'label':'A','quantity':1.0},{'label':'B','quantity':3.0}])]
class PipelineTests(unittest.TestCase):
    def test_cleaning(self):
        for rows,expected in cases:
            original=copy.deepcopy(rows)
            cleaned=clean_rows(rows)
            self.assertEqual(rows,original)
            self.assertTrue(all(type(row['quantity']) is float for row in cleaned))
            self.assertIsNot(cleaned,rows)
            self.assertEqual(cleaned,[{'label':str(r.get('label','')).strip() or 'Untitled','quantity':float(r['quantity'])} for r in rows])
    def test_grouping(self):
        for rows,expected in cases:
            # Standalone cleaned inputs expose this module independently.
            cleaned=[{'label':str(r.get('label','')).strip() or 'Untitled','quantity':float(r['quantity'])} for r in rows]
            self.assertEqual(group_quantities(cleaned),expected)
    def test_rendering(self):
        for rows,expected in cases:
            snapshot=copy.deepcopy(expected)
            text=render_report(expected)
            self.assertEqual(json.loads(text),{'groups':expected})
            self.assertEqual(expected,snapshot)
            if any(x['label']=='数据' for x in expected):self.assertIn('数据',text)
    def test_invalid_cleaning(self):
        for value in ['invalid','-1','nan','inf','-inf','']:
            with self.assertRaises(ValueError):clean_rows([{'label':'x','quantity':value}])
        with self.assertRaises(ValueError):clean_rows([{'label':'missing'}])
    def test_invalid_csv(self):
        for value in ['invalid','-1','nan','inf','-inf','']:
            with self.assertRaises(ValueError):report_csv('label,quantity\\nx,'+value+'\\n')
    def test_empty_csv(self):
        self.assertEqual(json.loads(report_csv('label,quantity\\n')),{'groups':[]})
    def test_composition(self):
        self.assertEqual(json.loads(report_csv('label,quantity\\n 数据 ,2.5\\n数据,1.5\\nB,3\\n')),{'groups':[{'label':'B','quantity':3.0},{'label':'数据','quantity':4.0}]})
unittest.main()
'''}
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
    objective={'arithmetic':OBJECTIVE,'conflict':CONFLICT_OBJECTIVE,'pipeline':PIPELINE_OBJECTIVE}[args.scenario]
    paths={'arithmetic':["addition.py", "multiplication.py", "report.py"], 'conflict':["labels.py"],
           'pipeline':['cleaning.py','aggregation.py','rendering.py','pipeline.py']}[args.scenario]
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
    parser.add_argument("--exercise-delivery", action="store_true")
    parser.add_argument("--scenario",choices=["arithmetic","conflict","pipeline"],default="arithmetic")
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
    delivery = {}
    if args.exercise_delivery and result['status']=='passed':
        svc=service(args)
        handoff=CollaborationDelivery(svc)
        try:
            packet=asyncio.run(handoff.prepare(result['run_id'],confirmed=True))
            delivery=handoff.approve(result['run_id'],actor='isolated-live-acceptance',
                                    manifest_digest=packet['manifest_digest'],confirmed=True)
            delivery['synthetic_owner_acknowledgment']=True
            delivery['actual_human_approval']=False
            result=svc.public(svc.load(result['run_id']))
        except Exception as exc:
            delivery={'status':'failed','error':f'{type(exc).__name__}: {exc}'}
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in repo.iterdir() if p.is_file()}
    active = set(); peak = 0
    worker_roles={n['id'] for n in result['nodes']}
    worker_roles.update(n['id']+'_format' for n in result['nodes'])
    for event in result["events"]:
        if event["event"] == "model_started" and event["role"] in worker_roles:
            active.add(event["role"]); peak = max(peak,len(active))
        if event["event"] in {"model_receipt", "model_completed", "worker_failed", "coordinator_recovered"}:
            if event["event"]=="coordinator_recovered": active.clear()
            else:
                role=event.get('role',event.get('node'))
                active.discard(role)
                if event['event']=='worker_failed':active.discard(role+'_format')
    checks = {"actual_integrated_pass": result["status"]=="passed", "source_preserved":before==after,
              "dynamic_task_plan":(2<=len(result['nodes'])<=8 and any(n['depends_on'] for n in result['nodes']))
                  if args.scenario=='pipeline' else len(result["nodes"])==(2 if args.scenario=="conflict" else 3),
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
    if args.exercise_delivery:
        checks['fresh_delivery_tests_pass']=bool(delivery.get('manifest',{}).get('tests')) and all(
            t['exit_code']==0 for t in delivery.get('manifest',{}).get('tests',[]))
        checks['immutable_delivery_acknowledged']=delivery.get('status')=='approved'
    checks["loaded_sources_unchanged"] = LOADED_FINGERPRINTS=={
        str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE_FILES}
    report = {"live_model":True,"scenario":args.scenario,"synthetic_repository":True,"independent_quality_benchmark":False,
        "passed":all(checks.values()),"checks":checks,"recovery":recovery,"peak_worker_requests":peak,
        "duration_seconds":round(time.monotonic()-start,3),"result":result,
        "delivery":delivery,
        "source_fingerprints":LOADED_FINGERPRINTS}
    (args.out / "report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("passed","checks","recovery","duration_seconds","peak_worker_requests")},ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
