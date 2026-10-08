"""Verified local coding artifacts become diagnostics, never release signals."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re

from .coding_comparison_service import CodingComparisonService, digest
from .coding_execution_context import CodingExecutionContext
from .coding_contracts import CodingContracts


def features(case):
    paths = case['paths']
    return dict(scope='one' if len(paths)==1 else 'two-four' if len(paths)<=4 else 'five-plus',
        language='python' if all(p.endswith('.py') for p in paths) else 'mixed',
        contracts='bound' if case['requirements'] else 'unbound',
        tests=len(case['test_commands']), post=len(case['post_commands']))


class CodingEvidenceService:
    def __init__(self, store, output_root):
        self.store, self.root = store, Path(output_root).resolve()
        with store.transaction() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS coding_evidence (
                    id TEXT PRIMARY KEY, folder TEXT NOT NULL, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, payload_digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS coding_decisions (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, payload_digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS coding_nominations (
                    id TEXT PRIMARY KEY, run_id INTEGER NOT NULL);
            ''')

    def path(self, path, *, base=None):
        p=Path(path)
        if not p.is_absolute():p=(base or self.root)/p
        resolved=p.resolve();resolved.relative_to(self.root)
        # Resolve only after inspecting the lexical path: an in-root link is
        # still mutable indirection, even if its current target is also inside.
        p.absolute().relative_to(self.root)
        for node in (p,*p.parents):
            if node==self.root.parent:break
            if node.is_symlink() or (hasattr(node,'is_junction') and node.is_junction()):
                raise ValueError('evidence links/junctions are not allowed')
        return resolved

    def verify(self, folder):
        folder=self.path(folder);used=0
        def read(path):
            nonlocal used
            p=self.path(path,base=folder);size=p.stat().st_size;used+=size
            if size>16*1024*1024 or used>64*1024*1024:raise ValueError('evidence exceeds bounded read limit')
            return json.loads(p.read_text(encoding='utf-8'))
        plan,report=read('plan.json'),read('report.json')
        if plan.get('schema') not in {CodingComparisonService.SCHEMA,'clawos.coding-selection.v1'}:
            raise ValueError('unsupported coding plan')
        if digest({k:v for k,v in plan.items() if k!='plan_digest'})!=plan.get('plan_digest'):
            raise ValueError('plan digest mismatch')
        if report.get('plan_digest')!=plan['plan_digest'] or report.get('complete') is not True:
            raise ValueError('incomplete or unbound coding report')
        rows=report.get('arms',[])
        if not rows or len(rows)!=len(plan['arms']) or len(rows)>192:raise ValueError('arm count mismatch')
        witness=plan['implementation_witness']
        if not witness or any(not re.fullmatch('[a-f0-9]{64}',v) for v in witness.values()):
            raise ValueError('invalid implementation witness')
        result=[]
        for scheduled,row in zip(plan['arms'],rows):
            if not re.fullmatch(r'arm-\d{2,3}(?:-[a-z0-9_-]{1,100})?/report\.json',row['artifact']):
                raise ValueError('invalid arm artifact path')
            if any(row.get(k)!=v for k,v in scheduled.items()):raise ValueError('arm order/identity mismatch')
            disk=read(row['artifact'])
            if digest(disk)!=row['report_digest'] or {k:v for k,v in row.items() if k not in {'artifact','report_digest'}}!=disk:
                raise ValueError('arm report digest mismatch')
            case=next(c for c in plan['cases'] if c['id']==row['case_id'])
            body={k:v for k,v in case.items() if k not in {'case_digest','repo'}}
            if digest(body)!=case['case_digest'] or row['case_digest']!=case['case_digest']:
                raise ValueError('case binding mismatch')
            group=digest({k:v for k,v in case.items() if k not in {'repo','id','source_stamp','source_head','task_group_digest','case_digest'}})
            if group!=case['task_group_digest'] or row['task_group_digest']!=group:raise ValueError('task group mismatch')
            limits=CodingComparisonService.limits(plan['limits'])
            if row['limits']!=limits:raise ValueError('arm budget mismatch')
            model=next(m for m in plan['models'] if m['id']==row['model_id'])
            if row['provider_fingerprint']!=model['fingerprint']:raise ValueError('model fingerprint mismatch')
            ledger=row['ledger'];answers=[]
            for ref in ledger['receipts']:
                if not re.fullmatch(r'answer-\d+\.json',ref['artifact']):raise ValueError('invalid answer path')
                value=read(str(Path(row['artifact']).parent/ref['artifact']))
                if digest(value)!=ref['digest'] or digest(value['content'])!=value['content_digest']:
                    raise ValueError('answer receipt mismatch')
                if value['call']!=ref['call']:raise ValueError('answer call identity mismatch')
                answers.append(value)
            if type(ledger['calls']) is not int or not 0<=ledger['calls']<=48:raise ValueError('invalid call ledger')
            numbers=[a['call'] for a in answers]
            if len(set(numbers))!=len(numbers) or any(not 1<=n<=ledger['calls'] for n in numbers):
                raise ValueError('duplicate/outside call receipt')
            reservations=ledger['reservations']
            if [r['call'] for r in reservations]!=list(range(1,ledger['calls']+1)):
                raise ValueError('reservation ledger mismatch')
            for a in answers:
                reservation=reservations[a['call']-1]
                if a['input_digest']!=reservation['input_digest'] or a['options']!=reservation['options']:
                    raise ValueError('answer input/options mismatch')
            for key in ('charged_tokens','provider_tokens','reserved_tokens','elapsed_seconds'):
                if type(ledger[key]) not in {int,float} or not math.isfinite(ledger[key]) or ledger[key]<0:
                    raise ValueError('invalid accounting value')
            # Unknown/failed transports remain diagnostic records. Only every
            # completed, identity-bound stop answer with known usage is usable
            # for cost/quality comparison; admitted requests alone are not proof.
            known=bool(answers) and len(answers)==ledger['calls'] and all(
                a['ok'] is True and a['content'] and a['finish_reason']=='stop' and
                a['provider']==model['actual_provider'] and a['model']==model['actual_model'] and
                a['accounting_source']=='provider_usage' and type(a['charged_tokens']) is int and a['charged_tokens']>0
                for a in answers)
            if known and sum(a['charged_tokens'] for a in answers)!=ledger['charged_tokens']:
                raise ValueError('answer/accounting sum mismatch')
            if known and ledger['provider_tokens']!=ledger['charged_tokens']:
                raise ValueError('provider/accounting sum mismatch')
            within=(ledger['calls']<=limits['max_model_calls'] and ledger['charged_tokens']<=limits['max_tokens'] and
                ledger['elapsed_seconds']<=limits['max_wall_seconds'] and ledger['reserved_tokens']==0)
            if row['within_budget']!=within:raise ValueError('budget predicate mismatch')
            validation=row['validation']
            if validation:
                tests=validation['tests']
                if [t['command'] for t in tests]!=case['test_commands']+case['post_commands']:
                    raise ValueError('caller test commands changed')
                patch=self.path(str(Path(row['artifact']).parent/'changes.patch'),base=folder)
                import hashlib
                if patch.stat().st_size>16*1024*1024:raise ValueError('replay patch exceeds read limit')
                if patch.stat().st_size!=validation['patch_bytes'] or hashlib.sha256(patch.read_bytes()).hexdigest()!=validation['patch_sha256']:
                    raise ValueError('replay patch digest mismatch')
                if any(r.get('clauses') or r.get('interface') for r in case['requirements']):
                    replay = self.path(validation['workspace']['workspace'], base=folder)
                    replay.relative_to(self.path(str(Path(row['artifact']).parent), base=folder))
                    expected = CodingContracts.results(case['requirements'],
                        [t for t in tests if t['phase']=='test_commands'], digest, repo=replay)
                    if validation.get('requirements') != expected:
                        raise ValueError('replay contract clause/interface evidence changed')
                    if validation['passed'] and not all(r['passed'] for r in expected):
                        raise ValueError('passing replay omitted declared contract')
            if row['mode']=='multi' and row['result'].get('run_id'):
                run_id=row['result']['run_id']
                if not re.fullmatch(r'collab-[a-f0-9]{32}',run_id):raise ValueError('invalid native run identity')
                base=Path(row['artifact']).parent/'c'/run_id
                envelope=read(str(base/'checkpoint.json'));state=envelope['state']
                if digest(state)!=envelope['sha256'] or state['run_id']!=run_id:
                    raise ValueError('native checkpoint changed')
                for sha,record in state.get('contexts',{}).items():
                    if not re.fullmatch('[a-f0-9]{64}',sha) or record['artifact']!='contexts/'+sha+'.json':
                        raise ValueError('native context identity mismatch')
                    packet=read(str(base/record['artifact']));CodingExecutionContext.verify_packet(packet)
                    if packet['context_digest']!=sha or packet['source_fingerprint']!=record['source_fingerprint']:
                        raise ValueError('native context changed')
                started={};available=[a['content_digest'] for a in answers]
                for event in state['events']:
                    if event['event']=='model_started':started[event['role']]=event
                    if event['event']!='model_receipt':continue
                    if not re.fullmatch(r'receipts/[a-z0-9_-]+\.json',event['receipt'].replace('\\','/')):
                        raise ValueError('invalid native receipt path')
                    receipt=read(str(base/event['receipt']));begin=started[event['role']]
                    if (digest(receipt['content'])!=receipt['content_digest'] or
                            receipt['content_digest']!=event['content_digest'] or receipt['role']!=event['role'] or
                            receipt['prompt_digest']!=begin['prompt_digest'] or
                            receipt.get('context_digest')!=begin.get('context_digest') or
                            receipt.get('context_digest')!=event.get('context_digest') or
                            (event.get('context_digest') and event['context_digest'] not in state.get('contexts',{})) or
                            receipt['content_digest'] not in available):
                        raise ValueError('native/normalized answer binding mismatch')
                    available.remove(receipt['content_digest'])
            accepted=(row['mode_status']=='passed' and validation.get('passed') is True and
                row['source_preserved'] is True and row['implementation_stable'] is True and within and not row['error'])
            if row['accepted']!=accepted:raise ValueError('acceptance predicate mismatch')
            if accepted and (not validation['patch_bytes'] or any(t['exit_code']!=0 for t in validation['tests'])):
                raise ValueError('acceptance lacks passing replay')
            error=' '.join([row['error']]+[str(e.get('error','')) for e in row['result'].get('events',[]) if e['event']=='coordinator_failed']).lower()
            category=('integrity' if not row['source_preserved'] or not row['implementation_stable'] else
                'budget' if not within else 'transport_unverified' if not known else
                'infrastructure' if any(s in error for s in ('filenotfound','permissionerror','git command failed','provider_http','network','sandbox')) else
                'format' if ('json' in error or 'modelformaterror' in error) else
                'test' if any(t['exit_code']!=0 for t in validation.get('tests',[])) else 'pipeline')
            namespace=digest(dict(model=model['fingerprint'],executor=digest(witness),limits=limits,features=features(case),
                prompt_digest=plan.get('strategy_binding',{}).get('prompt_digest','legacy')))
            result.append(dict(task_group=group,namespace=namespace,features=features(case),mode=row['mode'],
                accepted=accepted,category='passed' if accepted else category,
                usable=known and within and row['source_preserved'] is True and row['implementation_stable'] is True
                    and category not in {'infrastructure','integrity'},
                artifact=row['artifact'],calls=ledger['calls'],tokens=ledger['charged_tokens'],seconds=ledger['elapsed_seconds'],
                limits=limits))
        binding=plan.get('strategy_binding',{})
        return dict(id=digest(report),plan_digest=plan['plan_digest'],rows=result,binding=binding,
            paired=plan['schema']==CodingComparisonService.SCHEMA,report_digest=digest(report))

    def ingest(self, folder):
        return self._record(folder,'imported')

    def _record(self, folder, kind):
        bundle=self.verify(folder);relative=str(self.path(folder).relative_to(self.root))
        bundle['kind']=kind
        with self.store.transaction() as c:
            old=c.execute('SELECT payload FROM coding_evidence WHERE id=?',(bundle['id'],)).fetchone()
            if old:
                previous=json.loads(old['payload'])
                # Importing an owned result again must neither downgrade nor
                # elevate origin. Identical content has one persistent record.
                return previous
            c.execute('INSERT INTO coding_evidence VALUES (?,?,?,?,?)',
                (bundle['id'],relative,kind,json.dumps(bundle,ensure_ascii=False),digest(bundle)))
            for row in bundle['rows']:
                if row['accepted'] or not row['usable'] or row['category'] not in {'format','test','pipeline'}:continue
                key=digest({k:row[k] for k in ('task_group','namespace','mode','category')})
                card_id='coding-'+key
                if self.store.get_reflection_card(card_id):continue
                self.store.create_reflection_card(dict(id=card_id,task='Verified coding failure',
                    trigger='coding_evidence',outcome='failure',failure_category=row['category'],
                    root_cause='Observed '+row['category']+' failure; semantic cause requires review.',
                    patterns=['coding:'+row['category']],
                    outcome_detail=dict(report_id=bundle['id'],artifact=row['artifact'],source_kind=kind),
                    evidence=[dict(report_id=bundle['id'],task_group=row['task_group'],namespace=row['namespace'])]))
        return bundle

    def bundles(self):
        with self.store._conn() as c:records=c.execute('SELECT * FROM coding_evidence ORDER BY id').fetchall()
        values=[]
        for record in records:
            payload=json.loads(record['payload'])
            if digest(payload)!=record['payload_digest']:raise ValueError('stored coding evidence changed')
            current=self.verify(record['folder']);current['kind']=record['kind']
            if current!=payload:raise ValueError('coding evidence artifact changed after ingestion')
            values.append(payload)
        return values

    def failures(self):
        rows=[r|dict(report_id=b['id'],source_kind=b['kind']) for b in self.bundles() for r in b['rows'] if not r['accepted']]
        return dict(observations=rows,eligible=sum(r['usable'] and r['category'] in {'format','test','pipeline'} for r in rows),
            independent_groups=len({r['task_group'] for r in rows}),runtime_promotion_evidence=False)

    def nominate_failures(self, category='format'):
        if category not in {'format','test','pipeline'}:raise ValueError('failure category cannot nominate a policy')
        rows=[r for r in self.failures()['observations'] if r['usable'] and r['category']==category]
        if not rows:raise ValueError('no verified coding failure for this category')
        from reflection.self_evolution import SelfEvolutionManager
        rules=dict(format='Return one complete JSON object matching the requested schema. Escape code strings and close all arrays/objects. Preserve exact source anchors and every caller requirement. Never claim tests ran.',
            test='Preserve every caller requirement, including exceptional cases. Diagnose actual failed assertions before editing. Keep changes inside the frozen authorized scope.',
            pipeline='Check exact source anchors and authorized scope before proposing a patch. Preserve the complete original objective and caller-frozen commands.')
        with self.store.transaction() as c:
            current=self.store.get_runtime_policy('prompt_policy','coding.proposal') or {}
            base=current.get('payload',{}) if current.get('active') else {}
            keys=sorted({digest({k:r[k] for k in ('task_group','namespace','category')}) for r in rows})
            key=digest(dict(category=category,groups=keys,version=current.get('version',0),base=base))
            old=c.execute('SELECT run_id FROM coding_nominations WHERE id=?',(key,)).fetchone()
            if old:return self.store.get_self_evolution_run(old['run_id'])
            candidate={**base,'system':str(base.get('system',''))+'\n'+rules[category],
                'coding_failure_evidence':dict(digest=key,independent_groups=len({r['task_group'] for r in rows}),category=category,
                    runtime_promotion_evidence=False)}
            run=SelfEvolutionManager(self.store).create_run('prompt_policy','coding.proposal',base,candidate,
                title='Coding failure candidate: '+category,created_by='coding_evidence',
                conclusion='Diagnostic nomination only; executed regression, fresh shadow/canary and review are still required.')
            c.execute('INSERT INTO coding_nominations VALUES (?,?)',(key,run['id']))
            return run
