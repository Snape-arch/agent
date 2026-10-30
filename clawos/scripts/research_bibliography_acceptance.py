"""Opt-in bounded public citation/version acceptance, with optional isolated UI."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from memoryos.memory_store import MemoryStore
from services.research_watch import ResearchWatch
from services.research_watch_sources import WatchSources
from services.research_synthesis import ResearchSynthesis


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--preview-port',type=int,default=0)
    a=p.parse_args();root=a.output.resolve();root.mkdir(parents=True,exist_ok=True)
    if (root/'result.json').exists() or (root/'preview.db').exists():raise ValueError('Use a fresh output directory')
    sources=WatchSources();captured=[];checks={};started=time.time()
    try:
        for source,identifier in [('crossref','10.1038/nature14539'),('crossref','10.1038/nature14236'),('arxiv','1706.03762v1'),('arxiv','1706.03762v7')]:
            row=sources.lookup(source,identifier);captured.append(row)
            (root/f'public-record-{len(captured)}.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
        relation_page=json.loads(sources.transport('https://api.crossref.org/works?filter=relation.type%3Ais-preprint-of&rows=1'))['message']['items']
        if relation_page:
            row=sources._crossref_rows(relation_page)[0];captured.append(row)
            relation=next((r for r in row['relations'] if r['kind']=='is-preprint-of' and r['doi']),None)
            if relation:captured.append(sources.lookup('crossref',relation['doi']))
        for i,row in enumerate(captured,1):(root/f'public-record-{i}.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
        class Replay:
            def page(self,source,*_):return dict(rows=[r for r in captured if r['source']==source],complete=True,cursor='')
        store=MemoryStore(str(root/'preview.db'));watch=ResearchWatch(store,Replay(),source_interval=0)
        watch.create('local-user',dict(name='公开引用与版本验收',query='public citation version acceptance',sources=['crossref','arxiv'],directions=[dict(name='公开来源样本',terms=['learning','attention'])]))
        watch.tick(2);synthesis=ResearchSynthesis(watch);value=synthesis.create('local-user',dict(title='公开来源 · 引用与版本网络'))
        g=value['report']['bibliography_graph']
        checks['citation_pair']=any(e['kind']=='cites' and e['source']=='doi:10.1038/nature14539' and e['target']=='doi:10.1038/nature14236' for e in g['edges'])
        checks['exact_versions']=any(f['arxiv_id']=='1706.03762' and f['observed_versions']==[1,7] for f in g['families'])
        checks['missing_versions_not_fabricated']=not any(n['id'] in ['arxiv:1706.03762v'+str(v) for v in range(2,7)] for n in g['nodes'])
        checks['provider_preprint_relation']=any(e['kind']=='is-preprint-of' for e in g['edges'])
        checks['snapshot_evidence']=True
        for edge in g['edges']:
            for e in edge['evidence']:
                snap=watch.snapshot('local-user',e['snapshot_id'])
                assert snap['hash']==e['sha256']
                field=snap['paper'][e['field']]
                if edge['kind']=='cites':assert 'doi:'+field[e['index']]['doi']==edge['target']
        result=dict(passed=all(checks.values()),checks=checks,records=len(captured),coverage=g['coverage'],report_id=value['id'],duration_seconds=round(time.time()-started,3),boundary='Real public provider metadata, not independent scholarly semantic or peer-review certification. No live model calls.')
        (root/'overview-export.json').write_text(json.dumps(synthesis.export('local-user',value['id']),ensure_ascii=False,indent=2),encoding='utf-8')
    except Exception as exc:
        result=dict(passed=False,error=type(exc).__name__,http_status=getattr(exc,'code',None),checks=checks,records=len(captured))
        (root/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result));raise SystemExit(1)
    (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result),flush=True)
    if not result['passed']:raise SystemExit(1)
    if a.preview_port:
        from fastapi import FastAPI,HTTPException
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
        from services.collaboration import direct_owner
        from services.research_watch_api import research_watch_router
        import uvicorn
        if not 1024<=a.preview_port<=65535:raise ValueError('invalid preview port')
        class Identity:
            def identity(self,request):
                if not direct_owner(request):raise HTTPException(401,'local preview only')
                return dict(id='local-user')
        app=FastAPI();static=Path(__file__).resolve().parents[1]/'static'
        app.include_router(research_watch_router(lambda:watch,Identity,lambda:dict(running=False,last_error='',public_metadata_preview=True)))
        @app.get('/academy/research')
        def page():return FileResponse(static/'academy-research.html',headers={'Cache-Control':'no-store'})
        app.mount('/assets',StaticFiles(directory=static/'assets'))
        uvicorn.run(app,host='127.0.0.1',port=a.preview_port,access_log=False)


if __name__=='__main__':main()
