"""Run ClawOS on Aider's pinned Python exercises and original unit tests."""
from __future__ import annotations

import argparse
import ast
import asyncio
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from providers.deepseek import DeepSeekProvider
from scripts.run_coding_maintenance import DEEPSEEK_URL, clean_environment, git
from services.autonomous_coding_service import AutonomousCodingService
from services.coding_comparison_service import ComparisonCapture, operation, save
from services.coding_workflow_service import CodingWorkflowService
from services.coding_workspace_service import CodingWorkspaceService
from services.sandbox_runtime import SandboxRuntime


UPSTREAM = '7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f'
TRACK = 'python/exercises/practice/'
PYTHON = ['python', '-B', '-X', 'utf8']
BOUNDARY = ('strict_boundary_verified', 'parent_token_verified',
            'git_control_pointer_sealed', 'profile_and_grants_removed')
LIMITS = dict(max_model_calls=4, max_tokens=50_000, max_output_tokens=1800,
              timeout_seconds=100, max_wall_seconds=240)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def upstream_cases(repo):
    files = git(repo, 'ls-tree', '-r', '--name-only', UPSTREAM, '--', TRACK).decode().splitlines()
    names = sorted({p.removeprefix(TRACK).split('/')[0] for p in files})
    if not names:
        raise ValueError('pinned Aider Python track was not found')
    cases = {}
    for name in names:
        if not re.fullmatch(r'[a-z0-9-]+', name):
            raise ValueError('invalid exercise path')
        prefix = TRACK + name + '/'
        paths = {p.removeprefix(prefix) for p in files if p.startswith(prefix)}
        module = name.replace('-', '_')
        starter, test = module + '.py', module + '_test.py'
        read = lambda p: git(repo, 'show', f'{UPSTREAM}:{prefix}{p}')
        docs = [read(p).decode('utf-8') for p in ('.docs/instructions.md', '.docs/instructions.append.md') if p in paths]
        tests = {p: read(p) for p in sorted(paths - {starter}) if re.fullmatch(r'[a-z0-9_]+\.py', p)}
        if not docs or test not in tests:
            raise ValueError(f'{name}: missing original exercise or test')
        test_count = sum(isinstance(method, ast.FunctionDef) and method.name.startswith('test_')
                         for node in ast.parse(tests[test]).body if isinstance(node, ast.ClassDef)
                         for method in node.body)
        if not test_count:
            raise ValueError(f'{name}: no upstream test cases')
        cases[name] = dict(starter=starter, body=read(starter), tests=tests, test_module=test.removesuffix('.py'),
                           test_count=test_count,
                           objective='Implement the supplied exercise in ' + starter + '. Preserve its public API.\n\n'
                                     + '\n\n'.join(docs))
    return cases


def scorer(repo, case, patch):
    if patch:
        subprocess.run(['git', 'apply', '--whitespace=nowarn', '-'], input=patch, cwd=repo,
                       env=clean_environment(), capture_output=True, timeout=30, check=True)
    for path, contents in case['tests'].items():
        (repo / path).write_bytes(contents)
    code = ('import sys, unittest; sys.path.insert(0, "."); '
            f'suite = unittest.TestLoader().discover(".", pattern={case["test_module"] + ".py"!r}); '
            'result = unittest.TextTestRunner().run(suite); sys.exit(not result.wasSuccessful())')
    command = PYTHON + ['-c', code]
    result = CodingWorkflowService._run_command(repo, command, 60, require_strict=True)
    if any((repo / path).read_bytes() != contents for path, contents in case['tests'].items()):
        raise RuntimeError('original Aider test bytes changed')
    counts = re.findall(r'^Ran ([1-9]\d*) tests? in ', result['stderr'], re.MULTILINE)
    sandbox = result.get('sandbox', {})
    return dict(exit_code=result['exit_code'], timed_out=bool(result.get('timed_out')),
                strict=all(sandbox.get(key) is True for key in BOUNDARY),
                tests=int(counts[-1]) if counts else 0,
                load_failed='Failed to import test module:' in result['stderr'],
                stderr=result['stderr'][-3000:])


