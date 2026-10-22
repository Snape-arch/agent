"""Operating-system execution backends with evidence-first probes."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any


class WindowsJobSandbox:
    """Constrain a child process with a Windows Job Object.

    This backend enforces process-count, process-memory, and kill-on-close
    limits. It intentionally does not claim filesystem or network isolation.
    """

    KILL_ON_JOB_CLOSE = 0x00002000
    ACTIVE_PROCESS = 0x00000008
    PROCESS_MEMORY = 0x00000100
    EXTENDED_LIMIT_INFORMATION = 9

    def __init__(
        self, *, max_processes: int = 1, process_memory_mb: int = 256
    ):
        self.max_processes = max(1, int(max_processes))
        self.process_memory_mb = max(32, int(process_memory_mb))

    @staticmethod
    def available() -> bool:
        return platform.system().lower() == "windows"

    def run_probe(
        self, workspace: str | Path, *, timeout_seconds: float = 15
    ) -> dict[str, Any]:
        if not self.available():
            return {
                "schema": "clawos.os-sandbox-probe.v1",
                "passed": False,
                "backend": "windows-job-object",
                "reason": "Windows backend is unavailable on this platform",
                "os_enforced": False,
            }
        workspace_path = Path(workspace).expanduser().resolve()
        if not workspace_path.is_dir():
            raise ValueError("workspace must be an existing directory")
        started = time.perf_counter()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        structures = self._structures()
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE, wintypes.HANDLE,
        ]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        process = None
        try:
            info = structures["extended"]()
            info.BasicLimitInformation.LimitFlags = (
                self.KILL_ON_JOB_CLOSE
                | self.ACTIVE_PROCESS
                | self.PROCESS_MEMORY
            )
            info.BasicLimitInformation.ActiveProcessLimit = self.max_processes
            info.ProcessMemoryLimit = self.process_memory_mb * 1024 * 1024
            if not kernel32.SetInformationJobObject(
                job, self.EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info), ctypes.sizeof(info),
            ):
                raise OSError(
                    ctypes.get_last_error(), "SetInformationJobObject failed"
                )
            script = (
                "import ctypes,json,os,subprocess,sys;"
                "input();"
                "k=ctypes.WinDLL('kernel32',use_last_error=True);"
                "k.GetCurrentProcess.restype=ctypes.c_void_p;"
                "k.IsProcessInJob.argtypes=[ctypes.c_void_p,ctypes.c_void_p,"
                "ctypes.POINTER(ctypes.c_int)];"
                "k.IsProcessInJob.restype=ctypes.c_int;"
                "flag=ctypes.c_int();"
                "ok=k.IsProcessInJob(k.GetCurrentProcess(),None,"
                "ctypes.byref(flag));err=ctypes.get_last_error();"
                "spawn='allowed';"
                "\ntry:\n subprocess.run([sys.executable,'-c','print(1)'],"
                "check=True,capture_output=True,timeout=3)\n"
                "except Exception as exc:\n spawn=type(exc).__name__\n"
                "print(json.dumps({'in_job':bool(ok and flag.value),"
                "'job_query_error':err,"
                "'spawn_result':spawn,'cwd':os.getcwd(),"
                "'secret_visible':'CLAWOS_SANDBOX_TEST_SECRET' in os.environ}))"
            )
            environment = {
                "PATH": os.environ.get("PATH", ""),
                "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                "TEMP": os.environ.get("TEMP", ""),
                "TMP": os.environ.get("TMP", ""),
                "PYTHONIOENCODING": "utf-8",
            }
            interpreter = str(
                getattr(sys, "_base_executable", "") or sys.executable
            )
            process = subprocess.Popen(
                [interpreter, "-c", script],
                cwd=workspace_path,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
            )
            if not kernel32.AssignProcessToJobObject(
                job, wintypes.HANDLE(int(process._handle))
            ):
                raise OSError(
                    ctypes.get_last_error(), "AssignProcessToJobObject failed"
                )
            stdout, stderr = process.communicate(
                "\n", timeout=max(1, float(timeout_seconds))
            )
            if not stdout.strip():
                return {
                    "schema": "clawos.os-sandbox-probe.v1",
                    "passed": False,
                    "backend": "windows-job-object",
                    "os_enforced": True,
                    "exit_code": process.returncode,
                    "reason": "sandbox child produced no probe payload",
                    "stderr": stderr[-2000:],
                    "production_sandbox_ready": False,
                }
            payload = json.loads(stdout.strip().splitlines()[-1])
            passed = bool(
                process.returncode == 0
                and payload.get("in_job")
                and payload.get("spawn_result") != "allowed"
                and not payload.get("secret_visible")
                and Path(payload.get("cwd", "")).resolve() == workspace_path
            )
            return {
                "schema": "clawos.os-sandbox-probe.v1",
                "passed": passed,
                "backend": "windows-job-object",
                "platform": platform.platform(),
                "os_enforced": bool(payload.get("in_job")),
                "resource_isolation": {
                    "active_process_limit": self.max_processes,
                    "process_memory_mb": self.process_memory_mb,
                    "nested_process_blocked": payload.get("spawn_result") != "allowed",
                    "kill_on_job_close": True,
                },
                "environment_isolation": {
                    "allowlisted_environment": True,
                    "secret_shaped_test_variable_absent": not payload.get(
                        "secret_visible"
                    ),
                },
                "filesystem_isolated": False,
                "network_isolated": False,
                "production_sandbox_ready": False,
                "exit_code": process.returncode,
                "stderr_digest": hashlib.sha256(stderr.encode()).hexdigest(),
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "truth_boundary": (
                    "Windows Job Objects enforce process and resource containment. "
                    "Filesystem ACL/AppContainer and network isolation are not "
                    "implemented or claimed by this probe."
                ),
            }
        finally:
            if process and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            kernel32.CloseHandle(job)

    def run(
        self,
        command: list[str],
        workspace: str | Path,
        *,
        input_text: str = "",
        environment: dict[str, str] | None = None,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Run a real worker inside a resource-constrained Windows Job Object."""
        if not self.available():
            raise RuntimeError("Windows Job Object backend is unavailable")
        workspace_path = Path(workspace).expanduser().resolve()
        if not workspace_path.is_dir():
            raise ValueError("workspace must be an existing directory")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
        structures = self._structures()
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
        ntdll.NtResumeProcess.restype = ctypes.c_long
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        process = None
        started = time.perf_counter()
        try:
            info = structures["extended"]()
            info.BasicLimitInformation.LimitFlags = self.KILL_ON_JOB_CLOSE | self.ACTIVE_PROCESS | self.PROCESS_MEMORY
            info.BasicLimitInformation.ActiveProcessLimit = self.max_processes
            info.ProcessMemoryLimit = self.process_memory_mb * 1024 * 1024
            if not kernel32.SetInformationJobObject(job, self.EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)):
                raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
            process = subprocess.Popen(
                command,
                cwd=workspace_path,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                creationflags=subprocess.CREATE_NO_WINDOW | 0x00000004,
            )
            if not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))):
                raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
            resume_status = ntdll.NtResumeProcess(wintypes.HANDLE(int(process._handle)))
            if resume_status != 0:
                raise OSError(int(resume_status), "NtResumeProcess failed")
            try:
                stdout, stderr = process.communicate(input_text, timeout=max(1, float(timeout_seconds)))
                timed_out = False
            except subprocess.TimeoutExpired:
                kernel32.TerminateJobObject(job, 124)
                stdout, stderr = process.communicate(timeout=5)
                timed_out = True
            return {
                "exit_code": 124 if timed_out else int(process.returncode or 0),
                "stdout": stdout,
                "stderr": stderr,
                "timed_out": timed_out,
                "sandbox": {
                    "backend": "windows-job-object",
                    "os_enforced": True,
                    "max_processes": self.max_processes,
                    "process_memory_mb": self.process_memory_mb,
                    "filesystem_isolated": False,
                    "network_isolated": False,
                },
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        finally:
            if process and process.poll() is None:
                kernel32.TerminateJobObject(job, 125)
                process.wait(timeout=5)
            kernel32.CloseHandle(job)

    @staticmethod
    def _structures() -> dict[str, Any]:
        ulong_ptr = ctypes.c_size_t

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ulong_ptr),
                ("MaximumWorkingSetSize", ulong_ptr),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ulong_ptr),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ulong_ptr),
                ("JobMemoryLimit", ulong_ptr),
                ("PeakProcessMemoryUsed", ulong_ptr),
                ("PeakJobMemoryUsed", ulong_ptr),
            ]

        return {"extended": EXTENDED_LIMIT_INFORMATION}


