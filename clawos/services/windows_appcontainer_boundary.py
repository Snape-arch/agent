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

    def __init__(self, profile_name: str = "ClawOS.CodingSandbox", *, runtime_dir: str | Path | None = None):
        name = str(profile_name or "").strip()
        if not name or len(name) > 64 or not all(ch.isalnum() or ch in ".-_" for ch in name):
            raise ValueError("AppContainer profile name is invalid")
        self.profile_name = name
        self.runtime_dir = Path(runtime_dir or os.environ["CLAWOS_APPCONTAINER_RUNTIME"]) if runtime_dir or os.environ.get("CLAWOS_APPCONTAINER_RUNTIME") else None

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
            "network_capabilities": [], "direct_network_denied": False,
            "production_ready": False, "reason": "installation is not isolation acceptance",
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
        from .appcontainer_process import safe_tree
        path = safe_tree(Path(workspace).expanduser())
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
        label = subprocess.run(["icacls", str(path), "/setintegritylevel", "(OI)(CI)L"],
            capture_output=True, text=True, errors="replace", timeout=30)
        if label.returncode != 0:
            raise RuntimeError("sandbox low-integrity label failed")
        return {
            "workspace": str(path), "profile": self.profile_name,
            "sid": sid, "modify_granted": True,
            "other_user_acl_removed": False,
        }

    def grant_runtime(self, *, confirmed: bool = False) -> dict[str, Any]:
        if confirmed is not True:
            raise PermissionError("confirmed=true required to grant a private runtime")
        from .appcontainer_process import safe_tree
        if self.runtime_dir is None:
            raise ValueError("CLAWOS_APPCONTAINER_RUNTIME must name a private copied runtime")
        runtime = safe_tree(self.runtime_dir)
        if not (runtime / "python.exe").is_file():
            raise ValueError("private runtime must contain python.exe")
        status = self.status()
        if not status.get("installed"):
            raise RuntimeError("AppContainer profile is not installed")
        result = subprocess.run(["icacls", str(runtime), "/grant", f"*{status['sid']}:(OI)(CI)RX"],
            capture_output=True, text=True, errors="replace", timeout=30)
        if result.returncode != 0:
            raise RuntimeError("private runtime read/execute grant failed")
        return {"runtime": str(runtime), "sid": status["sid"], "read_execute_granted": True}

    def run_command(self, command: list[str], workspace: str | Path, *,
                    timeout_seconds: float = 180, confirmed_acl: bool = False) -> dict[str, Any]:
        from .appcontainer_process import launch, safe_tree, validate_python_command, GitControlSeal
        if confirmed_acl is not True:
            raise PermissionError("confirmed=true required for sandbox workspace ACL")
        if self.runtime_dir is None:
            raise ValueError("strict sandbox requires a private copied Python runtime")
        validate_python_command(command)
        cwd, runtime = safe_tree(Path(workspace)), safe_tree(self.runtime_dir)
        if cwd == runtime or cwd in runtime.parents or runtime in cwd.parents:
            raise ValueError("runtime must be separate from writable workspace")
        control = cwd / '.git'
        if control.is_dir():
            raise ValueError('strict execution requires a Git worktree pointer, not a writable Git database')
        with GitControlSeal(control) as sealed:
            # A fresh SID prevents concurrent tasks from gaining each other's grants.
            scoped = WindowsAppContainerBoundary('ClawOS.Exec.' + uuid.uuid4().hex, runtime_dir=runtime)
            installed = None
            try:
                installed = scoped.install(confirmed=True)
                if not installed.get('created'):
                    raise RuntimeError('refusing to reuse a command profile')
                scoped.grant_runtime(confirmed=True)
                acl = scoped.grant_workspace(cwd, confirmed=True)
                result = launch(scoped, command, cwd, runtime, max(.1, min(float(timeout_seconds), 900)))
                result['sandbox'].update(workspace_acl=acl, ephemeral_profile=True,
                    git_control_pointer_sealed=sealed.handle is not None)
            finally:
                try:
                    # Restore through the pre-opened WRITE_DAC handle before ACL cleanup.
                    sealed.restore()
                finally:
                    cleanup = []
                    if installed and installed.get('created'):
                        for path in (cwd, runtime):
                            revoked = subprocess.run(['icacls', str(path), '/remove:g', '*' + installed['sid'], '/T', '/Q'],
                                capture_output=True, timeout=60)
                            cleanup.append(revoked.returncode == 0)
                        removed = scoped.uninstall(confirmed=True)
                        if not all(cleanup) or not removed.get('deleted'):
                            raise RuntimeError('command profile or ACL cleanup failed; boundary not accepted')
            result['sandbox']['profile_and_grants_removed'] = True
            return result

    def probe(self, workspace: str | Path, *, confirmed_acl: bool = False) -> dict[str, Any]:
        # Legacy entrypoint now runs the synthetic attack matrix, never public Internet.
        from .strict_sandbox_acceptance import probe_boundary
        return probe_boundary(self, Path(workspace), confirmed_acl=confirmed_acl)

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
