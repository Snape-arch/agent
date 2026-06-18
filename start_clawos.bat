@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "ROOT=%~dp0"
set "CLAWOS_DIR=%ROOT%clawos"
set "VENV_PYTHON=%CLAWOS_DIR%\.venv\Scripts\python.exe"
set "PYTHON="
set "MTCLAW_DIR="
set "MTCLAW_PORT=18791"
set "CLAWOS_PORT=18790"
set "MTCLAW_BASE_URL=http://127.0.0.1:%MTCLAW_PORT%"

echo ============================================
echo   ClawOS + MTClaw Windows Launcher
echo ============================================
echo.

if exist "%VENV_PYTHON%" (
    set "PYTHON=%VENV_PYTHON%"
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON=python"
    ) else (
        where py >nul 2>nul
        if not errorlevel 1 (
            set "PYTHON=py"
        )
    )
)

if not defined PYTHON (
    echo [ERROR] Python not found.
    echo         Expected virtualenv: %VENV_PYTHON%
    echo         Or install Python and make python/py available in PATH.
    echo.
    pause
    exit /b 1
)

if not exist "%VENV_PYTHON%" (
    echo [WARN] Project virtualenv not found:
    echo        %VENV_PYTHON%
    echo [WARN] Falling back to system Python: %PYTHON%
    echo        For a reproducible competition demo, creating clawos\.venv is still recommended.
    echo.
)

echo [INFO] Python runtime: %PYTHON%
%PYTHON% --version
if errorlevel 1 (
    echo [ERROR] Selected Python runtime is not usable: %PYTHON%
    pause
    exit /b 1
)

if not exist "%CLAWOS_DIR%\.env" (
    echo [WARN] clawos\.env not found. Model calls may fail until local config is added.
) else (
    echo [INFO] Loading local environment from clawos\.env
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%CLAWOS_DIR%\.env") do (
        if not "%%A"=="" if not defined %%A set "%%A=%%B"
    )
)

if not defined MODEL_API_KEY if defined DEEPSEEK_API_KEY (
    set "MODEL_API_KEY=%DEEPSEEK_API_KEY%"
)

for /d %%D in ("%ROOT%MTClaw-*") do (
    set "MTCLAW_DIR=%%~fD"
)

if not defined MTCLAW_DIR (
    echo [ERROR] MTClaw directory not found under:
    echo         %ROOT%
    pause
    exit /b 1
)

echo [1/5] Preparing MTClaw runtime...
"%PYTHON%" "%CLAWOS_DIR%\mtclaw\prepare_runtime.py"
if errorlevel 1 (
    echo [ERROR] Failed to prepare MTClaw runtime.
    pause
    exit /b 1
)

echo.
echo [2/5] Starting MTClaw Function Router on %MTCLAW_BASE_URL% ...
start "MTClaw Function Router" /D "%MTCLAW_DIR%" "%PYTHON%" "function_router\server.py" --config "%CLAWOS_DIR%\mtclaw_runtime\config.json"

echo [3/5] Waiting for MTClaw health check...
"%PYTHON%" "%CLAWOS_DIR%\scripts\windows_health_check.py" --url "%MTCLAW_BASE_URL%/health" --name MTClaw --timeout 30
if errorlevel 1 (
    echo [ERROR] MTClaw did not become healthy. Check the MTClaw window for details.
    pause
    exit /b 1
)

echo.
echo [4/5] Starting ClawOS on http://127.0.0.1:%CLAWOS_PORT% ...
set "MTCLAW_ENABLED=true"
set "MTCLAW_BASE_URL=%MTCLAW_BASE_URL%"
start "ClawOS Server" /D "%CLAWOS_DIR%" "%PYTHON%" "clawos_server.py" --host 127.0.0.1 --port %CLAWOS_PORT%

echo [5/5] Waiting for ClawOS health check...
"%PYTHON%" "%CLAWOS_DIR%\scripts\windows_health_check.py" --url "http://127.0.0.1:%CLAWOS_PORT%/health" --name ClawOS --timeout 45
if errorlevel 1 (
    echo [ERROR] ClawOS did not become healthy. Check the ClawOS window for details.
    pause
    exit /b 1
)

echo.
echo [OK] ClawOS is ready:
echo      http://127.0.0.1:%CLAWOS_PORT%
echo.
echo MTClaw:
echo      %MTCLAW_BASE_URL%
echo.
echo Close the MTClaw and ClawOS console windows to stop the services.
pause
