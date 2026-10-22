"""Read-only local model/tool/context acceptance; never loads production memories."""
import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mtclaw.adapter import MTClawAdapter


def verify(evidence,code):
    health,result=evidence['health'],evidence['result']
    trace=result.get('trace') or []
    times=[t for t in trace if t.get('function_name')=='time_now' and not t.get('is_error')]
    checks={
        'router_ready':bool(health.get('ready')),
        'request_trace_contract':health.get('request_trace_version',0)>=2,
        'context_contract':health.get('caller_context_version',0)>=1,
        'answer_succeeded':result.get('ok') is True,
        'current_request_trace':bool(trace) and all(t.get('request_id')==result.get('request_id') for t in trace),
        'actual_time_tool':bool(times),
        'answer_contains_actual_time':bool(times) and all(str(t.get('tool_result',{}).get('datetime','__missing__')) in result.get('content','') for t in times),
        'answer_contains_memory_code':bool(code) and code in result.get('content',''),
    }
    return dict(passed=all(checks.values()),checks=checks,duration_ms=result.get('duration_ms'),tools_loaded=health.get('tools_loaded'),scope='synthetic local time/context chain; not general model quality, all-tool coverage or sustained load')


async def live(url,code,timeout):
    target=urlsplit(url)
    if target.scheme!='http' or target.hostname not in ('127.0.0.1','localhost','::1') or target.username or target.password:
        raise ValueError('Acceptance connects only to a direct loopback HTTP router')
    adapter=MTClawAdapter(dict(enabled=True,base_url=url,timeout_s=timeout,fallback_on_error=False))
    try:
        health=await adapter.health()
        if not health.get('ready'):raise RuntimeError('Local router is not ready')
        result=await adapter.route([
            dict(role='system',content='Synthetic MemoryOS background: the project validation code is '+code+'.'),
            dict(role='user',content='Call time_now to get the current local time, and include the project validation code from the supplied background. Do not estimate the time.')
        ],'acceptance-'+uuid.uuid4().hex)
        return dict(health=health,result=result,validation_code=code)
    finally:
        if adapter._http:await adapter._http.aclose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--router-url',help='Existing isolated MTClaw router, e.g. http://127.0.0.1:18908')
    mode.add_argument('--replay',type=Path,help='Check saved evidence only; does not make a new model request')
    parser.add_argument('--validation-code',default='')
    parser.add_argument('--timeout',type=float,default=180)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:
        code=args.validation_code or 'CHAIN_'+uuid.uuid4().hex[:12]
        evidence=json.loads(args.replay.read_text(encoding='utf-8')) if args.replay else asyncio.run(live(args.router_url,code,args.timeout))
        if args.replay:code=args.validation_code or evidence.get('validation_code','')
        report=verify(evidence,code);report['mode']='saved_evidence_check' if args.replay else 'live_local_chain'
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(dict(**evidence,acceptance=report),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 0 if report['passed'] else 1
    except (ValueError,KeyError,RuntimeError,OSError) as e:
        print(json.dumps(dict(passed=False,error=str(e)),ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
