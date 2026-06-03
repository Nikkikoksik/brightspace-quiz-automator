@echo off
cd /d "%~dp0"

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
    echo Download it from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

:: Install dependencies if missing
%PY% -c "import customtkinter" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    %PY% -m pip install customtkinter playwright pdf2docx
)

%PY% -c "import playwright" >nul 2>&1
if errorlevel 1 (
    echo Installing playwright...
    %PY% -m pip install playwright
)

:: Install Playwright browser if missing
%PY% -m playwright install chromium >nul 2>&1

:: Launch
%PY% gui.py
pause
