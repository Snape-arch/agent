"""Only disposable profiles, runtimes and canaries; never alters firewall."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from services.windows_appcontainer_boundary import WindowsAppContainerBoundary
from services.strict_sandbox_acceptance import fingerprint


def prepare_runtime(destination):
    destination.mkdir(parents=True, exist_ok=False)
    source = Path(getattr(sys, '_base_executable', sys.executable)).parent
    for pattern in ('python.exe', '*.dll', 'LICENSE*'):
        for path in source.glob(pattern):
            if path.is_file(): shutil.copy2(path, destination / path.name)
    for name in ('DLLs', 'Lib'):
        shutil.copytree(source / name, destination / name,
            ignore=shutil.ignore_patterns('site-packages', '__pycache__', 'test', 'tests', '*.pyc'))
    (destination / '.clawos-private-runtime.json').write_text(json.dumps({'copied': True,
        'source_interpreter': str(source / 'python.exe'), 'dependencies': 'stdlib only'}), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=BASE / 'output' / 'strict-sandbox')
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to((BASE / 'output').resolve())
    root = output / uuid.uuid4().hex[:12]; root.mkdir(parents=True, exist_ok=False)
    runtime, workspace = root / 'runtime', root / 'workspace'
    workspace.mkdir()
    boundary = WindowsAppContainerBoundary('ClawOS.Probe.' + uuid.uuid4().hex, runtime_dir=runtime)
    report = {'root': str(root), 'source_fingerprints': fingerprint(), 'passed': False}
    created, sid = False, None
    try:
        prepare_runtime(runtime)
        installed = boundary.install(confirmed=True); created = installed['created']; sid = installed.get('sid')
        if not created: raise RuntimeError('refusing to reuse or delete an existing profile')
        report['installation'] = installed
        report['runtime_grant'] = boundary.grant_runtime(confirmed=True)
        os.environ['CLAWOS_SANDBOX_TEST_SECRET'] = 'synthetic-canary-only'
        report['acceptance'] = boundary.probe(workspace, confirmed_acl=True)
        report['passed'] = report['acceptance']['passed']
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        os.environ.pop('CLAWOS_SANDBOX_TEST_SECRET', None)
        cleanup = []
        if sid and created:
            for path in (workspace, runtime):
                result = subprocess.run(['icacls', str(path), '/remove:g', '*' + sid, '/T', '/Q'],
                    capture_output=True, timeout=60)
                cleanup.append({'path': str(path), 'exit_code': result.returncode})
            try:
                report['profile_cleanup'] = boundary.uninstall(confirmed=True)
            except Exception as exc:
                report['cleanup_error'] = f'{type(exc).__name__}: {exc}'
                report['passed'] = False
        report['acl_cleanup'] = cleanup
        if any(item['exit_code'] != 0 for item in cleanup): report['passed'] = False
        report['source_stable'] = report['source_fingerprints'] == fingerprint()
        report['passed'] = report['passed'] and report['source_stable']
        (root / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'root': str(root), 'passed': report['passed'], 'error': report.get('error'),
        'checks': report.get('acceptance', {}).get('checks'), 'cleanup': report.get('profile_cleanup')}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
