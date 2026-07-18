"""Native ClawOS desktop shell with hidden local-service lifecycle."""

from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

APP_NAME = "ClawOS"
CLAWOS_PORT = 18790
MTCLAW_PORT = 18791
CREATE_NO_WINDOW = 0x08000000
MUTEX_ALREADY_EXISTS = 183


def install_root() -> Path:
    override = os.environ.get("CLAWOS_INSTALL_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def runtime_python(root: Path, *, windowed: bool = False) -> Path:
    name = "pythonw.exe" if windowed else "python.exe"
    candidates = [root / "runtime" / name, root / "clawos" / ".venv" / "Scripts" / name]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"ClawOS runtime is incomplete: {name} is missing")


def application_paths(root: Path) -> tuple[Path, Path]:
    packaged = root / "app" / "clawos"
    if packaged.exists():
        return packaged, root / "app" / "mtclaw-source"
    return root / "clawos", next(root.glob("MTClaw-*"), root / "MTClaw-source")


def user_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return (base / APP_NAME).resolve()


def desktop_environment(app_dir: Path, data_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "CLAWOS_DESKTOP": "1",
            "CLAWOS_DATA_DIR": str(data_dir),
            "CLAWOS_OUTPUT_DIR": str(data_dir / "output"),
            "CLAWOS_MEMORY_DB": str(data_dir / "memoryos.db"),
            "CLAWOS_ENV_PATH": str(data_dir / ".env"),
            "CLAWOS_CONFIG_PATH": str(app_dir / "config.json"),
            "MTCLAW_ENABLED": "true",
            "MTCLAW_BASE_URL": f"http://127.0.0.1:{MTCLAW_PORT}",
            "NO_PROXY": "127.0.0.1,localhost,::1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    # Software compositing avoids blank WebView2 surfaces in Windows Sandbox,
    # remote-desktop sessions and GPU-restricted competition machines.
    env.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--disable-gpu")
    return env


def http_json(url: str, timeout: float = 1.5) -> dict | None:
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            if not 200 <= response.status < 300:
                return None
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
            return payload if isinstance(payload, dict) else None
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def wait_for_health(url: str, timeout: float) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = http_json(url)
        if payload is not None:
            return payload
        time.sleep(0.35)
    return None


def smoke_duration(arguments: list[str]) -> float | None:
    for argument in arguments:
        if argument == "--smoke-test":
            return 20.0
        if argument.startswith("--smoke-test="):
            try:
                return max(1.0, min(float(argument.split("=", 1)[1]), 120.0))
            except ValueError:
                return 20.0
    return None


def port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def message_box(text: str, title: str = APP_NAME, error: bool = False) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 if error else 0x40)


def acquire_single_instance():
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\ClawOSDesktop-v1")
    if not handle or ctypes.windll.kernel32.GetLastError() == MUTEX_ALREADY_EXISTS:
        message_box("ClawOS 已经在运行。")
        return None
    return handle


def spawn_hidden(command: list[str], cwd: Path, env: dict[str, str], log_path: Path) -> tuple[subprocess.Popen, object]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW,
    )
    return process, log_file


def terminate(process: subprocess.Popen | None) -> None:
    if not process or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def prepare_mtclaw(python: Path, app_dir: Path, env: dict[str, str], log_path: Path) -> bool:
    script = app_dir / "mtclaw" / "prepare_runtime.py"
    if not script.exists():
        return False
    with log_path.open("a", encoding="utf-8") as log_file:
        result = subprocess.run(
            [str(python), str(script)], cwd=str(app_dir), env=env,
            stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW, timeout=45, check=False,
        )
    return result.returncode == 0


def run() -> int:
    mutex = acquire_single_instance()
    if mutex is None:
        return 0
    root = install_root()
    app_dir, mtclaw_source = application_paths(root)
    data_dir = user_data_dir()
    for directory in (data_dir, data_dir / "logs", data_dir / "uploads", data_dir / "output"):
        directory.mkdir(parents=True, exist_ok=True)
    spawned: list[subprocess.Popen] = []
    logs: list[object] = []
    env = desktop_environment(app_dir, data_dir)
    python = runtime_python(root)
    pythonw = runtime_python(root, windowed=True)

    try:
        mtclaw_health = f"http://127.0.0.1:{MTCLAW_PORT}/health"
        if http_json(mtclaw_health) is None:
            if port_is_open(MTCLAW_PORT):
                raise RuntimeError(f"端口 {MTCLAW_PORT} 已被其他程序占用。")
            prepare_log = data_dir / "logs" / "mtclaw-prepare.log"
            if not prepare_mtclaw(python, app_dir, env, prepare_log):
                raise RuntimeError(f"MTClaw 运行时准备失败。日志：{prepare_log}")
            process, log = spawn_hidden(
                [str(pythonw), str(mtclaw_source / "function_router" / "server.py"),
                 "--config", str(app_dir / "mtclaw_runtime" / "config.json")],
                mtclaw_source, env, data_dir / "logs" / "mtclaw.log",
            )
            spawned.append(process); logs.append(log)
            if wait_for_health(mtclaw_health, 35) is None:
                raise RuntimeError(f"MTClaw 启动失败。日志：{data_dir / 'logs' / 'mtclaw.log'}")

        clawos_health = f"http://127.0.0.1:{CLAWOS_PORT}/health"
        if http_json(clawos_health) is None:
            if port_is_open(CLAWOS_PORT):
                raise RuntimeError(f"端口 {CLAWOS_PORT} 已被其他程序占用。")
            process, log = spawn_hidden(
                [str(pythonw), str(app_dir / "clawos_server.py"), "--host", "127.0.0.1", "--port", str(CLAWOS_PORT)],
                app_dir, env, data_dir / "logs" / "clawos.log",
            )
            spawned.append(process); logs.append(log)
            if wait_for_health(clawos_health, 60) is None:
                raise RuntimeError(f"ClawOS 启动失败。日志：{data_dir / 'logs' / 'clawos.log'}")

        smoke_seconds = smoke_duration(sys.argv[1:])
        if smoke_seconds is not None:
            if http_json(f"http://127.0.0.1:{CLAWOS_PORT}/api/workspace/capabilities", timeout=5) is None:
                raise RuntimeError("桌面验收无法读取工作台能力接口。")
            time.sleep(smoke_seconds)
            return 0

        os.environ.update(env)
        import webview
        webview.create_window(APP_NAME, f"http://127.0.0.1:{CLAWOS_PORT}/console",
                              width=1440, height=960, min_size=(1024, 700),
                              confirm_close=False, text_select=True)
        webview.start(gui="edgechromium", debug=False, private_mode=False,
                      storage_path=str(data_dir / "webview"))
        return 0
    except Exception as exc:
        message_box(f"ClawOS 无法启动。\n\n{exc}", error=True)
        return 1
    finally:
        for process in reversed(spawned):
            terminate(process)
        for log in logs:
            log.close()
        ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    raise SystemExit(run())
