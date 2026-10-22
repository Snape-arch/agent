"""Parent-attested LPAC launcher. No shell, ambient handles, or child receipts."""
from __future__ import annotations

import ctypes as c
import hashlib
from ctypes import wintypes as w
import os
from pathlib import Path
import subprocess
import stat
import threading
import time

from .os_sandbox import WindowsJobSandbox


def dacl_policy(sddl):
    # Windows can set AUTO_INHERITED on restoration. Preserve exact ACEs and
    # protection/null-ACL semantics; only ignore these OS-maintained flags.
    head,separator,aces=sddl.partition('(')
    return head.replace('AI','').replace('AR','')+separator+aces


class GitControlSeal:
    """Hold a non-write/delete-shared pointer and restore its original DACL.

    Protects the host's subsequent Git calls even if guest code changes ACLs.
    Ordinary .git databases are rejected by the caller; they cannot be sealed
    with a single file handle.
    """
    def __init__(self, path):
        self.handle, self.descriptor, self.dacl = None, c.c_void_p(), c.c_void_p()
        self.restored = False
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.advapi = c.WinDLL('advapi32', use_last_error=True)
        if not path.exists():
            return
        if not path.is_file() or path.stat().st_size > 4096:
            raise ValueError('Git control must be a bounded ordinary pointer file')
        self.kernel.CreateFileW.argtypes = [w.LPCWSTR,w.DWORD,w.DWORD,c.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
        self.kernel.CreateFileW.restype = w.HANDLE
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.LocalFree.argtypes = [c.c_void_p]
        self.kernel.LocalFree.restype = c.c_void_p
        self.advapi.GetSecurityInfo.argtypes = [w.HANDLE,c.c_int,w.DWORD,c.c_void_p,c.c_void_p,
            c.POINTER(c.c_void_p),c.c_void_p,c.POINTER(c.c_void_p)]
        self.advapi.GetSecurityInfo.restype = w.DWORD
        self.advapi.GetSecurityDescriptorControl.argtypes = [c.c_void_p,c.POINTER(w.WORD),c.POINTER(w.DWORD)]
        self.advapi.GetSecurityDescriptorControl.restype = w.BOOL
        self.advapi.SetSecurityInfo.argtypes = [w.HANDLE,c.c_int,w.DWORD,c.c_void_p,c.c_void_p,c.c_void_p,c.c_void_p]
        self.advapi.SetSecurityInfo.restype = w.DWORD
        handle = self.kernel.CreateFileW(str(path), 0x80000000 | 0x40000, 1, None, 3, 0x200000, None)
        if not handle or handle == c.c_void_p(-1).value:
            raise OSError(c.get_last_error(), 'Git pointer seal failed')
        self.handle = handle
        try:
            code = self.advapi.GetSecurityInfo(handle,1,4,None,None,c.byref(self.dacl),None,c.byref(self.descriptor))
            if code: raise OSError(code,'Git pointer ACL snapshot failed')
            control, revision = w.WORD(), w.DWORD()
            if not self.advapi.GetSecurityDescriptorControl(self.descriptor,c.byref(control),c.byref(revision)):
                raise OSError(c.get_last_error(),'Git pointer ACL control query failed')
            self.protection = 0x80000000 if control.value & 0x1000 else 0x20000000
        except BaseException:
            self.close();raise

    def restore(self):
        if self.handle and not self.restored:
            code = self.advapi.SetSecurityInfo(self.handle,1,4 | self.protection,None,None,self.dacl,None)
            if code: raise OSError(code,'Git pointer ACL restore failed')
            self.restored = True

    def snapshot(self, path):
        """Host journal written before granting a fresh command SID any access."""
        if not self.handle:
            return {'exists': False}
        convert = self.advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW
        convert.argtypes = [c.c_void_p,w.DWORD,w.DWORD,c.POINTER(w.LPWSTR),c.POINTER(w.DWORD)]
        convert.restype = w.BOOL
        value = w.LPWSTR()
        if not convert(self.descriptor,1,4,c.byref(value),None):
            raise OSError(c.get_last_error(),'Git DACL serialization failed')
        try:
            info = path.stat()
            return dict(exists=True,device=info.st_dev,inode=info.st_ino,
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),sddl=value.value)
        finally:self.kernel.LocalFree(c.cast(value,c.c_void_p))

    @classmethod
    def restore_snapshot(cls, path, saved):
        if saved == {'exists': False}:
            if path.exists():raise ValueError('Git pointer appeared after journal snapshot')
            return
        with cls(path) as sealed:
            current = sealed.snapshot(path)
            if not current.get('exists') or any(current.get(k)!=saved.get(k) for k in ('device','inode','sha256')):
                raise ValueError('Git pointer identity or bytes changed; quarantine remains')
            convert = sealed.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
            convert.argtypes = [w.LPCWSTR,w.DWORD,c.POINTER(c.c_void_p),c.POINTER(w.DWORD)]
            convert.restype = w.BOOL
            descriptor,dacl = c.c_void_p(),c.c_void_p()
            if not convert(saved['sddl'],1,c.byref(descriptor),None):
                raise OSError(c.get_last_error(),'Saved Git DACL is invalid')
            try:
                # Use the saved descriptor's protection, never the interrupted DACL's.
                get_acl = sealed.advapi.GetSecurityDescriptorDacl
                get_acl.argtypes = [c.c_void_p,c.POINTER(w.BOOL),c.POINTER(c.c_void_p),c.POINTER(w.BOOL)]
                get_acl.restype = w.BOOL
                present,defaulted,control,revision = w.BOOL(),w.BOOL(),w.WORD(),w.DWORD()
                if not get_acl(descriptor,c.byref(present),c.byref(dacl),c.byref(defaulted)) or not present.value:
                    raise ValueError('Saved Git DACL is missing')
                if not sealed.advapi.GetSecurityDescriptorControl(descriptor,c.byref(control),c.byref(revision)):
                    raise OSError(c.get_last_error(),'Saved Git DACL control unavailable')
                protection = 0x80000000 if control.value & 0x1000 else 0x20000000
                code = sealed.advapi.SetSecurityInfo(sealed.handle,1,4|protection,None,None,dacl,None)
                if code:raise OSError(code,'Saved Git DACL restore failed')
                sealed.restored = True
            finally:sealed.kernel.LocalFree(descriptor)
        with cls(path) as verified:
            actual=verified.snapshot(path)
            if any(actual.get(k)!=saved.get(k) for k in ('exists','device','inode','sha256')) or dacl_policy(actual['sddl'])!=dacl_policy(saved['sddl']):
                raise RuntimeError('Restored Git DACL verification failed')

    def close(self):
        if self.descriptor:
            self.kernel.LocalFree(self.descriptor);self.descriptor = c.c_void_p()
        if self.handle:
            self.kernel.CloseHandle(self.handle);self.handle = None

    def __enter__(self): return self

    def __exit__(self, kind, value, traceback):
        try: self.restore()
        finally: self.close()