class WindowsRestrictedTokenSandbox:
    """Run one child with a restricted low-integrity primary token."""

    TOKEN_ALL_ACCESS = 0xF01FF
    DISABLE_MAX_PRIVILEGE = 0x1
    LUA_TOKEN = 0x4
    TOKEN_INTEGRITY_LEVEL = 25
    SE_GROUP_INTEGRITY = 0x20
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    WAIT_OBJECT_0 = 0

    @staticmethod
    def available() -> bool:
        return platform.system().lower() == "windows"

    def run_probe(
        self, workspace: str | Path, sandbox_root: str | Path,
        *, timeout_seconds: float = 20,
    ) -> dict[str, Any]:
        if not self.available():
            return {
                "schema": "clawos.restricted-token-probe.v1",
                "passed": False, "restricted_token": False,
                "reason": "Windows backend is unavailable",
            }
        workspace_path = Path(workspace).expanduser().resolve()
        root = Path(sandbox_root).expanduser().resolve()
        if not workspace_path.is_dir():
            raise ValueError("workspace must be an existing directory")
        try:
            root.relative_to(workspace_path)
        except ValueError as exc:
            raise ValueError("sandbox_root must be inside workspace") from exc
        root.mkdir(parents=True, exist_ok=True)
        label = subprocess.run(
            ["icacls", str(root), "/setintegritylevel", "(OI)(CI)L"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15,
        )
        if label.returncode != 0:
            return {
                "schema": "clawos.restricted-token-probe.v1",
                "passed": False, "restricted_token": False,
                "reason": "failed to label sandbox directory low integrity",
                "icacls_exit_code": label.returncode,
            }
        report_path = root / "restricted-token-report.json"
        inside_path = root / "inside-write.txt"
        outside_path = workspace_path / "restricted-token-escape.txt"
        for path in (report_path, inside_path):
            if path.exists():
                path.unlink()
        if outside_path.exists():
            outside_path.unlink()
        child = (
            "import ctypes,json,os,pathlib;"
            f"inside=pathlib.Path({str(inside_path)!r});"
            f"outside=pathlib.Path({str(outside_path)!r});"
            f"report=pathlib.Path({str(report_path)!r});"
            "inside_ok=outside_ok=False;"
            "\ntry:\n inside.write_text('inside',encoding='utf-8');inside_ok=True\n"
            "except Exception: pass\n"
            "try:\n outside.write_text('escape',encoding='utf-8');outside_ok=True\n"
            "except Exception: pass\n"
            "a=ctypes.WinDLL('advapi32',use_last_error=True);"
            "a.OpenProcessToken.argtypes=[ctypes.c_void_p,ctypes.c_uint32,"
            "ctypes.POINTER(ctypes.c_void_p)];"
            "a.IsTokenRestricted.argtypes=[ctypes.c_void_p];"
            "a.IsTokenRestricted.restype=ctypes.c_int;"
            "k=ctypes.WinDLL('kernel32');k.GetCurrentProcess.restype=ctypes.c_void_p;"
            "token=ctypes.c_void_p();"
            "a.OpenProcessToken(k.GetCurrentProcess(),8,ctypes.byref(token));"
            "restricted=bool(a.IsTokenRestricted(token));"
            "report.write_text(json.dumps({'inside_write':inside_ok,"
            "'outside_write':outside_ok,'restricted_token':restricted,"
            "'secret_visible':'CLAWOS_SANDBOX_TEST_SECRET' in os.environ}),"
            "encoding='utf-8')"
        )
        result = self._create_low_process(
            child, root, timeout_seconds=timeout_seconds
        )
        payload = {}
        if report_path.is_file():
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        escaped = outside_path.exists()
        if escaped:
            outside_path.unlink()
        appcontainer = self.appcontainer_capability()
        checks = {
            "restricted_token": bool(result.get("restricted_token_created")),
            "low_integrity_directory_write": bool(payload.get("inside_write")),
            "workspace_escape_blocked": not bool(payload.get("outside_write"))
            and not escaped,
            "secret_environment_removed": not bool(payload.get("secret_visible")),
            "child_exit_success": result.get("exit_code") == 0,
        }
        return {
            "schema": "clawos.restricted-token-probe.v1",
            "passed": all(checks.values()),
            "backend": "windows-restricted-token-low-integrity",
            "checks": checks,
            "restricted_token": bool(result.get("restricted_token_created")),
            "is_token_restricted_api": bool(payload.get("restricted_token")),
            "filesystem_write_isolated": checks["workspace_escape_blocked"],
            "sandbox_root": str(root),
            "appcontainer": appcontainer,
            "network_isolated": False,
            "production_sandbox_ready": bool(
                all(checks.values()) and appcontainer.get("enabled")
            ),
            **result,
            "truth_boundary": (
                "Restricted Token and low mandatory integrity enforce the tested "
                "write boundary. AppContainer remains disabled until an explicit "
                "installation/profile grant; network isolation is delegated to "
                "the authenticated egress proxy."
            ),
        }

    def run_command(
        self,
        command: list[str],
        workspace: str | Path,
        *,
        environment: dict[str, str] | None = None,
        timeout_seconds: float = 180,
    ) -> dict[str, Any]:
        """Execute an allowlisted command under a low-integrity token.

        The caller must provide a disposable task workspace.  The integrity
        label is intentionally applied to that worktree only so the restricted
        child can create caches and test outputs without gaining write access
        to the source repository.
        """

        if not self.available():
            raise RuntimeError("Windows restricted-token backend is unavailable")
        cwd = Path(workspace).expanduser().resolve()
        if not cwd.is_dir():
            raise ValueError("workspace must be an existing directory")
        if not command or any("\x00" in str(item) for item in command):
            raise ValueError("command must contain safe non-empty arguments")
        label = subprocess.run(
            ["icacls", str(cwd), "/setintegritylevel", "(OI)(CI)L"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        if label.returncode != 0:
            raise RuntimeError("failed to label task workspace low integrity")
        report_dir = cwd / ".clawos-sandbox"
        report_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["icacls", str(report_dir), "/setintegritylevel", "(OI)(CI)L"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15,
        )
        report_path = report_dir / f"command-{int(time.time() * 1000)}-{os.getpid()}.json"
        bounded_timeout = max(1, min(float(timeout_seconds or 180), 900.0))
        child = (
            "import json,pathlib,subprocess,time;"
            f"cmd={list(map(str, command))!r};"
            f"cwd={str(cwd)!r};report=pathlib.Path({str(report_path)!r});"
            f"limit={bounded_timeout!r};started=time.perf_counter();"
            "payload={};"
            "\ntry:\n"
            " r=subprocess.run(cmd,cwd=cwd,capture_output=True,text=True,"
            "encoding='utf-8',errors='replace',timeout=limit);"
            " payload={'exit_code':r.returncode,'stdout':r.stdout[-8000:],"
            "'stderr':r.stderr[-4000:],'timed_out':False}\n"
            "except subprocess.TimeoutExpired as exc:\n"
            " payload={'exit_code':124,'stdout':str(exc.stdout or '')[-8000:],"
            "'stderr':str(exc.stderr or '')[-4000:],'timed_out':True}\n"
            "payload['duration_ms']=round((time.perf_counter()-started)*1000,2);"
            "report.write_text(json.dumps(payload),encoding='utf-8')"
        )
        process = self._create_low_process(
            child, cwd, timeout_seconds=bounded_timeout + 10,
            environment=environment,
        )
        if not report_path.is_file():
            raise RuntimeError("restricted command did not produce a result")
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        report_path.unlink(missing_ok=True)
        try:
            report_dir.rmdir()
        except OSError:
            pass
        return {
            "command": list(map(str, command)),
            **payload,
            "sandbox": {
                "backend": "windows-restricted-token-low-integrity",
                "os_enforced": True,
                "restricted_token": bool(process.get("restricted_token_created")),
                "filesystem_write_boundary": "isolated-task-worktree-low-integrity",
                "network_proxy_required": True,
                "network_non_bypass_enforced": False,
                "production_sandbox_ready": False,
            },
        }

    @staticmethod
    def appcontainer_capability() -> dict[str, Any]:
        if platform.system().lower() != "windows":
            return {"api_available": False, "enabled": False}
        try:
            userenv = ctypes.WinDLL("userenv", use_last_error=True)
            available = all(hasattr(userenv, name) for name in (
                "CreateAppContainerProfile",
                "DeriveAppContainerSidFromAppContainerName",
                "DeleteAppContainerProfile",
            ))
        except OSError:
            available = False
        return {
            "api_available": available,
            "enabled": False,
            "requires_explicit_installation_grant": True,
        }

    def _create_low_process(
        self, script: str, cwd: Path, *, timeout_seconds: float,
        environment: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class SID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

        class TOKEN_MANDATORY_LABEL(ctypes.Structure):
            _fields_ = [("Label", SID_AND_ATTRIBUTES)]

        class STARTUPINFO(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
                ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
                ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                ("dwXCountChars", wintypes.DWORD),
                ("dwYCountChars", wintypes.DWORD),
                ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
                ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
                ("hStdError", wintypes.HANDLE),
            ]

        class PROCESS_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
            ]

        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        advapi.OpenProcessToken.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
        ]
        advapi.OpenProcessToken.restype = wintypes.BOOL
        advapi.CreateRestrictedToken.argtypes = [
            wintypes.HANDLE, wintypes.DWORD,
            wintypes.DWORD, ctypes.c_void_p,
            wintypes.DWORD, ctypes.c_void_p,
            wintypes.DWORD, ctypes.c_void_p,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        advapi.CreateRestrictedToken.restype = wintypes.BOOL
        advapi.IsTokenRestricted.argtypes = [wintypes.HANDLE]
        advapi.IsTokenRestricted.restype = wintypes.BOOL
        advapi.DuplicateTokenEx.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
            ctypes.c_int, ctypes.c_int, ctypes.POINTER(wintypes.HANDLE),
        ]
        advapi.DuplicateTokenEx.restype = wintypes.BOOL
        advapi.ConvertStringSidToSidW.argtypes = [
            wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi.ConvertStringSidToSidW.restype = wintypes.BOOL
        advapi.GetLengthSid.argtypes = [ctypes.c_void_p]
        advapi.GetLengthSid.restype = wintypes.DWORD
        advapi.SetTokenInformation.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ]
        advapi.SetTokenInformation.restype = wintypes.BOOL
        token = wintypes.HANDLE()
        restricted = wintypes.HANDLE()
        sid = ctypes.c_void_p()
        current = kernel32.GetCurrentProcess()
        if not advapi.OpenProcessToken(
            current, self.TOKEN_ALL_ACCESS, ctypes.byref(token)
        ):
            raise OSError(ctypes.get_last_error(), "OpenProcessToken failed")
        process_info = PROCESS_INFORMATION()
        try:
            source_token_already_restricted = bool(advapi.IsTokenRestricted(token))
            restriction_flags = 0
            if source_token_already_restricted:
                if not advapi.DuplicateTokenEx(
                    token, self.TOKEN_ALL_ACCESS, None,
                    2, 1, ctypes.byref(restricted),
                ):
                    raise OSError(
                        ctypes.get_last_error(), "DuplicateTokenEx failed"
                    )
            else:
                restriction_flags = self.DISABLE_MAX_PRIVILEGE | self.LUA_TOKEN
                if not advapi.CreateRestrictedToken(
                    token, restriction_flags,
                    0, None, 0, None, 0, None, ctypes.byref(restricted),
                ):
                    first_error = ctypes.get_last_error()
                    restricted = wintypes.HANDLE()
                    restriction_flags = self.DISABLE_MAX_PRIVILEGE
                    if not advapi.CreateRestrictedToken(
                        token, restriction_flags,
                        0, None, 0, None, 0, None, ctypes.byref(restricted),
                    ):
                        raise OSError(
                            ctypes.get_last_error() or first_error,
                            "CreateRestrictedToken failed",
                        )
            if not advapi.ConvertStringSidToSidW(
                "S-1-16-4096", ctypes.byref(sid)
            ):
                raise OSError(
                    ctypes.get_last_error(), "ConvertStringSidToSidW failed"
                )
            label = TOKEN_MANDATORY_LABEL(
                SID_AND_ATTRIBUTES(sid, self.SE_GROUP_INTEGRITY)
            )
            length = ctypes.sizeof(label) + advapi.GetLengthSid(sid)
            if not advapi.SetTokenInformation(
                restricted, self.TOKEN_INTEGRITY_LEVEL,
                ctypes.byref(label), length,
            ):
                raise OSError(
                    ctypes.get_last_error(), "SetTokenInformation failed"
                )
            interpreter = str(
                getattr(sys, "_base_executable", "") or sys.executable
            )
            command = ctypes.create_unicode_buffer(
                subprocess.list2cmdline([interpreter, "-c", script])
            )
            child_environment = {
                "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                "PATH": os.environ.get("PATH", ""),
                "TEMP": str(cwd), "TMP": str(cwd),
                "PYTHONIOENCODING": "utf-8",
            }
            for key, value in (environment or {}).items():
                normalized = str(key or "").strip()
                if normalized and "\0" not in normalized and "=" not in normalized:
                    child_environment[normalized] = str(value).replace("\0", "")
            environment_text = "".join(
                f"{key}={value}\0" for key, value in sorted(child_environment.items())
            ) + "\0"
            environment_buffer = ctypes.create_unicode_buffer(environment_text)
            startup = STARTUPINFO()
            startup.cb = ctypes.sizeof(startup)
            created = advapi.CreateProcessAsUserW(
                restricted, None, command, None, None, False,
                self.CREATE_UNICODE_ENVIRONMENT, environment_buffer,
                str(cwd), ctypes.byref(startup), ctypes.byref(process_info),
            )
            backend = "CreateProcessAsUserW"
            if not created:
                create_with_token = getattr(advapi, "CreateProcessWithTokenW")
                created = create_with_token(
                    restricted, 0, None, command,
                    self.CREATE_UNICODE_ENVIRONMENT, environment_buffer,
                    str(cwd), ctypes.byref(startup), ctypes.byref(process_info),
                )
                backend = "CreateProcessWithTokenW"
            if not created:
                raise OSError(
                    ctypes.get_last_error(), "restricted process creation failed"
                )
            wait = kernel32.WaitForSingleObject(
                process_info.hProcess, int(max(1, timeout_seconds) * 1000)
            )
            if wait != self.WAIT_OBJECT_0:
                kernel32.TerminateProcess(process_info.hProcess, 124)
                raise TimeoutError("restricted process probe timed out")
            exit_code = wintypes.DWORD()
            kernel32.GetExitCodeProcess(
                process_info.hProcess, ctypes.byref(exit_code)
            )
            return {
                "process_creation_backend": backend,
                "restricted_token_created": True,
                "restriction_flags": restriction_flags,
                "source_token_already_restricted": source_token_already_restricted,
                "low_integrity_sid": "S-1-16-4096",
                "exit_code": int(exit_code.value),
            }
        finally:
            for handle in (
                process_info.hThread, process_info.hProcess,
                restricted, token,
            ):
                if handle:
                    kernel32.CloseHandle(handle)
            if sid.value:
                kernel32.LocalFree(sid)
