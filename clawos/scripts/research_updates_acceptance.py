"""Replay captured public metadata in a new DB; no live source or model requests."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from memoryos.memory_store import MemoryStore
from services.research_watch import ResearchWatch
from services.research_synthesis import ResearchSynthesis
from services.research_updates import ResearchUpdates


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-records',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--preview-port',type=int,default=0)
    a=parser.parse_args();root=a.output.resolve()
    if root.exists():raise SystemExit('Use a new output directory')
    paths=sorted(a.source_records.glob('public-record-*.json'))
    rows=[json.loads(p.read_text(encoding='utf-8')) for p in paths]
    if len(rows)!=6:raise ValueError('This scenario requires six captured public records')
    initial=[r for r in rows if r.get('doi')=='10.1038/nature14539' or r.get('arxiv_id')=='1706.03762v1']
    if len(initial)!=2:raise ValueError('Expected initial citation/version records missing')
    root.mkdir(parents=True);now=[time.time()];current=[initial]
    class Replay:
        def page(self,source,*_):return dict(rows=[r for r in current[0] if r['source']==source],complete=True,cursor='')
    watch=ResearchWatch(MemoryStore(str(root/'preview.db')),Replay(),clock=lambda:now[0],source_interval=0)
    sid=watch.create('local-user',dict(name='公开语料增量回放',query='learning attention',sources=['crossref','arxiv'],directions=[dict(name='公开样本',terms=['learning','attention'])]))['id']
    watch.tick(2);synth=ResearchSynthesis(watch);updates=ResearchUpdates(watch)
    baseline=synth.create('local-user',dict(title='公开语料 · 自动更新验收',subscription_id=sid))
    manual=synth.create('local-user',dict(title='公开语料 · 手动更新验收',subscription_id=sid))
    updates.configure('local-user',baseline['id'],dict(enabled=True,interval_hours=6,version=0))
    now[0]+=21601;current[0]=rows;watch.tick(2)
    result=updates.tick()[0];assert result['changed']
    delta=result['update']['delta'];assert delta['counts']['added_papers']==3
    assert any(e['kind']=='observed_revision_order' for e in delta['relations']['added'])
    head=synth.get('local-user',result['head_id'])
    assert head['report']['lineage']['parent_report_id']==baseline['id']
    assert synth.get('local-user',baseline['id'])['report']==baseline['report']
    assert updates.notifications('local-user')['unread']==1
    now[0]+=61
    version=updates.status('local-user',head['id'])['track']['version']
    assert not updates.check('local-user',head['id'],dict(version=version))['changed']
    assert updates.notifications('local-user')['unread']==1
    for edge in delta['relations']['added']:
        for e in edge['evidence']:
            assert watch.snapshot('local-user',e['snapshot_id'])['hash']==e['sha256']
    export=updates.export('local-user',result['update']['id'])
    assert baseline['id'] in export['markdown'] and 'SHA256' in export['markdown']
    (root/'update-export.json').write_text(json.dumps(export,ensure_ascii=False,indent=2),encoding='utf-8')
    audit=dict(passed=True,checks=dict(automatic_due=True,added_papers=True,observed_revision=True,baseline_frozen=True,no_duplicate_notification=True,source_hashes=True,exports=True),counts=delta['counts'],
        baseline_id=baseline['id'],head_id=head['id'],manual_report_id=manual['id'],
        input_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        boundary='Replay of six captured public records with a controlled scheduling clock, not new live collection, real six-hour waiting or model evaluation.')
    (root/'result.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(audit),flush=True)
    watch.action('local-user',sid,'pause')
    # Preview uses real wall time after controlled-clock mechanism checks.
    watch.clock=time.time
    if a.preview_port:
        if not 1024<=a.preview_port<=65535:raise ValueError('Invalid preview port')
        from fastapi import FastAPI,HTTPException
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
        from services.collaboration import direct_owner
        from services.research_watch_api import research_watch_router
        import uvicorn
        class Identity:
            def identity(self,request):
                if not direct_owner(request):raise HTTPException(401,'local preview only')
                return dict(id='local-user')
        app=FastAPI();app.include_router(research_watch_router(lambda:watch,Identity,lambda:dict(running=False,last_error='',public_metadata_preview=True,controlled_clock_replay=True)))
        static=Path(__file__).resolve().parents[1]/'static'
        @app.get('/academy/research')
        def page():return FileResponse(static/'academy-research.html',headers={'Cache-Control':'no-store'})
        app.mount('/assets',StaticFiles(directory=static/'assets'))
        uvicorn.run(app,host='127.0.0.1',port=a.preview_port,access_log=False)


if __name__=='__main__':main()
