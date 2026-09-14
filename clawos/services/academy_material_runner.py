"""Standalone, fixed teaching runner. Inputs are JSON data, never executable code."""
import json
import re
from pathlib import Path


def tokens(value):
    chars=re.sub(r'[\W_]','',value.lower())
    return {chars[i:i+2] for i in range(len(chars)-1)}


def run(data):
    config=data['config']
    chunks=[]
    for p in data['passages']:
        for start in range(0,len(p['text']),config['chunk_size']):
            text=p['text'][start:start+config['chunk_size']]
            chunks.append(dict(citation=p['id'],text=text,start=start))
    rows=[]
    for case in data['cases']:
        q=tokens(case['query'])
        scored=[dict(c,score=len(q & tokens(c['text']))/max(1,len(q))) for c in chunks]
        found=sorted([c for c in scored if c['score']>0 and c['score']>=config['min_score']],key=lambda c:-c['score'])[:config['top_k']]
        response=found[0] if found else None
        passed=(response is None) if case['citation'] is None else bool(response and response['citation']==case['citation'] and case['quote'] in response['text'])
        rows.append(dict(query=case['query'],passed=passed,response=response,retrieved=found,expected=case))
    return dict(rows=rows,passed=sum(r['passed'] for r in rows),total=len(rows),revision=data['revision'],
        boundary='仅验证用户编写的测试；无答案标签由用户指定。执行成功不等于测试全通过，也不等于学会编程。')


if __name__=='__main__':
    root=Path(__file__).resolve().parent
    result=run(json.loads((root/'input.json').read_text(encoding='utf-8')))
    (root/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=result['passed'],total=result['total'])))
