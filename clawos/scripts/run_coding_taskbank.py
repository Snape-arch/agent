"""Frozen internal taskbank controls and optional real single/multi comparison."""
from __future__ import annotations
import argparse
import ast
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(Path(__file__).parent))
from benchmarks.coding_taskbank_v1 import SOURCE_REVISION, TASKS
from probe_strict_sandbox import prepare_runtime
from services.windows_appcontainer_boundary import WindowsAppContainerBoundary
from services.strict_sandbox_acceptance import fingerprint

PREFIX = "import sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path.cwd()/'clawos'))\n"


def reference_source(task, source):
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == task['function'])
    lines = source.splitlines(keepends=True); body = ''.join(lines[node.lineno-1:node.end_lineno])
    if 'reference' in task:
        body = task['reference']
    elif 'reference_suffix' in task:
        body = body.replace('    return result\n', task['reference_suffix'])
    elif 'reference_prefix' in task:
        header, rest = body.split('\n', 1); body = header + '\n' + task['reference_prefix'] + rest
    else:
        body = body.replace('    exact =', task['reference_insertion'] + '    exact =', 1)
    return ''.join(lines[:node.lineno-1]) + body + '\n' + ''.join(lines[node.end_lineno:])


def public_only_source(task, source):
    # Intentionally overfit solutions. The post checks must reject every one.
    implementations = {
        'richtext-canonical-runs': "def validate_inline(value):\n    return [{'text':'ab','marks':[]}] if len(value)==2 else []\n",
        'table-shape-contract': "def merge_table(base,local,remote):\n    raise MergeConflict('always rejected')\n",
        'paper-citation-boundary': "def _canonical_citation(citation,document_id):\n    return 'doc:1#page=2&chunk=3' if citation=='doc:001#page=02&chunk=03' else ''\n",
        'history-character-budget': "def request_history(messages, *, max_characters=24000):\n    return messages[-2:-1]\n",
        'evidence-document-review': "def source_usable(connection,source):\n    return False\n",
        'learning-health-telemetry': "def runtime_health_passed(rows):\n    return False\n",
    }
    return reference_source(dict(task, reference=implementations[task['id']]), source)


def git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, capture_output=True, check=True, timeout=30).stdout


def seed(task, root):
    repo = root / task['id']; target = repo / 'clawos' / 'services' / (task['module'] + '.py')
    target.parent.mkdir(parents=True)
    path = 'clawos/services/' + task['module'] + '.py'
    source = git(BASE.parent, 'show', SOURCE_REVISION + ':' + path).decode('utf-8')
    target.write_text(source, encoding='utf-8')
    (target.parent / '__init__.py').write_text('', encoding='utf-8')
    # document_merge's existing lazy import must retain its actual dependency.
    dependencies = []
    if task['module'] == 'document_merge':
        dependency = 'clawos/services/document_richtext.py'
        (repo / dependency).write_bytes(git(BASE.parent, 'show', SOURCE_REVISION + ':' + dependency))
        dependencies.append(dependency)
    (repo / 'acceptance_public.py').write_text(PREFIX + task['public'], encoding='utf-8')
    (repo / 'TASK_ORIGIN.md').write_text('Maintainer-authored internal task on ClawOS commit ' + SOURCE_REVISION + '.\n'
        'This is a selected-module project slice, not an external blind benchmark or full repository task.\n', encoding='utf-8')
    git(repo, 'init', '-q'); git(repo, 'add', '.')
    git(repo, '-c', 'user.name=ClawOS Acceptance', '-c', 'user.email=acceptance@localhost',
        '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Freeze task source and public checks')
    # No post test file or reference implementation exists in the model workspace.
    post = "exec(bytes.fromhex('" + (PREFIX + task['post']).encode('utf-8').hex() + "').decode('utf-8'))"
    case = dict(id=task['id'], repo=str(repo), objective=task['objective'], paths=[path],
        test_commands=[['python','-B','acceptance_public.py']], post_commands=[['python','-c',post]],
        requirements=[dict(id='complete_contract',statement=task['objective'],paths=[path],test_indexes=[0],
            clauses=[dict(id='whole_requirement',category='output',statement=task['objective'],test_indexes=[0])])])
    return case, source, dependencies


def controls(boundary, case, task, source, root):
    from services.coding_workspace_service import CodingWorkspaceService
    meta = CodingWorkspaceService().create_task(case['repo'], root/'controls'/task['id'], 'validity-controls', confirmed=True)
    workspace = Path(meta['workspace'])
    target = workspace / case['paths'][0]
    results = {}
    variants = [('original', source), ('reference', reference_source(task, source)),
                ('public_only', public_only_source(task, source))]
    if task['id'] == 'richtext-canonical-runs':
        # A real previously accepted proposal used a UI-style priority order.
        # It must pass public examples but fail the full lexicographic contract.
        wrong_order = reference_source(task, source).replace(
            "span['marks'].sort(key=lambda mark: mark['type'])",
            "span['marks'].sort(key=lambda mark: ('bold','italic','strike','code','underline','highlight','link').index(mark['type']))",
        )
        if wrong_order == reference_source(task, source):
            raise RuntimeError('wrong-order control anchor is missing')
        variants.append(('wrong_mark_priority', wrong_order))
    try:
        for name, text in variants:
            target.write_text(text, encoding='utf-8')
            rows = [boundary.run_command(command, workspace, timeout_seconds=30, confirmed_acl=True)
                for command in case['test_commands'] + case['post_commands']]
            # Source/project failure must be an actual Python failure, never a sandbox launch failure.
            expected = [1,1] if name == 'original' else ([0,0] if name == 'reference' else [0,1])
            results[name] = dict(passed=[row['exit_code'] for row in rows] == expected and
                all(row['sandbox'].get('parent_token_verified') and row['sandbox'].get('profile_and_grants_removed') for row in rows),
                expected_exit_codes=expected, executions=rows)
    finally:
        target.write_text(source, encoding='utf-8')
    if git(case['repo'], 'status', '--porcelain').strip():
        raise RuntimeError('controls changed the frozen baseline')
    return dict(id=task['id'], passed=all(v['passed'] for v in results.values()), controls=results,
        source_sha256=hashlib.sha256(source.encode()).hexdigest(),
        public_sha256=hashlib.sha256((PREFIX+task['public']).encode()).hexdigest(),
        post_sha256=hashlib.sha256((PREFIX+task['post']).encode()).hexdigest())


