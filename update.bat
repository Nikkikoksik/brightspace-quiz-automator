@echo off
:: ── UPDATE THIS after you create the GitHub repo ──────────────────────────
set REPO_ZIP=https://github.com/Nikkikoksik/brightspace-quiz-automator/archive/refs/heads/main.zip
set REPO_FOLDER=brightspace-quiz-automator-main
:: ──────────────────────────────────────────────────────────────────────────

cd /d "%~dp0"
echo ============================================
echo   Brightspace Quiz Automator - Update
echo ============================================
echo.
echo Downloading latest version from GitHub...

powershell -Command "Invoke-WebRequest -Uri '%REPO_ZIP%' -OutFile 'update.zip'"
if errorlevel 1 (
    echo ERROR: Download failed. Check your internet connection.
    pause
    exit /b 1
)

echo Extracting...
powershell -Command "Expand-Archive -Path 'update.zip' -DestinationPath '.' -Force"

echo Copying files...
powershell -Command "Get-ChildItem -Path '.\%REPO_FOLDER%' | Where-Object { $_.Name -ne 'session.json' } | Copy-Item -Destination '.' -Recurse -Force"

echo Cleaning up...
del update.zip
rmdir /s /q "%REPO_FOLDER%"

echo Updating dependencies...
pip install -r requirements.txt -q

echo.
echo ============================================
echo   Update complete!
echo ============================================
pause
