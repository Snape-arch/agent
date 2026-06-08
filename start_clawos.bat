@echo off
chcp 65001 >nul
echo ============================================
echo   ClawOS - Personal AI Agent
echo ============================================
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.10+ first.
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Starting ClawOS server on http://127.0.0.1:18790
echo Press Ctrl+C to stop
echo.

cd /d "%~dp0clawos"

REM Install dependencies if needed
if not exist ".deps_installed" (
    echo [FIRST RUN] Installing dependencies...
    pip install fastapi uvicorn httpx numpy 2>nul
    if %errorlevel% equ 0 (
        echo. > .deps_installed
        echo Dependencies installed.
    ) else (
        echo [WARNING] pip install failed. Install manually: pip install -r requirements.txt
    )
)

python clawos_server.py --host 127.0.0.1 --port 18790
pause
