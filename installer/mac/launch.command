#!/usr/bin/env bash
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# Python 3 check with user-friendly error
if ! command -v python3 &>/dev/null; then
    osascript -e 'display dialog "Python 3 is required. Download from python.org/downloads" buttons {"OK"}'
    exit 1
fi

# First-time setup
if [ ! -d "$HERE/.venv" ]; then
    echo "First-time setup (takes ~5 min)..."
    python3 -m venv "$HERE/.venv"
    source "$HERE/.venv/bin/activate"
    pip install --quiet customtkinter playwright pdf2docx watchdog
    python -m playwright install chromium
    echo "installed" > "$HERE/.playwright_installed"
fi

source "$HERE/.venv/bin/activate"
python "$HERE/src/auto_update.py"
python "$HERE/gui.py"
