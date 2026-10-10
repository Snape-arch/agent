"""Synthetic canaries only: no real credentials, external hosts, or firewall changes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import uuid


PROBE_CODE = r'''
import json, os, pathlib, socket, subprocess, sys
cfg = json.loads(sys.argv[1]); result = {}
def deny(key, fn):
    try:
        fn(); result[key] = False
    except PermissionError:
        result[key] = True
    except Exception as exc:
        result[key] = False; result[key + '_error'] = type(exc).__name__
inside = pathlib.Path('inside.txt'); inside.write_text('inside', encoding='utf-8')
result['workspace_read_write'] = inside.read_text(encoding='utf-8') == 'inside'
outside = pathlib.Path(cfg['outside']); runtime = pathlib.Path(cfg['runtime'])
deny('outside_read_denied', lambda: outside.read_text(encoding='utf-8'))
deny('outside_write_denied', lambda: outside.write_text('escape', encoding='utf-8'))
deny('all_apps_read_denied', lambda: pathlib.Path(cfg['all_apps']).read_text(encoding='utf-8'))
result['runtime_read_allowed'] = runtime.read_text(encoding='utf-8') == 'runtime'
deny('runtime_write_denied', lambda: runtime.write_text('escape', encoding='utf-8'))
result['secret_environment_removed'] = 'CLAWOS_SANDBOX_TEST_SECRET' not in os.environ
pointer = pathlib.Path('.git')
deny('git_pointer_write_denied', lambda: pointer.write_text('escape', encoding='utf-8'))
deny('git_pointer_delete_denied', lambda: pointer.unlink())
deny('git_pointer_rename_denied', lambda: pointer.rename('moved-git'))
# Try to remove its DACL; sharing protection must hold even if ACL mutation succeeds.
import ctypes
from ctypes import wintypes
advapi = ctypes.WinDLL('advapi32')
advapi.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
advapi.SetNamedSecurityInfoW.restype = wintypes.DWORD
result['git_acl_change_code'] = advapi.SetNamedSecurityInfoW(str(pointer.absolute()),1,4,None,None,None,None)
deny('git_pointer_after_acl_denied', lambda: pointer.write_text('escape', encoding='utf-8'))
for host, port, family, kind, key in cfg['sockets']:
    sock = None
    try:
        sock = socket.socket(family, kind); sock.settimeout(1)
        if kind == socket.SOCK_STREAM:
            sock.connect((host, port))
        else:
            sock.sendto(b'canary', (host, port))
        result[key] = False
    except OSError as exc:
        result[key] = getattr(exc, 'winerror', None) == 10013
        result[key + '_winerror'] = getattr(exc, 'winerror', None)
    finally:
        if sock: sock.close()
try:
    child = subprocess.run([sys.executable, '-E', '-s', '-S', '-c', 'print(1)'], capture_output=True, timeout=3)
    result['child_spawn_denied'] = False
except OSError as exc:
    result['child_spawn_denied'] = exc.winerror in (5, 1816)
    result['child_spawn_winerror'] = exc.winerror
print(json.dumps(result))
'''


def fingerprint():
    names = ('appcontainer_process.py', 'windows_appcontainer_boundary.py',
             'strict_sandbox_acceptance.py', 'coding_workflow_service.py', 'os_sandbox.py')
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in names}


def probe_boundary(boundary, workspace: Path, *, confirmed_acl=False):
    if confirmed_acl is not True:
        raise PermissionError('confirmed=true required for owned probe workspace')
    if boundary.runtime_dir is None:
        raise ValueError('private runtime required')
    initial, root, nonce = fingerprint(), workspace.resolve(), uuid.uuid4().hex
    outside, all_apps = root.parent / ('protected-' + nonce), root.parent / ('all-apps-' + nonce)
    runtime = boundary.runtime_dir.resolve() / ('canary-' + nonce)
    outside.write_text('protected', encoding='utf-8'); all_apps.write_text('all-apps', encoding='utf-8')
    runtime.write_text('runtime', encoding='utf-8')
    pointer = root / '.git'
    if pointer.exists():
        raise ValueError('probe requires a fresh directory without existing Git control data')
    pointer.write_text('gitdir: synthetic-control\n', encoding='utf-8')
    sockets, specs, positive = [], [], {}
    try:
        acl = subprocess.run(['icacls', str(all_apps), '/grant', '*S-1-15-2-1:RX'], capture_output=True, timeout=30)
        if acl.returncode:
            raise RuntimeError('ALL_APPLICATION_PACKAGES synthetic control grant failed')
        for host, family, label in (('127.0.0.1', socket.AF_INET, 'ipv4'), ('::1', socket.AF_INET6, 'ipv6')):
            for kind, transport in ((socket.SOCK_STREAM, 'tcp'), (socket.SOCK_DGRAM, 'udp')):
                receiver = socket.socket(family, kind); sockets.append(receiver)
                receiver.bind((host, 0)); receiver.settimeout(2)
                port = receiver.getsockname()[1]
                if kind == socket.SOCK_STREAM:
                    receiver.listen(4)
                with socket.socket(family, kind) as control:
                    control.settimeout(2)
                    if kind == socket.SOCK_STREAM:
                        control.connect((host, port)); client, _ = receiver.accept(); client.close()
                    else:
                        control.sendto(b'positive', (host, port)); receiver.recvfrom(32)
                key = label + '_' + transport + '_denied'
                positive[key] = True; specs.append([host, port, family, kind, key])
        positive['protected_read_write'] = outside.read_text(encoding='utf-8') == 'protected'
        outside.write_text('protected', encoding='utf-8')
        pointer.write_text('gitdir: synthetic-control\n', encoding='utf-8')
        positive['git_pointer_write'] = pointer.read_text(encoding='utf-8') == 'gitdir: synthetic-control\n'
        positive['all_apps_read'] = all_apps.read_text(encoding='utf-8') == 'all-apps'
        # Establish that the copied runtime and normal process launch work without the boundary.
        normal = subprocess.run([str(boundary.runtime_dir / 'python.exe'), '-E', '-s', '-S', '-c', 'print(1)'],
            capture_output=True, timeout=15)
        positive['normal_runtime_launch'] = normal.returncode == 0 and normal.stdout.strip() == b'1'
        cfg = dict(outside=str(outside), all_apps=str(all_apps), runtime=str(runtime), sockets=specs)
        result = boundary.run_command(['python', '-c', PROBE_CODE, json.dumps(cfg)], root,
            timeout_seconds=20, confirmed_acl=True)
        try:
            details = json.loads(result.get('stdout', '').strip())
        except (ValueError, TypeError):
            details = {}
        expected = ['workspace_read_write', 'outside_read_denied', 'outside_write_denied',
            'all_apps_read_denied', 'runtime_read_allowed', 'runtime_write_denied',
            'secret_environment_removed', 'child_spawn_denied', 'git_pointer_write_denied',
            'git_pointer_delete_denied', 'git_pointer_rename_denied', 'git_pointer_after_acl_denied'] + [s[-1] for s in specs]
        checks = {key: details.get(key) is True for key in expected}
        checks.update(parent_positive_controls=all(positive.values()),
            outside_unchanged=outside.read_text(encoding='utf-8') == 'protected',
            runtime_unchanged=runtime.read_text(encoding='utf-8') == 'runtime',
            parent_token_verified=result.get('sandbox', {}).get('parent_token_verified') is True,
            git_pointer_sealed=result.get('sandbox', {}).get('git_control_pointer_sealed') is True,
            git_pointer_unchanged=pointer.read_text(encoding='utf-8') == 'gitdir: synthetic-control\n',
            probe_exit_success=result.get('exit_code') == 0)
        timeout = boundary.run_command(['python', '-c', 'import time; time.sleep(60)'], root,
            timeout_seconds=.5, confirmed_acl=True)
        overflow = boundary.run_command(['python', '-c', 'import os; [os.write(1,b"x"*8192) for _ in range(400)]'], root,
            timeout_seconds=10, confirmed_acl=True)
        checks.update(timeout_terminated=timeout.get('timed_out') is True and timeout['exit_code'] == 124,
            output_overflow_terminated=overflow.get('output_limit_exceeded') is True and overflow['exit_code'] == 125,
            implementation_stable=initial == fingerprint())
        return {'schema': 'clawos.strict-sandbox-acceptance.v1', 'passed': all(checks.values()),
            'checks': checks, 'positive_controls': positive, 'probe': details, 'execution': result,
            'timeout': timeout, 'overflow': {k: v for k, v in overflow.items() if k not in ('stdout', 'stderr')},
            'source_fingerprints': initial, 'production_sandbox_ready': False,
            'scope': 'Windows LPAC / Python stdlib / one process / synthetic local canaries; not production certification'}
    finally:
        for sock in sockets: sock.close()
        for path in (outside, all_apps, runtime, root / 'inside.txt', pointer, root/'moved-git'):
            path.unlink(missing_ok=True)
