@echo off
cd /d "%~dp0"

:: DEV LAUNCHER — runs your LOCAL code with no auto-update.
:: Use this while developing so your edits actually run.
:: (run.bat pulls the latest from GitHub first, which overwrites local changes.)

:: Find Python
set PY=
py --version >nul 2>&1
if not errorlevel 1 set PY=py
if "%PY%"=="" (
    python --version >nul 2>&1
    if not errorlevel 1 set PY=python
)
if "%PY%"=="" (
    echo ERROR: Python is not installed or not on PATH.
    pause
    exit /b 1
)

echo ============================================
echo  DEV MODE - running local code, no update.
echo  Edits hot-reload. Ctrl+C to stop.
echo ============================================
%PY% dev.py
pause
