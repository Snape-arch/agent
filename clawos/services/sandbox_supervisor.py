"""Host-owned supervisor retains cleanup ownership when its caller exits."""
from __future__ import annotations
import ctypes as c
from contextlib import contextmanager
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = 'services'
from .appcontainer_process import safe_tree, validate_python_command
from .file_transactions import _file_lock, write_text
from .sandbox_runtime import sandbox_storage


class ProcessIdentity:
    """A kept Windows process handle plus creation time prevents PID reuse."""
    def __init__(self, pid, creation=None):
        if os.name != 'nt': raise RuntimeError('Windows process identity required')
        self.k = c.WinDLL('kernel32', use_last_error=True)
        self.k.OpenProcess.argtypes = [w.DWORD,w.BOOL,w.DWORD]; self.k.OpenProcess.restype = w.HANDLE
        self.k.GetProcessTimes.argtypes = [w.HANDLE,*([c.POINTER(w.FILETIME)]*4)]
        self.k.WaitForSingleObject.argtypes = [w.HANDLE,w.DWORD]; self.k.WaitForSingleObject.restype = w.DWORD
        self.k.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.k.OpenProcess(0x100000 | 0x1000, False, int(pid))
        if not self.handle: raise OSError(c.get_last_error(), 'cannot verify caller identity')
        times = [w.FILETIME() for _ in range(4)]
        try:
            if not self.k.GetProcessTimes(self.handle, *[c.byref(value) for value in times]):
                raise OSError(c.get_last_error(), 'caller creation time unavailable')
            self.creation = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            if creation is not None and self.creation != creation: raise ValueError('caller identity changed')
        except BaseException: self.close(); raise

    def exited(self):
        result = self.k.WaitForSingleObject(self.handle, 0)
        if result not in (0,258): raise OSError(c.get_last_error(), 'caller wait failed')
        return result == 0

    def close(self):
        if self.handle: self.k.CloseHandle(self.handle); self.handle = None


def save(path, data):
    write_text(path, json.dumps(data, ensure_ascii=False, sort_keys=True))


def host_lock(target, timeout=10):
    # Supervisor TEMP is intentionally private. Locks must not depend on TEMP.
    folder=sandbox_storage()/'locks'
    parent=Path(target).absolute().parent
    if folder==parent or folder in parent.parents or parent in folder.parents:
        raise ValueError('host locks must remain outside the leased tree')
    folder.mkdir(parents=True,exist_ok=True);safe_tree(folder)
    return _file_lock(target,timeout=timeout,lock_dir=folder)


def unresolved(root, workspace):
    for request in root.glob('*/request.json'):
        try:
            data = json.loads(request.read_text(encoding='utf-8'))
            if data['workspace'] != str(workspace): continue
            result = request.with_name('result.json')
            receipt = json.loads(result.read_text(encoding='utf-8')) if result.exists() else {}
            if not receipt.get('cleanup_verified') or receipt.get('request_digest') != hashlib.sha256(request.read_bytes()).hexdigest():
                raise RuntimeError('workspace has an unresolved supervisor receipt; quarantine remains')
        except (ValueError,KeyError,TypeError,OSError) as exc:
            raise RuntimeError('invalid supervisor journal; quarantine remains') from exc


