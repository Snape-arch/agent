"""Explicit loopback, frozen paired coding comparison on an internal snapshot."""
import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).parent))
import collaboration_project_acceptance as project
from providers.qwen import QwenProvider
from services.coding_comparison_service import CodingComparisonService

WITNESS={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),
    ROOT/'providers/qwen.py',ROOT/'providers/openai_compatible.py',Path(project.__file__)]}


async def execute(args):
    source=project.seed(args.out)
    # A new explicit contract version. Earlier stage-3 failures stay negative.
    objective=project.OBJECTIVE + ' All invalid max_messages values, including wrong types, bool and int subclasses, must raise ValueError (never TypeError).'
    requirements=copy.deepcopy(project.REQUIREMENTS)
    for r in requirements:
        r.pop('rule',None)
        if r['id']=='history_exact_bound':r['statement']+=' Every invalid value must raise ValueError, including wrong types, bool and int subclasses.'
    case=dict(id='document-history-v2',repo=str(source),objective=objective,paths=list(project.PATHS),
        test_commands=[[sys.executable,'-B','acceptance_public.py'],
            [sys.executable,'-B','-m','unittest','discover','-s','clawos/tests','-p','test_document_realtime.py']],
        post_commands=[[sys.executable,'-B','acceptance_holdout.py']],requirements=requirements)
    runner=CodingComparisonService(args.out/'comparison',witness=WITNESS)
    models=[]
    for identifier,url,name in args.model:
        cfg=dict(base_url=url,model=name,api_key='',requires_api_key=False,timeout_s=300)
        factory=lambda role,cfg=cfg:QwenProvider(cfg)
        models.append(dict(id=identifier,factory=factory,fingerprint=runner.svc.provider_signature(factory('identity'))))
    report=await runner.run([case],models,confirmed=True,repetitions=args.repetitions)
    print(json.dumps(dict(complete=report['complete'],protocol_valid=report['protocol_valid'],
        execution_comparable=report['execution_comparable'],budget_conformant=report['budget_conformant'],
        all_tasks_resolved=report['all_tasks_resolved'],model_comparison_available=report['model_comparison_available'],
        groups=report['groups']),ensure_ascii=False))
    return 0 if report['complete'] and report['protocol_valid'] else 2


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--live',action='store_true',required=True)
    p.add_argument('--model',nargs=3,action='append',metavar=('ID','LOOPBACK_URL','MODEL'),required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--repetitions',type=int,choices=(1,2,3),default=2);args=p.parse_args()
    if not 1<=len(args.model)<=4:p.error('1..4 explicit model entries required')
    for identifier,url,name in args.model:
        parsed=urlparse(url)
        if (parsed.scheme!='http' or parsed.hostname not in {'localhost','127.0.0.1','::1'}
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            p.error('explicit credential-free loopback HTTP endpoints required')
    args.out=args.out.resolve();args.out.relative_to(ROOT/'output')
    if args.out.exists():p.error('fresh output directory required; previous evidence is immutable')
    args.out.mkdir(parents=True)
    return asyncio.run(execute(args))


if __name__=='__main__':raise SystemExit(main())