def safe_tree(path: Path) -> Path:
    """ACL grants must not follow junctions, symlinks or external hard links."""
    path = Path(os.path.abspath(path))
    for item in [path, *path.parents]:
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('reparse points are forbidden in sandbox paths')
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            info = (Path(root) / name).lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400 or (stat.S_ISREG(info.st_mode) and info.st_nlink > 1):
                raise ValueError('sandbox tree contains a reparse point or hard link')
    return path


def validate_python_command(command):
    if not isinstance(command, list) or not command or not all(isinstance(v, str) and '\0' not in v for v in command):
        raise ValueError('command must be a nonempty string argument list')
    if Path(command[0]).stem.lower() not in {'python', 'python3', 'python312'}:
        raise ValueError('strict runtime currently supports Python stdlib commands only')
    if any(x in command[1:] for x in ('-E', '-I', '-s', '-S')):
        raise ValueError('interpreter isolation flags are owned by the launcher')


def launch(boundary, command: list[str], cwd: Path, runtime: Path, timeout: float, *, cancelled=None, on_start=None):
    if os.name != 'nt':
        raise RuntimeError('LPAC requires Windows')
    validate_python_command(command)
    executable = runtime / 'python.exe'
    if not executable.is_file():
        raise ValueError('private Python runtime is missing')
    k, a = c.WinDLL('kernel32', use_last_error=True), c.WinDLL('advapi32', use_last_error=True)

    class SA(c.Structure):
        _fields_ = [('size', w.DWORD), ('descriptor', c.c_void_p), ('inherit', w.BOOL)]

    class SI(c.Structure):
        _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR),
            ('x', w.DWORD), ('y', w.DWORD), ('cx', w.DWORD), ('cy', w.DWORD),
            ('charsx', w.DWORD), ('charsy', w.DWORD), ('fill', w.DWORD), ('flags', w.DWORD),
            ('show', w.WORD), ('reserved2', w.WORD), ('bytes', c.c_void_p),
            ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]

    class SIX(c.Structure):
        _fields_ = [('si', SI), ('attributes', c.c_void_p)]

    class PI(c.Structure):
        _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]

    class CAPS(c.Structure):
        _fields_ = [('sid', c.c_void_p), ('groups', c.c_void_p), ('count', w.DWORD), ('reserved', w.DWORD)]

    class SIDATTR(c.Structure):
        _fields_ = [('sid', c.c_void_p), ('attributes', w.DWORD)]

    class GROUPS(c.Structure):
        _fields_ = [('count', w.DWORD), ('groups', SIDATTR * 1)]

    signatures = {
        'CreatePipe': ([c.POINTER(w.HANDLE), c.POINTER(w.HANDLE), c.POINTER(SA), w.DWORD], w.BOOL),
        'SetHandleInformation': ([w.HANDLE, w.DWORD, w.DWORD], w.BOOL),
        'InitializeProcThreadAttributeList': ([c.c_void_p, w.DWORD, w.DWORD, c.POINTER(c.c_size_t)], w.BOOL),
        'UpdateProcThreadAttribute': ([c.c_void_p, w.DWORD, c.c_size_t, c.c_void_p, c.c_size_t, c.c_void_p, c.c_void_p], w.BOOL),
        'DeleteProcThreadAttributeList': ([c.c_void_p], None),
        'CreateProcessW': ([w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p, w.BOOL, w.DWORD, c.c_void_p, w.LPCWSTR, c.POINTER(SI), c.POINTER(PI)], w.BOOL),
        'CreateJobObjectW': ([c.c_void_p, w.LPCWSTR], w.HANDLE),
        'SetInformationJobObject': ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL),
        'AssignProcessToJobObject': ([w.HANDLE, w.HANDLE], w.BOOL),
        'TerminateJobObject': ([w.HANDLE, w.UINT], w.BOOL),
        'TerminateProcess': ([w.HANDLE, w.UINT], w.BOOL),
        'ResumeThread': ([w.HANDLE], w.DWORD),
        'WaitForSingleObject': ([w.HANDLE, w.DWORD], w.DWORD),
        'GetExitCodeProcess': ([w.HANDLE, c.POINTER(w.DWORD)], w.BOOL),
        'ReadFile': ([w.HANDLE, c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.c_void_p], w.BOOL),
        'CloseHandle': ([w.HANDLE], w.BOOL),
    }
    for name, (args, result) in signatures.items():
        getattr(k, name).argtypes, getattr(k, name).restype = args, result
    a.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
    a.OpenProcessToken.restype = w.BOOL
    a.GetTokenInformation.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
    a.GetTokenInformation.restype = w.BOOL
    a.ConvertSidToStringSidW.argtypes = [c.c_void_p, c.POINTER(w.LPWSTR)]
    a.ConvertSidToStringSidW.restype = w.BOOL
    a.EqualSid.argtypes = [c.c_void_p, c.c_void_p]
    a.EqualSid.restype = w.BOOL
    derive = c.WinDLL('kernelbase', use_last_error=True).DeriveCapabilitySidsFromName
    derive.argtypes = [w.LPCWSTR, c.POINTER(c.POINTER(c.c_void_p)),
        c.POINTER(w.DWORD), c.POINTER(c.POINTER(c.c_void_p)), c.POINTER(w.DWORD)]
    derive.restype = w.BOOL

    def checked(ok, name):
        if not ok:
            raise OSError(c.get_last_error(), name + ' failed')

    handles, threads, streams = [], [], [bytearray(), bytearray()]
    count, overflow, output_lock = [0], threading.Event(), threading.Lock()
    job, pi, token, attributes, initialized = None, PI(), w.HANDLE(), None, False
    sid_text, sid_pointer = boundary._derive_sid()
    capability_groups, capability_sids = c.POINTER(c.c_void_p)(), c.POINTER(c.c_void_p)()
    group_count, capability_count = w.DWORD(), w.DWORD()
    started, assigned = time.perf_counter(), False
    try:
        pipes = []
        security = SA(c.sizeof(SA), None, True)
        # stdin is an EOF pipe. Only its read handle and the two output write handles are inherited.
        for _ in range(3):
            read, write = w.HANDLE(), w.HANDLE()
            checked(k.CreatePipe(c.byref(read), c.byref(write), c.byref(security), 0), 'CreatePipe')
            handles.extend([read.value, write.value]); pipes.append((read.value, write.value))
        for handle in (pipes[0][1], pipes[1][0], pipes[2][0]):
            checked(k.SetHandleInformation(handle, 1, 0), 'SetHandleInformation')
        inherited = (w.HANDLE * 3)(pipes[0][0], pipes[1][1], pipes[2][1])
        size = c.c_size_t()
        k.InitializeProcThreadAttributeList(None, 4, 0, c.byref(size))
        buffer = c.create_string_buffer(size.value)
        attributes = c.cast(buffer, c.c_void_p)
        checked(k.InitializeProcThreadAttributeList(attributes, 4, 0, c.byref(size)), 'InitializeProcThreadAttributeList')
        initialized = True
        checked(derive('registryRead', c.byref(capability_groups),
            c.byref(group_count), c.byref(capability_sids), c.byref(capability_count)), 'DeriveCapabilitySidsFromName')
        if capability_count.value != 1:
            raise RuntimeError('unexpected registryRead capability derivation')
        read_capability = SIDATTR(capability_sids[0], 4)
        capabilities, opt_out = CAPS(sid_pointer, c.cast(c.pointer(read_capability), c.c_void_p), 1, 0), w.DWORD(1)
        for identifier, value in ((0x20009, capabilities), (0x2000F, opt_out), (0x20002, inherited)):
            checked(k.UpdateProcThreadAttribute(attributes, 0, identifier, c.byref(value), c.sizeof(value), None, None), 'UpdateProcThreadAttribute')
        job = k.CreateJobObjectW(None, None)
        checked(job, 'CreateJobObjectW')
        limits = WindowsJobSandbox._structures()['extended']()
        limits.BasicLimitInformation.LimitFlags = 0x2000 | 8 | 0x100
        limits.BasicLimitInformation.ActiveProcessLimit = 1
        limits.ProcessMemoryLimit = 512 * 1024 * 1024
        checked(k.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits)), 'SetInformationJobObject')
        jobs = (w.HANDLE * 1)(job)
        checked(k.UpdateProcThreadAttribute(attributes,0,0x2000D,c.byref(jobs),c.sizeof(jobs),None,None), 'Assign Job at process creation')
        startup = SIX(); startup.si.cb = c.sizeof(startup); startup.si.flags = 0x100
        startup.si.stdin, startup.si.stdout, startup.si.stderr = inherited
        startup.attributes = attributes
        argv = [str(executable), '-E', '-s', '-S', '-B', '-X', 'utf8', *command[1:]]
        line = c.create_unicode_buffer(subprocess.list2cmdline(argv))
        env = {'SYSTEMROOT': os.environ.get('SYSTEMROOT', r'C:\Windows'), 'TEMP': str(cwd), 'TMP': str(cwd),
               'PATH': str(runtime), 'PYTHONIOENCODING': 'utf-8',
               'USERPROFILE': str(cwd), 'APPDATA': str(cwd), 'LOCALAPPDATA': str(cwd)}
        environment = c.create_unicode_buffer('\0'.join(f'{key}={value}' for key, value in sorted(env.items())) + '\0\0')
        checked(k.CreateProcessW(str(executable), line, None, None, True,
            0x80000 | 0x8000000 | 0x400 | 4, environment, str(cwd), c.byref(startup.si), c.byref(pi)), 'CreateProcessW')
        assigned = True  # JOB_LIST binds the child before CreateProcessW returns.
        checked(a.OpenProcessToken(pi.process, 8, c.byref(token)), 'OpenProcessToken')

        def information(kind):
            needed = w.DWORD()
            a.GetTokenInformation(token, kind, None, 0, c.byref(needed))
            storage = c.create_string_buffer(needed.value)
            checked(a.GetTokenInformation(token, kind, storage, needed.value, c.byref(needed)), 'GetTokenInformation')
            return storage

        if c.cast(information(29), c.POINTER(w.DWORD))[0] != 1:
            raise RuntimeError('child token is not AppContainer')
        token_capabilities = information(30)
        groups = c.cast(token_capabilities, c.POINTER(GROUPS)).contents
        if groups.count != 1 or not a.EqualSid(groups.groups[0].sid, capability_sids[0]):
            raise RuntimeError('child token has unexpected capabilities')
        package = information(31)
        actual_sid, sid_string = c.cast(package, c.POINTER(c.c_void_p))[0], w.LPWSTR()
        checked(a.ConvertSidToStringSidW(actual_sid, c.byref(sid_string)), 'ConvertSidToStringSidW')
        try:
            if sid_string.value != sid_text:
                raise RuntimeError('child AppContainer SID mismatch')
        finally:
            boundary._local_free(sid_string)
        # The process remains suspended until all parent-owned checks are complete.
        if on_start: on_start(pi.pid)
        for handle in (pipes[0][0], pipes[0][1], pipes[1][1], pipes[2][1]):
            k.CloseHandle(handle); handles.remove(handle)

        def drain(handle, index):
            data, read = c.create_string_buffer(8192), w.DWORD()
            while k.ReadFile(handle, data, len(data), c.byref(read), None) and read.value:
                chunk = data.raw[:read.value]
                with output_lock:
                    count[0] += len(chunk)
                    streams[index].extend(chunk)
                    del streams[index][:-16000]
                    if count[0] > 2 * 1024 * 1024:
                        overflow.set()
                        k.TerminateJobObject(job, 125)
        for index, pair in enumerate(pipes[1:]):
            thread = threading.Thread(target=drain, args=(pair[0], index), daemon=True)
            thread.start(); threads.append(thread)
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError('caller exited before child resume')
        if k.ResumeThread(pi.thread) == 0xFFFFFFFF:
            raise OSError(c.get_last_error(), 'ResumeThread failed')
        deadline, caller_cancelled = time.monotonic() + timeout, False
        while True:
            wait = k.WaitForSingleObject(pi.process, 100)
            if wait not in (0, 258): raise OSError(c.get_last_error(), 'WaitForSingleObject failed')
            if wait == 0: break
            if cancelled is not None and cancelled.is_set(): caller_cancelled=True; break
            if time.monotonic() >= deadline: break
        timed_out = wait == 258 and not caller_cancelled
        if caller_cancelled: checked(k.TerminateJobObject(job, 130), 'TerminateJobObject on caller exit')
        if timed_out:
            checked(k.TerminateJobObject(job, 124), 'TerminateJobObject')
        checked(k.WaitForSingleObject(pi.process, 10000) == 0, 'process termination')
        for thread in threads:
            thread.join(5)
        if any(t.is_alive() for t in threads):
            raise RuntimeError('output drain did not finish')
        exit_code = w.DWORD()
        checked(k.GetExitCodeProcess(pi.process, c.byref(exit_code)), 'GetExitCodeProcess')
        return {'command': command, 'exit_code': 125 if overflow.is_set() else (130 if caller_cancelled else (124 if timed_out else exit_code.value)),
            'stdout': streams[0].decode('utf-8', errors='replace')[-8000:],
            'stderr': streams[1].decode('utf-8', errors='replace')[-4000:],
            'timed_out': timed_out, 'caller_cancelled': caller_cancelled, 'output_limit_exceeded': overflow.is_set(), 'output_bytes': count[0],
            'duration_ms': round((time.perf_counter() - started) * 1000, 2),
            'sandbox': {'backend': 'windows-lpac-job', 'os_enforced': True, 'parent_token_verified': True,
                'profile_sid': sid_text, 'network_capabilities': [], 'capabilities': ['registryRead'], 'lpac_attribute_applied': True,
                'filesystem_isolated': True, 'network_isolated': True, 'direct_socket_non_bypass_enforced': True,
                'job_max_processes': 1, 'job_memory_mb': 512, 'inherited_handle_count': 3, 'job_assigned_at_creation': True,
                'strict_boundary_verified': True, 'production_sandbox_ready': False,
                'runtime': str(runtime), 'workspace': str(cwd)}}
    finally:
        if pi.process:
            if assigned:
                k.TerminateJobObject(job, 126)
            else:
                k.TerminateProcess(pi.process, 126)
            k.WaitForSingleObject(pi.process, 10000)
        for thread in threads:
            thread.join(5)
        for handle in [*handles, token.value, pi.thread, pi.process, job]:
            if handle:
                k.CloseHandle(handle)
        if initialized:
            k.DeleteProcThreadAttributeList(attributes)
        boundary._free_sid(sid_pointer)
        for array, size in ((capability_groups, group_count.value), (capability_sids, capability_count.value)):
            if array:
                for index in range(size): boundary._local_free(array[index])
                boundary._local_free(array)