async def exercise(name, case, folder, provider, witness, *, limits, repair_reasoning):
    starter = case['starter']
    source = folder / 's'
    source.mkdir(parents=True)
    (source / starter).write_bytes(case['body'])
    env = clean_environment()
    git(source, 'init', '-q', env=env)
    git(source, 'config', 'core.autocrlf', 'false', env=env)
    git(source, 'add', '--', starter, env=env)
    git(source, '-c', 'user.name=ClawOS Benchmark', '-c', 'user.email=benchmark@localhost',
        '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=.', 'commit', '-qm', 'Freeze Aider starter', env=env)
    baseline = git(source, 'rev-parse', 'HEAD', env=env).decode().strip()
    workspaces = CodingWorkspaceService()

    async def workspace(label):
        meta = await operation(workspaces.create_task, source, folder / 'w', label, confirmed=True)
        return Path(meta['workspace'])

    control = await operation(scorer, await workspace('base'), case, b'')
    capture = ComparisonCapture(folder, limits, witness)
    workflow = CodingWorkflowService(artifact_root=folder / 'a')
    service = AutonomousCodingService(capture.wrap(provider), workflow=workflow)
    smoke = PYTHON + ['-c', f'compile(open({starter!r}, "rb").read(), {starter!r}, "exec")']
    attempts = []
    status = 'baseline_infrastructure_error'
    if (control['strict'] and not control['timed_out'] and control['exit_code'] == 1 and
            (control['tests'] == case['test_count'] or (control['load_failed'] and control['tests'] == 1))):
        status = 'failed'
        feedback = None
        for index in range(1, 3):
            task = await workspace(f'edit{index}')
            try:
                effort = repair_reasoning if index == 2 else None
                proposal = await service.propose(task, case['objective'], focus_paths=[starter],
                    test_commands=[smoke], previous_failure=feedback, reasoning_effort=effort,
                    max_output_tokens=limits['max_output_tokens'] if effort else LIMITS['max_output_tokens'])
            except (ValueError, RuntimeError, TimeoutError) as exc:
                attempts.append(dict(status='proposal_failed', error=type(exc).__name__))
                feedback = dict(error='Previous proposal was incomplete or did not validate. Use compact exact edits.')
                continue
            result = await operation(workflow.execute, task, case['objective'], proposal['proposal']['changes'],
                                     [smoke], confirmed=True, max_rounds=1, timeout_seconds=45)
            if result['status'] != 'passed':
                attempts.append(dict(status='candidate_gate_failed'))
                feedback = dict(error='Candidate did not pass its syntax and sandbox checks.')
                continue
            if git(task, 'diff', '--name-only', baseline, env=env).decode().splitlines() != [starter]:
                raise ValueError('patch violates Aider starter scope or is empty')
            patch = git(task, 'diff', '--binary', baseline, '--', starter, env=env)
            (folder / f'candidate-{index}.patch').write_bytes(patch)
            score = await operation(scorer, await workspace(f'score{index}'), case, patch)
            attempts.append(dict(status='scored', patch_sha256=sha(patch), score=score))
            if not score['strict'] or score['timed_out']:
                status = 'scoring_infrastructure_error'
                break
            if score['exit_code'] == 0 and not score['load_failed'] and score['tests'] == case['test_count']:
                status = 'passed'
                break
            # Aider's second turn can use failed-test output. Test files and
            # score worktrees remain outside the agent's context in both turns.
            feedback = service.repair_feedback(proposal, error='Upstream unit tests failed.', rounds=[dict(tests=[score])])
    if not capture.stable() or git(source, 'status', '--porcelain', env=env).strip():
        raise ValueError('benchmark implementation or starter changed')
    return dict(id=name, status=status, starter_sha256=sha(case['body']), control=control, attempts=attempts,
                test_sha256={p: sha(body) for p, body in case['tests'].items()}, ledger=capture.snapshot())


