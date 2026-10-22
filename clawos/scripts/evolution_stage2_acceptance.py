"""Owned HTTP contract acceptance; fixtures are not real model/teacher evidence."""
import argparse
import json
import sys
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.evolution_experiments import digest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:18919')
    parser.add_argument('--out',default=str(ROOT/'output/evolution-stage2-http-20261004'))
    args=parser.parse_args(); out=Path(args.out).resolve()
    if not out.is_relative_to((ROOT/'output').resolve()): parser.error('keep evidence in ignored output')
    out.mkdir(parents=True,exist_ok=True)
    checks=[]
    def check(name,condition):
        assert condition,name
        checks.append(name); print('PASS '+name,flush=True)
    with httpx.Client(base_url=args.url,timeout=190) as client:
        marker=client.get('/api/qa/environment').json()
        check('owned model-free isolated preview',marker.get('isolated') and not marker.get('models_enabled'))
        check('malformed and non-object payloads fail explicitly',client.post('/api/self-evolution/experiments',json=[]).status_code==400 and client.post('/api/self-evolution/experiments',content='broken').status_code==400)
        rows=[{'id':f'stage2-{i}','group_id':f'fixture-group-{i}','query':f'Phase two HTTP question {i}',
               'reviewed_by':'synthetic-http-fixture','segment':'default',
               'route':{'allowed_tools':['file_read','file_write','shell_exec','web_fetch','web_search']},
               'required_tools':['file_read'],'forbidden_tools':['file_write','shell_exec','web_fetch']} for i in range(200)]
        frozen=client.post('/api/self-evolution/experiments',json={'target_type':'tool_routing_policy','target_key':'stage-two-http','baseline_payload':{},'cases':rows})
        frozen.raise_for_status(); exp=frozen.json()['experiment']; base=f'/api/self-evolution/experiments/{exp["id"]}'
        paused=client.post(base+'/control',json={'action':'pause'})
        check('pending pause retains immutable definition',paused.status_code==200 and paused.json()['experiment']['definition_digest']==exp['definition_digest'])
        replay=client.post(base+'/replay'); replay.raise_for_status(); exp=replay.json()['experiment']; report=exp['report']
        check('resume completes actual checkpointed production replay',exp['status']=='completed' and exp['job']['checkpoint_count']>0 and report['holdout_groups']==37 and report['eligible_for_regression_queue'])
        check('predeclared segment gate participates in acceptance',report['stratified_gate']['passed'] and report['gates']['segment_non_regression'])
        repeated=client.post('/api/self-evolution/experiments',json={'target_type':'tool_routing_policy','target_key':'renamed-campaign','baseline_payload':{},'cases':rows})
        check('used holdout cannot be renamed into a new campaign',repeated.status_code==400 and 'holdout exposure' in repeated.text)
        check('completed evidence cannot be cancelled or replayed',client.post(base+'/control',json={'action':'cancel'}).status_code==409 and client.post(base+'/replay').status_code==409)
        outputs={'definition_digest':exp['definition_digest'],'report_digest':report['report_digest'],'actor_id':'synthetic-output-submitter',
                 'outputs':[{'case_id':pair['case_id'],'input_digest':pair['input_digest'],
                 'variants':{variant:{'text':f'Synthetic answer for {pair["case_id"]}; fixture only.',
                    'provider':'synthetic-http','model':'not-a-real-model','policy_digest':digest(policy)}
                    for variant,policy in [('control',exp['definition']['baseline_payload']),('candidate',report['selected_payload'])]}}
                    for pair in report['holdout_pairs']]}
        bad={**outputs,'definition_digest':'wrong'}
        check('model outputs must match the exact experiment version',client.post(base+'/review-outputs',json=bad).status_code==400)
        packet=client.post(base+'/review-outputs',json=outputs); packet.raise_for_status(); packet=packet.json()['packet']
        check('blind export omits policy/provider and variant mapping','mapping' not in json.dumps(packet) and 'policy_digest' not in json.dumps(packet) and 'provider' not in json.dumps(packet))
        check('frozen output import is idempotent',client.post(base+'/review-outputs',json=outputs).json()['packet']==packet)
        ratings=[]
        for name in ['synthetic-reviewer-a','synthetic-reviewer-b']:
            review={'packet_digest':packet['packet_digest'],'reviewer':name,
                    'ratings':[{'entry_id':entry['entry_id'],'options':{label:{'text_digest':value['text_digest'],'score':.8,'rationale':'Synthetic HTTP check; not actual teacher feedback','critical_error':False}
                    for label,value in entry['options'].items()}} for entry in packet['entries']]}
            response=client.post(base+'/reviews',json=review); response.raise_for_status(); summary=response.json()['summary']; ratings.append(review)
        check('two task-bound reviews retain unverified provenance',summary['reviewer_count']==2 and summary['reported_review_passed'] and not summary['reviewer_identity_verified'] and not summary['provider_execution_verified'])
        check('review does not create runtime promotion evidence',not summary['runtime_promotion_evidence'] and not summary['semantic_entailment_verified'])
        ratings[0]['ratings'][0]['options']['A']['score']=.7
        check('review judgments cannot be overwritten',client.post(base+'/reviews',json=ratings[0]).status_code==400)
        check('review writes retain cross-site protection',client.post(base+'/reviews',json={},headers={'Origin':'https://untrusted.example'}).status_code==403)
        evidence=client.get(base+'/review/evidence'); evidence.raise_for_status()
        check('downloaded complete review evidence binds input and output digests',evidence.json()['evidence']['packet_digest']==packet['packet_digest'] and len(evidence.json()['evidence']['reviews'])==2)
        for name,value in [('experiment.json',exp),('outputs.json',outputs),('packet.json',packet),('review-evidence.json',evidence.json()['evidence'])]:
            (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        (out/'result.json').write_text(json.dumps({'passed':len(checks),'checks':checks,'marker':marker,'definition_digest':exp['definition_digest'],
            'report_digest':report['report_digest'],'source_sha256':exp['definition']['source_sha256'],'holdout_groups':report['holdout_groups'],
            'scope':'synthetic one-host API; no genuine model output, teacher identity or quality gain claim'},indent=2),encoding='utf-8')


if __name__=='__main__': main()
