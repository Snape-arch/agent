"""Audit a frozen overview, or explicitly run its bounded local-model acceptance."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from memoryos.memory_store import MemoryStore
from services.research_watch import ResearchWatch,packed,fingerprint
from services.research_ai import ResearchAI,catalog,normalize,SECTIONS


async def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report-json',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--audit-only',action='store_true');mode.add_argument('--model-url')
    a=p.parse_args();root=a.output.resolve();root.mkdir(parents=True,exist_ok=True)
    if (root/'result.json').exists():raise ValueError('Do not reuse acceptance evidence')
    source=json.loads(a.report_json.read_text(encoding='utf-8'))
    if 'data' in source:source=source['data']
    report=source['report']
    if fingerprint(report)!=source['hash']:raise ValueError('Frozen overview fingerprint mismatch')
    refs,coverage=catalog(report)
    with tempfile.TemporaryDirectory(dir=root) as td:
        w=ResearchWatch(MemoryStore(str(Path(td)/'db')))
        ai=ResearchAI(w)
        with w.store._conn() as c:c.execute('INSERT INTO research_synthesis_reports VALUES (?,?,?,?,?)',(report['id'],'local-user',w.clock(),packed(report),source['hash']))
        if a.audit_only:
            values={k:[] for k in SECTIONS}
            values['evidence']=[dict(text='Accuracy reaches 999.12345 percent.',citations=[refs[0]['id']],kind='reported')]
            accepted,excluded=normalize(values,refs)
            assert not accepted and excluded[0]['reason']=='unsupported_quantity'
            result=dict(mode='mechanical_evidence_audit_only',coverage=coverage,numeric_negative_control=True,real_model_verified=False)
        else:
            u=urlsplit(a.model_url)
            if u.scheme!='http' or u.hostname not in ('127.0.0.1','::1') or u.path!='/v1' or u.username or u.password or u.query or u.fragment:
                raise ValueError('Explicit credential-free loopback HTTP /v1 endpoint required')
            import httpx
            from providers.openai_compatible import OpenAICompatibleProvider
            async with httpx.AsyncClient(trust_env=False,timeout=190) as client:
                found=await client.get(a.model_url+'/models');found.raise_for_status();model=found.json()['data'][0]['id']
                provider=OpenAICompatibleProvider(dict(provider='qwen',base_url=a.model_url,model=model,requires_api_key=False,timeout_s=180))
                async def call(messages,tools,**options):
                    response=await provider.complete(messages,dict(options,tools=[]),http_client=client)
                    if not response['ok']:raise RuntimeError('local_model_request_failed')
                    raw=dict(response['raw']);raw['clawos_model']={k:response.get(k) for k in ('provider','model','usage','duration_ms')};return raw
                queued=ai.enqueue('local-user',report['id']);job=ai.claim();await ai.execute(job,call)
                result=ai.get('local-user',queued['id'])
                result['boundary']='Actual calls, not independent scholarly semantic certification. Inspect exclusions and draft before accepting.'
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(mode='audit_only' if a.audit_only else 'local_model',status=result.get('status'),coverage=coverage,
            real_model_transport_completed=bool(not a.audit_only and result.get('status')=='completed'),independent_semantic_verification=False)))
        if not a.audit_only and (result['status']!='completed' or result['result']['outcome']!='draft_ready'):raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
