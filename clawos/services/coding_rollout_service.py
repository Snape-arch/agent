"""Provider-executed, offline baseline/candidate coding regression evidence.

Only service-owned, immutable records enter the coding regression gate. These
experiments never create live quality signals or publish a runtime policy.
"""
from __future__ import annotations

from collections import defaultdict
import copy
import hashlib
import json
from pathlib import Path
import random
import uuid

from .coding_comparison_service import CodingComparisonService, digest, save
from .coding_evidence_service import CodingEvidenceService
from .file_transactions import _file_lock
from .learning_governance import THRESHOLDS

SCHEMA='clawos.coding-rollout.v1'


def frozen_run(store, run_id):
    if type(run_id) is not int or run_id<=0:raise ValueError('positive integer candidate run_id required')
    run=store.get_self_evolution_run(run_id)
    if not run:raise ValueError('coding candidate not found')
    if not ((run['target_type']=='prompt_policy' and run['target_key']=='coding.proposal') or
            (run['target_type']=='routing_policy' and run['target_key'].startswith('coding.strategy.'))):
        raise ValueError('unsupported coding candidate target')
    current=store.get_runtime_policy(run['target_type'],run['target_key']) or {}
    base=current.get('payload',{}) if current.get('active') else {}
    if current.get('version',0)!=run['baseline_policy_version'] or base!=run['baseline_payload']:
        raise ValueError('coding candidate baseline changed')
    permitted={'system','prompt','coding_failure_evidence'} if run['target_type']=='prompt_policy' else {'coding_mode','namespace','coding_evidence_digest'}
    for payload in (run['baseline_payload'],run['candidate_payload']):
        if not isinstance(payload,dict) or set(payload)-permitted:raise ValueError('unsupported coding policy fields')
        for key in ('system','prompt'):
            if key in payload and (not isinstance(payload[key],str) or len(payload[key])>4000):
                raise ValueError('coding prompt must be bounded text')
    if run['baseline_payload']==run['candidate_payload']:raise ValueError('coding candidate has no policy change')
    signature={k:run[k] for k in ('id','target_type','target_key','baseline_payload','candidate_payload','baseline_policy_version')}
    return run,digest(signature)


def check_experiment(store, packet):
    if set(packet)!={'run_id','signature','variant','stage'} or packet['variant'] not in {'baseline','candidate'} or packet['stage']!='offline':
        raise ValueError('invalid coding experiment binding')
    run,signature=frozen_run(store,packet['run_id'])
    if signature!=packet['signature']:raise ValueError('coding candidate changed during experiment')
    if run['status'] not in {'candidate','rejected','validated'}:raise ValueError('coding experiment requires an unpublished candidate')
    return run


def candidate_family(store, run):
    with store._conn() as c:
        rows=c.execute('SELECT candidate_payload FROM self_evolution_runs WHERE target_type=? AND target_key=? AND baseline_policy_version=? LIMIT 5001',
            (run['target_type'],run['target_key'],run['baseline_policy_version'])).fetchall()
    if len(rows)>5000:raise ValueError('coding candidate family exceeds bounded review limit')
    return max(1,len({digest(json.loads(row['candidate_payload'])) for row in rows}))


