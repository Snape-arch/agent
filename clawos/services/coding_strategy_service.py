"""Cost-sensitive paired recommendations with explicit, governed runtime policy."""
from __future__ import annotations

from collections import defaultdict
import copy
import hashlib
import json
import random
from pathlib import Path
import uuid

from reflection.evolution_runtime import RuntimePolicyController
from .coding_comparison_service import CodingComparisonService, digest, save
from .coding_evidence_service import CodingEvidenceService, features
from .learning_governance import THRESHOLDS

LOADED_WITNESS = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (
    Path(__file__),Path(__file__).with_name('coding_evidence_service.py'),
    Path(__file__).with_name('coding_rollout_service.py'),
    Path(__file__).parents[1]/'reflection/evolution_runtime.py',
    Path(__file__).parents[1]/'reflection/self_evolution.py')}


def utility(row):
    limits=row['limits']
    return (float(row['accepted'])-.10*row['tokens']/limits['max_tokens']
        -.05*row['seconds']/limits['max_wall_seconds']-.02*row['calls']/limits['max_model_calls'])


def paired_benefit(bundles, namespace):
    clusters=defaultdict(lambda:defaultdict(list));sources=[]
    for bundle in bundles:
        if bundle['kind']!='native-paired' or not bundle['paired']:continue
        # Incomplete or censored paired experiments do not quietly lose their
        # bad arm while retaining a good one. The whole pair is quarantined.
        grouped=defaultdict(list)
        for row in bundle['rows']:
            if row['namespace']==namespace:grouped[row['task_group']].append(row)
        for group,rows in grouped.items():
            if set(r['mode'] for r in rows)!={'single','multi'} or any(not r['usable'] for r in rows):continue
            sources.append((bundle['id'],group))
            for r in rows:clusters[group][r['mode']].append(utility(r))
    deltas=[]
    for group,modes in sorted(clusters.items()):
        deltas.append(sum(modes['multi'])/len(modes['multi'])-sum(modes['single'])/len(modes['single']))
    mean=sum(deltas)/len(deltas) if deltas else 0
    bounds={}
    for mode,sign in (('multi',1),('single',-1)):
        rng=random.Random(1701)
        draws=sorted(sign*sum(rng.choice(deltas) for _ in deltas)/len(deltas) for _ in range(1000)) if deltas else []
        # Two inspected modes: one-sided 97.5% per mode, task cluster bootstrap.
        bounds[mode]=draws[24] if draws else None
    minimum=THRESHOLDS.lightweight_router_samples
    recommended=next((m for m in ('multi','single') if len(deltas)>=minimum and bounds[m]>.02),None)
    return dict(independent_groups=len(deltas),minimum=minimum,mean_multi_minus_single=round(mean,6),
        lower_bounds=bounds,recommendation=recommended,dataset_digest=digest(sorted(sources)),
        utility='accepted - .10*token_fraction - .05*wall_fraction - .02*call_fraction',
        confidence='equal-weight task clusters; 1000 bootstrap draws; two-mode family correction',
        runtime_promotion_evidence=False)


