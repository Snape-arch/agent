"""Compare issue-only repository repair pipelines against frozen historical fixes."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import traceback
import uuid
import zipfile

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from benchmarks.coding_repository_v1 import CASES
from providers.deepseek import DeepSeekProvider
from scripts.run_coding_crossrepo import sandbox_verified
from scripts.run_coding_maintenance import DEEPSEEK_URL, clean_environment, git
from services.agentic_coding_loop_service import AgenticCodingLoopService
from services.autonomous_coding_service import AutonomousCodingService
from services.coding_comparison_service import ComparisonCapture, operation, save
from services.coding_execution_context import CodingExecutionContext
from services.coding_trace_service import CodingTraceService
from services.coding_workflow_service import CodingWorkflowService
from services.coding_workspace_service import CodingWorkspaceService
from services.execution_governance import ExecutionBudget
from services.sandbox_runtime import SandboxRuntime

PUBLIC = 'tests/_clawos_issue_public.py'
HOLDOUT = 'tests/_clawos_issue_heldout.py'
COMMAND = ['python', '-B', '-X', 'utf8', PUBLIC]
LIMITS = dict(max_model_calls=8, max_tokens=85_000, max_output_tokens=2000,
              max_wall_seconds=420, timeout_seconds=90)
BOOTSTRAP = 'import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path.cwd()))\n'
ENV = clean_environment()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def patch_apply(repo, patch):
    result = subprocess.run(['git', 'apply', '--binary', '--whitespace=nowarn', '-'], cwd=repo, input=patch,
                            capture_output=True, timeout=30, env=ENV)
    if result.returncode:
        raise ValueError('frozen patch replay failed: ' + result.stderr.decode('utf-8', errors='replace')[-1000:])


def seed(case, upstream, folder):
    fix = case['fix']
    base = git(upstream, 'rev-parse', fix + '^', env=ENV).decode().strip()
    raw = git(upstream, '-c', 'core.autocrlf=false', 'archive', '--format=zip', base, env=ENV)
    source = folder / 's'
    source.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or '..' in path.parts or '.git' in path.parts or '\\' in entry.filename:
                raise ValueError('invalid upstream archive path')
            if entry.is_dir():
                continue
            target = source / entry.filename
            target.resolve().relative_to(source.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(entry))
    public = source / PUBLIC
    public.parent.mkdir(exist_ok=True)
    public.write_bytes((BOOTSTRAP + case['public']).encode())
    git(source, 'init', '-q', env=ENV)
    git(source, 'config', 'core.autocrlf', 'false', env=ENV)
    git(source, 'add', '--', '.', env=ENV)
    git(source, '-c', 'user.name=ClawOS Benchmark', '-c', 'user.email=benchmark@localhost',
        '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=.', 'commit', '-qm', 'Freeze repository issue inputs', env=ENV)
    allowed = set(CodingExecutionContext.source_candidates(CodingExecutionContext.inventory(source)))
    reference_paths = [p for p in git(upstream, 'diff', '--name-only', base, fix, env=ENV).decode().splitlines() if p in allowed]
    if not reference_paths:
        raise ValueError('historical reference changes no eligible source')
    reference = git(upstream, 'diff', '--binary', base, fix, '--', *reference_paths, env=ENV)
    return dict(source=source, allowed=allowed, upstream_base=base, archive_sha256=sha(raw), reference=reference,
                tree=git(source, 'rev-parse', 'HEAD^{tree}', env=ENV).decode().strip(),
                public_sha256=sha(public.read_bytes()), heldout_sha256=sha((BOOTSTRAP + case['heldout']).encode()))


def workspace(prepared, root, label):
    return Path(CodingWorkspaceService().create_task(prepared['source'], root, label, confirmed=True)['workspace'])


def execute(repo, command):
    result = CodingWorkflowService._run_command(repo, command, 60, require_strict=True)
    return {key: result.get(key) for key in ('exit_code', 'timed_out', 'stdout', 'stderr', 'sandbox')} | dict(command=command)


def score(case, prepared, folder, patch):
    repo = workspace(prepared, folder / 'v', 'independent-scoring')
    if patch:
        patch_apply(repo, patch)
    heldout = repo / HOLDOUT
    heldout.write_bytes((BOOTSTRAP + case['heldout']).encode())
    rows = [execute(repo, cmd) for cmd in (COMMAND, [*COMMAND[:-1], HOLDOUT])]
    if sha((repo / PUBLIC).read_bytes()) != prepared['public_sha256'] or sha(heldout.read_bytes()) != prepared['heldout_sha256']:
        raise ValueError('scoring fixture bytes changed')
    return rows


def controls(case, prepared, folder):
    baseline = score(case, prepared, folder/'base', b'')
    reference = score(case, prepared, folder/'ref', prepared['reference'])
    return dict(baseline=baseline, reference=reference, verified=(
        all(sandbox_verified(row) for row in baseline + reference) and
        [row['exit_code'] for row in baseline] == [1, 1] and
        [row['exit_code'] for row in reference] == [0, 0]))


def error_evidence(exc):
    errors = []
    while exc is not None:
        stack = traceback.extract_tb(exc.__traceback__)
        frame = stack[-1] if stack else None
        code = provider_http_error(str(exc))
        errors.append(dict(type=type(exc).__name__, file=Path(frame.filename).name if frame else None,
                           line=frame.lineno if frame else None, function=frame.name if frame else None)
                      | ({'provider_error': code} if code else {}))
        exc = exc.__cause__
    return errors


def provider_http_error(error):
    if isinstance(error, str):
        return error if re.fullmatch(r'provider_http_[1-5][0-9]{2}', error) else None
    return next((item['provider_error'] for item in error or [] if 'provider_error' in item), None)


async def preflight(selected, root, args):
    pool = asyncio.Semaphore(args.jobs)
    prepared, checks = {}, {}

    async def one(case):
        name = case['id']
        async with pool:
            data = await operation(seed, case, getattr(args, case['project']).resolve(), root/name)
            check = await operation(controls, case, data, root/name/'control')
            prepared[name], checks[name] = data, check
            save(root/'preflight.json', checks)
            print(name, 'controls', check['verified'], flush=True)

    await asyncio.gather(*(one(case) for case in selected))
    return prepared, checks


async def proposal_arm(case, prepared, folder, provider):
    repo = await operation(workspace, prepared, folder/'w', 'proposal')
    baseline = await operation(execute, repo, COMMAND)
    if not sandbox_verified(baseline) or baseline['exit_code'] != 1:
        return repo, dict(status='baseline_unavailable', attempts=[], baseline=baseline)
    workflow = CodingWorkflowService(artifact_root=folder/'a')
    service = AutonomousCodingService(provider, workflow=workflow)
    budget = ExecutionBudget(max_model_calls=LIMITS['max_model_calls'], max_tokens=LIMITS['max_tokens'],
                             max_wall_seconds=LIMITS['max_wall_seconds'])
    attempts = []
    previous = None
    status = 'failed'
    for _ in range(3):
        try:
            proposal = await service.propose(repo, case['objective'], test_commands=[COMMAND], baseline_results=[baseline],
                                             previous_failure=previous, budget=budget,
                                             max_output_tokens=LIMITS['max_output_tokens'])
        except (RuntimeError, ValueError) as exc:
            return repo, dict(status='proposal_failed', attempts=attempts, baseline=baseline, error=error_evidence(exc))
        result = await operation(workflow.execute, repo, case['objective'], proposal['proposal']['changes'], [COMMAND],
                                 confirmed=True, max_rounds=1, timeout_seconds=60, require_strict=True)
        attempts.append(dict(paths=[change['path'] for change in proposal['proposal']['changes']], result=result))
        if result['status'] == 'passed':
            status = 'passed'
            break
        if result.get('test_boundary_failure'):
            status = 'test_boundary_failed'
            break
        previous = service.repair_feedback(proposal, error=result.get('failure'), rounds=result.get('rounds', []))
    return repo, dict(status=status, attempts=attempts, baseline=baseline)


async def agent_arm(case, prepared, folder, provider):
    workflow = CodingWorkflowService(artifact_root=folder/'a')
    service = AgenticCodingLoopService(provider, workflow=workflow, trace=CodingTraceService(folder/'trace.json'))
    result = await service.run(prepared['source'], case['objective'], confirmed=True, test_commands=[COMMAND],
                               task_id=case['id'], session_id=folder.name, max_turns=LIMITS['max_model_calls'],
                               timeout_seconds=60)
    baseline = next((row for row in result['observations'] if row['type'] == 'baseline_tests'), None)
    if not baseline or not baseline['available'] or [test['exit_code'] for test in baseline['tests']] != [1]:
        result = result | {'status': 'baseline_unavailable'}
    return Path(baseline['workspace']['workspace']) if baseline else prepared['source'], result


async def arm(case, prepared, mode, folder, provider, witness):
    capture = ComparisonCapture(folder, LIMITS, witness)
    result = {}
    try:
        repo, result = await asyncio.wait_for((agent_arm if mode == 'agentic' else proposal_arm)(
            case, prepared, folder, capture.wrap(provider)), timeout=LIMITS['max_wall_seconds'])
        names = git(repo, 'diff', '--name-only', 'HEAD', env=ENV).decode().splitlines()
        untracked = git(repo, 'ls-files', '--others', '--exclude-standard', env=ENV).strip()
        if not set(names) <= prepared['allowed'] or untracked:
            raise ValueError('candidate changed paths outside tracked source scope')
        patch = git(repo, 'diff', '--binary', 'HEAD', env=ENV)
        (folder/'candidate.patch').write_bytes(patch)
        rows = await operation(score, case, prepared, folder/'score', patch) if patch else []
        if not capture.verify() or git(prepared['source'], 'status', '--porcelain', env=ENV).strip():
            raise ValueError('benchmark inputs or implementation changed')
        return dict(status=result['status'], paths=names, patch_sha256=sha(patch), scores=rows,
                    accepted=bool(rows and result['status']=='passed' and
                                  all(sandbox_verified(row) and row['exit_code']==0 for row in rows)),
                    result=result, provider_error=provider_http_error(result.get('error')), ledger=capture.snapshot())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        return dict(status='execution_error', accepted=False, error=error_evidence(exc),
                    result=result, ledger=capture.snapshot())


async def evaluate(selected, prepared, root, model, key, jobs, plan):
    provider = DeepSeekProvider(dict(base_url=DEEPSEEK_URL, model=model, api_key=key, timeout_s=85, trust_env=False))
    sem = asyncio.Semaphore(jobs)
    rows = {}
    payment_blocked = asyncio.Event()

    async def one(case, mode):
        name = case['id']
        async with sem:
            if payment_blocked.is_set():
                result = dict(status='provider_blocked', accepted=False, provider_error='provider_http_402')
            else:
                result = await arm(case, prepared[name], mode, root/name/mode, provider, plan['witness'])
                if result.get('provider_error') == 'provider_http_402':
                    payment_blocked.set()
            rows[(name, mode)] = dict(id=name, mode=mode, **result)
            save(root/'progress.json', dict(completed=len(rows), planned=2*len(selected), rows=list(rows.values())))
            print(name, mode, result['status'], result['accepted'], flush=True)

    await asyncio.gather(*(one(case, mode) for i, case in enumerate(selected) for mode in
                           (('proposal', 'agentic') if i % 2 == 0 else ('agentic', 'proposal'))))
    save(root/'report.json', plan | dict(rows=list(rows.values()),
        provider_blocked=payment_blocked.is_set(), passed={mode: sum(
            row['accepted'] for row in rows.values() if row['mode']==mode) for mode in ('proposal','agentic')}),
        immutable=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight-only', action='store_true')
    parser.add_argument('--case', action='append')
    parser.add_argument('--jobs', type=int, choices=(1, 2, 3), default=3)
    parser.add_argument('--model', default='deepseek-v4-pro')
    parser.add_argument('--boltons', type=Path, default=APP/'output/repo-agent-boltons')
    parser.add_argument('--toolz', type=Path, default=APP/'output/repo-agent-toolz')
    args = parser.parse_args()
    selected = [case for case in CASES if not args.case or case['id'] in args.case]
    if not selected or (args.case and set(args.case) != {case['id'] for case in selected}):
        parser.error('unknown issue case')
    boundary = SandboxRuntime().resolve()
    if not boundary:
        parser.error('strict Windows runtime required')
    os.environ.update(CLAWOS_REQUIRE_OS_SANDBOX='1', CLAWOS_APPCONTAINER_PROFILE=boundary.profile_name,
                      CLAWOS_APPCONTAINER_RUNTIME=str(boundary.runtime_dir))
    root = APP/'output'/('rp-'+uuid.uuid4().hex[:8])
    root.mkdir()
    print(root, flush=True)
    prepared, checks = asyncio.run(preflight(selected, root, args))
    if not all(check['verified'] for check in checks.values()):
        return 2
    if args.preflight_only:
        return 0
    if not sys.stdin.isatty():
        parser.error('interactive hidden key input required')
    key = getpass.getpass('DeepSeek API key (hidden): ').strip()
    if not key:
        parser.error('DeepSeek API key required')
    witness = {str(path): sha(path.read_bytes()) for path in (
        Path(__file__).resolve(), APP/'benchmarks/coding_repository_v1.py', APP/'services/agentic_coding_loop_service.py',
        APP/'services/autonomous_coding_service.py', APP/'services/coding_workflow_service.py',
        APP/'services/coding_comparison_service.py', APP/'services/coding_execution_context.py',
        APP/'services/coding_structured_output.py', APP/'services/coding_context_service.py',
        APP/'services/coding_diagnostics_service.py', APP/'services/coding_workspace_service.py',
        APP/'services/coding_working_memory.py',
        APP/'providers/deepseek.py', APP/'providers/openai_compatible.py',
    )}
    plan = dict(model=args.model, limits=LIMITS, witness=witness, cases=[dict(id=c['id'], project=c['project'], fix=c['fix'],
        **{k:v for k,v in prepared[c['id']].items() if k not in {'source','reference','allowed'}}) for c in selected])
    save(root/'plan.json', plan, immutable=True)
    asyncio.run(evaluate(selected, prepared, root, args.model, key, args.jobs, plan))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
