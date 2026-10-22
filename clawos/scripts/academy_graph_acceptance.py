"""Real HTTP/model graph acceptance against an explicitly isolated loopback preview.

Input books stay outside source control. Results prove transport/source contracts,
not semantic prerequisite accuracy or real learning outcomes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx


def plan_batches(index,selected=None,limit=18000):
    """Preserve book order without exceeding the service's chapter/text limits."""
    chapters=index['chapters']
    if selected is not None:
        if len(selected)!=len(set(selected)) or set(selected)-{c['id'] for c in chapters}:raise ValueError('Unknown or duplicate chapter IDs')
        chapters=[c for c in chapters if c['id'] in selected]
    batches=[];batch=[];size=0
    for c in chapters:
        chars=sum(s['end']-s['start'] for s in c['sources'])
        if c['review_required'] or chars>24000:raise ValueError('Chapter needs source review or a smaller manual directory: '+c['id'])
        if batch and (size+chars>limit or len(batch)>=6):batches.append(batch);batch=[];size=0
        batch.append(c['id']);size+=chars
    if batch:batches.append(batch)
    return batches


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--session',required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--chapters',nargs='+',help='Exact chapter IDs; default first chapter')
    parser.add_argument('--all-chapters',action='store_true',help='Actually send every indexed chapter, in bounded batches')
    parser.add_argument('--material',help='Reuse an already uploaded QA material')
    parser.add_argument('--upload-name',help='Explicit QA filename, avoiding an older deduplicated material')
    parser.add_argument('--index-algorithm',help='Refuse a different directory algorithm before any model call')
    parser.add_argument('--require-empty',action='store_true',help='Require a new empty graph for an independent full-book round')
    args=parser.parse_args()
    endpoint=urlsplit(args.url)
    if endpoint.scheme!='http' or endpoint.hostname not in ('127.0.0.1','::1') or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or endpoint.path not in ('','/'):
        parser.error('Only explicit credential-free loopback HTTP preview roots are allowed')
    if args.output.exists():parser.error('Use a fresh output directory; evidence is never overwritten')
    args.output.mkdir(parents=True)
    def save(name,value):
        (args.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    with httpx.Client(base_url=args.url,timeout=400,trust_env=False) as client:
        env=client.get('/api/qa/environment');env.raise_for_status();env=env.json()
        if env.get('isolated') is not True or env.get('session')!=args.session or env.get('models_enabled') is not True:
            raise SystemExit('Not the requested isolated, model-enabled QA preview')
        raw=args.source.read_bytes()
        if args.material:mid=args.material
        else:
            response=client.post('/api/academy/learning/materials',files={'file':(args.upload_name or args.source.name,raw)},data={'title':'QA: '+args.source.stem})
            response.raise_for_status();upload=response.json();save('upload.json',upload)
            if upload['document']['status']!='ready':raise SystemExit('Material parsing failed')
            mid=upload['document']['id']
        prefix='/api/academy/learning/lab/books/'+mid
        material=client.get('/api/academy/learning/materials/'+mid);material.raise_for_status();material=material.json()['document']
        source_sha=hashlib.sha256(raw).hexdigest()
        if material['digest']!=source_sha:raise SystemExit('Uploaded material differs from the supplied source; no model call made')
        save('source-binding.json',dict(digest=source_sha,material_id=mid,revision=material['payload']['revision'],filename=material['filename']))
        before=client.get(prefix);before.raise_for_status();before=before.json();save('before.json',before)
        graph=before['graph'];initial=graph
        if args.index_algorithm and graph['index'].get('algorithm')!=args.index_algorithm:raise SystemExit('Directory algorithm differs; no model call made')
        if args.require_empty and (graph['version'] or graph['nodes'] or graph['edges']):raise SystemExit('Graph is not fresh; no model call made')
        selected=args.chapters or (None if args.all_chapters else [graph['index']['chapters'][0]['id']])
        batches=plan_batches(graph['index'],selected);save('plan.json',dict(material_id=mid,batches=batches))
        results=[];started=time.perf_counter()
        for i,chapters in enumerate(batches):
            at=time.perf_counter();response=client.post(prefix+'/graph-propose',json={'chapters':chapters})
            request_seconds=time.perf_counter()-at
            try:payload=response.json()
            except ValueError:payload={'non_json_response':True}
            save(f'batch-{i+1:02}-response.json',payload)
            after=client.get(prefix);after.raise_for_status();after=after.json()
            current=after['graph'];passed=response.status_code==200
            new_edges=current['edges'][len(graph['edges']):] if passed else []
            checks=dict(http_success=passed,
                        response_within_budget=request_seconds<=400,
                        version_incremented=current['version']==graph['version']+1 if passed else current['version']==graph['version'],
                        model_edges_unconfirmed=all(e['status']=='proposed' for e in new_edges),
                        failed_action_preserves_graph=passed or current==graph)
            result=dict(chapters=chapters,http_status=response.status_code,seconds=round(time.perf_counter()-at,3),checks=checks,passed=all(checks.values()),
                        new_nodes=len(current['nodes'])-len(graph['nodes']),new_edges=len(new_edges),run_id=payload.get('run_id') or response.headers.get('x-academy-run-id'),
                        model_calls=payload.get('model_calls'),contract_repairs=payload.get('contract_repairs'))
            results.append(result);save('progress.json',dict(planned=len(batches),finished=len(results),results=results))
            print(json.dumps(result,ensure_ascii=True),flush=True);graph=current
            if request_seconds>400:break  # Pause/suspension is not successful load.
        save('after.json',after)
        report=dict(material_id=mid,total_chapters=len(initial['index']['chapters']),source_sha256=hashlib.sha256(raw).hexdigest(),
                    seconds=round(time.perf_counter()-started,3),batches=results,round_complete=len(results)==len(batches),passed=len(results)==len(batches) and all(r['passed'] for r in results),
                    chapters_attempted=sum(len(b['chapters']) for b in results),covered_chapters=len(graph['covered_chapters']),
                    new_nodes=len(graph['nodes'])-len(initial['nodes']),new_edges=len(graph['edges'])-len(initial['edges']),
                    semantic_accuracy_verified=False,teacher_calibration_verified=False,real_learning_effect_verified=False)
        save('report.json',report);print(json.dumps(report,ensure_ascii=True))
        return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
