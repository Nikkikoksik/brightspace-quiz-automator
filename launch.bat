@echo off
cd /d "%~dp0"

:: Try bundled Python first
set PY=%~dp0python\python.exe
if exist "%PY%" goto :run

:: Fall back to system Python
py --version >nul 2>&1
if not errorlevel 1 (
    set PY=py
    goto :run
)

python --version >nul 2>&1
if not errorlevel 1 (
    set PY=python
    goto :run
)

echo ERROR: Python not found. Please reinstall Brightspace Automator.
pause & exit /b 1

:run
"%PY%" src\auto_update.py
"%PY%" -c "import PyQt6" >nul 2>&1
if errorlevel 1 "%PY%" -m pip install PyQt6 -q
"%PY%" gui_pyqt6.py
pause
