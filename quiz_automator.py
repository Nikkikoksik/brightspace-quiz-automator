#!/usr/bin/env python3
"""
Brightspace Quiz Automator
Bulk-updates quiz settings across a course.

Usage:
  python quiz_automator.py                 # live run
  python quiz_automator.py --dry-run       # preview only, nothing saved
  python quiz_automator.py --limit 3       # process first 3 quizzes only

Install:
  pip install playwright
  playwright install chromium
"""

import asyncio
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from browser import run

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Bulk-update quiz settings in Brightspace")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without saving")
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N quizzes")
    args = parser.parse_args()

    asyncio.run(run(dry_run=args.dry_run, limit=args.limit))
