#!/usr/bin/env python3
"""Map CourseBridge evaluation HTML to a gradebook structure JSON."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import gradebook_automator as ga


def _read_items(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse CourseBridge evaluation HTML and sort gradebook items."
    )
    parser.add_argument("--html", required=True, type=Path,
                        help="File containing CourseBridge evaluation HTML/table output.")
    parser.add_argument("--items", required=True, type=Path,
                        help="Text file with one Brightspace gradebook item name per line.")
    args = parser.parse_args()

    structure = ga.structure_from_evaluation_html(
        args.html.read_text(encoding="utf-8"),
        _read_items(args.items),
    )
    print(json.dumps(structure, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
