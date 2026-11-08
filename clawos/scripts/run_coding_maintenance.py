"""Replay real historical defects, then optionally run the production single/multi pair."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit
import uuid

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from benchmarks.coding_maintenance_v1 import IMPORTS, TASKS
from scripts.application_runtime import clean_environment
from services.coding_comparison_service import CodingComparisonService, digest, save


def git(repo, *args, env=None):
    return subprocess.run(['git', *args], cwd=repo, env=env, check=True,
                          capture_output=True, timeout=30).stdout


def snapshot(task, revision):
    return {path: git(APP.parent, 'show', f'{revision}:{path}') for path in task['paths'] + task['dependencies']}


def public_only(task_id, baseline, fixed):
    def replace_once(source, anchor, replacement):
        if anchor not in source:
            raise ValueError('historical negative control anchor missing')
        return source.replace(anchor, replacement, 1)

    if task_id == 'atomic-publish':
        return {path: replace_once(replace_once(content, b'range(8)', b'range(3)'), b'attempt == 7', b'attempt == 2')
                for path, content in fixed.items()}
    if task_id == 'pdf-cache-type':
        return {path: replace_once(content, b'if type(page) is not int or page<1:', b'if page is True:')
                for path, content in fixed.items()}
    return {path: replace_once(content, b'    for row in exact or rows:',
                              b"    if '#' in str(source) and not exact:\n        return False\n    for row in exact or rows:")
            for path, content in baseline.items()}


def write_snapshot(repo, files, public):
    repo.mkdir(parents=True, exist_ok=False)
    for relative, body in files.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    (repo / 'acceptance_public.py').write_bytes(public)


def test_pair(repo, commands):
    results = []
    for command in commands:
        result = subprocess.run([sys.executable, '-I', *command[1:]], cwd=repo, env=clean_environment(),
                                capture_output=True, timeout=30)
        results.append(dict(exit_code=result.returncode, stdout=result.stdout.decode('utf-8', 'replace')[-2000:],
                            stderr=result.stderr.decode('utf-8', 'replace')[-2000:]))
    return results


def build_case(task, root):
    baseline, fixed = (snapshot(task, task[key]) for key in ('baseline', 'fixed'))
    public = (IMPORTS + task['public']).encode('utf-8')
    post = (IMPORTS + task['post']).encode('utf-8')
    # The AppContainer launcher adds its own interpreter isolation flags.
    python = ['python', '-B', '-X', 'utf8']
    test = python + ['acceptance_public.py']
    # The post check is bound to the common replay, outside model worktrees.
    verification = python + ['-c', f"exec(bytes.fromhex('{post.hex()}').decode('utf-8'))"]
    repo = root / 'src' / task['id']
    write_snapshot(repo, baseline, public)
    env = clean_environment()
    env.update(GIT_AUTHOR_DATE='2026-01-01T00:00:00Z', GIT_COMMITTER_DATE='2026-01-01T00:00:00Z')
    git(repo, 'init', '-q', env=env)
    git(repo, 'config', 'core.autocrlf', 'false', env=env)
    git(repo, 'add', '--', '.', env=env)
    git(repo, '-c', 'user.name=ClawOS Benchmark', '-c', 'user.email=benchmark@localhost',
        '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=.', 'commit', '-qm', 'Freeze historical task inputs', env=env)
    checks = {}
    for name, files, expected in (('baseline', baseline, [1, 1]), ('historical_fix', fixed, [0, 0]),
                                  ('public_only', public_only(task['id'], baseline, fixed), [0, 1])):
        control = root / 'controls' / task['id'] / name
        write_snapshot(control, files, public)
        results = test_pair(control, [test, verification])
        checks[name] = dict(expected=expected, results=results,
                            passed=[r['exit_code'] for r in results] == expected and all(
                                r['exit_code'] == 0 or 'AssertionError:' in r['stderr'] for r in results))
    if git(repo, 'status', '--porcelain', env=env).strip():
        raise ValueError('historical baseline workspace was modified by controls')
    case = dict(id=task['id'], repo=str(repo), objective=task['objective'], paths=task['paths'], test_commands=[test],
                post_commands=[verification], requirements=[dict(id='maintenance_contract', statement=task['objective'],
                                                                  paths=task['paths'], test_indexes=[0])])
    fingerprint = lambda body: hashlib.sha256(body).hexdigest()
    receipt = dict(id=task['id'], baseline=task['baseline'], historical_fix=task['fixed'],
                   baseline_files={p:fingerprint(content) for p,content in baseline.items()},
                   fixed_files={p:fingerprint(content) for p,content in fixed.items()},
                   public_sha256=fingerprint(public), post_sha256=fingerprint(post), checks=checks,
                   passed=all(check['passed'] for check in checks.values()))
    return case, receipt


async def run_live(args, cases, root, binding, witness):
    import httpx
    from providers.qwen import QwenProvider
    from services.sandbox_runtime import SandboxRuntime

    boundary = SandboxRuntime().resolve() if os.name == 'nt' else None
    if boundary is None:
        raise RuntimeError('managed Windows AppContainer runtime required for live coding benchmark')
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            response = await client.get(args.url.rstrip('/') + '/models')
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise RuntimeError('configured loopback model endpoint unavailable') from exc
    advertised = {item.get('id') for item in data.get('data', []) if isinstance(item,dict)} if isinstance(data,dict) else set()
    if args.model not in advertised:
        raise ValueError('requested model is not advertised by the local endpoint')
    os.environ.update(CLAWOS_REQUIRE_OS_SANDBOX='1', CLAWOS_APPCONTAINER_PROFILE=boundary.profile_name,
                      CLAWOS_APPCONTAINER_RUNTIME=str(boundary.runtime_dir))
    runner = CodingComparisonService(root / 'pair', witness=witness)
    def factory(role):
        return QwenProvider(dict(base_url=args.url, model=args.model, api_key='', requires_api_key=False, timeout_s=300))
    model = dict(id='local-model', factory=factory, fingerprint=runner.svc.provider_signature(factory('identity')))
    return await runner.run(cases, [model], confirmed=True, repetitions=args.repetitions, binding=binding)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Opt in to real calls and strict sandbox execution')
    parser.add_argument('--url'); parser.add_argument('--model')
    parser.add_argument('--repetitions', type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args()
    if args.execute:
        url = urlsplit(args.url or '')
        if (url.scheme != 'http' or url.hostname not in {'127.0.0.1','localhost','::1'} or url.path.rstrip('/') != '/v1' or
                url.username or url.password or url.query or url.fragment or not args.model):
            parser.error('real execution requires an explicit credential-free loopback /v1 URL and model')
    root = APP / 'output' / 'cm' / uuid.uuid4().hex[:10]
    root.mkdir(parents=True, exist_ok=False)
    paths = (Path(__file__), APP / 'benchmarks/coding_maintenance_v1.py',
             APP / 'providers/qwen.py', APP / 'providers/openai_compatible.py')
    witness = {str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    cases, controls = [], []
    for task in TASKS:
        case, receipt = build_case(task, root)
        cases.append(case)
        controls.append(receipt)
        save(root / 'controls-progress.json', controls)
    manifest = [{key:row[key] for key in ('id','baseline','historical_fix','baseline_files','fixed_files','public_sha256','post_sha256')}
                for row in controls]
    if any(hashlib.sha256(Path(path).read_bytes()).hexdigest() != sha for path,sha in witness.items()):
        raise RuntimeError('maintenance benchmark source changed')
    binding = dict(corpus='clawos.coding-maintenance.v1', manifest_digest=digest(manifest), controls_digest=digest(controls),
                   published_tasks=True, release_evidence=False)
    report = dict(binding, controls=controls, source_witness=witness, controls_passed=all(row['passed'] for row in controls),
                  real_execution=False)
    save(root / 'cases.json', cases, immutable=True)
    if args.execute and report['controls_passed']:
        try:
            live = asyncio.run(run_live(args, cases, root, binding, witness))
            ledgers = [arm['ledger'] for arm in live['arms']]
            report.update(real_execution=any(ledger['provider_tokens'] > 0 for ledger in ledgers),
                          model_call_attempts=sum(ledger['calls'] for ledger in ledgers),
                          provider_answer_receipts=sum(len(ledger['receipts']) for ledger in ledgers),
                          comparison={key:live[key] for key in ('plan_digest','complete','protocol_valid',
                              'budget_conformant','execution_comparable','all_tasks_resolved','groups')})
        except (ValueError, OSError, RuntimeError) as exc:
            report['execution_error_type'] = type(exc).__name__
    save(root / 'report.json', report, immutable=True)
    print(json.dumps({key:value for key,value in report.items() if key not in {'controls','source_witness'}} | {'output':str(root)}, ensure_ascii=False))
    return int(not report['controls_passed'] or (args.execute and not report.get('comparison',{}).get('execution_comparable')))


if __name__ == '__main__':
    raise SystemExit(main())
