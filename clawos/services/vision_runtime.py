"""Owned ClawVision process. Separate storage, minimal environment, no model startup."""
import atexit
import ctypes
import json
import os
from pathlib import Path
import secrets
import signal
import site
import subprocess
import sys
import threading
import time
import uuid


SOURCE_ROOT=Path(__file__).resolve().parents[2]/'integrations/clawvision'
EXTRA_LIBS=Path(__file__).resolve().parents[1]/'output/vision-libs'


class ChildGroup:
    def __init__(self,process):
        self.process=process;self.handle=None
        if os.name=='nt':
            from ctypes import wintypes as w
            from services.os_sandbox import WindowsJobSandbox
            self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            k=self.kernel;k.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];k.CreateJobObjectW.restype=w.HANDLE
            k.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD];k.SetInformationJobObject.restype=w.BOOL
            k.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE];k.AssignProcessToJobObject.restype=w.BOOL
            k.CloseHandle.argtypes=[w.HANDLE];k.CloseHandle.restype=w.BOOL
            self.handle=k.CreateJobObjectW(None,None)
            if not self.handle: raise OSError('vision child group creation failed')
            info=WindowsJobSandbox._structures()['extended']();info.BasicLimitInformation.LimitFlags=0x2000
            if not k.SetInformationJobObject(self.handle,9,ctypes.byref(info),ctypes.sizeof(info)) or not k.AssignProcessToJobObject(self.handle,w.HANDLE(int(process._handle))):
                self.close();raise OSError('vision child group assignment failed')
    def close(self):
        if self.handle: self.kernel.CloseHandle(self.handle);self.handle=None
        elif os.name!='nt' and self.process.poll() is None:
            try: os.killpg(self.process.pid,signal.SIGTERM)
            except ProcessLookupError: pass


class VisionRuntime:
    def __init__(self,data_dir,source_root=SOURCE_ROOT):
        self.root=Path(data_dir).resolve();self.source=Path(source_root).resolve()
        self.process=None;self.group=None;self.port=None;self.secret=None;self.log=None;self.error=''
        self.lock=threading.RLock();atexit.register(self.close)
    def status(self):
        with self.lock:
            running=bool(self.process and self.process.poll() is None and self.port)
            if self.process and self.process.poll() is not None: self._dispose()
            return dict(running=running,state='running' if running else 'stopped',error=self.error,
                source_available=(self.source/'serve_clawos.py').is_file(),scope='local_owner_only',
                storage='isolated_vision_store',model_loaded_automatically=False)
    def _dispose(self):
        if self.group:self.group.close()
        if self.log:self.log.close()
        self.process=self.group=self.port=self.secret=self.log=None
    def start(self):
        with self.lock:
            if self.status()['running']:return self.status()
            if not (self.source/'serve_clawos.py').is_file():raise ValueError('ClawVision源码未随应用安装')
            self.root.mkdir(parents=True,exist_ok=True);session=uuid.uuid4().hex
            ready=self.root/('session-'+session+'.json');self.secret=secrets.token_urlsafe(48);self.error=''
            # Do not inherit model/provider keys, DATABASE_URL, user proxy or .env.
            env={k:os.environ[k] for k in ('SYSTEMROOT','WINDIR','PATH','TEMP','TMP','COMSPEC') if k in os.environ}
            env.update(PYTHONIOENCODING='utf-8',PYTHONUNBUFFERED='1',PYTHONNOUSERSITE='1',
                PYTHONPATH=os.pathsep.join([str(self.source/'sdk'),str(self.source/'runtime-libs'),str(EXTRA_LIBS),*site.getsitepackages()]),
                CLAWVISION_DATA_DIR=str(self.root/'data'),CLAWVISION_OBJECT_DIR=str(self.root/'objects'),
                CLAWVISION_AUTH_MODE='disabled',CLAWVISION_HOST='127.0.0.1',CLAWVISION_MAX_BODY_MB='32',CLAWVISION_MAX_CONCURRENCY='2')
            python=getattr(sys,'_base_executable',None) or sys.executable
            self.log=(self.root/('worker-'+session+'.log')).open('ab')
            try:
                self.process=subprocess.Popen([python,'-X','utf8',str(self.source/'serve_clawos.py'),'--ready',str(ready),'--session',session],
                    cwd=self.source,env=env,stdin=subprocess.PIPE,stdout=self.log,stderr=self.log,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt')
                self.group=ChildGroup(self.process)
                self.process.stdin.write((json.dumps(dict(gateway=self.secret))+'\n').encode());self.process.stdin.close()
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    if self.process.poll() is not None:raise RuntimeError('vision_worker_exited')
                    if ready.is_file():
                        value=json.loads(ready.read_text(encoding='utf-8'))
                        if value.get('pid')!=self.process.pid or value.get('session')!=session or type(value.get('port')) is not int or not 1024<=value['port']<=65535:
                            raise RuntimeError('vision_worker_identity_mismatch')
                        self.port=value['port'];return self.status()
                    time.sleep(.1)
                raise TimeoutError('vision_worker_start_timeout')
            except Exception as exc:
                self.error=type(exc).__name__
                if self.process and self.process.poll() is None:self.process.terminate();self.process.wait(timeout=5)
                self._dispose();raise RuntimeError('实验服务启动失败：'+self.error) from None
    def endpoint(self):
        with self.lock:
            if not self.status()['running']:raise LookupError('实验服务尚未启动')
            return f'http://127.0.0.1:{self.port}',self.secret
    def close(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                try:
                    import urllib.request
                    req=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/__clawos_shutdown',data=b'{}',headers={'X-ClawOS-Vision-Gateway':self.secret or ''})
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=2):pass
                    self.process.wait(timeout=4)
                except Exception:self.process.terminate()
                try:self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=3)
            self._dispose()
            return self.status()
