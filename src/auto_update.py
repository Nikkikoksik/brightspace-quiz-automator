"""
Auto-updater: checks GitHub for a newer version and downloads it if available.
Called by run.bat on every launch. Requires no Git installation.
"""

import json
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO     = "Nikkikoksik/brightspace-quiz-automator"
API_URL  = f"https://api.github.com/repos/{REPO}/commits/main"
ZIP_URL  = f"https://github.com/{REPO}/archive/refs/heads/main.zip"
HERE     = Path(__file__).parent.parent
VERSION  = HERE / ".version"

# Files that should never be overwritten by an update
PROTECTED = {
    "session.json", "cb_session.json", "bs_session.json",
    "outline_config.json", "courses.txt", ".version",
    ".playwright_installed", "coursebridge_preview.html",
}

# Library modules that live in src/ — route them there even if the GitHub ZIP
# still ships them at the repo root (handles transition from flat → src/ layout).
SRC_FILES = {
    "actions.py", "auto_update.py", "browser.py", "config.py",
    "course_outline_automator.py", "navigation.py",
    "staging_automator.py", "staging_scraper.py",
}


def get_remote_sha() -> str | None:
    try:
        req = urllib.request.Request(API_URL, headers={"User-Agent": "brightspace-updater"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())["sha"]
    except Exception:
        return None


def get_local_sha() -> str:
    try:
        return VERSION.read_text().strip()
    except FileNotFoundError:
        return ""


def download_and_extract(sha: str):
    zip_path = HERE / "_update.zip"
    tmp_dir  = HERE / "_update_tmp"

    print("  Downloading update...")
    try:
        urllib.request.urlretrieve(ZIP_URL, zip_path)
    except Exception as e:
        print(f"  Download failed: {e}")
        return False

    print("  Extracting...")
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(tmp_dir)
    except Exception as e:
        print(f"  Extraction failed: {e}")
        return False

    # Extracted folder is named "brightspace-quiz-automator-main"
    src = tmp_dir / "brightspace-quiz-automator-main"
    if not src.exists():
        print("  Unexpected ZIP structure — skipping update")
        return False

    print("  Installing new files...")
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        if rel.parts[0] in PROTECTED or rel.name in PROTECTED:
            continue
        # Route flat-ZIP library files into src/ regardless of where they sit in the ZIP
        if item.is_file() and len(rel.parts) == 1 and rel.name in SRC_FILES:
            dest = HERE / "src" / rel.name
        else:
            dest = HERE / rel
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)

    VERSION.write_text(sha)
    return True


def cleanup():
    for path in [HERE / "_update.zip", HERE / "_update_tmp"]:
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)


def main(ask_restart_fn=None):
    """
    ask_restart_fn: optional callable that shows a dialog and returns True to restart.
    If None, falls back to a terminal prompt (CLI mode).
    """
    if (HERE / ".git").exists():
        return

    print("Checking for updates...")
    remote_sha = get_remote_sha()

    if remote_sha is None:
        print("  Could not reach GitHub — skipping update check")
        return

    local_sha = get_local_sha()

    if not local_sha:
        # Fresh install — record current SHA so we don't re-download on next launch
        VERSION.write_text(remote_sha)
        print("  Fresh install — version recorded, no update needed")
        return

    if remote_sha == local_sha:
        print("  Already up to date")
        return

    print(f"  New version available — updating...")
    if download_and_extract(remote_sha):
        cleanup()
        print("  ✓ Updated successfully.")
        if ask_restart_fn is not None:
            if ask_restart_fn():
                os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            ans = input("  Restart now to apply the update? (y/n): ").strip().lower()
            if ans == "y":
                os.execv(sys.executable, [sys.executable] + sys.argv)
            else:
                print("  Skipping restart — update will apply next launch.")
    else:
        print("  Update failed — running current version")
        cleanup()


if __name__ == "__main__":
    main()
