"""Real single-agent proposal; frozen project tests on an owned worktree.

This reuses an internal, previously exercised task, not a public blind benchmark.
Model-selected test commands are recorded but never executed by this harness.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(Path(__file__).parent))
import collaboration_project_acceptance as project
from providers.qwen import QwenProvider
from services.autonomous_coding_service import AutonomousCodingService
from services.coding_execution_context import CodingExecutionContext
from services.coding_workflow_service import CodingWorkflowService

SOURCES=project.SOURCE_FILES+[Path(__file__)]
LOADED=project.fingerprints(SOURCES)


async def execute(args):
    start=time.monotonic();repo=project.seed(args.out)
    coordinator=project.Service(lambda spec:None,root=args.out/'evidence')
    original=coordinator.source_stamp(repo,project.PATHS)
    meta=coordinator.workspaces.create_task(repo,args.out/'workspaces','single',confirmed=True)
    workspace=Path(meta['workspace']);capture={};proposal={};result={};post={};error=''
    provider=QwenProvider(dict(base_url=args.url,model=args.model,timeout_s=300,
                              api_key='',requires_api_key=False))
    class CapturedProvider:
        async def complete(self,messages,options):
            options=dict(options,max_tokens=1800,response_format={'type':'json_object'})
            capture['started']=True
            response=await provider.complete(messages,options)
            finish=((response.get('raw') or {}).get('choices') or [{}])[0].get('finish_reason')
            capture.update(input_digest=coordinator.digest(messages),options=options,
                content=str(response.get('content') or ''),provider=response.get('provider'),model=response.get('model'),
                usage=response.get('usage'),finish_reason=finish,ok=response.get('ok'))
            capture['content_digest']=coordinator.digest(capture['content'])
            (args.out/'answer.json').write_text(json.dumps(capture,ensure_ascii=False,indent=2),encoding='utf-8')
            if finish in {'length','content_filter'}:
                raise RuntimeError('real single-agent answer incomplete')
            return response
    workflow=CodingWorkflowService(artifact_root=args.out/'coding-evidence')
    commands=[[sys.executable,'-B','acceptance_public.py'],
              [sys.executable,'-B','-m','unittest','discover','-s','clawos/tests','-p','test_document_realtime.py']]
    try:
        proposal=await AutonomousCodingService(CapturedProvider(),workflow=workflow).propose(
            workspace,project.OBJECTIVE,focus_paths=project.PATHS)
        view=proposal['execution_context']
        (args.out/'context.json').write_text(json.dumps(view,ensure_ascii=False,indent=2),encoding='utf-8')
        CodingExecutionContext.verify(workspace,view)
        # Caller authorization applies only to this disposable worktree.
        result=workflow.execute(workspace,project.OBJECTIVE,proposal['proposal']['changes'],commands,
                                confirmed=True,max_rounds=1,timeout_seconds=300,actor='single-project-acceptance')
        if result['status']=='passed':
            post=workflow._run_command(workspace,[sys.executable,'-B','acceptance_holdout.py'],120)
    except Exception as exc:
        error=f'{type(exc).__name__}: {exc}'
    checks=dict(real_model=capture.get('provider')=='qwen' and capture.get('ok') is True,
        integrated_pass=result.get('status')=='passed',postcheck_pass=post.get('exit_code')==0,
        seed_preserved=original==coordinator.source_stamp(repo,project.PATHS),
        sources_stable=LOADED==project.fingerprints(SOURCES),no_exception=not error,
        shared_context=proposal.get('execution_context',{}).get('schema')==CodingExecutionContext.SCHEMA)
    report=dict(passed=all(checks.values()),checks=checks,error=error,duration_seconds=round(time.monotonic()-start,3),
        internal_project_slice=True,independent_public_benchmark=False,
        model_test_commands_executed=False,caller_frozen_commands=commands,model_calls=int(capture.get('started',False)),
        model_capture=capture,proposal=proposal,result=result,postcheck=post,source_fingerprints=LOADED,
        holdout_feedback_to_model=False,holdout_scope='same previously exercised internal post-checks as collaboration harness',
        provenance=json.loads((args.out/'provenance.json').read_text(encoding='utf-8')))
    (args.out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','checks','error','duration_seconds')},ensure_ascii=False))
    return 0 if report['passed'] else 1


def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true',required=True)
    p.add_argument('--url',required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--model',default='Qwen3.5-9B-Q4_K_M');args=p.parse_args()
    url=urlparse(args.url)
    if url.scheme!='http' or url.hostname not in {'localhost','127.0.0.1','::1'}:
        p.error('explicit loopback provider required')
    args.out=args.out.resolve();args.out.relative_to(ROOT/'output')
    if args.out.exists():p.error('fresh output directory required')
    args.out.mkdir(parents=True)
    return asyncio.run(execute(args))


if __name__=='__main__':raise SystemExit(main())
