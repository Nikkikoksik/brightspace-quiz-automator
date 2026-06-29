#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Find Python
PY=""
if command -v python3 &>/dev/null; then
    PY="python3"
elif command -v python &>/dev/null; then
    PY="python"
else
    echo "ERROR: Python is not installed or not on PATH."
    echo "Install it with: sudo pacman -S python"
    read -rp "Press Enter to exit..."
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    "$PY" -m venv .venv
fi

# Activate it
source .venv/bin/activate

# Install dependencies if any are missing
if ! python -c "import PyQt6" &>/dev/null 2>&1; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
fi

if ! python -c "import playwright" &>/dev/null 2>&1; then
    echo "Installing playwright..."
    pip install playwright
fi

# Install Playwright browser only if not already done
if [ ! -f ".playwright_installed" ]; then
    echo "Installing Playwright browser (first time only)..."
    python -m playwright install chromium
    echo "installed" > .playwright_installed
fi

# Check for updates
python src/auto_update.py

# Launch
python gui_pyqt6.py
read -rp "Press Enter to exit..."