async def run(cases, root, model, key, jobs, *, repair_reasoning):
    witness = {str(p): sha(p.read_bytes()) for p in (
        Path(__file__).resolve(), APP / 'services/autonomous_coding_service.py', APP / 'services/coding_workflow_service.py',
        APP / 'services/coding_execution_context.py', APP / 'providers/deepseek.py', APP / 'providers/openai_compatible.py',
        APP / 'services/sandbox_supervisor.py', APP / 'services/windows_appcontainer_boundary.py',
    )}
    limits = LIMITS | (dict(max_output_tokens=8192, timeout_seconds=180, max_wall_seconds=420)
                       if repair_reasoning else {})
    provider = DeepSeekProvider(dict(base_url=DEEPSEEK_URL, model=model, api_key=key,
                                     timeout_s=limits['timeout_seconds'] - 5, trust_env=False))
    plan = dict(upstream=UPSTREAM, model=model, limits=limits, cases=list(cases), witness=witness,
                repair_reasoning=repair_reasoning,
                method='ClawOS single agent, two candidate attempts, original upstream Python tests')
    save(root / 'plan.json', plan, immutable=True)
    pool = asyncio.Semaphore(jobs)
    rows = {}

    async def one(name, case):
        async with pool:
            try:
                row = await exercise(name, case, root / name, provider, witness,
                                     limits=limits, repair_reasoning=repair_reasoning)
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                row = dict(id=name, status='infrastructure_error', error=type(exc).__name__)
            rows[name] = row
            save(root / 'progress.json', dict(completed=len(rows), planned=len(cases), rows=list(rows.values())))
            print(f'{name} {row["status"]} ({len(rows)}/{len(cases)})', flush=True)

    await asyncio.gather(*(one(name, case) for name, case in cases.items()))
    report = plan | dict(rows=[rows[name] for name in cases], passed=sum(row['status'] == 'passed' for row in rows.values()),
                         planned=len(cases), official_leaderboard_run=False)
    save(root / 'report.json', report, immutable=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('upstream', type=Path)
    parser.add_argument('--model', default='deepseek-v4-pro')
    parser.add_argument('--jobs', type=int, choices=(1, 2, 3), default=2)
    parser.add_argument('--repair-reasoning', choices=('low', 'high'), help='Bounded DeepSeek reasoning on attempt two')
    parser.add_argument('--exercise', action='append', help='Repeat to run an explicit subset; default is the full Python track')
    args = parser.parse_args()
    cases = upstream_cases(args.upstream.resolve())
    if args.exercise:
        if unknown := set(args.exercise) - set(cases):
            parser.error('unknown upstream exercise: ' + ', '.join(sorted(unknown)))
        cases = {name: cases[name] for name in args.exercise}
    boundary = SandboxRuntime().resolve()
    if not boundary or not sys.stdin.isatty():
        parser.error('strict Windows runtime and interactive hidden key input required')
    key = getpass.getpass('DeepSeek API key (hidden): ').strip()
    if not key:
        parser.error('DeepSeek API key required')
    os.environ.update(CLAWOS_REQUIRE_OS_SANDBOX='1', CLAWOS_APPCONTAINER_PROFILE=boundary.profile_name,
                      CLAWOS_APPCONTAINER_RUNTIME=str(boundary.runtime_dir))
    root = APP / 'output' / ('ap-' + uuid.uuid4().hex[:8])
    root.mkdir()
    print(root, flush=True)
    report = asyncio.run(run(cases, root, args.model, key, args.jobs, repair_reasoning=args.repair_reasoning))
    print(json.dumps(dict(passed=report['passed'], planned=report['planned'], report=str(root / 'report.json'))))
    return int(report['passed'] != report['planned'])


if __name__ == '__main__':
    raise SystemExit(main())
