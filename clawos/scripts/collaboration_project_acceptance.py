"""Real-provider collaboration on an unchanged committed ClawOS Python snapshot.

Two real feature requests, public regressions and a sealed post-delivery holdout.
Only owned children may be deliberately killed; no daily data/config is loaded.
This is an internal project slice, not an independent public-project benchmark.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from providers.qwen import QwenProvider
from services.reliable_collaboration import ReliableCollaborationService as Service
from services.collaboration_delivery import CollaborationDelivery

PATHS = ['clawos/services/document_merge.py', 'clawos/services/response_contract.py']
OBJECTIVE = (
    'Implement two independent feature requests in the actual existing ClawOS modules. '
    'Use independent parallel tasks for these unrelated modules. '
    'In document_merge.merge_document(base, local, remote), before constructing ID maps, '
    'reject duplicate block IDs within ANY individual input document by raising the existing '
    'MergeConflict; never silently collapse duplicate IDs. Identical IDs across different '
    'documents are normal. Preserve all valid merge behavior, Unicode and input immutability. '
    'In response_contract.request_history(messages), add keyword-only max_messages=None. '
    'None preserves the exact existing behavior. When supplied use exact built-in type validation '
    '(type(max_messages) is int): reject bool AND all int subclasses. It must be '
    'strictly positive, otherwise raise ValueError even if messages is empty. '
    'After the existing filtering and exclusion of the final user message and later answers, '
    'return only the last max_messages eligible history rows, with copied dictionaries as '
    'before. Preserve None fallback when the existing function has no earlier history. '
    'Keep RESPONSE_STYLE and SYSTEM_PROMPT unchanged. No other files may be changed.'
)
REQUIREMENTS = [
    dict(id='merge_unique_ids', paths=[PATHS[0]], test_indexes=[0],
         statement='Reject duplicate block IDs within each base/local/remote input with MergeConflict. Cross-branch IDs are normal; do not mutate inputs.'),
    dict(id='merge_compatibility', paths=[PATHS[0]], test_indexes=[1],
         statement='Preserve valid rich text, table, Unicode, nonoverlapping edits, ACL and conflict behavior covered by existing document tests.'),
    dict(id='history_exact_bound', paths=[PATHS[1]], test_indexes=[0],
         statement='max_messages=None is unlimited. Otherwise require type(max_messages) is int and max_messages>0, rejecting bool AND int subclasses even on empty input.',
         rule=dict(kind='python_exact_type', function='request_history', parameter='max_messages', builtin_type='int')),
    dict(id='history_compatibility', paths=[PATHS[1]], test_indexes=[0],
         statement='Keep keyword-only max_messages; preserve filtering, copied rows and None fallback. Exclude final user and later answers, then return the last N eligible rows. Preserve system/style constants.')
]
SOURCE_FILES = [ROOT / p for p in (
    'services/reliable_collaboration.py', 'services/collaboration_delivery.py',
    'services/coding_contracts.py', 'services/coding_workflow_service.py', 'services/os_sandbox.py',
    'services/coding_execution_context.py', 'services/coding_context_service.py',
    'services/autonomous_coding_service.py', 'services/agentic_coding_loop_service.py')]+[Path(__file__)]
LOADED = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE_FILES}

PUBLIC = '''import copy,sys,unittest
sys.path.insert(0,'clawos')
from services.document_merge import merge_document,MergeConflict
from services.response_contract import request_history
class PublicContracts(unittest.TestCase):
    def test_duplicate_each_input(self):
        base=dict(title='文档',context='',blocks=[dict(id='p',type='paragraph',text='hello')])
        for i in range(3):
            docs=[copy.deepcopy(base) for _ in range(3)]
            docs[i]['blocks'].append(copy.deepcopy(docs[i]['blocks'][0]))
            with self.assertRaises(MergeConflict):merge_document(*docs)
    def test_valid_merge(self):
        base=dict(title='文档',context='',blocks=[dict(id='p',type='paragraph',text='hello')])
        snapshot=copy.deepcopy(base)
        self.assertEqual(merge_document(base,base,base),base)
        self.assertEqual(base,snapshot)
    def test_history_bound(self):
        rows=[dict(role='user',content='old'),dict(role='assistant',content='reply'),dict(role='user',content='now')]
        self.assertEqual(request_history(rows),rows[:2])
        self.assertEqual(request_history(rows,max_messages=1),rows[1:2])
        self.assertIsNone(request_history([],max_messages=1))
    def test_invalid_bound(self):
        class IntSubclass(int):pass
        for value in (0,-1,True,False,'2',1.5,IntSubclass(2)):
            with self.assertRaises(ValueError):request_history([],max_messages=value)
unittest.main()
'''

# Holdout source is never placed in authorized model context or caller test commands.
# Tests are disclosed only in this maintainers' harness; this is not external blinding.
HOLDOUT = '''import copy,random,sys,unittest
sys.path.insert(0,'clawos')
from services.document_merge import merge_document,merge_text,MergeConflict
from services.response_contract import request_history
class SealedHoldout(unittest.TestCase):
    def test_duplicate_locations(self):
        for n in (2,3,7,31):
            base=dict(title='研究😀',context='context',blocks=[dict(id='块'+str(i),type='paragraph',text=str(i)) for i in range(n)])
            for branch in range(3):
                for index in (0,n//2,n-1):
                    docs=[copy.deepcopy(base) for _ in range(3)]
                    # Distinct payloads prove no dictionary collapse is acceptable.
                    duplicate=copy.deepcopy(docs[branch]['blocks'][index]);duplicate['text']='different'
                    docs[branch]['blocks'].insert(index,duplicate)
                    before=copy.deepcopy(docs)
                    with self.assertRaises(MergeConflict):merge_document(*docs)
                    self.assertEqual(docs,before)
    def test_valid_disjoint_rich_table_and_additions(self):
        base=dict(title='研究😀',context='context',blocks=[dict(id='a',type='paragraph',text='abcd'),dict(id='t',type='table',text='',cells=[['1','2'],['3','4']])])
        local=copy.deepcopy(base);remote=copy.deepcopy(base)
        local['blocks'][0]['text']='Abcd';remote['blocks'][0]['text']='abcD'
        local['blocks'][1]['cells'][0][0]='10';remote['blocks'][1]['cells'][1][1]='40'
        local['blocks'].append(dict(id='x',type='paragraph',text='新增😀'))
        before=copy.deepcopy([base,local,remote]);value=merge_document(base,local,remote)
        self.assertEqual(value['blocks'][0]['text'],'AbcD')
        self.assertEqual(value['blocks'][1]['cells'],[['10','2'],['3','40']])
        self.assertEqual(value['blocks'][-1]['id'],'x')
        self.assertEqual([base,local,remote],before)
        with self.assertRaises(MergeConflict):merge_text('abc','axc','ayc')
    def test_random_history_against_frozen_reference(self):
        rng=random.Random(20261006)
        def reference(messages):
            rows=[dict(role=m.get('role'),content=m['content']) for m in messages or [] if isinstance(m,dict) and m.get('role') in {'user','assistant'} and isinstance(m.get('content'),str)]
            last=next((i for i in range(len(rows)-1,-1,-1) if rows[i]['role']=='user'),-1)
            return rows[:last] if last>0 else None
        for size in range(40):
            rows=[rng.choice([None,7,{},dict(role='system',content='ignore'),dict(role='user',content='用户😀'),dict(role='assistant',content='回答'),dict(role='user',content=5)]) for _ in range(size)]
            before=copy.deepcopy(rows);expected=reference(rows)
            self.assertEqual(request_history(rows),expected)
            for cap in (1,2,7,100):
                actual=request_history(rows,max_messages=cap)
                self.assertEqual(actual,expected[-cap:] if expected is not None else None)
                if actual:
                    actual[0]['content']='mutated output'
                    self.assertEqual(rows,before)
            self.assertEqual(rows,before)
    def test_bounds_keyword_and_subclass(self):
        class IntSubclass(int):pass
        for value in (0,-99,False,True,'1',[],{},0.5,IntSubclass(2)):
            with self.assertRaises(ValueError):request_history(None,max_messages=value)
        with self.assertRaises(TypeError):request_history([],2)
        rows=[dict(role='assistant',content='first'),dict(role='user',content='last'),dict(role='assistant',content='later')]
        self.assertEqual(request_history(rows,max_messages=5),rows[:1])
unittest.main()
'''


# The first six cases have now been exercised. They are diagnostic regressions,
# not a fresh holdout; the last two cases are frozen before the next live run.
HOLDOUT = HOLDOUT.replace('unittest.main()', '''
    def test_fresh_history_matrix(self):
        for prefix in ([],[dict(role='assistant',content='first')]):
            for n in range(1,15):
                earlier=prefix+[dict(role='user' if i%2 else 'assistant',content='内容😀'+str(i),ignored='extra') for i in range(n)]
                for suffix in ([],[dict(role='assistant',content='later')],[dict(role='system',content='discard'),dict(role='assistant',content='tail')]):
                    rows=earlier+[dict(role='user',content='current')]+suffix
                    expected=[dict(role=r['role'],content=r['content']) for r in earlier]
                    for cap in (1,3,n,99):
                        self.assertEqual(request_history(rows,max_messages=cap),expected[-cap:])
    def test_fresh_cross_branch_ids(self):
        base=dict(title='空😀',context='',blocks=[])
        local=copy.deepcopy(base);remote=copy.deepcopy(base)
        block=dict(id='共同',type='paragraph',text='same')
        local['blocks']=[copy.deepcopy(block)];remote['blocks']=[copy.deepcopy(block)]
        self.assertEqual(merge_document(base,local,remote)['blocks'],[block])
        remote['blocks'][0]['text']='different'
        with self.assertRaises(MergeConflict):merge_document(base,local,remote)
        before=copy.deepcopy([base,local,remote])
        self.assertEqual(merge_document(base,base,base),base)
        self.assertEqual([base,local,remote],before)
    def test_new_generators_tuples_and_large_caps(self):
        rows=[dict(role='user' if i%2 else 'assistant',content='消息😀'+str(i)) for i in range(103)]
        rows.append(dict(role='user',content='current'))
        expected=[dict(role=r['role'],content=r['content']) for r in rows[:-1]]
        for cap in (1,17,103,10**50):
            self.assertEqual(request_history(tuple(rows),max_messages=cap),expected[-cap:])
            self.assertEqual(request_history((r for r in rows),max_messages=cap),expected[-cap:])
    def test_new_disjoint_document_metadata(self):
        base=dict(title='研究😀',context='原文',blocks=[])
        local=copy.deepcopy(base);remote=copy.deepcopy(base)
        local['title']='标题🌍';remote['context']='新版资料'
        before=copy.deepcopy([base,local,remote])
        self.assertEqual(merge_document(base,local,remote),dict(title='标题🌍',context='新版资料',blocks=[]))
        self.assertEqual([base,local,remote],before)
unittest.main()
''')


def fingerprints(paths):
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def seed(out, project=ROOT.parent):
    """Extract only tracked Python regular files from committed HEAD, no runtime data."""
    repo = out / 'source'
    if repo.exists():
        return repo
    revision = Service.git(project, 'rev-parse', 'HEAD').stdout.strip()
    archive = subprocess.run(['git','archive','--format=tar',revision,'clawos'],
        cwd=project,capture_output=True,check=True,timeout=60).stdout
    repo.mkdir(parents=True)
    entries = []
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith('.py'):
                continue
            rel = Service.safe_path(member.name)
            blob = tar.extractfile(member).read()
            target = repo / rel
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(blob)
            entries.append(dict(path=rel,bytes=len(blob),sha256=hashlib.sha256(blob).hexdigest()))
    for rel in PATHS:
        if not (repo / rel).is_file():
            raise ValueError('required actual project module missing')
    (repo / '.gitignore').write_text('__pycache__/\n.clawos-sandbox/\n',encoding='utf-8')
    (repo / 'acceptance_public.py').write_text(PUBLIC,encoding='utf-8')
    (repo / 'acceptance_holdout.py').write_text(HOLDOUT,encoding='utf-8')
    (out / 'provenance.json').write_text(json.dumps(dict(source_head=revision,files=entries,
        file_count=len(entries),bytes=sum(e['bytes'] for e in entries),
        holdout_sha256=hashlib.sha256(HOLDOUT.encode()).hexdigest(),
        public_sha256=hashlib.sha256(PUBLIC.encode()).hexdigest()),indent=2),encoding='utf-8')
    for command in [('init',),('add','.'),('-c','user.name=Acceptance','-c',
            'user.email=acceptance@local','commit','-m','Unchanged committed ClawOS Python snapshot and sealed tests')]:
        Service.git(repo,*command)
    return repo


def service(args):
    class FaultService(Service):
        def event(self,state,kind,**fields):
            super().event(state,kind,**fields)
            if args.crash_after and kind=='worker_completed' and sum(
                    e['event']=='worker_completed' for e in state['events'])==args.crash_after:
                os._exit(17)
    return FaultService(lambda spec:QwenProvider(dict(base_url=args.url,model=args.model,
        timeout_s=300,api_key='',requires_api_key=False)),root=args.out/'runs',max_concurrency=2)


async def execute(args,resume=''):
    return await service(args).run(seed(args.out),OBJECTIVE,allowed_paths=PATHS,
        test_commands=[[sys.executable,'-B','acceptance_public.py'],
            [sys.executable,'-B','-m','unittest','discover','-s','clawos/tests','-p','test_document_realtime.py']],
        actor='project-snapshot-acceptance',confirmed=True,resume_run=resume,
        requirements=REQUIREMENTS,
        limits=dict(timeout_seconds=300,max_wall_seconds=1800,max_tokens=50000))


def peak_workers(result):
    roles={n['id'] for n in result.get('nodes',[])}
    roles|={r+'_format' for r in roles}
    active=set();peak=0
    for e in result.get('events',[]):
        role=e.get('role',e.get('node'))
        if e['event']=='model_started' and role in roles:
            active.add(role);peak=max(peak,len(active))
        if e['event']=='coordinator_recovered':active.clear()
        elif e['event'] in {'model_receipt','model_completed','worker_failed'}:
            active.discard(role)
            if e['event']=='worker_failed':active.discard(str(role)+'_format')
    return peak


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--live',action='store_true',required=True)
    p.add_argument('--url',required=True)
    p.add_argument('--model',default='Qwen3.5-9B-Q4_K_M')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--repeated-crashes',type=int,choices=[0,2],default=0)
    p.add_argument('--resume',default='',help=argparse.SUPPRESS)
    p.add_argument('--crash-after',type=int,default=0,help=argparse.SUPPRESS)
    args=p.parse_args()
    url=urlparse(args.url)
    if url.scheme!='http' or url.hostname not in {'localhost','127.0.0.1','::1'}:
        p.error('explicit loopback HTTP provider required')
    args.out=args.out.resolve();args.out.relative_to(ROOT/'output')
    if args.out.exists() and not (args.resume or args.crash_after):
        p.error('fresh output directory required; previous evidence must be preserved')
    args.out.mkdir(parents=True,exist_ok=True)
    if args.crash_after:
        result=asyncio.run(execute(args,args.resume))
        print(json.dumps(dict(status=result['status'],fault_not_reached=True)))
        return 2
    start=time.monotonic();repo=seed(args.out);svc=service(args)
    before=svc.source_stamp(repo,PATHS)
    result={};delivery={};hidden={};crashes=[];error='';resume=''
    try:
        for index in range(1,args.repeated_crashes+1):
            command=[sys.executable,__file__,'--live','--url',args.url,'--model',args.model,
                '--out',str(args.out),'--crash-after',str(index)]
            if resume:command+=['--resume',resume]
            with (args.out/f'crash-{index}.log').open('w',encoding='utf-8') as log:
                child=subprocess.run(command,stdout=log,stderr=log,timeout=1850)
            checkpoints=list((args.out/'runs').glob('*/checkpoint.json'))
            if len(checkpoints)!=1:raise RuntimeError('one owned checkpoint required')
            state=json.loads(checkpoints[0].read_text(encoding='utf-8'))['state']
            resume=state['run_id']
            completed={k:v['commit'] for k,v in state['results'].items() if v['status']=='passed'}
            crashes.append(dict(exit_code=child.returncode,completed=completed,
                attempts={k:[a['status'] for a in values] for k,values in state['attempts'].items()}))
            if child.returncode!=17:raise RuntimeError('real accepted worker crash point was not reached')
        result=asyncio.run(execute(args,resume))
        if result['status']=='passed':
            handoff=CollaborationDelivery(svc)
            packet=asyncio.run(handoff.prepare(result['run_id'],confirmed=True))
            delivery=handoff.inspect(result['run_id'])
            # A fresh replay, no model access/repair from holdout results.
            replay=packet['manifest']['replay']['workspace']['workspace']
            hidden=svc.workflow._run_command(Path(replay),[sys.executable,'-B','acceptance_holdout.py'],120)
            hidden['feedback_to_model']=False
            delivery=handoff.inspect(result['run_id'])
            # A quality check is not a synthetic owner's release approval.
            delivery['actual_human_approval']=False
            result=svc.public(svc.load(result['run_id']))
    except Exception as exc:
        error=f'{type(exc).__name__}: {exc}'
        checkpoints=list((args.out/'runs').glob('*/checkpoint.json'))
        if len(checkpoints)==1:
            result=svc.public(json.loads(checkpoints[0].read_text(encoding='utf-8'))['state'])
    after=svc.source_stamp(repo,PATHS)
    preserved=before==after
    reused=all(result.get('results',{}).get(k,{}).get('commit')==commit
        for crash in crashes for k,commit in crash['completed'].items())
    checks=dict(real_model=bool([e for e in result.get('events',[]) if e['event']=='model_completed'])
        and all(e.get('provider')=='qwen' for e in result.get('events',[]) if e['event']=='model_completed'),
        integrated_pass=result.get('status')=='passed',source_preserved=preserved,
        parallel_requests=peak_workers(result)>=2,
        fresh_delivery_pass=delivery.get('status')=='ready',
        sealed_holdout_pass=hidden.get('exit_code')==0,
        repeated_death_recovery=(len(crashes)==args.repeated_crashes and reused
            and all(c['exit_code']==17 and c['completed'] for c in crashes)),
        sources_stable=LOADED==fingerprints(SOURCE_FILES),no_exception=not error)
    checks['frozen_requirements_verified'] = (len(result.get('requirement_results', []))==len(REQUIREMENTS)
        and all(r['passed'] for r in result.get('requirement_results', []))
        and delivery.get('manifest',{}).get('requirements_digest')==result.get('requirements_digest')
        and bool(result.get('requirements_digest')))
    checks['execution_context_bound'] = (bool(result.get('contexts')) and bool(result.get('context_policy'))
        and all(e.get('context_digest') in result['contexts'] for e in result.get('events', [])
                if e['event'] in {'model_started','model_receipt'})
        and delivery.get('manifest',{}).get('contexts') == result.get('contexts'))
    report=dict(schema='clawos.project-collaboration-acceptance.v1',passed=all(checks.values()),
        live_model=True,internal_project_slice=True,independent_public_benchmark=False,
        holdout_exposed_to_workers=False,holdout_feedback_to_model=False,
        holdout_scope='six previously exercised regression cases plus two newly frozen cases; internal maintainer tests',
        duration_seconds=round(time.monotonic()-start,3),checks=checks,error=error,
        provenance=json.loads((args.out/'provenance.json').read_text(encoding='utf-8')),
        crashes=crashes,peak_worker_requests=peak_workers(result),result=result,
        delivery=delivery,holdout=hidden,source_fingerprints=LOADED)
    (args.out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','duration_seconds','checks','error','peak_worker_requests')},ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
