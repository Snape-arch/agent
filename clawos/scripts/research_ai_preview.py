"""Loopback synthetic UI acceptance; explicitly NOT a live model evaluation."""
import argparse
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI,HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from memoryos.memory_store import MemoryStore
from services.research_watch import ResearchWatch
from services.research_synthesis import ResearchSynthesis
from services.research_ai import ResearchAI,ResearchAIWorker,SECTIONS
from services.research_watch_api import research_watch_router
from services.collaboration import direct_owner


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.output.resolve();root.mkdir(parents=True,exist_ok=True)
    if not 1024<=args.port<=65535:parser.error('invalid port')
    db=root/'preview.db'
    if db.exists():raise SystemExit('Use a new output directory; never overwrite acceptance evidence')
    store=MemoryStore(str(db))
    class Sources:
        def page(self,*_):return dict(rows=[dict(title='[人工样例] Evidence study A',doi='10.9999/ai-fixture-a',authors=['Synthetic Author'],published='2025',
            abstract='We study evidence retrieval. We propose a synthetic method for UI validation. This artificial fixture cannot demonstrate real research quality.',url='https://example.org/a',categories=['cs.IR']),
            dict(title='[人工样例] Evidence study B',doi='10.9999/ai-fixture-b',authors=['Synthetic Author'],published='2026-02',
            abstract='We study evidence retrieval. We introduce an artificial comparison framework. However this sample is limited to software acceptance.',url='https://example.org/b',categories=['cs.IR'])],cursor='',complete=True)
    watch=ResearchWatch(store,Sources(),source_interval=0)
    sid=watch.create('local-user',dict(name='AI综合人工样例',query='evidence retrieval',sources=['crossref'],directions=[dict(name='证据检索',terms=['evidence','retrieval'])]))['id']
    watch.tick(1);watch.action('local-user',sid,'pause')
    report=ResearchSynthesis(watch).create('local-user',dict(title='人工样例 · AI证据综述'))
    (root/'fixture.json').write_text(json.dumps(dict(report_id=report['id'],synthetic=True)),encoding='utf-8')
    async def model(messages,tools,**opts):
        data=json.loads(messages[-1]['content'])
        if 'claims' in data:value=dict(reviews=[dict(id=c['id'],verdict='supported',reason='Artificial fixture direct quote.') for c in data['claims']])
        else:
            value={k:[] for k in SECTIONS}
            value['overview']=[dict(text=data['evidence'][0]['quote'],citations=[data['evidence'][0]['id']],kind='reported')]
        return dict(choices=[dict(message=dict(content=json.dumps(value)),finish_reason='stop')],clawos_model=dict(provider='synthetic-fixture',model='人工夹具（非真实模型）',usage=dict(total_tokens=0)))
    ai=ResearchAI(watch);worker=ResearchAIWorker(ai,model)
    @asynccontextmanager
    async def lifespan(app):
        worker.start();yield;await worker.close()
    app=FastAPI(lifespan=lifespan)
    class Identity:
        def identity(self,request):
            if not direct_owner(request):raise HTTPException(401,'Local fixture preview only')
            return dict(id='local-user')
    app.include_router(research_watch_router(lambda:watch,Identity,lambda:dict(running=False,last_error='',fixture=True),lambda:dict(ready=True,local_only=True,model='人工夹具（非真实模型）')))
    static=Path(__file__).resolve().parents[1]/'static'
    @app.get('/academy/research')
    def page():return FileResponse(static/'academy-research.html',headers={'Cache-Control':'no-store'})
    app.mount('/assets',StaticFiles(directory=static/'assets'))
    print('SYNTHETIC AI PREVIEW; NOT REAL MODEL ACCEPTANCE',args.port,flush=True)
    uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False)


if __name__=='__main__':main()