class CodingStrategyService:
    def __init__(self, store, output_root):
        self.store,self.root=store,Path(output_root).resolve()
        self.evidence=CodingEvidenceService(store,self.root)

    def _runner(self):
        folder=self.root/'cs'/uuid.uuid4().hex[:10]
        if any(hashlib.sha256(Path(p).read_bytes()).hexdigest()!=sha for p,sha in LOADED_WITNESS.items()):
            raise RuntimeError('loaded coding strategy implementation changed')
        return CodingComparisonService(folder,witness=LOADED_WITNESS)

    def _prepare(self, case, factory, limits, baseline_mode, experiment=None):
        if baseline_mode not in {'single','multi'}:raise ValueError('baseline mode must be single or multi')
        runner=self._runner();case=runner.case(case);limits=runner.limits(limits)
        controller=RuntimePolicyController(self.store);identity=case['task_group_digest']
        prompt=controller.resolve('prompt_policy','coding.proposal',identity)
        applied_prompt=copy.deepcopy(prompt)
        if experiment:
            from .coding_rollout_service import check_experiment
            run=check_experiment(self.store,experiment)
            if run['target_type']=='prompt_policy':
                if prompt['payload']!=run['baseline_payload']:
                    raise ValueError('live prompt differs from frozen coding baseline')
                applied_prompt['payload']=copy.deepcopy(run[experiment['variant']+'_payload'])
        prompt_digest=digest(applied_prompt)
        guard={'prompt':prompt,'route':None,'key':None}
        def guarded_factory(role):
            raw=factory(role)
            class BoundProvider:
                name=getattr(raw,'name','');model=getattr(raw,'model','');base_url=getattr(raw,'base_url','')
                chat_template_kwargs=getattr(raw,'chat_template_kwargs',None)
                upstream_signature=runner.svc.provider_signature(raw)
                def prepare_messages(_,messages):
                    if experiment:check_experiment(self.store,experiment)
                    if controller.resolve('prompt_policy','coding.proposal',identity)!=guard['prompt']:
                        raise RuntimeError('coding prompt policy changed during execution')
                    if controller.resolve('routing_policy',guard['key'],identity)!=guard['route']:
                        raise RuntimeError('coding routing policy changed during execution')
                    messages=copy.deepcopy(messages)
                    if messages:
                        messages[0]['content']=controller.apply_prompt(messages[0]['content'],applied_prompt)
                    return messages
                async def complete(_,messages,options):
                    return await raw.complete(messages,options)
            return BoundProvider()
        prototype=guarded_factory('comparison_identity')
        fingerprint=runner.svc.provider_signature(prototype)
        namespace=digest(dict(model=fingerprint,executor=digest(runner.witness),limits=limits,
            features=features(case),prompt_digest=digest(prompt)))
        target='coding.strategy.'+namespace
        route=controller.resolve('routing_policy',target,identity);guard.update(route=route,key=target)
        payload=route['payload'];mode=payload.get('coding_mode',baseline_mode)
        if mode not in {'single','multi'} or (payload and payload.get('namespace')!=namespace):
            raise ValueError('active coding mode policy does not match this namespace')
        if experiment and run['target_type']=='routing_policy':
            if run['target_key']!=target or payload!=run['baseline_payload']:
                raise ValueError('coding routing experiment namespace/baseline mismatch')
            variant_payload=run[experiment['variant']+'_payload']
            mode=variant_payload.get('coding_mode',baseline_mode)
            if mode not in {'single','multi'} or (variant_payload and variant_payload.get('namespace')!=namespace):
                raise ValueError('coding routing candidate namespace mismatch')
        stats=paired_benefit(self.evidence.bundles(),namespace)
        decision=dict(id=uuid.uuid4().hex,namespace=namespace,target_key=target,case_digest=case['case_digest'],
            task_group_digest=identity,features=features(case),limits=limits,baseline_mode=baseline_mode,
            selected_mode=mode,prompt_policy=prompt,routing_policy=route,benefit=stats,
            selection_source='governed_runtime_policy' if 'coding_mode' in payload else 'explicit_baseline',
            strategy_recommendation_applied=False,automatic_publication=False)
        if experiment:decision['experiment']=copy.deepcopy(experiment)
        save(runner.root/'decision.json',decision,immutable=True)
        with self.store.transaction() as c:
            c.execute('INSERT INTO coding_decisions VALUES (?,?,?)',
                (decision['id'],json.dumps(decision,ensure_ascii=False),digest(decision)))
        model=dict(id='configured',factory=guarded_factory,fingerprint=fingerprint,
            actual_provider=prototype.name,actual_model=prototype.model)
        binding=dict(prompt_digest=prompt_digest,namespace=namespace,decision_digest=digest(decision))
        if experiment:binding['experiment']=copy.deepcopy(experiment)
        return runner,case,model,decision,binding

    def preview(self, case, factory, *, limits=None, baseline_mode='single'):
        return self._prepare(case,factory,limits,baseline_mode)[3]

    async def run(self, case, factory, *, confirmed=False, limits=None, baseline_mode='single',paired=False,repetitions=1,_experiment=None):
        if confirmed is not True:raise PermissionError('owned-workspace execution authorization required')
        if type(paired) is not bool or type(repetitions) is not int or not 1<=repetitions<=3:
            raise ValueError('invalid paired mode/repetitions')
        if _experiment and paired:raise ValueError('candidate rollout uses separately frozen variants')
        if _experiment:
            from .coding_rollout_service import check_experiment
        runner,case,model,decision,binding=self._prepare(case,factory,limits,baseline_mode,_experiment)
        # Runtime source witnesses are checked by the same capture wrapper.
        # Freeze the original case contract, not its derived stamp fields.
        original={k:case[k] for k in ('id','repo','objective','paths','test_commands','post_commands','requirements')}
        if paired:
            report=await runner.run([original],[{k:model[k] for k in ('id','factory','fingerprint')}],
                confirmed=True,limits=decision['limits'],repetitions=repetitions,binding=binding)
        else:
            plan=dict(schema='clawos.coding-selection.v1',cases=[case],models=[{k:v for k,v in model.items() if k!='factory'}],
                limits=decision['limits'],implementation_witness=runner.witness,strategy_binding=binding,
                arms=[dict(case_id=case['id'],model_id=model['id'],mode=decision['selected_mode'],repetition=1)])
            plan['plan_digest']=digest(plan);save(runner.root/'plan.json',plan,immutable=True)
            row=await runner.arm(case,model,decision['selected_mode'],decision['limits'],1,1)
            if json.loads((runner.root/'plan.json').read_text(encoding='utf-8'))!=plan:
                raise ValueError('selected coding plan changed')
            runner.verify_arm(row);runner.check_case(case)
            report=dict(schema=plan['schema'],plan_digest=plan['plan_digest'],complete=True,arms=[row])
            save(runner.root/'report.json',report,immutable=True)
        controller=RuntimePolicyController(self.store)
        if (controller.resolve('prompt_policy','coding.proposal',decision['task_group_digest'])!=decision['prompt_policy'] or
                controller.resolve('routing_policy',decision['target_key'],decision['task_group_digest'])!=decision['routing_policy']):
            raise RuntimeError('runtime policy changed before evidence admission')
        if _experiment:check_experiment(self.store,_experiment)
        evidence=self.evidence._record(runner.root,'native-experiment' if _experiment else 'native-paired' if paired else 'native-selected')
        return dict(decision=decision,report=report,evidence=evidence,
            folder=str(runner.root.relative_to(self.root)),source_checkout_applied=False)

    def nominate_routing(self, decision_id):
        from reflection.self_evolution import SelfEvolutionManager
        with self.store.transaction() as c:
            item=c.execute('SELECT * FROM coding_decisions WHERE id=?',(decision_id,)).fetchone()
            if not item:raise ValueError('coding decision not found')
            decision=json.loads(item['payload'])
            if digest(decision)!=item['payload_digest']:raise ValueError('coding decision changed')
            stats=paired_benefit(self.evidence.bundles(),decision['namespace'])
            if not stats['recommendation'] or stats!=decision['benefit']:
                raise ValueError('insufficient or changed independent paired coding evidence')
            current=self.store.get_runtime_policy('routing_policy',decision['target_key']) or {}
            if int(current.get('version',0))!=decision['routing_policy']['policy_version']:
                raise ValueError('coding policy baseline changed')
            base=current.get('payload',{}) if current.get('active') else {}
            candidate={**base,'coding_mode':stats['recommendation'],'namespace':decision['namespace'],
                'coding_evidence_digest':stats['dataset_digest']}
            key=digest(dict(candidate=candidate,version=current.get('version',0)))
            old=c.execute('SELECT run_id FROM coding_nominations WHERE id=?',(key,)).fetchone()
            if old:return self.store.get_self_evolution_run(old['run_id'])
            run=SelfEvolutionManager(self.store).create_run('routing_policy',decision['target_key'],base,candidate,
                title='Coding mode recommendation',created_by='coding_strategy',
                conclusion='Paired cost/quality recommendation only; executed regression and fresh shadow/canary evidence still required.')
            c.execute('INSERT INTO coding_nominations VALUES (?,?)',(key,run['id']))
            return run
