"""Recover only host-journaled, dead v2 command owners; never replay execution."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from .appcontainer_process import GitControlSeal, safe_tree
from .sandbox_runtime import sandbox_storage
from .sandbox_supervisor import ProcessIdentity, save, host_lock


def dead(pid, creation):
    if type(pid) is not int or pid<=0 or type(creation) is not int or creation<=0:
        raise ValueError('process identity missing')
    try:identity=ProcessIdentity(pid,creation)
    except ValueError:return True  # PID reused: the original process is gone. Never kill it.
    except OSError as exc:
        if exc.errno==87:return True  # ERROR_INVALID_PARAMETER: no such process
        raise  # access denied/unknown is not proof of exit
    try:return identity.exited()
    finally:identity.close()


def load_plan(folder):
    safe_tree(folder)
    request_path=folder/'request.json';state_path=folder/'state.json'
    for path in (request_path,state_path):
        if path.stat().st_size>1024*1024:raise ValueError('oversized host recovery journal')
    request=json.loads(request_path.read_text(encoding='utf-8'))
    state=json.loads(state_path.read_text(encoding='utf-8'))
    digest=hashlib.sha256(request_path.read_bytes()).hexdigest()
    if not re.fullmatch('[0-9a-f]{32}',folder.name) or request.get('schema')!='clawos.sandbox-command.v2':
        raise ValueError('legacy/unknown request; quarantine remains')
    if state.get('schema')!='clawos.sandbox-recovery.v1' or state.get('request_digest')!=digest:
        raise ValueError('recovery journal is not bound to request')
    profile='ClawOS.Exec.'+folder.name
    if request.get('command_profile')!=profile or state.get('profile')!=profile or state.get('profile_absent_verified') is not True or state.get('job_assigned_at_creation') is not True:
        raise ValueError('fresh profile/creation Job intent is not proven')
    for key in ('owner_pid','owner_creation','workspace','runtime'):
        if state.get(key)!=request.get(key):raise ValueError('recovery identity mismatch: '+key)
    workspace,runtime=Path(request['workspace']),Path(request['runtime'])
    if not workspace.is_absolute() or not runtime.is_absolute():raise ValueError('absolute recovery roots required')
    for path,identity in ((workspace,state.get('workspace_identity')),(runtime,state.get('runtime_identity'))):
        safe_tree(path);info=path.stat()
        if identity!=[info.st_dev,info.st_ino]:raise ValueError('recovery directory identity changed')
    for path in (workspace,runtime):
        for control in (folder,sandbox_storage()/'locks'):
            if control==path or control in path.parents or path in control.parents:raise ValueError('host journal or locks overlap guest roots')
    if workspace==runtime or workspace in runtime.parents or runtime in workspace.parents:raise ValueError('guest roots overlap')
    saved=state.get('git_control')
    if not isinstance(saved,dict) or type(saved.get('exists')) is not bool:raise ValueError('Git snapshot missing')
    if saved['exists'] and (not isinstance(saved.get('sddl'),str) or len(saved['sddl'])>65536 or not re.fullmatch('[0-9a-f]{64}',saved.get('sha256',''))):
        raise ValueError('Git snapshot malformed')
    return request,state,digest


def recover_command(command_id, *, confirmed=False):
    if confirmed is not True:raise PermissionError('confirmed=true required for host cleanup recovery')
    if os.name!='nt':raise RuntimeError('Windows recovery required')
    if not re.fullmatch('[0-9a-f]{32}',str(command_id)):raise ValueError('exact command ID required')
    folder=sandbox_storage()/'commands'/command_id
    # Lock before reading intent. The workspace lease serializes cleanup/reuse.
    with host_lock(folder/'recovery-lock',timeout=10):
        request,state,digest=load_plan(folder)
        with host_lock(Path(request['workspace'])/'.clawos-supervisor',timeout=2):
            request,state,digest=load_plan(folder)
            for key in ('owner','supervisor','child'):
                if key=='child' and 'child_pid' not in state:continue
                if not dead(state.get(key+'_pid'),state.get(key+'_creation')):
                    raise RuntimeError(key+' is still alive; quarantine remains')
            receipt=folder/'result.json'
            if receipt.exists():
                result=json.loads(receipt.read_text(encoding='utf-8'))
                if result.get('cleanup_verified') is True and result.get('request_digest')==digest:
                    return dict(ok=True,command_id=command_id,already_clean=True,execution_replayed=False)
            from .windows_appcontainer_boundary import WindowsAppContainerBoundary
            boundary=WindowsAppContainerBoundary(state['profile'],runtime_dir=request['runtime'])
            status=boundary.status();sid=status.get('sid')
            if not sid or (state.get('sid') and state['sid']!=sid):raise ValueError('owned profile SID cannot be verified')
            # Prevalidate pointer before mutating any ACL or deleting a profile.
            control=Path(request['workspace'])/'.git'
            with GitControlSeal(control) as sealed:
                current=sealed.snapshot(control);saved=state['git_control']
                if saved['exists']:
                    if any(current.get(k)!=saved.get(k) for k in ('exists','device','inode','sha256')):
                        raise ValueError('Git pointer changed; quarantine remains')
                elif current!=saved:raise ValueError('Git pointer appeared; quarantine remains')
            save(folder/'recovery.json',dict(request_digest=digest,phase='cleaning',cleanup_verified=False))
            for path in (request['workspace'],request['runtime']):
                result=subprocess.run(['icacls',path,'/remove:g','*'+sid,'/T','/Q'],capture_output=True,timeout=60)
                if result.returncode:raise RuntimeError('recovery ACL revocation failed; quarantine remains')
            GitControlSeal.restore_snapshot(control,state['git_control'])
            if status.get('installed'):boundary.uninstall(confirmed=True)
            if boundary.status().get('installed'):raise RuntimeError('profile still installed; quarantine remains')
            result=dict(request_digest=digest,cleanup_verified=True,recovered=True,
                        recovery_kind='dead-command-cleanup',execution_replayed=False,
                        error='Interrupted command cleaned after restart; execution result unavailable',
                        supervisor_pid=state['supervisor_pid'])
            save(folder/'recovery.json',dict(result,phase='complete'))
            save(receipt,result)
            return dict(ok=True,command_id=command_id,cleanup_verified=True,execution_replayed=False)


def recover_pending():
    """Startup reconciliation: ambiguous/legacy/live records remain quarantined."""
    report=dict(recovered=[],blocked=[],active=[],production_sandbox_ready=False)
    for path in sorted((sandbox_storage()/'commands').glob('*/request.json')):
        try:
            data=json.loads(path.with_name('result.json').read_text(encoding='utf-8')) if path.with_name('result.json').exists() else {}
            if data.get('cleanup_verified') is True and data.get('request_digest')==hashlib.sha256(path.read_bytes()).hexdigest():continue
            request,state,_=load_plan(path.parent)
            if not dead(state['supervisor_pid'],state['supervisor_creation']) or not dead(state['owner_pid'],state['owner_creation']):
                report['active'].append(path.parent.name);continue
            report['recovered'].append(recover_command(path.parent.name,confirmed=True))
        except Exception as exc:
            report['blocked'].append(dict(command_id=path.parent.name,error=type(exc).__name__+': '+str(exc)))
    return report
