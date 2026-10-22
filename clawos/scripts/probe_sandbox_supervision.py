"""Actual caller termination, integrity failure and quarantine; owned files only."""
from __future__ import annotations
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from services.coding_workspace_service import CodingWorkspaceService
from services.coding_workflow_service import CodingWorkflowService
from services.sandbox_runtime import SandboxRuntime, sandbox_storage
from services.sandbox_supervisor import ProcessIdentity
from services.windows_appcontainer_boundary import WindowsAppContainerBoundary
from services.strict_sandbox_acceptance import fingerprint


def git(repo,*args):
    return subprocess.run(['git',*args],cwd=repo,capture_output=True,check=True,timeout=30)


def file_security(path):
    advapi=c.WinDLL('advapi32',use_last_error=True)
    advapi.GetFileSecurityW.argtypes=[w.LPCWSTR,w.DWORD,c.c_void_p,w.DWORD,c.POINTER(w.DWORD)]
    size=w.DWORD();advapi.GetFileSecurityW(str(path),4,None,0,c.byref(size))
    storage=c.create_string_buffer(size.value)
    if not advapi.GetFileSecurityW(str(path),4,storage,size.value,c.byref(size)):
        raise OSError(c.get_last_error(),'Git DACL read failed')
    return storage.raw[:size.value]


def until(fn,seconds=30):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=fn()
        if value:return value
        time.sleep(.05)
    raise TimeoutError('owned acceptance state did not arrive')