def paired_statistics(observations, *, family_size=1):
    if type(family_size) is not int or not 1<=family_size<=5000:raise ValueError('invalid coding candidate family size')
    clusters=defaultdict(lambda:defaultdict(list))
    for row in observations:
        clusters[row['task_group']][row['variant']].append(row)
    deltas=[];base_success=[];candidate_success=[]
    usable=bool(clusters)
    from .coding_strategy_service import utility
    for _,variants in sorted(clusters.items()):
        if set(variants)!={'baseline','candidate'} or any(not r['usable'] for rows in variants.values() for r in rows):
            usable=False;continue
        means={v:sum(utility(r) for r in rows)/len(rows) for v,rows in variants.items()}
        deltas.append(means['candidate']-means['baseline'])
        base_success.append(sum(r['accepted'] for r in variants['baseline'])/len(variants['baseline']))
        candidate_success.append(sum(r['accepted'] for r in variants['candidate'])/len(variants['candidate']))
    rng=random.Random(1701)
    draws=sorted(sum(rng.choice(deltas) for _ in deltas)/len(deltas) for _ in range(1000)) if deltas else []
    alpha=.05/family_size
    lower=draws[int(alpha*999)] if draws else None
    baseline=sum(base_success)/len(base_success) if base_success else 0
    candidate=sum(candidate_success)/len(candidate_success) if candidate_success else 0
    minimum=THRESHOLDS.shadow_samples
    passed=usable and len(deltas)>=minimum and candidate>=.8 and candidate>=baseline and lower>=-.02
    return dict(independent_groups=len(clusters),usable_groups=len(deltas),minimum=minimum,all_pairs_usable=usable,
        baseline_success_rate=baseline,candidate_success_rate=candidate,mean_utility_delta=sum(deltas)/len(deltas) if deltas else 0,
        utility_lower_bound=lower,tolerance=.02,passed=passed,
        candidate_family=family_size,alpha=alpha,
        confidence='1000 task-cluster bootstrap draws, equal task weights; Bonferroni across baseline-bound candidate payloads',
        runtime_promotion_evidence=False)


