@echo off
if "%~1"=="" start /min "" "%~f0" skip & exit /b
cd /d "%~dp0"
set PY=%~dp0python\python.exe
set PYW=%~dp0python\pythonw.exe
if not exist "%PY%" (
    echo ERROR: Python not found. Please reinstall Brightspace Automator.
    pause & exit /b 1
)
"%PY%" auto_update.py
start "" "%PYW%" gui.py
