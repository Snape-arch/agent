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
set "QWEN_PORT=8000"
set "MTCLAW_BASE_URL=http://127.0.0.1:%MTCLAW_PORT%"
set "QWEN_BASE_URL=http://127.0.0.1:%QWEN_PORT%/v1"
set "LOCAL_PROFILE="
set "RUNTIME_CHECK_ONLY="
if /I "%~1"=="--local" set "LOCAL_PROFILE=1"
if /I "%~1"=="--check-runtime" set "RUNTIME_CHECK_ONLY=1"

echo ============================================
echo   ClawOS + MTClaw Windows Launcher
echo ============================================
if defined LOCAL_PROFILE echo   Mode: local daily-use profile
echo.

if defined RUNTIME_CHECK_ONLY goto runtime_selection
call :check_port %MTCLAW_PORT% MTClaw
if errorlevel 1 (
    pause
    exit /b 1
)

call :check_port %CLAWOS_PORT% ClawOS
if errorlevel 1 (
    pause
    exit /b 1
)

:runtime_selection
if defined CLAWOS_PYTHON (
    set "PYTHON=%CLAWOS_PYTHON%"
) else if exist "%VENV_PYTHON%" (
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
"%PYTHON%" --version
if errorlevel 1 (
    echo [ERROR] Selected Python runtime is not usable: %PYTHON%
    pause
    exit /b 1
)

rem A prepared application runtime takes precedence over the test/system fallback.
rem An explicit CLAWOS_PYTHON remains an intentional development override.
if not defined CLAWOS_PYTHON if exist "%CLAWOS_DIR%\output\app-runtimes\current.json" (
    "%PYTHON%" -I "%CLAWOS_DIR%\scripts\application_runtime.py" selected --path-file "%CLAWOS_DIR%\output\app-runtimes\launcher-python.txt"
    if errorlevel 1 (
        echo [ERROR] Prepared application runtime failed verification. No fallback was started.
        pause
        exit /b 1
    )
    set /p "PYTHON="<"%CLAWOS_DIR%\output\app-runtimes\launcher-python.txt"
)
echo [INFO] Application Python: %PYTHON%
if defined RUNTIME_CHECK_ONLY (
    if defined CLAWOS_PYTHON (
        "%PYTHON%" -I "%CLAWOS_DIR%\scripts\application_runtime.py" verify --python "%PYTHON%" >nul
        if errorlevel 1 exit /b 1
    ) else if not exist "%CLAWOS_DIR%\output\app-runtimes\current.json" (
        echo [ERROR] No locked application runtime is prepared.
        exit /b 1
    )
    echo [OK] Locked application runtime verified. No service was started.
    exit /b 0
)

if defined LOCAL_PROFILE (
    set "CLAWOS_SKIP_LOCAL_ENV=1"
    echo [INFO] Local profile: skipping cloud environment file.
) else if not exist "%CLAWOS_DIR%\.env" (
    echo [WARN] clawos\.env not found. Model calls may fail until local config is added.
    echo        Mock/offline checks still work without a real API key.
) else (
    echo [INFO] Loading local environment from clawos\.env
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%CLAWOS_DIR%\.env") do (
        if not "%%A"=="" if not defined %%A set "%%A=%%B"
    )
)

if not defined MODEL_API_KEY if defined DEEPSEEK_API_KEY (
    set "MODEL_API_KEY=%DEEPSEEK_API_KEY%"
)

if defined LOCAL_PROFILE (
    "%PYTHON%" -c "import importlib.util,sys; missing=[n for n in ('chromadb','sentence_transformers','torch') if importlib.util.find_spec(n) is None]; print('Local retrieval dependencies missing: '+', '.join(missing)) if missing else None; sys.exit(bool(missing))"
    if errorlevel 1 (
        echo [ERROR] Install local retrieval dependencies in this runtime, or set CLAWOS_PYTHON to a prepared Python executable.
        pause
        exit /b 1
    )
    set "CLAWOS_CONFIG_PATH=%CLAWOS_DIR%\config.local.json"
    set "MODEL_PROVIDER=qwen"
    set "MODEL_BASE_URL=%QWEN_BASE_URL%"
    set "MODEL_NAME=Qwen3.5-9B-Q4_K_M"
    set "MODEL_REQUIRES_API_KEY=false"
    set "MODEL_API_KEY="
    set "VECTOR_PROVIDER=chroma"
    set "EMBEDDING_PROVIDER=qwen3"
    set "EMBEDDING_MODEL_PATH=%ROOT%tools\models\qwen3-embedding-0.6b"
    set "EMBEDDING_DIM=1024"
    set "RERANKER_PROVIDER=none"
    if defined NO_PROXY (
        set "NO_PROXY=127.0.0.1,localhost,::1,%NO_PROXY%"
    ) else (
        set "NO_PROXY=127.0.0.1,localhost,::1"
    )
    echo [INFO] Local profile selected. Existing clawos\.env was not modified.
)

if not defined MODEL_API_KEY (
    if defined LOCAL_PROFILE (
        echo [LOCAL] No API key is required for the selected local profile.
    ) else (
        echo.
        echo [INFO] MODEL_API_KEY not found. ClawOS will open in configuration-first mode.
        echo        Choose API mode or local/offline Qwen from the web console when you are ready.
        echo        No model weights or llama.cpp runtime will be downloaded by this launcher.
        if not defined MODEL_PROVIDER set "MODEL_PROVIDER=mock"
        if not defined MODEL_NAME set "MODEL_NAME=mock"
    )
) else (
    echo [INFO] MODEL_API_KEY found. API provider remains primary.
)

if defined LOCAL_PROFILE (
    call :qwen_health
    if errorlevel 1 (
        call :check_port %QWEN_PORT% "Local Qwen"
        if errorlevel 1 (
            pause
            exit /b 1
        )
        echo.
        echo [LOCAL] Starting Qwen on %QWEN_BASE_URL% ...
        echo         This launcher will not download missing model or runtime files.
        start "Qwen Local Model" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CLAWOS_DIR%\scripts\start_qwen_llama_server.ps1"
        "%PYTHON%" "%CLAWOS_DIR%\scripts\windows_health_check.py" --url "http://127.0.0.1:%QWEN_PORT%/health" --name "Local Qwen" --timeout 90
        if errorlevel 1 (
            echo [ERROR] Local Qwen did not become healthy. Check the Qwen window and local model assets.
            pause
            exit /b 1
        )
    ) else (
        echo [LOCAL] Reusing healthy Qwen service on %QWEN_BASE_URL%
    )
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
"%PYTHON%" "%CLAWOS_DIR%\scripts\windows_health_check.py" --url "http://127.0.0.1:%CLAWOS_PORT%/health" --name ClawOS --timeout 45 --require-ready
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

exit /b 0

:check_port
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %1 -State Listen -ErrorAction SilentlyContinue) { exit 1 }"
if not errorlevel 1 (
    exit /b 0
)
echo [ERROR] Port %1 is already in use. %2 cannot start on its default port.
echo         Close the existing process or change the port in start_clawos.bat.
exit /b 1

:qwen_health
powershell -NoProfile -Command "try { $response = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:%QWEN_PORT%/health' -TimeoutSec 2; if ($response.StatusCode -eq 200) { exit 0 }; exit 1 } catch { exit 1 }"
exit /b %errorlevel%
