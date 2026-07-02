#!/usr/bin/env python3
"""
Brightspace Quiz Automator — CLI entry point.
For the GUI, run: python gui_pyqt6.py  (or double-click run.bat)

Usage:
  python quiz_automator.py
  python quiz_automator.py --dry-run
  python quiz_automator.py --limit 3
  python quiz_automator.py --url https://...
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from browser import run
from config import SETTINGS, COURSES_FILE


def load_courses() -> list[str]:
    try:
        with open(COURSES_FILE) as f:
            return [l.strip() for l in f if l.strip() and not l.startswith("#")]
    except FileNotFoundError:
        return []


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Bulk-update quiz settings in Brightspace")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    parser.add_argument("--limit", type=int, default=None, help="Process only first N quizzes")
    parser.add_argument("--url", type=str, default=None, help="Single URL (skips courses.txt)")
    args = parser.parse_args()

    urls = [args.url] if args.url else load_courses()
    if not urls:
        print("No URLs found. Add them to courses.txt or use --url.")
        sys.exit(1)

    asyncio.run(run(urls=urls, dry_run=args.dry_run, settings=SETTINGS, limit=args.limit))
