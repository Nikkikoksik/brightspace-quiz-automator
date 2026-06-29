#!/usr/bin/env bash
VERSION=$(python3 -c "import re; print(re.search(r'VERSION\\s*=\\s*\"(.*?)\"', open('gui/constants.py').read()).group(1))")
STAGE="/tmp/BrightspaceAutomator_staging/BrightspaceAutomator"
mkdir -p "$STAGE" dist

rsync -av \
  --exclude='.venv' --exclude='.git' --exclude='__pycache__' \
  --exclude='*.pyc' --exclude='session.json' --exclude='bs_session.json' \
  --exclude='cb_session.json' --exclude='outline_config.json' \
  --exclude='courses.txt' --exclude='.version' --exclude='.playwright_installed' \
  --exclude='downloads' --exclude='installer' --exclude='.github' \
  --exclude='.claude' --exclude='bs_profile' \
  . "$STAGE/"

cp installer/mac/launch.command "$STAGE/"
chmod +x "$STAGE/launch.command"

# Write README with Gatekeeper instructions
cat > "$STAGE/README.txt" << 'EOF'
1. Drag BrightspaceAutomator folder to /Applications/
2. Double-click launch.command
3. First time: right-click launch.command → Open (macOS security step)
4. First launch installs packages + Chromium (~5 min, one-time)
EOF

hdiutil create -volname "Brightspace Automator" \
  -srcfolder "/tmp/BrightspaceAutomator_staging" \
  -ov -format UDZO "dist/BrightspaceAutomator-${VERSION}-mac.dmg"