class CodingRolloutService:
    def __init__(self, store, output_root):
        self.store,self.root=store,Path(output_root).resolve()
        self.evidence=CodingEvidenceService(store,self.root)
        with store.transaction() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS coding_rollouts (
                id TEXT PRIMARY KEY, run_id INTEGER NOT NULL, root TEXT NOT NULL,
                folder TEXT NOT NULL, payload TEXT NOT NULL, payload_digest TEXT NOT NULL)''')

    async def run(self, run_id, cases, factory, *, confirmed=False, limits=None, baseline_mode='single',repetitions=1):
        if confirmed is not True:raise PermissionError('coding rollout requires owned-workspace execution authorization')
        if not isinstance(cases,list) or not 1<=len(cases)<=8 or type(repetitions) is not int or not 1<=repetitions<=3:
            raise ValueError('rollout needs 1..8 cases and 1..3 predeclared repetitions')
        run,signature=frozen_run(self.store,run_id)
        packet=dict(run_id=run_id,signature=signature,variant='baseline',stage='offline')
        check_experiment(self.store,packet)
        from .coding_strategy_service import CodingStrategyService
        strategy=CodingStrategyService(self.store,self.root)
        root=self.root/'cr'/uuid.uuid4().hex[:10];runner=strategy._runner()
        cases=[runner.case(c) for c in copy.deepcopy(cases)];caps=runner.limits(limits)
        if len({c['id'] for c in cases})!=len(cases):raise ValueError('duplicate rollout case ids')
        prototype=factory('comparison_identity')
        provider=runner.svc.provider_signature(prototype)
        scheduled=[]
        for i,case in enumerate(cases):
            for rep in range(1,repetitions+1):
                order=('baseline','candidate') if (i+rep)%2 else ('candidate','baseline')
                scheduled.extend(dict(case_id=case['id'],repetition=rep,variant=v) for v in order)
        plan=dict(schema=SCHEMA,run_id=run_id,signature=signature,cases=cases,limits=caps,baseline_mode=baseline_mode,
            provider_fingerprint=provider,implementation_witness=runner.witness,arms=scheduled,
            candidate_family=candidate_family(self.store,run),
            order_policy='AB/BA by task and repetition; sequential; no cold-cache control')
        plan['plan_digest']=digest(plan);save(root/'plan.json',plan,immutable=True)
        observations=[]
        lock=self.root/'cr'/('candidate-'+digest(str(self.store._db_path))[:10]+'-'+str(run_id))
        with _file_lock(lock,timeout=0):
            for scheduled_arm in scheduled:
                check_experiment(self.store,packet)
                if json.loads((root/'plan.json').read_text(encoding='utf-8'))!=plan:raise ValueError('coding rollout plan changed')
                if runner.svc.provider_signature(factory('comparison_identity'))!=provider:raise ValueError('rollout provider changed')
                if not all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in runner.witness.items()):
                    raise ValueError('rollout implementation changed')
                case=next(c for c in cases if c['id']==scheduled_arm['case_id']);runner.check_case(case)
                frozen={k:case[k] for k in ('id','repo','objective','paths','test_commands','post_commands','requirements')}
                arm_packet=packet|{'variant':scheduled_arm['variant']}
                result=await strategy.run(frozen,factory,confirmed=True,limits=caps,baseline_mode=baseline_mode,_experiment=arm_packet)
                bundle=result['evidence'];row=bundle['rows'][0]
                observations.append(row|scheduled_arm|dict(child_folder=result['folder'],child_id=bundle['id'],child_digest=digest(bundle),
                    case_digest=case['case_digest'],provider_fingerprint=provider,executor_digest=digest(runner.witness)))
                save(root/'progress.json',dict(completed=len(observations),planned=len(scheduled),observations=observations))
            check_experiment(self.store,packet)
            if json.loads((root/'plan.json').read_text(encoding='utf-8'))!=plan:raise ValueError('coding rollout plan changed')
            for case in cases:runner.check_case(case)
            report=dict(schema=SCHEMA,run_id=run_id,signature=signature,plan_digest=plan['plan_digest'],complete=True,
                observations=observations,statistics=paired_statistics(observations,family_size=plan['candidate_family']),source_checkout_applied=False,quality_signals_created=0)
            save(root/'report.json',report,immutable=True)
            payload=dict(id=digest(report),plan_digest=plan['plan_digest'],report_digest=digest(report),signature=signature)
            with self.store.transaction() as c:
                frozen_run(self.store,run_id)
                c.execute('INSERT INTO coding_rollouts VALUES (?,?,?,?,?,?)',(payload['id'],run_id,str(self.root),str(root.relative_to(self.root)),json.dumps(payload),digest(payload)))
        return dict(folder=str(root.relative_to(self.root)),report=report,candidate_published=False)

    def verified(self, run_id):
        run,signature=frozen_run(self.store,run_id)
        with self.store._conn() as c:records=c.execute('SELECT * FROM coding_rollouts WHERE run_id=? ORDER BY id',(run_id,)).fetchall()
        observations=[];group_bindings={};experiment_binding=None
        family_size=candidate_family(self.store,run)
        from .coding_strategy_service import LOADED_WITNESS
        from .coding_comparison_service import LOADED_WITNESS as CORE_WITNESS
        current_witness=dict(CORE_WITNESS)|LOADED_WITNESS
        for record in records:
            if Path(record['root']).resolve()!=self.root:continue
            payload=json.loads(record['payload'])
            if digest(payload)!=record['payload_digest']:raise ValueError('stored rollout receipt changed')
            folder=self.evidence.path(record['folder'])
            def read(name):
                file=self.evidence.path(name,base=folder)
                if file.stat().st_size>8*1024*1024:raise ValueError('rollout receipt exceeds read limit')
                return json.loads(file.read_text(encoding='utf-8'))
            plan,report=read('plan.json'),read('report.json')
            if (plan['schema']!=SCHEMA or digest({k:v for k,v in plan.items() if k!='plan_digest'})!=plan['plan_digest'] or
                    report['complete'] is not True or report['signature']!=signature or plan['signature']!=signature or
                    payload!=dict(id=digest(report),plan_digest=plan['plan_digest'],report_digest=digest(report),signature=signature) or
                    report['plan_digest']!=plan['plan_digest'] or plan['run_id']!=run_id or report['run_id']!=run_id or
                    len(plan['arms'])!=len(report['observations'])):raise ValueError('rollout receipt binding mismatch')
            if plan['implementation_witness']!=current_witness or any(hashlib.sha256(Path(p).read_bytes()).hexdigest()!=sha for p,sha in current_witness.items()):
                raise ValueError('rollout executor is stale')
            binding=(plan['provider_fingerprint'],digest(current_witness),digest(plan['limits']),plan['baseline_mode'])
            if experiment_binding is not None and experiment_binding!=binding:raise ValueError('incompatible rollout model/budget/mode')
            experiment_binding=binding
            for scheduled,row in zip(plan['arms'],report['observations']):
                if any(row[k]!=v for k,v in scheduled.items()):raise ValueError('rollout order/variant mismatch')
                case=next(c for c in plan['cases'] if c['id']==row['case_id'])
                if (row['provider_fingerprint']!=plan['provider_fingerprint'] or row['executor_digest']!=digest(current_witness) or
                        row['limits']!=plan['limits'] or row['task_group']!=case['task_group_digest']):
                    raise ValueError('rollout model/executor/budget/task mismatch')
                body={k:v for k,v in case.items() if k not in {'case_digest','repo'}}
                if digest(body)!=case['case_digest'] or row['case_digest']!=case['case_digest']:raise ValueError('rollout case changed')
                old=group_bindings.setdefault(row['task_group'],case['case_digest'])
                if old!=case['case_digest']:raise ValueError('same task group has conflicting frozen inputs')
                child=self.evidence.verify(row['child_folder']);child['kind']='native-experiment'
                child_plan_path=self.evidence.path('plan.json',base=self.evidence.path(row['child_folder']))
                child_plan=json.loads(child_plan_path.read_text(encoding='utf-8'))
                if child_plan['cases'][0]['case_digest']!=case['case_digest']:raise ValueError('rollout child frozen input mismatch')
                with self.store._conn() as c:stored=c.execute('SELECT * FROM coding_evidence WHERE id=?',(child['id'],)).fetchone()
                if not stored or stored['kind']!='native-experiment' or digest(json.loads(stored['payload']))!=stored['payload_digest']:
                    raise ValueError('rollout child is not service-owned experimental evidence')
                if json.loads(stored['payload'])!=child or row['child_id']!=child['id'] or row['child_digest']!=digest(child):
                    raise ValueError('rollout child receipt changed')
                expected=dict(run_id=run_id,signature=signature,variant=row['variant'],stage='offline')
                if child['binding'].get('experiment')!=expected:raise ValueError('rollout child candidate/variant binding mismatch')
                if any(row[k]!=v for k,v in child['rows'][0].items()):raise ValueError('rollout outcome changed')
                observations.append(row)
            if report['statistics']!=paired_statistics(report['observations'],family_size=plan['candidate_family']):raise ValueError('rollout statistics changed')
            family_size=max(family_size,plan['candidate_family'])
        return dict(records=len(records),observations=observations,statistics=paired_statistics(observations,family_size=family_size),runtime_promotion_evidence=False)


def coding_gate(store, run_id):
    """Read only the roots registered by this service, never caller metrics."""
    gate=dict(passed=False,records=0,statistics=paired_statistics([]),reason='missing provider-executed coding rollout')
    with store._conn() as c:
        exists=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='coding_rollouts'").fetchone()
        roots=c.execute('SELECT DISTINCT root FROM coding_rollouts WHERE run_id=?',(run_id,)).fetchall() if exists else []
    if not roots:return gate
    if len(roots)!=1:return gate|{'reason':'multiple coding rollout ownership roots'}
    try:
        result=CodingRolloutService(store,roots[0]['root']).verified(run_id)
        return dict(passed=result['statistics']['passed'],records=result['records'],statistics=result['statistics'],
            reason='verified offline coding regression' if result['statistics']['passed'] else 'coding sample/quality/cost gate not met')
    except (OSError,ValueError,TypeError,KeyError,RuntimeError) as exc:
        return gate|{'reason':str(exc)}