def run_supervised(command, workspace, runtime, timeout):
    validate_python_command(command)
    workspace, runtime = safe_tree(workspace), safe_tree(runtime)
    if workspace == runtime or workspace in runtime.parents or runtime in workspace.parents:
        raise ValueError('runtime must be separate from writable workspace')
    if (workspace/'.git').is_dir(): raise ValueError('strict execution requires a Git worktree pointer')
    root = sandbox_storage() / 'commands'; root.mkdir(parents=True, exist_ok=True); safe_tree(root)
    if any(control==p or control in p.parents or p in control.parents
           for control in (root,sandbox_storage()/'locks') for p in (workspace,runtime)):
        raise ValueError('supervisor receipts must be outside sandbox workspace/runtime')
    with host_lock(workspace/'.clawos-supervisor',timeout=10):
        safe_tree(workspace)
        unresolved(root,workspace)
        owner = ProcessIdentity(os.getpid())
        try: creation = owner.creation
        finally: owner.close()
        folder = root / uuid.uuid4().hex; folder.mkdir()
        request = dict(schema='clawos.sandbox-command.v2', owner_pid=os.getpid(), owner_creation=creation,
                       command_profile='ClawOS.Exec.'+folder.name,
                       workspace=str(workspace), runtime=str(runtime), command=command,
                       timeout=max(.1,min(float(timeout),900)))
        save(folder/'request.json',request)
    env = {key:os.environ[key] for key in ('SYSTEMROOT','LOCALAPPDATA') if key in os.environ}
    env.update(TEMP=str(folder),TMP=str(folder),CLAWOS_OUTPUT_DIR=str(root.parent.parent))
    with (folder/'host.log').open('wb') as log:
        process = subprocess.Popen([sys.executable,'-E','-s','-S','-B',str(Path(__file__).resolve()),
                                    str(folder/'request.json')],env=env,stdin=subprocess.DEVNULL,
                                   stdout=log,stderr=log,close_fds=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try: process.wait(timeout=request['timeout']+180)
        except BaseException:
            (folder/'abort').touch()
            # Do not kill the supervisor that owns the seal and cleanup lock.
            try: process.wait(timeout=120)
            except subprocess.TimeoutExpired: pass
            raise
    receipt = folder/'result.json'
    if process.returncode != 0 or not receipt.is_file():
        raise RuntimeError('supervisor failed; workspace quarantined: '+str(folder))
    data = json.loads(receipt.read_text(encoding='utf-8'))
    if not data.get('cleanup_verified') or data.get('request_digest') != hashlib.sha256((folder/'request.json').read_bytes()).hexdigest():
        raise RuntimeError('supervisor receipt invalid; workspace quarantined')
    if data.get('error'): raise RuntimeError(data['error'])
    result = data['result']
    result['sandbox'].update(supervised=True, supervisor_receipt=str(receipt), caller_exit_cleanup_supported=True)
    return result


@contextmanager
def cleanup_lease(workspace):
    workspace = Path(workspace).absolute()
    with host_lock(workspace/'.clawos-supervisor',timeout=2):
        unresolved(sandbox_storage()/'commands',workspace)
        yield


def serve(request_path):
    request_path = Path(request_path).absolute(); folder = request_path.parent
    safe_tree(folder)
    request = json.loads(request_path.read_text(encoding='utf-8'))
    if request.get('schema') != 'clawos.sandbox-command.v2': raise ValueError('invalid host request')
    if request.get('command_profile') != 'ClawOS.Exec.'+folder.name:raise ValueError('command profile not bound to host request')
    workspace, runtime = safe_tree(Path(request['workspace'])), safe_tree(Path(request['runtime']))
    if any(folder == p or folder in p.parents or p in folder.parents for p in (workspace,runtime)):
        raise ValueError('host request overlaps guest grants')
    receipt = dict(request_digest=hashlib.sha256(request_path.read_bytes()).hexdigest(),
                   supervisor_pid=os.getpid(), cleanup_verified=False)
    cancel, stop = threading.Event(), threading.Event()
    owner = None
    try:
        owner = ProcessIdentity(request['owner_pid'],request['owner_creation'])
        def monitor():
            while not stop.wait(.1):
                try:
                    if owner.exited() or (folder/'abort').exists(): cancel.set(); return
                except OSError: cancel.set(); return
        watcher = threading.Thread(target=monitor,daemon=True); watcher.start()
        if owner.exited(): cancel.set()
        from .windows_appcontainer_boundary import WindowsAppContainerBoundary
        supervisor = ProcessIdentity(os.getpid())
        try:supervisor_creation = supervisor.creation
        finally:supervisor.close()
        state = dict(schema='clawos.sandbox-recovery.v1', request_digest=receipt['request_digest'],
                     supervisor_pid=os.getpid(),supervisor_creation=supervisor_creation,
                     owner_pid=request['owner_pid'],owner_creation=request['owner_creation'])
        def journal(value):
            state.update(value)
            save(folder/'state.json',state)
        with host_lock(workspace/'.clawos-supervisor', timeout=10):
            result = WindowsAppContainerBoundary(runtime_dir=runtime)._run_owned_command(
                request['command'], workspace, timeout_seconds=request['timeout'], confirmed_acl=True,
                cancelled=cancel, journal=journal, command_profile=request['command_profile'])
            receipt.update(result=result,cleanup_verified=True,caller_exited=owner.exited())
    except BaseException as exc:
        receipt['error'] = type(exc).__name__+': '+str(exc)
        state = folder/'state.json'
        if state.exists(): receipt['cleanup_verified'] = json.loads(state.read_text(encoding='utf-8')).get('cleaned') is True
    finally:
        stop.set()
        if owner:
            if 'watcher' in locals(): watcher.join(2)
            owner.close()
        save(folder/'result.json',receipt)
    return 0


if __name__ == '__main__': raise SystemExit(serve(sys.argv[1]))
