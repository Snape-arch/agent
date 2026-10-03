from __future__ import annotations

import ctypes
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Any


PROFILE_ALREADY_EXISTS = 0x800700B7
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000
TOKEN_QUERY = 0x0008
TOKEN_IS_APP_CONTAINER = 29


class WindowsAppContainerBoundary:
    """Persistent AppContainer profile with zero network capabilities.

    Networked work is deliberately brokered by the host.  The sandbox process
    receives no internetClient/privateNetwork capability, preventing direct
    socket egress at the operating-system token boundary.
    """

    def __init__(self, profile_name: str = "ClawOS.CodingSandbox"):
        name = str(profile_name or "").strip()
        if not name or len(name) > 64 or not all(ch.isalnum() or ch in ".-_" for ch in name):
            raise ValueError("AppContainer profile name is invalid")
        self.profile_name = name

    @staticmethod
    def available() -> bool:
        return platform.system().lower() == "windows"

    def status(self) -> dict[str, Any]:
        if not self.available():
            return {
                "available": False, "installed": False,
                "profile": self.profile_name, "production_ready": False,
            }
        try:
            sid, pointer = self._derive_sid()
        except OSError:
            return {
                "available": True, "installed": False,
                "profile": self.profile_name, "production_ready": False,
            }
        self._free_sid(pointer)
        if not self._profile_exists(sid):
            return {
                "available": True, "installed": False,
                "profile": self.profile_name, "sid": sid,
                "production_ready": False,
            }
        return {
            "available": True, "installed": True,
            "profile": self.profile_name, "sid": sid,
            "network_capabilities": [], "direct_network_denied": True,
            "production_ready": True,
        }

    def install(self, *, confirmed: bool = False) -> dict[str, Any]:
        if confirmed is not True:
            raise PermissionError("confirmed=true is required to install an AppContainer profile")
        if not self.available():
            raise RuntimeError("AppContainer is unavailable on this platform")
        userenv = ctypes.WinDLL("userenv", use_last_error=True)
        userenv.CreateAppContainerProfile.argtypes = [
            wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
        ]
        userenv.CreateAppContainerProfile.restype = ctypes.c_long
        sid_pointer = ctypes.c_void_p()
        hr = userenv.CreateAppContainerProfile(
            self.profile_name, "ClawOS Coding Sandbox",
            "No-network coding task AppContainer", None, 0,
            ctypes.byref(sid_pointer),
        )
        code = int(hr) & 0xFFFFFFFF
        created = code == 0
        if code not in {0, PROFILE_ALREADY_EXISTS}:
            raise OSError(code, "CreateAppContainerProfile failed")
        if sid_pointer.value:
            self._free_sid(sid_pointer)
        status = self.status()
        if not status.get("installed"):
            raise RuntimeError("AppContainer profile could not be derived after installation")
        return {**status, "created": created, "system_state_changed": created}

    def uninstall(self, *, confirmed: bool = False) -> dict[str, Any]:
        if confirmed is not True:
            raise PermissionError("confirmed=true is required to delete an AppContainer profile")
        if not self.available():
            raise RuntimeError("AppContainer is unavailable on this platform")
        userenv = ctypes.WinDLL("userenv", use_last_error=True)
        userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
        userenv.DeleteAppContainerProfile.restype = ctypes.c_long
        code = int(userenv.DeleteAppContainerProfile(self.profile_name)) & 0xFFFFFFFF
        if code not in {0, 0x80070002}:
            raise OSError(code, "DeleteAppContainerProfile failed")
        return {"deleted": code == 0, "profile": self.profile_name}

    def grant_workspace(self, workspace: str | Path, *, confirmed: bool = False) -> dict[str, Any]:
        if confirmed is not True:
            raise PermissionError("confirmed=true is required to grant AppContainer workspace ACL")
        path = Path(workspace).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("workspace must be an existing directory")
        status = self.status()
        if not status.get("installed"):
            raise RuntimeError("AppContainer profile is not installed")
        sid = status["sid"]
        result = subprocess.run(
            ["icacls", str(path), "/grant", f"*{sid}:(OI)(CI)M"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip() or "icacls grant failed")
        return {
            "workspace": str(path), "profile": self.profile_name,
            "sid": sid, "modify_granted": True,
            "other_user_acl_removed": False,
        }

    def run_command(
        self,
        command: list[str],
        workspace: str | Path,
        *,
        timeout_seconds: float = 180,
        confirmed_acl: bool = False,
    ) -> dict[str, Any]:
        cwd = Path(workspace).expanduser().resolve()
        acl = self.grant_workspace(cwd, confirmed=confirmed_acl)
        report_dir = cwd / ".clawos-appcontainer"
        report_dir.mkdir(parents=True, exist_ok=True)
        self.grant_workspace(report_dir, confirmed=True)
        report = report_dir / f"result-{uuid.uuid4().hex}.json"
        bounded = max(1, min(float(timeout_seconds or 180), 900.0))
        safe_environment = {
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
            "PATH": os.environ.get("PATH", ""), "TEMP": str(cwd), "TMP": str(cwd),
            "PYTHONIOENCODING": "utf-8", "PYTHONNOUSERSITE": "1",
        }
        wrapper = (
            "import ctypes,json,os,pathlib,subprocess,time;"
            f"safe_env={safe_environment!r};os.environ.clear();os.environ.update(safe_env);"
            "from ctypes import wintypes;"
            f"cmd={list(map(str, command))!r};cwd={str(cwd)!r};"
            f"report=pathlib.Path({str(report)!r});limit={bounded!r};"
            "a=ctypes.WinDLL('advapi32',use_last_error=True);k=ctypes.WinDLL('kernel32');"
            "k.GetCurrentProcess.restype=wintypes.HANDLE;"
            "a.OpenProcessToken.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE)];"
            "a.GetTokenInformation.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)];"
            "token=wintypes.HANDLE();flag=wintypes.DWORD();size=wintypes.DWORD();"
            "a.OpenProcessToken(k.GetCurrentProcess(),8,ctypes.byref(token));"
            "a.GetTokenInformation(token,29,ctypes.byref(flag),ctypes.sizeof(flag),ctypes.byref(size));"
            "started=time.perf_counter();"
            "\nif not flag.value: raise SystemExit('AppContainer token required; command was not started')\n"
            "\ntry:\n"
            " r=subprocess.run(cmd,cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=limit,env=safe_env);"
            " payload={'exit_code':r.returncode,'stdout':r.stdout[-8000:],'stderr':r.stderr[-4000:],'timed_out':False}\n"
            "except subprocess.TimeoutExpired as exc:\n"
            " payload={'exit_code':124,'stdout':str(exc.stdout or '')[-8000:],'stderr':str(exc.stderr or '')[-4000:],'timed_out':True}\n"
            "payload['is_appcontainer']=bool(flag.value);"
            "payload['duration_ms']=round((time.perf_counter()-started)*1000,2);"
            "report.write_text(json.dumps(payload),encoding='utf-8')"
        )
        process = self._create_process(wrapper, cwd, bounded + 15)
        if not report.is_file():
            raise RuntimeError("AppContainer worker did not produce a result")
        payload = json.loads(report.read_text(encoding="utf-8"))
        report.unlink(missing_ok=True)
        try:
            report_dir.rmdir()
        except OSError:
            pass
        is_container = bool(payload.get("is_appcontainer"))
        return {
            "command": list(map(str, command)), **payload,
            "sandbox": {
                "backend": "windows-appcontainer",
                "os_enforced": is_container,
                "profile": self.profile_name, "workspace_acl": acl,
                "network_capabilities": [], "network_isolated": is_container,
                "direct_socket_non_bypass_enforced": is_container,
                "filesystem_isolated": is_container,
                "production_sandbox_ready": is_container,
                "process_exit_code": process["exit_code"],
            },
        }

    def probe(self, workspace: str | Path, *, confirmed_acl: bool = False) -> dict[str, Any]:
        """Prove the token, workspace write boundary and direct-socket denial."""
        root = Path(workspace).expanduser().resolve()
        outside = root.parent / f".clawos-boundary-probe-{uuid.uuid4().hex}.tmp"
        probe_code = (
            "import json,pathlib,socket,sys;"
            "inside=pathlib.Path(sys.argv[1]);outside=pathlib.Path(sys.argv[2]);"
            "result={};"
            "\ntry:\n inside.write_text('ok',encoding='utf-8');result['workspace_write']=True\n"
            "except Exception as e:\n result['workspace_write']=False;result['workspace_error']=type(e).__name__\n"
            "\ntry:\n outside.write_text('forbidden',encoding='utf-8');result['outside_write_denied']=False\n"
            "except Exception as e:\n result['outside_write_denied']=True;result['outside_error']=type(e).__name__\n"
            "s=socket.socket();s.settimeout(1);"
            "\ntry:\n result['direct_network_denied']=s.connect_ex(('1.1.1.1',443))!=0\n"
            "except Exception as e:\n result['direct_network_denied']=True;result['network_error']=type(e).__name__\n"
            "s.close();print(json.dumps(result))"
        )
        inside = root / ".clawos-appcontainer-probe.tmp"
        result = self.run_command(
            [sys.executable, "-c", probe_code, str(inside), str(outside)], root,
            timeout_seconds=20, confirmed_acl=confirmed_acl,
        )
        inside.unlink(missing_ok=True)
        outside_created = outside.exists()
        outside.unlink(missing_ok=True)
        try:
            details = json.loads(str(result.get("stdout") or "").strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            details = {}
        passed = bool(
            result.get("sandbox", {}).get("os_enforced")
            and details.get("workspace_write")
            and details.get("outside_write_denied")
            and details.get("direct_network_denied")
            and not outside_created
        )
        return {**result, "probe": details, "passed": passed, "outside_artifact_created": outside_created}

    def _create_process(self, script: str, cwd: Path, timeout_seconds: float) -> dict[str, Any]:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class STARTUPINFO(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
                ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
                ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
                ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
                ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
                ("hStdError", wintypes.HANDLE),
            ]

        class STARTUPINFOEX(ctypes.Structure):
            _fields_ = [("StartupInfo", STARTUPINFO), ("lpAttributeList", ctypes.c_void_p)]

        class PROCESS_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
            ]

        class SECURITY_CAPABILITIES(ctypes.Structure):
            _fields_ = [
                ("AppContainerSid", ctypes.c_void_p),
                ("Capabilities", ctypes.c_void_p),
                ("CapabilityCount", wintypes.DWORD), ("Reserved", wintypes.DWORD),
            ]

        kernel32.InitializeProcThreadAttributeList.argtypes = [
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
        kernel32.UpdateProcThreadAttribute.argtypes = [
            ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t,
            ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p,
        ]
        kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
        kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
        kernel32.CreateProcessW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
            wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
            ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESS_INFORMATION),
        ]
        kernel32.CreateProcessW.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        sid_text, sid_pointer = self._derive_sid()
        size = ctypes.c_size_t()
        kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attribute_buffer = ctypes.create_string_buffer(size.value)
        attribute_list = ctypes.cast(attribute_buffer, ctypes.c_void_p)
        process_info = PROCESS_INFORMATION()
        try:
            if not kernel32.InitializeProcThreadAttributeList(
                attribute_list, 1, 0, ctypes.byref(size)
            ):
                raise OSError(ctypes.get_last_error(), "InitializeProcThreadAttributeList failed")
            capabilities = SECURITY_CAPABILITIES(sid_pointer, None, 0, 0)
            if not kernel32.UpdateProcThreadAttribute(
                attribute_list, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                ctypes.byref(capabilities), ctypes.sizeof(capabilities), None, None,
            ):
                raise OSError(ctypes.get_last_error(), "UpdateProcThreadAttribute failed")
            startup = STARTUPINFOEX()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            startup.lpAttributeList = attribute_list
            interpreter = str(getattr(sys, "_base_executable", "") or sys.executable)
            command_line = ctypes.create_unicode_buffer(
                subprocess.list2cmdline([interpreter, "-I", "-S", "-c", script])
            )
            created = kernel32.CreateProcessW(
                None, command_line, None, None, False,
                EXTENDED_STARTUPINFO_PRESENT | CREATE_NO_WINDOW,
                None, str(cwd), ctypes.byref(startup.StartupInfo),
                ctypes.byref(process_info),
            )
            if not created:
                raise OSError(ctypes.get_last_error(), "AppContainer CreateProcessW failed")
            wait = kernel32.WaitForSingleObject(
                process_info.hProcess, int(max(1, timeout_seconds) * 1000)
            )
            if wait != 0:
                kernel32.TerminateProcess(process_info.hProcess, 124)
                raise TimeoutError("AppContainer worker timed out")
            exit_code = wintypes.DWORD()
            kernel32.GetExitCodeProcess(process_info.hProcess, ctypes.byref(exit_code))
            return {"exit_code": int(exit_code.value), "profile_sid": sid_text}
        finally:
            if attribute_list:
                kernel32.DeleteProcThreadAttributeList(attribute_list)
            for handle in (process_info.hThread, process_info.hProcess):
                if handle:
                    kernel32.CloseHandle(handle)
            self._free_sid(sid_pointer)

    def _derive_sid(self) -> tuple[str, ctypes.c_void_p]:
        userenv = ctypes.WinDLL("userenv", use_last_error=True)
        userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
            wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
        ]
        userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
        pointer = ctypes.c_void_p()
        code = int(userenv.DeriveAppContainerSidFromAppContainerName(
            self.profile_name, ctypes.byref(pointer)
        )) & 0xFFFFFFFF
        if code != 0 or not pointer.value:
            raise OSError(code, "AppContainer profile is not installed")
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR),
        ]
        text_pointer = wintypes.LPWSTR()
        if not advapi.ConvertSidToStringSidW(pointer, ctypes.byref(text_pointer)):
            self._free_sid(pointer)
            raise OSError(ctypes.get_last_error(), "ConvertSidToStringSidW failed")
        try:
            return str(text_pointer.value), pointer
        finally:
            self._local_free(text_pointer)

    @staticmethod
    def _local_free(pointer: Any) -> None:
        if pointer:
            kernel32 = ctypes.WinDLL("kernel32")
            kernel32.LocalFree.argtypes = [ctypes.c_void_p]
            kernel32.LocalFree.restype = ctypes.c_void_p
            kernel32.LocalFree(pointer)

    @staticmethod
    def _free_sid(pointer: Any) -> None:
        if pointer:
            advapi = ctypes.WinDLL("advapi32")
            advapi.FreeSid.argtypes = [ctypes.c_void_p]
            advapi.FreeSid.restype = ctypes.c_void_p
            advapi.FreeSid(pointer)

    @staticmethod
    def _profile_exists(sid: str) -> bool:
        try:
            import winreg
            key_path = rf"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppContainer\Mappings\{sid}"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path):
                return True
        except (ImportError, FileNotFoundError, OSError):
            return False


