"""Replay live-captured papers in a new DB and verify 8->10 versions per field."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from memoryos.memory_store import MemoryStore
from services.research_watch import ResearchWatch
from services.research_synthesis import ResearchSynthesis
from services.research_updates import ResearchUpdates
from services import research_domains
from research_domain_build import load_captures


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for key in ('primary', 'supplements', 'output'): ap.add_argument('--'+key, type=Path, required=True)
    ap.add_argument('--preview-port', type=int, default=0)
    a = ap.parse_args()
    if a.output.exists(): raise SystemExit('Use a new independent output directory')
    if a.preview_port and not 1024 <= a.preview_port <= 65535: raise ValueError('invalid preview port')
    pack = research_domains.library(); records = load_captures(a.primary) | load_captures(a.supplements)
    a.output.mkdir(parents=True); active = {}; now = [time.time()]
    class Replay:
        def page(self, source, query, *_):
            return dict(rows=[records[pid]['paper'] for pid in active[query]], complete=True, cursor='')
    watch = ResearchWatch(MemoryStore(str(a.output/'preview.db')), Replay(), clock=lambda: now[0], source_interval=0)
    synthesis = ResearchSynthesis(watch); updates = ResearchUpdates(watch); results = []
    for domain in pack['domains']:
        query = domain['query']; active[query] = [p['id'] for p in domain['papers']]
        sid = watch.create('local-user', dict(name=domain['name']+' · 真实元数据回放', query=query, sources=['arxiv'], interval_hours=24,
            directions=[dict(name=c, terms=[p['title'][:80] for p in domain['papers'] if p['category']==c]) for c in domain['categories']]))['id']
        watch.tick(1)
        baseline = synthesis.create('local-user', dict(title=domain['name']+' · 对照前8篇', subscription_id=sid))
        before = baseline['report']
        if before['coverage']['papers'] != 8: raise AssertionError('initial paper ingestion incomplete')
        active[query] += [p['id'] for p in domain['supplements']]
        watch.action('local-user', sid, 'collect'); watch.tick(1); now[0] += 61
        result = updates.check('local-user', baseline['id'], dict(version=0))
        if not result['changed'] or result['update']['delta']['counts']['added_papers'] != 2: raise AssertionError('two-paper update missing')
        head = synthesis.get('local-user', result['head_id'])
        if head['report']['coverage']['papers'] != 10 or synthesis.get('local-user', baseline['id'])['report'] != before: raise AssertionError('version integrity failure')
        n = 0
        for p in head['report']['papers']:
            for claims in p['sections'].values():
                for c in claims:
                    e = c['evidence']; src = next(s for s in p['sources'] if s['sha256'] == e['sha256'])
                    if src['text'][e['start']:e['end']] != e['quote']: raise AssertionError('excerpt mismatch')
                    n += 1
        # Semantic overlap candidates are not silently promoted to confirmed lineage.
        if any(e['status'] != 'proposed' for e in head['report']['edges']): raise AssertionError('unreviewed relation promoted')
        try: synthesis.get('another-user', head['id'])
        except LookupError: pass
        else: raise AssertionError('cross-owner report leak')
        watch.action('local-user', sid, 'pause')
        (a.output/(domain['id']+'-source-report.json')).write_text(json.dumps(head, ensure_ascii=False, indent=2), encoding='utf-8')
        (a.output/(domain['id']+'-update.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        (a.output/(domain['id']+'.md')).write_text(research_domains.markdown(domain['id']), encoding='utf-8')
        results.append(dict(domain=domain['id'], initial=8, revised=10, added=2, exact_excerpts=n, baseline_unchanged=True, owner_isolation=True))
    audit = dict(mechanism_passed=True, domains=results, source_capture='fresh public retrieval, then offline replay into an isolated database',
        real_model_calls=0, independent_human_reviews=0, semantic_validation_passed=False,
        boundary='规则综述与版本增量的机制验收；61秒受控时钟只绕过测试等待，不是长期实测。阅读报告为助手整理，非模型生成验收或专家综述质量通过。')
    (a.output/'result.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(audit, ensure_ascii=False), flush=True)
    if a.preview_port:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
        from services.collaboration import direct_owner
        from services.research_watch_api import research_watch_router
        import uvicorn
        watch.clock = time.time
        class Identity:
            def identity(self, request):
                if not direct_owner(request): raise HTTPException(401, 'local preview only')
                return dict(id='local-user')
        app = FastAPI(); app.include_router(research_watch_router(lambda:watch, Identity, lambda:dict(running=False, isolated_public_corpus_replay=True)))
        static = Path(__file__).resolve().parents[1]/'static'
        @app.get('/academy/research')
        def page(): return FileResponse(static/'academy-research.html', headers={'Cache-Control':'no-store'})
        app.mount('/assets', StaticFiles(directory=static/'assets'))
        uvicorn.run(app, host='127.0.0.1', port=a.preview_port, access_log=False)


if __name__ == '__main__': main()
