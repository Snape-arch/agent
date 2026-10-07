"""Local coding strategy workbench, with an explicit isolated evidence DB.

Diagnostics need no provider. Execution needs --execute, a clean frozen case
and a credential-free loopback provider. No business patch is applied to source.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from memoryos.memory_store import MemoryStore
from services.coding_strategy_service import CodingStrategyService


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('ingest','failures','nominate_failure','nominate_routing','preview','run','compare'))
    parser.add_argument('--workspace',type=Path,required=True,help='Owned evidence state under clawos/output')
    parser.add_argument('--folder',type=Path,help='Comparison report folder under clawos/output')
    parser.add_argument('--case',type=Path,help='Frozen case JSON with repo/objective/scope/commands/requirements')
    parser.add_argument('--url');parser.add_argument('--model');parser.add_argument('--execute',action='store_true')
    parser.add_argument('--baseline-mode',choices=('single','multi'),default='single')
    parser.add_argument('--repetitions',type=int,choices=(1,2,3),default=1)
    parser.add_argument('--category',choices=('format','test','pipeline'),default='format')
    parser.add_argument('--decision-id');args=parser.parse_args()
    output=(ROOT/'output').resolve();workspace=args.workspace.resolve()
    try:workspace.relative_to(output)
    except ValueError:parser.error('workspace must be inside clawos/output')
    for node in (args.workspace.absolute(),*args.workspace.absolute().parents):
        if node==output.parent:break
        if node.is_symlink() or (hasattr(node,'is_junction') and node.is_junction()):parser.error('workspace links are forbidden')
    workspace.mkdir(parents=True,exist_ok=True)
    store=MemoryStore(str(workspace/'coding-evidence.db'));service=CodingStrategyService(store,output)
    if args.action=='ingest':
        if not args.folder:parser.error('--folder required')
        result=service.evidence.ingest(args.folder.resolve())
    elif args.action=='failures':result=service.evidence.failures()
    elif args.action=='nominate_failure':result=service.evidence.nominate_failures(args.category)
    elif args.action=='nominate_routing':result=service.nominate_routing(args.decision_id)
    else:
        if not args.case or not args.url or not args.model:parser.error('--case, --url and --model required')
        url=urlparse(args.url)
        if (url.scheme!='http' or url.hostname not in {'localhost','127.0.0.1','::1'} or
                url.username or url.password or url.query or url.fragment):parser.error('credential-free loopback HTTP required')
        from providers.qwen import QwenProvider
        factory=lambda role:QwenProvider(dict(base_url=args.url,model=args.model,api_key='',requires_api_key=False,timeout_s=300))
        if args.case.stat().st_size>128000:parser.error('case JSON exceeds read limit')
        case=json.loads(args.case.read_text(encoding='utf-8'));options={'baseline_mode':args.baseline_mode}
        if args.action=='preview':result=service.preview(case,factory,**options)
        else:
            if not args.execute:parser.error('execution requires --execute')
            result=asyncio.run(service.run(case,factory,confirmed=True,paired=args.action=='compare',repetitions=args.repetitions,**options))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