class WindowsFirewallPackageGuard:
    """Optional defense-in-depth block rule scoped to an AppContainer SID."""

    def __init__(self, display_name: str = "ClawOS Coding AppContainer - Block Direct Egress"):
        self.display_name = display_name

    def status(self) -> dict[str, Any]:
        command = (
            f"Get-NetFirewallRule -DisplayName '{self.display_name.replace(chr(39), chr(39)*2)}' "
            "-ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Enabled"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        )
        return {"installed": result.stdout.strip().lower() == "true", "display_name": self.display_name}

    def install(self, package_sid: str, *, confirmed: bool = False) -> dict[str, Any]:
        if confirmed is not True:
            raise PermissionError("confirmed=true is required to install a firewall rule")
        sid = str(package_sid or "").strip()
        if not sid.startswith("S-1-15-2-"):
            raise ValueError("package_sid must be an AppContainer SID")
        script = (
            f"New-NetFirewallRule -DisplayName '{self.display_name.replace(chr(39), chr(39)*2)}' "
            f"-Direction Outbound -Action Block -Profile Any -Package '{sid}' | Out-Null"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        if result.returncode != 0:
            raise PermissionError((result.stderr or result.stdout).strip() or "firewall rule installation failed")
        return {**self.status(), "package_sid": sid, "direct_egress_blocked": True}

    def remove(self, *, confirmed: bool = False) -> dict[str, Any]:
        if confirmed is not True:
            raise PermissionError("confirmed=true is required to remove a firewall rule")
        name = self.display_name.replace(chr(39), chr(39) * 2)
        script = f"Remove-NetFirewallRule -DisplayName '{name}' -ErrorAction SilentlyContinue"
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        if result.returncode != 0:
            raise PermissionError((result.stderr or result.stdout).strip() or "firewall rule removal failed")
        return {**self.status(), "removed": True}
