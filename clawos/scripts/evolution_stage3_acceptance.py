"""Small actual-provider API acceptance on an owned isolated loopback preview.

Questions and ratings are synthetic, hence no quality gain or teacher claim.
Session cookies exist only in memory and are never printed or saved.
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:18920')
    parser.add_argument('--out',default=str(ROOT/'output/evolution-stage3-http-20261004'))
    args=parser.parse_args();out=Path(args.out).resolve()
    from urllib.parse import urlparse
    endpoint=urlparse(args.url)
    if endpoint.scheme!='http' or endpoint.hostname!='127.0.0.1' or endpoint.username or endpoint.password:parser.error('owned loopback required')
    if not out.is_relative_to((ROOT/'output').resolve()):parser.error('ignored output directory required')
    out.mkdir(parents=True,exist_ok=True);checks=[];started=time.monotonic()
    def check(name,condition):
        assert condition,name
        checks.append(name);print('PASS '+name,flush=True)
    with httpx.Client(base_url=args.url,timeout=200,trust_env=False) as owner:
        marker=owner.get('/api/qa/environment').json()
        check('isolated preview explicitly configured for local provider',marker.get('isolated') and marker.get('models_enabled'))
        unique=uuid.uuid4().hex
        cases=[{'id':f'actual-{i}','group_id':f'group-{i}','query':f'验收任务 {unique} {i}：只用一句中文列出 context 中允许的工具，并说明是否允许 shell_exec。',
                'reviewed_by':'synthetic-protocol-author','route':{'allowed_tools':['file_read','file_write','shell_exec','web_fetch','web_search']},
                'required_tools':['file_read'],'forbidden_tools':['file_write','shell_exec','web_fetch']} for i in range(10)]
        response=owner.post('/api/self-evolution/experiments',json={'target_type':'tool_routing_policy','target_key':'stage3-actual-'+unique,'baseline_payload':{},'cases':cases})
        response.raise_for_status();exp=response.json()['experiment'];eid=exp['id'];base=f'/api/self-evolution/experiments/{eid}'
        response=owner.post(base+'/replay');response.raise_for_status();exp=response.json()['experiment']
        plan=owner.get(base+'/model-capture').json()['plan'];check('paired plan covers every held-out case',plan['calls']>0 and plan['calls']==2*len(exp['report']['holdout_pairs']))
        response=owner.post(base+'/model-capture',json={'max_calls':plan['calls'],'max_tokens':256,'timeout':60})
        response.raise_for_status();packet=response.json()['packet']
        response=owner.get(base+'/model-receipts');response.raise_for_status();receipts=response.json()['receipts']
        check('actual local-provider paired responses completed without tools',len(receipts)==plan['calls'] and all(row['finish_reason']=='stop' and row['request']['options']['tools']==[] for row in receipts))
        check('captured provenance and request/output digests retained',owner.get(base+'/review/summary').json()['summary']['provider_execution_verified'] and all(row['request_digest'] and row['text_digest'] and row['receipt_digest'] for row in receipts))
        doc=owner.post('/api/academy/learning/documents',json={'title':'Stage 3 synthetic identity fixture','blocks':[{'id':'p','type':'paragraph','text':'Synthetic acceptance; not teacher identity evidence'}]}).json()
        clients=[];uids=[]
        try:
            for role in ('reviewer','reviewer','adjudicator'):
                invite=owner.post(f'/api/collaboration/documents/{doc["id"]}/invite',json={'role':'viewer'}).json()
                client=httpx.Client(base_url=args.url,timeout=30,trust_env=False);clients.append(client)
                response=client.post('/api/collaboration/join',json={'code':invite['code'],'name':'Synthetic '+role});response.raise_for_status();uid=response.json()['id'];uids.append(uid)
                response=owner.post(base+'/review-grants',json={'user_id':uid,'role':role});response.raise_for_status()
            check('server-issued sessions cannot access owner administration',clients[0].get('/api/self-evolution/review-users').status_code==403)
            path=f'/api/evolution-review/{eid}'
            blinded=clients[0].get(path+'/packet').json();check('assigned reviewer cannot see other scores or variant mapping',blinded['viewer']['id']==uids[0] and 'reviewed_gate' not in blinded['summary'] and 'mapping' not in json.dumps(blinded['packet']))
            for i,client in enumerate(clients[:2]):
                rating={'packet_digest':packet['packet_digest'],'reviewer':'spoofed-owner','ratings':[{'entry_id':entry['entry_id'],'options':{label:{'score':(.3 if i==1 and label=='A' else .8),'rationale':'Synthetic protocol score; not actual teacher judgment','critical_error':False,'text_digest':value['text_digest']} for label,value in entry['options'].items()}} for entry in packet['entries']]}
                response=client.post(path+'/ratings',json=rating);response.raise_for_status()
            summary=owner.get(base+'/review/summary').json()['summary']
            check('two authenticated reviews preserve disagreements',summary['authenticated_reviewer_count']==2 and len(summary['authenticated_adjudication_required'])==len(packet['entries']))
            decision_packet=clients[2].get(path+'/packet').json();check('adjudicator receives conflicts and pseudonymous original ratings',decision_packet['role']=='adjudicator' and len(decision_packet['packet']['prior_ratings'])==2)
            for entry in decision_packet['packet']['entries']:
                decision={'packet_digest':packet['packet_digest'],'entry_id':entry['entry_id'],'review_set_digest':decision_packet['summary']['authenticated_review_set_digest'],
                   'options':{label:{'score':.8,'rationale':'Synthetic adjudication, preserves original observations','critical_error':False,'text_digest':value['text_digest']} for label,value in entry['options'].items()}}
                response=clients[2].post(path+'/adjudication',json=decision);response.raise_for_status()
            summary=owner.get(base+'/review/summary').json()['summary']
            check('adjudication resolves conflicts without inflating small-sample support',summary['authenticated_resolved_entries']==len(packet['entries']) and not summary['authenticated_review_passed'] and not summary['runtime_promotion_evidence'])
            response=owner.post(base+'/review-grants',json={'user_id':uids[0],'role':'revoked'});response.raise_for_status()
            check('revoked reviewer loses read and write rights immediately',clients[0].get(path+'/packet').status_code==403 and clients[0].post(path+'/ratings',json={}).status_code==403)
            evidence=owner.get(base+'/review/evidence').json()['evidence']
            check('original scores and independent decisions remain immutable evidence',len(evidence['reviews'])==2 and len(evidence['adjudications'])==len(packet['entries']) and all(row['reviewer']=='session:'+uid for row,uid in zip(sorted(evidence['reviews'],key=lambda row:row['reviewer']),sorted(uids[:2]))))
            check('credentials do not enter exported evidence',not any(secret in json.dumps(evidence) for client in clients for secret in client.cookies.values()))
            result={'passed':len(checks),'checks':checks,'experiment_id':eid,'model_calls':len(receipts),'holdout_groups':exp['report']['holdout_groups'],
              'duration_seconds':round(time.monotonic()-started,3),'models':sorted({row['model'] for row in receipts}),
              'total_provider_prompt_tokens':sum(row['usage'].get('prompt_tokens',0) for row in receipts),
              'total_provider_completion_tokens':sum(row['usage'].get('completion_tokens',0) for row in receipts),
              'definition_digest':exp['definition_digest'],'report_digest':exp['report']['report_digest'],'packet_digest':packet['packet_digest'],
              'source_sha256':exp['definition']['source_sha256'],'summary':summary,
              'scope':'actual local provider HTTP responses, synthetic questions and ratings; no teacher validation, person independence, quality gain or automatic release claim'}
            for name,value in [('result.json',result),('experiment.json',exp),('receipts.json',receipts),('review-evidence.json',evidence)]:
                (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        finally:
            for client in clients:client.post('/api/collaboration/logout');client.close()


if __name__=='__main__':main()
