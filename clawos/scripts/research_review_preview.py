"""Isolated UI fixture. Synthetic account judgments are NOT human validation."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from memoryos.memory_store import MemoryStore
from services.research_watch import ResearchWatch
from services.research_review import ResearchReview
from services.collaboration import Collaboration,direct_owner


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--port',type=int,required=True)
    a=p.parse_args();root=a.output.resolve()
    if root.exists():raise SystemExit('Use a new output directory')
    if not 1024<=a.port<=65535:raise ValueError('invalid preview port')
    root.mkdir(parents=True);store=MemoryStore(str(root/'preview.db'));Collaboration(store)
    with store._conn() as c:c.executemany('INSERT INTO collaboration_users VALUES (?,?)',[(v,'自动化测试账户，非真人') for v in ('fixture-reviewer-1','fixture-reviewer-2','fixture-adjudicator')])
    watch=ResearchWatch(store);review=ResearchReview(watch)
    value=review.create('local-user',dict(kind='benchmark',reviewer_ids=['fixture-reviewer-1','fixture-reviewer-2'],adjudicator_id='fixture-adjudicator'))
    def vote(verdict,ref):return dict(verdict=verdict,reason='[自动化测试夹具，非真实人工评审] 验证盲评判断、分歧与有效账户统计。',issues=['version'],evidence_ids=[ref],human_confirmed=True)
    review.vote('fixture-reviewer-1',value['id'],'AI-01',vote('supported','attention-v7'))
    review.vote('fixture-reviewer-2',value['id'],'AI-01',vote('insufficient','attention-v7'))
    for actor in ('fixture-reviewer-1','fixture-reviewer-2'):review.vote(actor,value['id'],'AI-02',vote('contradicted','attention-v1'))
    value=review.get('local-user',value['id'])
    assert value['summary']['unresolved_conflicts']==1 and value['summary']['double_reviewed']==2 and not value['human_validation_complete']
    (root/'fixture.json').write_text(json.dumps(dict(round_id=value['id'],synthetic_assessments=True,independent_human_reviews=0,summary=value['summary']),ensure_ascii=False,indent=2),encoding='utf-8')
    from fastapi import FastAPI,HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    from services.research_watch_api import research_watch_router
    import uvicorn
    class Identity:
        def identity(self,request):
            if not direct_owner(request):raise HTTPException(401,'Local review fixture only')
            return dict(id='local-user')
    app=FastAPI();app.include_router(research_watch_router(lambda:watch,Identity,lambda:dict(running=False,last_error='',fixture=True)))
    static=Path(__file__).resolve().parents[1]/'static'
    @app.get('/academy/research')
    def page():return FileResponse(static/'academy-research.html',headers={'Cache-Control':'no-store'})
    app.mount('/assets',StaticFiles(directory=static/'assets'))
    print('REVIEW UI FIXTURE ONLY; ZERO INDEPENDENT HUMAN REVIEWS',value['id'],flush=True)
    uvicorn.run(app,host='127.0.0.1',port=a.port,access_log=False)


if __name__=='__main__':main()
