"""Seal a private cross-repository task pack and run a matched DeepSeek comparison."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from scripts.run_coding_maintenance import clean_environment, digest, git, run_live, save, write_snapshot
from services.coding_comparison_service import CodingComparisonService
from services.coding_evidence_service import CodingEvidenceService
from services.coding_execution_context import CodingExecutionContext
from services.coding_workflow_service import CodingWorkflowService
from services.sandbox_runtime import SandboxRuntime
from memoryos.memory_store import MemoryStore


OUTPUT = APP / 'output'
VARIANTS = {'baseline': [1, 1], 'reference': [0, 0], 'public_only': [0, 1]}
BOUNDARY_FIELDS = ('strict_boundary_verified', 'parent_token_verified',
                   'git_control_pointer_sealed', 'profile_and_grants_removed')
SCHEMA = 'clawos.crossrepo-blind.v1'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


RUNNER_WITNESS = {str(path): sha(path) for path in (
    Path(__file__).resolve(), APP / 'scripts/run_coding_maintenance.py',
    APP / 'providers/deepseek.py', APP / 'providers/openai_compatible.py',
)}


def contained(path):
    path = Path(path).absolute()
    path.relative_to(OUTPUT)
    if '..' in path.parts or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise ValueError('blind material cannot use linked paths')
    return path


def source_files(folder):
    files = {}
    for entry in sorted(contained(folder).rglob('*')):
        path = contained(entry)
        if path.is_dir():
            continue
        rel = path.relative_to(folder).as_posix()
        if rel != 'LICENSE':
            CodingExecutionContext.safe_path(rel)
            if path.suffix != '.py':
                raise ValueError('task sources are Python and the upstream license')
        if path.stat().st_size > 128_000:
            raise ValueError('blind task file exceeds source limit')
        files[rel] = path.read_bytes()
    if 'LICENSE' not in files or len(files) > 40:
        raise ValueError('blind task needs an upstream license and bounded source')
    return files


def seed(repo, files, public):
    write_snapshot(repo, files, public)
    env = clean_environment()
    env.update(GIT_AUTHOR_DATE='2026-01-01T00:00:00Z', GIT_COMMITTER_DATE='2026-01-01T00:00:00Z')
    git(repo, 'init', '-q', env=env)
    git(repo, 'config', 'core.autocrlf', 'false', env=env)
    git(repo, 'add', '--', '.', env=env)
    git(repo, '-c', 'user.name=ClawOS Benchmark', '-c', 'user.email=benchmark@localhost',
        '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=.', 'commit', '-qm', 'Freeze benchmark inputs', env=env)


def sandbox_verified(result):
    # The pack uses Python assertions for failures. Windows process startup
    # statuses and timeouts cannot count as model failures with valid evidence.
    return result.get('exit_code') in {0, 1} and not result.get('timed_out') and all(
        result.get('sandbox', {}).get(key) is True for key in BOUNDARY_FIELDS)


def preflight(pack, root):
    pack = contained(pack)
    spec = read(contained(pack / 'tasks.json'))
    if spec['schema'] != SCHEMA or not 8 <= len(spec['tasks']) <= 12:
        raise ValueError('blind pack requires 8–12 tasks')
    ids = set()
    repositories = set()
    write_sources = set()
    prepared = []
    for task in spec['tasks']:
        task_id = task['id']
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', task_id) or task_id in ids:
            raise ValueError('duplicate or invalid blind task id')
        ids.add(task_id)
        source = task['upstream']
        if (not re.fullmatch(r'[\w.-]+/[\w.-]+', source['repo']) or
                not re.fullmatch(r'[a-f0-9]{40}', source['commit'])):
            raise ValueError('upstream must use a pinned commit')
        repositories.add(source['repo'])
        paths = task['paths']
        if not paths or len(set(paths)) != len(paths):
            raise ValueError('task needs unique write paths')
        for p in paths:
            CodingExecutionContext.safe_path(p)
        task_folder = pack / task_id
        variants = {v: source_files(task_folder / v) for v in VARIANTS}
        baseline = variants['baseline']
        if 'acceptance_public.py' in baseline:
            raise ValueError('reserved task file')
        for p in paths:
            if p not in baseline or (source['repo'], p) in write_sources:
                raise ValueError('missing or reused upstream write target')
            write_sources.add((source['repo'], p))
        for files in variants.values():
            if files.keys() != baseline.keys() or any(files[p] != baseline[p] for p in baseline if p not in paths):
                raise ValueError('control changes outside frozen write scope')
        public = contained(task_folder / 'public.py').read_bytes()
        post = contained(task_folder / 'post.py').read_bytes()
        if not public or not post or public == post or len(public) > 32_000 or len(post) > 8_000:
            raise ValueError('independent post test is empty, repeated or too large')
        compile(public, 'public.py', 'exec')
        compile(post, 'post.py', 'exec')
        prepared.append((task, variants, public, post))
    if len(repositories) < 2 or not any(len(t[0]['paths']) > 1 for t in prepared):
        raise ValueError('blind pack needs two repositories and a cross-file task')

    boundary = SandboxRuntime().resolve()
    if boundary is None:
        raise RuntimeError('managed Windows AppContainer required')
    os.environ.update(CLAWOS_REQUIRE_OS_SANDBOX='1', CLAWOS_APPCONTAINER_PROFILE=boundary.profile_name,
                      CLAWOS_APPCONTAINER_RUNTIME=str(boundary.runtime_dir))
    service = CodingComparisonService(root / 'preflight', witness=RUNNER_WITNESS)
    cases, checks = [], []
    for task, variants, public, post in prepared:
        task_id = task['id']
        repo = root / 'src' / task_id
        seed(repo, variants['baseline'], public)
        python = ['python', '-B', '-X', 'utf8']
        commands = [python + ['acceptance_public.py'],
                    python + ['-c', f"exec(bytes.fromhex('{post.hex()}').decode('utf-8'))"]]
        case = dict(id=task_id, repo=str(repo), objective=task['objective'], paths=task['paths'],
                    test_commands=commands[:1], post_commands=commands[1:],
                    requirements=[dict(id='caller_contract', statement=task['objective'],
                                       paths=task['paths'], test_indexes=[0])])
        frozen = service.case(case)
        cases.append(case)
        meta = service.svc.workspaces.create_task(repo, root / 'controls' / task_id, 'control', confirmed=True)
        work = Path(meta['workspace'])
        results = {}
        for variant, expected in VARIANTS.items():
            for path in task['paths']:
                (work / path).write_bytes(variants[variant][path])
            rows = [CodingWorkflowService._run_command(work, command, 30) for command in commands]
            passed = [row['exit_code'] for row in rows] == expected and all(
                sandbox_verified(row) and (row['exit_code'] == 0 or
                    re.search(r'(?m)^AssertionError(?:[:\r]|$)', row['stderr'])) for row in rows)
            results[variant] = dict(passed=passed, rows=rows)
        checks.append(dict(id=task_id, upstream=task['upstream'], source_head=frozen['source_head'],
                           case_digest=frozen['case_digest'], results=results,
                           variant_sha256={name: {p: hashlib.sha256(body).hexdigest() for p, body in files.items()}
                                           for name, files in variants.items()}))
        save(root / 'controls-progress.json', checks)
        print(json.dumps(dict(id=task_id, passed=all(v['passed'] for v in results.values()))), flush=True)

    if any(sha(Path(path)) != expected for path, expected in service.witness.items()):
        raise ValueError('preflight implementation changed')
    body = dict(schema=SCHEMA, cases=cases, checks=checks, witness=service.witness,
                passed=all(v['passed'] for c in checks for v in c['results'].values()))
    save(root / 'seal.json', body | dict(seal_digest=digest(body)), immutable=True)
    return body['passed']


def verified_seal(root, expected_seal):
    value = read(contained(root / 'seal.json'))
    seal_digest = value.pop('seal_digest')
    if (seal_digest != expected_seal or value['schema'] != SCHEMA or
            digest(value) != seal_digest or value['passed'] is not True):
        raise ValueError('passing, intact preflight seal required')
    if any(sha(Path(path)) != expected for path, expected in value['witness'].items()):
        raise ValueError('sealed implementation changed')
    with tempfile.TemporaryDirectory(dir=root) as scratch:
        service = CodingComparisonService(Path(scratch) / 'verify', witness=value['witness'])
        for case, check in zip(value['cases'], value['checks'], strict=True):
            if case['id'] != check['id'] or service.case(case)['case_digest'] != check['case_digest']:
                raise ValueError('sealed task changed')
    return value


def compare(root, model, expected_seal):
    seal = verified_seal(root, expected_seal)
    run = root / ('run-' + uuid.uuid4().hex[:8])
    run.mkdir()
    if not sys.stdin.isatty():
        raise ValueError('DeepSeek requires an interactive hidden key prompt')
    key = getpass.getpass('DeepSeek API key (hidden): ').strip()
    if not key:
        raise ValueError('DeepSeek API key is required')
    args = argparse.Namespace(provider='deepseek', model=model, repetitions=1)
    binding = dict(corpus=SCHEMA, seal_digest=expected_seal, published_tasks=False, release_evidence=False)
    report = asyncio.run(run_live(args, seal['cases'], run, binding, seal['witness'], key))
    verified_seal(root, expected_seal)
    store = MemoryStore(str(run / 'audit.sqlite'))
    evidence = CodingEvidenceService(store, run).verify(run / 'pair')
    rows = []
    for arm, audit in zip(report['arms'], evidence['rows'], strict=True):
        tests = arm['validation'].get('tests', [])
        rows.append(dict(case=arm['case_id'], mode=arm['mode'], accepted=arm['accepted'],
                         pipeline_accepted=arm['pipeline_accepted'], category=audit['category'],
                         exits=[r['exit_code'] for r in tests],
                         strict_replay=len(tests) == 2 and all(sandbox_verified(r) for r in tests),
                         calls=arm['ledger']['calls'], tokens=arm['ledger']['provider_tokens'],
                         seconds=arm['ledger']['elapsed_seconds']))
    summary = dict(seal_digest=expected_seal, plan_digest=report['plan_digest'],
                   report_sha256=sha(run / 'pair' / 'report.json'), model=model,
                   comparable=report['execution_comparable'] and all(row['strict_replay'] for row in rows),
                   groups=report['groups'], arms=rows)
    save(run / 'audit.json', summary, immutable=True)
    print(json.dumps(summary | dict(output=str(run)), ensure_ascii=False))
    return summary['comparable']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--pack', type=Path, help='Preflight a private pack below clawos/output')
    group.add_argument('--run', type=Path, help='Run a sealed preflight with DeepSeek')
    parser.add_argument('--model', default='deepseek-v4-pro')
    parser.add_argument('--seal-digest', help='Recorded preflight seal digest required for live execution')
    args = parser.parse_args()
    if args.run:
        if not re.fullmatch(r'[a-f0-9]{64}', args.seal_digest or ''):
            parser.error('--run requires the preflight --seal-digest')
        return int(not compare(contained(args.run), args.model, args.seal_digest))
    root = OUTPUT / 'xr' / uuid.uuid4().hex[:8]
    root.mkdir(parents=True)
    print(json.dumps(dict(output=str(root))), flush=True)
    return int(not preflight(args.pack, root))


if __name__ == '__main__':
    raise SystemExit(main())
