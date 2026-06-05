cat > update.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail

REPO_ZIP="https://github.com/Nikkikoksik/brightspace-quiz-automator/archive/refs/heads/main.zip"
REPO_FOLDER="brightspace-quiz-automator-main"

cd "$(dirname "$0")"

echo "============================================"
echo "  Brightspace Quiz Automator - Update"
echo "============================================"
echo
echo "Downloading latest version from GitHub..."

if command -v curl &>/dev/null; then
    curl -fsSL "$REPO_ZIP" -o update.zip
elif command -v wget &>/dev/null; then
    wget -q "$REPO_ZIP" -O update.zip
else
    echo "ERROR: Neither curl nor wget is installed."
    echo "Install with: sudo pacman -S curl"
    exit 1
fi

if [ ! -f update.zip ]; then
    echo "ERROR: Download failed. Check your internet connection."
    read -rp "Press Enter to exit..."
    exit 1
fi

echo "Extracting..."
unzip -q update.zip

echo "Copying files..."
find "./$REPO_FOLDER" -mindepth 1 -maxdepth 1 ! -name "session.json" -exec cp -r {} . \;

echo "Cleaning up..."
rm -f update.zip
rm -rf "./$REPO_FOLDER"

# Re-activate venv and update dependencies
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "Updating dependencies..."
    pip install -r requirements.txt -q
else
    echo "WARNING: No .venv found — run ./setup.sh first."
fi

echo
echo "============================================"
echo "  Update complete!"
echo "============================================"
read -rp "Press Enter to exit..."
EOF
chmod +x update.sh