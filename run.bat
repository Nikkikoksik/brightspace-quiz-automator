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
    %PY% -m pip install customtkinter playwright pdf2docx watchdog mammoth sentry-sdk
)
%PY% -c "import watchdog" >nul 2>&1
if errorlevel 1 %PY% -m pip install watchdog
%PY% -c "import playwright" >nul 2>&1
if errorlevel 1 %PY% -m pip install playwright
%PY% -c "import mammoth" >nul 2>&1
if errorlevel 1 %PY% -m pip install mammoth
%PY% -c "import sentry_sdk" >nul 2>&1
if errorlevel 1 %PY% -m pip install sentry-sdk

:: Install Playwright browser only if not already installed
if not exist ".playwright_installed" (
    echo Installing Playwright browser ^(first time only^)...
    %PY% -m playwright install chromium
    echo installed > .playwright_installed
)

:: Create desktop shortcut if it doesn't exist yet (uses PowerShell to find real Desktop path, handles OneDrive)
powershell -NoProfile -Command "$desk = [Environment]::GetFolderPath('Desktop'); $lnk = Join-Path $desk 'Brightspace Automator.lnk'; if (-not (Test-Path $lnk)) { $ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut($lnk); $s.TargetPath = '%~dp0run.bat'; $s.WorkingDirectory = '%~dp0'; $s.IconLocation = '%~dp0installer\assets\icon.ico'; $s.Save(); Write-Host 'Desktop shortcut created.' }"

:: Check for updates
%PY% src\auto_update.py

:: Launch
%PY% dev.py
pause
