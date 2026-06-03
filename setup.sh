#!/usr/bin/env bash
set -euo pipefail

echo "============================================"
echo "  Brightspace Quiz Automator - Setup"
echo "============================================"
echo

cd "$(dirname "$0")"

if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python is not installed or not on PATH."
    echo "Install it with: sudo pacman -S python"
    read -rp "Press Enter to exit..."
    exit 1
fi

python3 --version

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
echo "Installing Python dependencies..."
if ! pip install -r requirements.txt; then
    echo "ERROR: pip install failed."
    read -rp "Press Enter to exit..."
    exit 1
fi

echo
echo "Installing Playwright browser..."
if ! playwright install chromium; then
    echo "ERROR: Playwright browser install failed."
    read -rp "Press Enter to exit..."
    exit 1
fi

echo
echo "============================================"
echo "  Setup complete! Run ./run.sh to start."
echo "============================================"
read -rp "Press Enter to exit..."
