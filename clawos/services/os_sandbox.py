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
