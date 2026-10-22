"""Owned native supervisor/tree death, fresh-process cleanup and app startup."""
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
from services.sandbox_runtime import SandboxRuntime,sandbox_storage
from services.sandbox_supervisor import ProcessIdentity,run_supervised,cleanup_lease
from services.appcontainer_process import GitControlSeal,dacl_policy
from services.windows_appcontainer_boundary import WindowsAppContainerBoundary
from services.coding_workspace_service import CodingWorkspaceService


def until(fn,seconds=60):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=fn()
        if value:return value
        time.sleep(.05)
    raise TimeoutError('owned probe condition did not complete')


def terminate_verified(identity):
    if identity.pid==os.getpid():raise ValueError('probe must never terminate its own orchestrator')
    k=identity.k
    handle=k.OpenProcess(0x100000|0x1000|1,False,identity.pid)
    if not handle:raise OSError(c.get_last_error(),'cannot open owned probe process')
    try:
        values=[w.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(handle,*[c.byref(value) for value in values]):raise OSError(c.get_last_error(),'owned identity unavailable')
        if ((values[0].dwHighDateTime<<32)|values[0].dwLowDateTime)!=identity.creation:raise ValueError('owned PID changed')
        k.TerminateProcess.argtypes=[w.HANDLE,w.UINT];k.TerminateProcess.restype=w.BOOL
        if not k.TerminateProcess(handle,77):raise OSError(c.get_last_error(),'owned termination failed')
        if k.WaitForSingleObject(handle,10000)!=0:raise RuntimeError('owned process did not exit')
    finally:k.CloseHandle(handle)


def process_identity(pid,creation=None):
    identity=ProcessIdentity(pid,creation);identity.pid=pid
    return identity


def find_command(root,caller_pid,workspace):
    for request in root.glob('*/request.json'):
        path=request.with_name('state.json')
        if path.exists():
            state=json.loads(path.read_text())
            if state.get('owner_pid')==caller_pid and state.get('workspace')==str(workspace) and state.get('child_pid') and not state.get('cleaned'):
                return request,state


def witness():
    names=['services/'+name+'.py' for name in ('sandbox_recovery','sandbox_supervisor','appcontainer_process','windows_appcontainer_boundary','sandbox_runtime','file_transactions','coding_workspace_service')]
    names+=['scripts/probe_sandbox_restart.py','scripts/sandbox_runtime.py','clawos_server.py']
    return {name:hashlib.sha256((BASE/name).read_bytes()).hexdigest() for name in names}


def application_restart(root,env):
    import httpx
    config=root/'app-config.json'
    config.write_text(json.dumps(dict(model_provider=dict(provider='qwen',base_url='http://127.0.0.1:18949/v1',model='offline-qa',api_key='',requires_api_key=False),mtclaw=dict(enabled=False),vector_store=dict(provider='lightweight',embedding_provider='hash'))))
    data=root/'app-data';data.mkdir()
    app_env=dict(env,CLAWOS_SKIP_LOCAL_ENV='1',CLAWOS_CONFIG_PATH=str(config),CLAWOS_DATA_DIR=str(data),CLAWOS_MEMORY_DB=str(data/'memory.db'),FEISHU_LIVE='false')
    code="import sys,threading,uvicorn;import clawos_server;s=uvicorn.Server(uvicorn.Config(clawos_server.app,host='127.0.0.1',port=18946,log_level='info'));threading.Thread(target=lambda:(sys.stdin.readline(),setattr(s,'should_exit',True)),daemon=True).start();s.run()"
    with httpx.Client(base_url='http://127.0.0.1:18946',trust_env=False,timeout=5) as client:
        try:client.get('/health');raise RuntimeError('QA port occupied; refusing to start')
        except httpx.ConnectError:pass
        with (root/'app.log').open('wb') as log:
            process=subprocess.Popen([sys.executable,'-u','-c',code],cwd=BASE,env=app_env,stdin=subprocess.PIPE,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                def healthy():
                    if process.poll() is not None:raise RuntimeError('owned app exited during startup')
                    try:
                        response=client.get('/health');response.raise_for_status();value=response.json()
                        return value if value.get('core_ready') else None
                    except httpx.HTTPError:return None
                state=until(healthy,80)
            finally:
                if process.poll() is None:
                    process.stdin.write(b'shutdown\n');process.stdin.flush();process.wait(timeout=25)
                process.stdin.close()
            if process.returncode:raise RuntimeError('owned app failed graceful shutdown')
        try:client.get('/health');raise RuntimeError('owned app port remained open')
        except httpx.ConnectError:pass
    return dict(core_ready=state['core_ready'],release=state['release'],port_closed=True)


def main():
    if os.name!='nt':raise RuntimeError('Windows native probe required')
    root=BASE/'output'/'sandbox-restart'/uuid.uuid4().hex[:12];root.mkdir(parents=True)
    os.environ['CLAWOS_OUTPUT_DIR']=str(root/'artifacts')
    manager=SandboxRuntime();identities=[];callers=[];commands=[]
    report=dict(root=str(root),passed=False,checks={},source=witness(),model_calls=0,physical_power_loss_verified=False)
    env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','LOCALAPPDATA','APPDATA','USERPROFILE','TEMP','TMP','PATH','PATHEXT'}}
    env.update(CLAWOS_OUTPUT_DIR=str(root/'artifacts'),CLAWOS_SKIP_LOCAL_ENV='1',FEISHU_LIVE='false')
    try:
        setup=manager.prepare(confirmed=True);runtime=manager.resolve().runtime_dir
        report['checks']['owned_runtime_integrity']=setup['integrity_verified']
        seed=root/'seed';seed.mkdir();(seed/'base.py').write_text('value=1\n')
        def git(*args):subprocess.run(['git',*args],cwd=seed,check=True,capture_output=True)
        git('init','-q');git('add','.')
        git('-c','user.name=Acceptance','-c','user.email=acceptance@localhost','-c','commit.gpgsign=false','commit','-qm','Owned restart baseline')
        meta=CodingWorkspaceService().create_task(seed,root/'tasks','restart',confirmed=True)
        workspace=Path(meta['workspace']);pointer=workspace/'.git'
        with GitControlSeal(pointer) as sealed:original=sealed.snapshot(pointer)
        driver=root/'caller.py'
        driver.write_text("import sys,json\nfrom pathlib import Path\nsys.path.insert(0,"+repr(str(BASE))+")\nfrom services.sandbox_supervisor import run_supervised\nprint(json.dumps(run_supervised(['python','hold.py'],Path(sys.argv[1]),Path(sys.argv[2]),90)),flush=True)\n",encoding='utf-8')
        for phase in ('supervisor','tree'):
            marker=workspace/('started-'+phase)
            (workspace/'hold.py').write_text("from pathlib import Path\nimport time\nPath("+repr(marker.name)+").write_text('started')\nwhile True:\n Path('tick').write_text(str(time.monotonic()))\n time.sleep(.05)\n",encoding='utf-8')
            with (root/(phase+'-caller.log')).open('wb') as log:
                caller=subprocess.Popen([sys._base_executable,'-E','-s','-S','-B',str(driver),str(workspace),str(runtime)],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                callers.append(caller);until(marker.exists)
                request,state=until(lambda:find_command(sandbox_storage()/'commands',caller.pid,workspace));commands.append(request.parent.name)
                owner=process_identity(state['owner_pid'],state['owner_creation']);supervisor=process_identity(state['supervisor_pid'],state['supervisor_creation']);child=process_identity(state['child_pid'],state['child_creation'])
                identities.extend([owner,supervisor,child])
                report[phase+'_identities']={key:dict(pid=value.pid,creation=value.creation) for key,value in [('owner',owner),('supervisor',supervisor),('child',child)]}
                report['checks'][phase+'_caller_identity_exact']=owner.pid==caller.pid
                report['checks'][phase+'_child_was_running']=not child.exited()
                other_temp=root/('other-temp-'+phase);other_temp.mkdir()
                lock_code="import sys;from pathlib import Path;sys.path.insert(0,"+repr(str(BASE))+");from services.sandbox_supervisor import host_lock\ntry:\n with host_lock(Path("+repr(str(workspace/'.clawos-supervisor'))+"),timeout=.15):print('incorrectly-acquired')\nexcept TimeoutError:print('blocked')\n"
                lock_test=subprocess.run([sys._base_executable,'-E','-s','-S','-c',lock_code],env=dict(env,TEMP=str(other_temp),TMP=str(other_temp)),capture_output=True,text=True,timeout=10)
                report['checks'][phase+'_cross_temp_lease_blocks']=lock_test.returncode==0 and lock_test.stdout.strip()=='blocked'
                terminate_verified(supervisor)
                if phase=='tree' and not owner.exited():terminate_verified(owner)
                caller.wait(timeout=15);until(child.exited,15)
                report['checks'][phase+'_all_owned_processes_exited']=all(value.exited() for value in (owner,supervisor,child))
                report['checks'][phase+'_no_forged_success']=not request.with_name('result.json').exists()
                try:
                    with cleanup_lease(workspace):raise AssertionError('unknown cleanup was reused')
                except RuntimeError:report['checks'][phase+'_quarantine_before_recovery']=True
            if phase=='supervisor':
                result=subprocess.run([sys._base_executable,str(BASE/'scripts/sandbox_runtime.py'),'recover','--command-id',request.parent.name,'--confirmed'],env=env,capture_output=True,text=True,timeout=90)
                (root/'manual-recovery.log').write_text(result.stdout+result.stderr)
                if result.returncode:raise RuntimeError('fresh CLI recovery failed; inspect manual-recovery.log')
                # Inject loss of the final publication after real ACL/profile cleanup.
                # Preserve the owned original receipt rather than deleting evidence.
                if root.resolve() not in request.resolve().parents:raise ValueError('probe journal escaped owned root')
                request.with_name('result.json').rename(request.with_name('receipt-before-publication-loss.json'))
                retry=subprocess.run([sys._base_executable,str(BASE/'scripts/sandbox_runtime.py'),'recover','--command-id',request.parent.name,'--confirmed'],env=env,capture_output=True,text=True,timeout=90)
                (root/'publication-retry.log').write_text(retry.stdout+retry.stderr)
                report['checks']['lost_publication_retry']=retry.returncode==0 and json.loads(retry.stdout).get('cleanup_verified') is True
                again=subprocess.run([sys._base_executable,str(BASE/'scripts/sandbox_runtime.py'),'recover','--command-id',request.parent.name,'--confirmed'],env=env,capture_output=True,text=True,timeout=30)
                report['checks']['fresh_cli_idempotent']=again.returncode==0 and json.loads(again.stdout).get('already_clean') is True
            else:report['app_restart']=application_restart(root,env)
            receipt=json.loads(request.with_name('result.json').read_text())
            report['checks'][phase+'_cleanup_recovered']=receipt.get('cleanup_verified') is True and receipt.get('recovered') is True
            report['checks'][phase+'_execution_not_replayed']=receipt.get('execution_replayed') is False and 'result' not in receipt
            with GitControlSeal(pointer) as sealed:actual=sealed.snapshot(pointer)
            report['checks'][phase+'_git_policy_and_bytes_restored']=all(actual[k]==original[k] for k in ('device','inode','sha256')) and dacl_policy(actual['sddl'])==dacl_policy(original['sddl'])
            report['checks'][phase+'_profile_deleted']=not WindowsAppContainerBoundary(state['profile']).status()['installed']
            replay=run_supervised(['python','-c','print(42)'],workspace,runtime,15)
            report['checks'][phase+'_reuse_after_recovery']=replay['exit_code']==0 and replay['stdout'].strip()=='42' and replay['sandbox'].get('job_assigned_at_creation') is True
        report['checks']['actual_app_startup_recovery']=report['app_restart']['core_ready'] and report['app_restart']['port_closed']
        report['passed']=all(report['checks'].values())
    except Exception as exc:report['error']=type(exc).__name__+': '+str(exc)
    finally:
        for identity in reversed(identities):
            try:
                if not identity.exited():terminate_verified(identity)
            except Exception as exc:report.setdefault('cleanup_errors',[]).append(str(exc));report['passed']=False
            finally:identity.close()
        for caller in callers:
            if caller.poll() is None:
                caller.terminate()  # Popen retains the exact owned process handle.
                try:caller.wait(timeout=15)
                except subprocess.TimeoutExpired:report.setdefault('cleanup_errors',[]).append('owned caller did not exit');report['passed']=False
        # Keep failed command journals/profile grants for guarded recovery.
        if report['passed']:
            deployment=json.loads(manager.config.read_text())
            report['discovery_profile_cleanup']=WindowsAppContainerBoundary(deployment['profile']).uninstall(confirmed=True)
            report['passed']=report['passed'] and report['discovery_profile_cleanup']['deleted']
        report['source_stable']=report['source']==witness();report['passed']=report['passed'] and report['source_stable']
        (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(root=str(root),passed=report['passed'],checks=report['checks'],error=report.get('error'))))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