async def live(args, cases, root):
    from providers.qwen import QwenProvider
    from services.coding_comparison_service import CodingComparisonService
    sources = [Path(__file__), BASE/'benchmarks/coding_taskbank_v1.py', BASE/'providers/qwen.py',
               BASE/'providers/openai_compatible.py', Path(__file__).with_name('probe_strict_sandbox.py')]
    witness = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    runner = CodingComparisonService(root/'comparison', witness=witness)
    factory = lambda role: QwenProvider(dict(base_url=args.url, model=args.model, api_key='', requires_api_key=False, timeout_s=300))
    models = [dict(id='local-qwen', factory=factory, fingerprint=runner.svc.provider_signature(factory('identity')))]
    selected = [case for case in cases if not args.case or case['id'] in args.case]
    if not selected or args.case and set(args.case)-{c['id'] for c in selected}:
        raise ValueError('unknown task selection')
    return await runner.run(selected, models, confirmed=True, repetitions=1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--live', action='store_true'); p.add_argument('--url'); p.add_argument('--model')
    p.add_argument('--case', action='append'); args=p.parse_args()
    if args.live:
        u=urlparse(args.url or '')
        if u.scheme != 'http' or u.hostname not in {'localhost','127.0.0.1','::1'} or u.username or u.password or u.query or u.fragment or not args.model:
            p.error('live mode needs a credential-free loopback URL and explicit model')
    root=BASE/'output'/'taskbank'/uuid.uuid4().hex[:12];root.mkdir(parents=True)
    runtime=root/'runtime'; workspace=root/'boundary';workspace.mkdir()
    boundary=WindowsAppContainerBoundary('ClawOS.Bank.'+uuid.uuid4().hex, runtime_dir=runtime)
    report=dict(schema='clawos.coding-taskbank-controls.v1', source_revision=SOURCE_REVISION,
        production_sandbox_ready=False, task_count=len(TASKS), results=[], source_fingerprints=fingerprint(), passed=False)
    created=False; sid=None
    env_keys=('CLAWOS_APPCONTAINER_RUNTIME','CLAWOS_APPCONTAINER_PROFILE','CLAWOS_REQUIRE_OS_SANDBOX')
    previous={k:os.environ.get(k) for k in env_keys}
    try:
        prepare_runtime(runtime)
        installed=boundary.install(confirmed=True);created=installed['created'];sid=installed['sid']
        if not created: raise RuntimeError('owned fresh profile required')
        boundary.grant_runtime(confirmed=True)
        report['boundary']=boundary.probe(workspace,confirmed_acl=True)
        if not report['boundary']['passed']: raise RuntimeError('strict attack matrix failed; task execution blocked')
        cases=[]
        for task in TASKS:
            case, source, dependencies=seed(task,root/'sources');cases.append(case)
            row=controls(boundary,case,task,source,root);report['results'].append(row)
            print(json.dumps(dict(id=task['id'],controls_passed=row['passed'])),flush=True)
            (root/'controls-progress.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        report['passed']=all(r['passed'] for r in report['results'])
        (root/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
        if args.live:
            if not report['passed']: raise RuntimeError('task validity controls failed; real model execution blocked')
            os.environ.update(CLAWOS_REQUIRE_OS_SANDBOX='1',CLAWOS_APPCONTAINER_RUNTIME=str(runtime),CLAWOS_APPCONTAINER_PROFILE=boundary.profile_name)
            result=asyncio.run(live(args,cases,root))
            report['live']={key:result[key] for key in ('complete','protocol_valid','budget_conformant','execution_comparable','all_tasks_resolved','groups')}
    except Exception as exc:
        report['error']=f'{type(exc).__name__}: {exc}';report['passed']=False
    finally:
        for key,value in previous.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value
        if created:
            cleanup=subprocess.run(['icacls',str(runtime),'/remove:g','*'+sid,'/T','/Q'],capture_output=True,timeout=60)
            report['runtime_acl_removed']=cleanup.returncode==0
            report['profile_removed']=boundary.uninstall(confirmed=True)
            report['passed']=report['passed'] and report['runtime_acl_removed'] and report['profile_removed'].get('deleted')
        report['source_stable']=report['source_fingerprints']==fingerprint()
        report['passed']=report['passed'] and report['source_stable']
        (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(root=str(root),passed=report['passed'],error=report.get('error'),live=report.get('live')),ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