def main():
    if os.name!='nt':raise RuntimeError('Windows native acceptance required')
    root=BASE/'output'/'supervision'/uuid.uuid4().hex[:12];root.mkdir(parents=True)
    os.environ['CLAWOS_OUTPUT_DIR']=str(root/'artifacts')
    os.environ['CLAWOS_REQUIRE_OS_SANDBOX']='1'
    os.environ.pop('CLAWOS_APPCONTAINER_RUNTIME',None);os.environ.pop('CLAWOS_APPCONTAINER_PROFILE',None)
    report=dict(root=str(root),source_fingerprints=fingerprint(),passed=False,checks={})
    manager=SandboxRuntime();created=False;parent=None;identity=None
    try:
        setup_results=[];setup_processes=[]
        setup_env={key:os.environ[key] for key in ('SYSTEMROOT','LOCALAPPDATA','CLAWOS_OUTPUT_DIR') if key in os.environ}
        for index in range(2):
            log=(root/('setup-'+str(index)+'.log')).open('wb')
            process=subprocess.Popen([sys.executable,str(BASE/'scripts/sandbox_runtime.py'),'setup','--confirmed'],
                env=setup_env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            setup_processes.append((process,log,index))
        for process,log,index in setup_processes:
            process.wait(timeout=45);log.close()
            if process.returncode:raise RuntimeError('concurrent setup failed: '+str(root/('setup-'+str(index)+'.log')))
            setup_results.append(json.loads((root/('setup-'+str(index)+'.log')).read_text(encoding='utf-8')))
        setup=next(value for value in setup_results if value['created']);created=True;report['setup']=setup
        report['checks']['concurrent_setup_one_deployment']=sum(bool(value['created']) for value in setup_results)==1 and len({value['profile'] for value in setup_results})==1
        report['checks']['default_deployment_verified']=setup['configured'] and setup['integrity_verified']
        seed=root/'seed';seed.mkdir();(seed/'sample.py').write_text('value=1\n')
        git(seed,'init','-q');git(seed,'add','.')
        git(seed,'-c','user.name=Acceptance','-c','user.email=acceptance@localhost',
            '-c','commit.gpgsign=false','commit','-qm','Owned supervision baseline')
        meta=CodingWorkspaceService().create_task(seed,root/'tasks','caller-termination',confirmed=True)
        workspace=Path(meta['workspace']);pointer=workspace/'.git'
        original=pointer.read_bytes();original_acl=file_security(pointer)
        host_root=str(sandbox_storage()/'commands')
        (workspace/'hold.py').write_text("from pathlib import Path\nimport time,json\nchecks={}\n"
            +"for name,action in [('read',lambda:list(Path("+repr(host_root)+").iterdir())),('write',lambda:(Path("+repr(host_root)+")/'guest-forged-receipt').write_text('forged'))]:\n"
            +"    try:action();checks[name]=False\n    except PermissionError:checks[name]=True\n"
            +"Path('host-access.json').write_text(json.dumps(checks))\nPath('started').write_text('running')\nwhile True:\n    Path('tick').write_text(str(time.monotonic()))\n    time.sleep(.05)\n",encoding='utf-8')
        driver=root/'caller.py'
        driver.write_text("import sys,json\nfrom pathlib import Path\nsys.path.insert(0,"+repr(str(BASE))+")\nfrom services.coding_workflow_service import CodingWorkflowService\nprint(json.dumps(CodingWorkflowService._run_command(Path(sys.argv[1]),['python','-B','hold.py'],60)),flush=True)\n",encoding='utf-8')
        env={key:os.environ[key] for key in ('SYSTEMROOT','LOCALAPPDATA','CLAWOS_OUTPUT_DIR','CLAWOS_REQUIRE_OS_SANDBOX') if key in os.environ}
        with (root/'caller.log').open('wb') as log:
            parent=subprocess.Popen([sys.executable,'-E','-s','-S','-B',str(driver),str(workspace)],env=env,
                stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            parent_identity=ProcessIdentity(parent.pid)
            report['caller_identity']=dict(pid=parent.pid,creation=parent_identity.creation)
            parent_identity.close()
            until(lambda:(workspace/'started').exists(),60)
            access=json.loads((workspace/'host-access.json').read_text())
            report['checks']['guest_host_receipt_read_denied']=access['read']
            report['checks']['guest_host_receipt_write_denied']=access['write']
            request=until(lambda:next((sandbox_storage()/'commands').glob('*/request.json'),None))
            state=until(lambda:json.loads(request.with_name('state.json').read_text(encoding='utf-8')) if request.with_name('state.json').exists() else None)
            identity=ProcessIdentity(state['child_pid'])
            report['child_identity']=dict(pid=state['child_pid'],creation=identity.creation)
            before=(workspace/'tick').read_text();time.sleep(.15)
            report['checks']['guest_actually_running']=before!=(workspace/'tick').read_text()
            try:
                CodingWorkspaceService().remove(seed,workspace,confirmed=True)
                report['checks']['active_workspace_removal_blocked']=False
            except (RuntimeError,TimeoutError):
                report['checks']['active_workspace_removal_blocked']=workspace.exists()
            parent.terminate();parent.wait(timeout=10)
            receipt=until(lambda:json.loads(request.with_name('result.json').read_text(encoding='utf-8')) if request.with_name('result.json').exists() else None)
            report['termination_receipt']=receipt
            report['checks']['child_terminated']=identity.exited()
            report['checks']['caller_exit_detected']=receipt.get('caller_exited') is True
            report['checks']['cleanup_verified']=receipt.get('cleanup_verified') is True
            report['checks']['cancel_exit_130']=receipt.get('result',{}).get('exit_code')==130
            report['checks']['git_bytes_and_dacl_restored']=pointer.read_bytes()==original and file_security(pointer)==original_acl
            report['checks']['command_profile_deleted']=not WindowsAppContainerBoundary(state['profile']).status()['installed']
        replay=CodingWorkflowService._run_command(workspace,['python','-c','print(42)'],10)
        report['replay']=replay
        report['checks']['workspace_reusable_after_cleanup']=replay['exit_code']==0 and replay['stdout'].strip()=='42' and replay['sandbox'].get('supervised') is True
        # A damaged private runtime must fail closed through the actual workflow.
        runtime=manager.resolve().runtime_dir;exe=runtime/'python.exe';saved=exe.read_bytes()
        try:
            exe.write_bytes(saved+b'canary')
            refused=CodingWorkflowService._run_command(workspace,['python','-c','print(42)'],10)
            report['checks']['runtime_tamper_refused']=refused['exit_code']==126 and 'integrity' in refused['stderr']
        finally:exe.write_bytes(saved)
        # Unknown supervisor state prevents actual workflow reuse, even with an intact runtime.
        orphan=sandbox_storage()/'commands'/'synthetic-unresolved';orphan.mkdir()
        (orphan/'request.json').write_text(json.dumps(dict(workspace=str(workspace))),encoding='utf-8')
        refused=CodingWorkflowService._run_command(workspace,['python','-c','print(42)'],10)
        report['checks']['unresolved_receipt_quarantines']=refused['exit_code']==126 and 'quarantine' in refused['stderr']
        report['passed']=all(report['checks'].values())
    except Exception as exc:report['error']=type(exc).__name__+': '+str(exc)
    finally:
        if parent is not None and parent.poll() is None:
            parent.terminate();parent.wait(timeout=10)
        if identity:identity.close()
        if created:
            data=json.loads(manager.config.read_text(encoding='utf-8'))
            report['deployment_cleanup']=WindowsAppContainerBoundary(data['profile']).uninstall(confirmed=True)
            report['passed']=report['passed'] and report['deployment_cleanup']['deleted']
        report['source_stable']=report['source_fingerprints']==fingerprint()
        report['passed']=report['passed'] and report['source_stable']
        (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(root=str(root),passed=report['passed'],checks=report['checks'],error=report.get('error')),ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
