"""Frozen, paired coding-pipeline comparisons; all failures remain in reports.

Caller-selected tests run on owned workspaces. This is not OS isolation, a
public benchmark, or a pure model comparison when execution modes differ.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from .autonomous_coding_service import AutonomousCodingService
from .coding_contracts import CodingContracts
from .coding_execution_context import CodingExecutionContext
from .coding_workflow_service import CodingWorkflowService
from .execution_governance import ExecutionBudget
from .file_transactions import write_text
from .reliable_collaboration import ReliableCollaborationService

CORE_FILES = ['autonomous_coding_service.py','coding_execution_context.py','coding_context_service.py',
    'coding_contracts.py','coding_workflow_service.py','coding_workspace_service.py',
    'reliable_collaboration.py','collaboration_delivery.py','os_sandbox.py','file_transactions.py','coding_comparison_service.py',
    'coding_structured_output.py', 'windows_appcontainer_boundary.py', 'appcontainer_process.py',
    'strict_sandbox_acceptance.py']
LOADED_WITNESS = {str(Path(__file__).with_name(p)):hashlib.sha256(Path(__file__).with_name(p).read_bytes()).hexdigest()
    for p in CORE_FILES}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode('utf-8')).hexdigest()


def save(path, value, *, immutable=False):
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2), create_only=immutable)


async def operation(fn, *args, **kwargs):
    task = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # The native operation owns its timeout; do not abandon a running write.
        await task
        raise


class ComparisonCapture:
    """Same admission/output/call accounting around both production pipelines."""
    def __init__(self, root, limits, witness, *, clock=time.monotonic):
        self.root, self.limits, self.witness, self.clock = Path(root), limits, witness, clock
        self.started = clock()
        self.ledger = dict(calls=0, charged_tokens=0, provider_tokens=0, reserved_tokens=0,
            reservations=[], receipts=[], accounting_policy='UTF8_bytes_of_all_messages_plus_output_cap; usage_when_valid_else_reservation')

    def stable(self):
        try:
            return all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == sha for p, sha in self.witness.items())
        except OSError:
            return False

    def snapshot(self):
        return copy.deepcopy(self.ledger) | dict(elapsed_seconds=round(self.clock()-self.started, 3))

    def wrap(self, provider):
        capture = self
        class CapturedProvider:
            name = getattr(provider, 'name', '')
            model = getattr(provider, 'model', '')
            base_url = getattr(provider, 'base_url', '')
            chat_template_kwargs = getattr(provider, 'chat_template_kwargs', None)

            async def complete(self, messages, options):
                if not capture.stable():
                    raise RuntimeError('comparison implementation source changed')
                messages = copy.deepcopy(messages)
                prepare = getattr(provider, 'prepare_messages', None)
                if prepare is not None:
                    messages = prepare(messages)
                left = capture.limits['max_wall_seconds'] - (capture.clock()-capture.started)
                options = dict(options, max_tokens=capture.limits['max_output_tokens'], temperature=0,
                    response_format=options.get('response_format') or {'type':'json_object'})
                reservation = len(json.dumps(messages, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) + options['max_tokens']
                ledger = capture.ledger
                if (left <= 0 or ledger['calls'] >= capture.limits['max_model_calls'] or
                        ledger['charged_tokens'] + ledger['reserved_tokens'] + reservation > capture.limits['max_tokens']):
                    raise RuntimeError('comparison admission budget exhausted')
                ledger['calls'] += 1
                number = ledger['calls']
                ledger['reserved_tokens'] += reservation
                ledger['reservations'].append(dict(call=number, reserved_tokens=reservation,
                    input_digest=digest(messages), options=options, status='started'))
                save(capture.root/'capture.json', capture.snapshot())
                started = capture.clock(); response = None; settled = False
                try:
                    response = await asyncio.wait_for(provider.complete(messages, options),
                        timeout=min(left, capture.limits['timeout_seconds']))
                    usage = (response.get('usage') or {}).get('total_tokens')
                    known = type(usage) is int and usage > 0
                    charged = usage if known else reservation
                    ledger['charged_tokens'] += charged
                    settled = True
                    if known:ledger['provider_tokens'] += usage
                    ledger['reservations'][number-1]['status'] = 'answered'
                    content = str(response.get('content') or '')
                    finish = ((response.get('raw') or {}).get('choices') or [{}])[0].get('finish_reason')
                    receipt = dict(call=number, input_digest=digest(messages), content=content,
                        content_digest=digest(content), options=options, charged_tokens=charged,
                        accounting_source='provider_usage' if known else 'conservative_reservation',
                        provider=response.get('provider'), model=response.get('model'), ok=response.get('ok'),
                        finish_reason=finish, duration_seconds=round(capture.clock()-started,3))
                    save(capture.root/f'answer-{number}.json', receipt, immutable=True)
                    ledger['receipts'].append(dict(call=number, artifact=f'answer-{number}.json', digest=digest(receipt)))
                    if ledger['charged_tokens'] + ledger['reserved_tokens'] - reservation > capture.limits['max_tokens']:
                        raise RuntimeError('provider reported usage exceeding frozen budget')
                    if response.get('provider') != self.name or response.get('model') != self.model:
                        raise RuntimeError('provider identity differs from frozen arm')
                    if finish in {'length','content_filter'}:
                        raise RuntimeError('comparison answer incomplete')
                    return response
                finally:
                    if not settled:
                        ledger['charged_tokens'] += reservation
                        ledger['reservations'][number-1]['status'] = 'no_complete_response'
                    ledger['reserved_tokens'] -= reservation
                    save(capture.root/'capture.json', capture.snapshot())
        return CapturedProvider()

    def verify(self):
        for reference in self.ledger['receipts']:
            value = json.loads((self.root/reference['artifact']).read_text(encoding='utf-8'))
            if digest(value) != reference['digest'] or digest(value['content']) != value['content_digest']:
                raise ValueError('comparison answer receipt changed')
        return self.stable()


class CodingComparisonService:
    SCHEMA = 'clawos.coding-comparison.v1'
    MODES = ('single', 'multi')
    DEFAULT_LIMITS = dict(max_model_calls=24, max_tokens=50000, max_wall_seconds=1800,
        timeout_seconds=300, max_output_tokens=1800, max_attempts=3)

    def __init__(self, root, *, witness=None):
        self.root = Path(root).resolve()
        if self.root.exists():raise ValueError('fresh comparison evidence directory required')
        self.root.mkdir(parents=True)
        if any(p in LOADED_WITNESS and sha!=LOADED_WITNESS[p] for p,sha in (witness or {}).items()):
            raise ValueError('caller witness conflicts with loaded implementation')
        self.witness = dict(LOADED_WITNESS) | (witness or {})
        self.svc = ReliableCollaborationService(lambda spec:None, root=self.root/'coordinator')

    @classmethod
    def limits(cls, value):
        limits = cls.DEFAULT_LIMITS | (value or {})
        bounds = dict(max_model_calls=(1,48), max_tokens=(500,100000), max_wall_seconds=(1,3600),
            timeout_seconds=(1,600), max_output_tokens=(100,1800), max_attempts=(1,3))
        if set(limits) != set(bounds) or any(type(limits[k]) is not int or not a<=limits[k]<=b for k,(a,b) in bounds.items()):
            raise ValueError('invalid comparison limits')
        return limits

    def case(self, value):
        case = copy.deepcopy(value)
        if (set(case) != {'id','repo','objective','paths','test_commands','post_commands','requirements'} or
                not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', str(case['id'])) or
                not isinstance(case['objective'], str) or not 1<=len(case['objective'])<=8000):
            raise ValueError('invalid frozen comparison case')
        repo = self.svc.workspaces._repo(case['repo']);case['repo'] = str(repo)
        if self.svc.git(repo,'status','--porcelain').stdout.strip():
            raise ValueError('comparison requires a clean explicit snapshot')
        paths = case['paths']
        if (not isinstance(paths,list) or not 1<=len(paths)<=24 or not all(isinstance(p,str) for p in paths)
                or len(set(p.casefold() for p in paths))!=len(paths)):
            raise ValueError('invalid comparison write scope')
        for path in paths:CodingExecutionContext.safe_path(path)
        for field in ('test_commands','post_commands'):
            commands = case[field]
            if not isinstance(commands,list) or not 1<=len(commands)<=5:
                raise ValueError('comparison needs frozen primary and post commands')
            case[field] = [CodingWorkflowService._validate_command(c) for c in commands]
        case['requirements'] = CodingContracts.validate(case['requirements'],paths,case['test_commands'])
        if any(r.get('rule') for r in case['requirements']):
            raise ValueError('comparison excludes asymmetric caller mechanical repair rules')
        case['source_stamp'] = self.svc.source_stamp(repo,paths)
        case['source_head'] = self.svc.git(repo,'rev-parse','HEAD').stdout.strip()
        case['tracked_tree'] = self.svc.git(repo,'rev-parse','HEAD^{tree}').stdout.strip()
        case['task_group_digest'] = digest({k:v for k,v in case.items() if k not in {'repo','id','source_stamp','source_head'}})
        case['case_digest'] = digest({k:v for k,v in case.items() if k != 'repo'})
        return case

    def check_case(self, case):
        if self.svc.source_stamp(case['repo'],case['paths']) != case['source_stamp']:
            raise ValueError('frozen comparison source drift')

    async def single(self, workspace, case, provider, capture, limits, folder):
        workflow = CodingWorkflowService(artifact_root=folder/'workflow')
        service = AutonomousCodingService(provider, workflow=workflow)
        budget = ExecutionBudget(max_model_calls=limits['max_model_calls'], max_tokens=limits['max_tokens'],
            max_tool_calls=100, max_wall_seconds=limits['max_wall_seconds'])
        previous = None; attempts = []; status='failed'
        for attempt in range(limits['max_attempts']):
            proposal = await service.propose(workspace,case['objective'],focus_paths=case['paths'],
                previous_failure=previous, budget=budget,test_commands=case['test_commands'],requirements=case['requirements'])
            save(folder/f'proposal-{attempt+1}.json', proposal, immutable=True)
            CodingExecutionContext.verify(workspace,proposal['execution_context'])
            result = await operation(workflow.execute,workspace,case['objective'],proposal['proposal']['changes'],
                case['test_commands'],confirmed=True,max_rounds=1,timeout_seconds=limits['timeout_seconds'],actor='paired-comparison')
            attempts.append(dict(attempt=attempt+1,status=result['status'],workflow=result,
                proposal_digest=proposal['proposal_digest'],context_digest=proposal['context_digest']))
            save(folder/'single-progress.json',dict(attempts=attempts))
            if result['status']=='passed':status='passed';break
            previous = dict(error='caller frozen tests failed and changes were restored',rounds=result.get('rounds',[]))
        return dict(status=status,attempts=attempts), workspace

    async def evaluate(self, case, final_repo, folder, capture):
        """Identical external replay/tests for both modes; no feedback to model."""
        changed = self.svc.git(final_repo,'diff','--name-only',case['source_head']).stdout.splitlines()
        if not set(changed)<=set(case['paths']):raise ValueError('comparison diff exceeds frozen scope')
        untracked = self.svc.git(final_repo,'ls-files','--others','--exclude-standard').stdout.splitlines()
        if untracked:raise ValueError('untracked output is outside comparison patch protocol')
        patch = subprocess.run(['git','diff','--binary',case['source_head']],cwd=final_repo,
            capture_output=True,check=True,timeout=30).stdout
        (folder/'changes.patch').write_bytes(patch)
        meta = await operation(self.svc.workspaces.create_task,case['repo'],folder/'replay','common-validation',confirmed=True)
        replay = Path(meta['workspace'])
        if patch:
            for check in (True,False):
                argv = ['git','apply','--binary','--whitespace=nowarn'] + (['--check'] if check else []) + ['-']
                proc = subprocess.run(argv,cwd=replay,input=patch,capture_output=True,timeout=30)
                if proc.returncode:raise ValueError('comparison patch replay failed')
        rows = []
        for phase in ('test_commands','post_commands'):
            for index,command in enumerate(case[phase]):
                remaining = int(capture.limits['max_wall_seconds']-(capture.clock()-capture.started))
                if remaining<=0:
                    row=dict(exit_code=124,timed_out=True,stdout='',stderr='comparison wall budget exhausted; command not started',
                        sandbox={'backend':'not-executed','production_sandbox_ready':False})
                else:
                    row = await operation(CodingWorkflowService._run_command,replay,command,
                        min(remaining,capture.limits['timeout_seconds']))
                rows.append(dict(row,phase=phase,index=index,command=command))
        requirement_results = CodingContracts.results(case['requirements'],
            [t for t in rows if t['phase']=='test_commands'],digest,repo=replay)
        return dict(passed=bool(patch) and all(t['exit_code']==0 for t in rows) and all(r['passed'] for r in requirement_results),tests=rows,
            patch_sha256=hashlib.sha256(patch).hexdigest(),patch_bytes=len(patch),workspace=meta,
            post_feedback_to_model=False, requirements=requirement_results)

    async def arm(self, case, model, mode, limits, number, repetition):
        folder=self.root/f'arm-{number:02d}';folder.mkdir()
        capture=ComparisonCapture(folder,limits,self.witness)
        result={};validation={};error='';final_repo=None;status='failed'
        async def pipeline():
            nonlocal result,final_repo,status
            self.check_case(case)
            prototype=model['factory']('comparison_identity')
            if self.svc.provider_signature(prototype)!=model['fingerprint']:
                raise ValueError('model configuration changed before comparison arm')
            meta=await operation(self.svc.workspaces.create_task,case['repo'],folder/'workspaces',mode,confirmed=True)
            workspace=Path(meta['workspace']);final_repo=workspace
            if mode=='single':
                result,final_repo=await self.single(workspace,case,capture.wrap(prototype),capture,limits,folder)
            else:
                def factory(spec):
                    provider=model['factory'](spec.role_id)
                    if self.svc.provider_signature(provider)!=model['fingerprint']:
                        raise ValueError('model configuration changed during arm')
                    return capture.wrap(provider)
                service=ReliableCollaborationService(factory,root=folder/'c',max_concurrency=2)
                result=await service.run(workspace,case['objective'],allowed_paths=case['paths'],
                    test_commands=case['test_commands'],requirements=case['requirements'],confirmed=True,
                    actor='paired-comparison',limits={k:v for k,v in limits.items() if k!='max_output_tokens'})
                record=result.get('integration',{}).get('workspace')
                if record:final_repo=Path(record['workspace'])
            status=result.get('status','failed')
        try:
            await asyncio.wait_for(pipeline(),timeout=limits['max_wall_seconds'])
        except Exception as exc:
            error=f'{type(exc).__name__}: {str(exc)[:500]}'
        pipeline_seconds=capture.clock()-capture.started
        try:
            self.check_case(case)
            if final_repo is not None and pipeline_seconds<limits['max_wall_seconds']:
                validation=await self.evaluate(case,final_repo,folder,capture)
            stable=capture.verify()
        except Exception as exc:
            error=error or f'{type(exc).__name__}: {str(exc)[:500]}';stable=False
        elapsed=capture.clock()-capture.started
        within=(elapsed<=limits['max_wall_seconds'] and capture.ledger['charged_tokens']<=limits['max_tokens']
            and capture.ledger['calls']<=limits['max_model_calls'] and capture.ledger['reserved_tokens']==0)
        row=dict(case_id=case['id'],case_digest=case['case_digest'],task_group_digest=case['task_group_digest'],
            repetition=repetition,model_id=model['id'],mode=mode,
            provider_fingerprint=model['fingerprint'],limits=limits,mode_status=status,error=error,
            pipeline_accepted=status=='passed',task_tests_passed=validation.get('passed') is True,
            accepted=status=='passed' and validation.get('passed') is True and stable and within and not error,
            source_preserved=self.svc.source_stamp(case['repo'],case['paths'])==case['source_stamp'],
            implementation_stable=stable,within_budget=within,ledger=capture.snapshot(),result=result,validation=validation,
            pipeline_seconds=round(pipeline_seconds,3),evaluation_seconds=round(elapsed-pipeline_seconds,3),
            model_execution_observed=capture.ledger['calls']>0,
            mechanical_events=[e for e in result.get('events',[]) if e.get('model_generated') is False])
        save(folder/'report.json',row,immutable=True)
        return row | dict(artifact=folder.name+'/report.json',report_digest=digest(row))

    def verify_arm(self, row):
        path=self.root/row['artifact']
        disk=json.loads(path.read_text(encoding='utf-8'))
        if digest(disk)!=row['report_digest']:raise ValueError('completed comparison arm report changed')
        for reference in row['ledger']['receipts']:
            value=json.loads((path.parent/reference['artifact']).read_text(encoding='utf-8'))
            if digest(value)!=reference['digest'] or digest(value['content'])!=value['content_digest']:
                raise ValueError('completed comparison receipt changed')

    async def run(self, cases, models, *, limits=None, confirmed=False, repetitions=1, binding=None):
        if confirmed is not True:raise PermissionError('explicit owned-workspace execution authorization required')
        if not isinstance(cases,list) or not 1<=len(cases)<=8:raise ValueError('1..8 explicit cases required')
        if not isinstance(models,list) or not 1<=len(models)<=4:raise ValueError('1..4 explicit model factories required')
        if type(repetitions) is not int or not 1<=repetitions<=3:raise ValueError('1..3 predeclared repetitions required')
        limits=self.limits(limits);cases=[self.case(c) for c in cases];models=[dict(m) for m in models]
        for model in models:
            if (set(model)!= {'id','factory','fingerprint'} or not isinstance(model['id'],str)
                    or not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}',model['id']) or not callable(model['factory'])
                    or not isinstance(model['fingerprint'],str) or not re.fullmatch(r'[a-f0-9]{64}',model['fingerprint'])):
                raise ValueError('invalid comparison model identity')
            prototype=model['factory']('comparison_identity')
            if self.svc.provider_signature(prototype)!=model['fingerprint']:
                raise ValueError('model fingerprint does not match explicit factory')
            model['actual_provider']=getattr(prototype,'name','')
            model['actual_model']=getattr(prototype,'model','')
            if not model['actual_provider'] or not model['actual_model']:
                raise ValueError('explicit provider/model identity required')
        if len({c['id'] for c in cases})!=len(cases) or len({m['id'] for m in models})!=len(models):
            raise ValueError('duplicate comparison identities')
        planned=[]
        for repetition in range(repetitions):
            for index,case in enumerate(cases):
                for model in models:
                    for mode in (self.MODES if (index+repetition)%2==0 else tuple(reversed(self.MODES))):
                        planned.append(dict(case_id=case['id'],model_id=model['id'],mode=mode,repetition=repetition+1))
        plan=dict(schema=self.SCHEMA,cases=cases,models=[{k:v for k,v in m.items() if k!='factory'} for m in models],
            limits=limits,arms=planned,implementation_witness=self.witness,
            repetitions=repetitions,order_policy='sequential; mode order alternates by case/repetition; no cold-cache control')
        if binding is not None:plan['strategy_binding']=copy.deepcopy(binding)
        plan['plan_digest']=digest(plan);save(self.root/'plan.json',plan,immutable=True)
        rows=[]
        for index,arm in enumerate(planned):
            if json.loads((self.root/'plan.json').read_text(encoding='utf-8'))!=plan:
                raise ValueError('frozen comparison plan changed')
            case=next(c for c in cases if c['id']==arm['case_id']);model=next(m for m in models if m['id']==arm['model_id'])
            rows.append(await self.arm(case,model,arm['mode'],limits,index+1,arm['repetition']))
            save(self.root/'progress.json',dict(plan_digest=plan['plan_digest'],completed=len(rows),planned=len(planned),
                results=[{k:r[k] for k in ('case_id','model_id','mode','accepted','mode_status')} for r in rows]))
        if json.loads((self.root/'plan.json').read_text(encoding='utf-8'))!=plan:
            raise ValueError('frozen comparison plan changed')
        for row in rows:self.verify_arm(row)
        for case in cases:self.check_case(case)
        if not ComparisonCapture(self.root,limits,self.witness).stable():
            raise ValueError('comparison implementation changed before final aggregation')
        groups=[]
        for model in models:
            for mode in self.MODES:
                group=[r for r in rows if r['model_id']==model['id'] and r['mode']==mode]
                groups.append(dict(model_id=model['id'],mode=mode,n=len(group),accepted=sum(r['accepted'] for r in group),
                    unique_tasks=len({r['task_group_digest'] for r in group}),
                    task_tests_passed=sum(r['task_tests_passed'] for r in group),
                    calls=sum(r['ledger']['calls'] for r in group),charged_tokens=sum(r['ledger']['charged_tokens'] for r in group),
                    elapsed_seconds=round(sum(r['ledger']['elapsed_seconds'] for r in group),3)))
        report=dict(schema=self.SCHEMA,plan_digest=plan['plan_digest'],complete=len(rows)==len(planned),
            protocol_valid=all(r['source_preserved'] and r['implementation_stable'] for r in rows),
            budget_conformant=all(r['within_budget'] for r in rows),
            execution_comparable=all(r['model_execution_observed'] and r['within_budget'] for r in rows),
            unique_task_groups=len({c['task_group_digest'] for c in cases}),repetitions=repetitions,
            all_tasks_resolved=all(r['accepted'] for r in rows),groups=groups,arms=rows,
            model_comparison_available=len({(m['actual_provider'],m['actual_model']) for m in models})>1,
            independent_public_benchmark=False,post_feedback_to_model=False,
            interpretation='Compare complete pipelines on these frozen cases only; different role prompts/review and mechanical repairs are mode effects. Small reused samples, server caches and order do not establish general superiority.')
        save(self.root/'report.json',report,immutable=True)
        return report
