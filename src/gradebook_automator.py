#!/usr/bin/env python3
"""
Gradebook Automator — outline → AI-proposed categories → review → apply.
fetch_gradebook_items / apply_categories are STUBS until the live
Brightspace walkthrough (see design spec 2026-07-02).
"""
import json
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

_HERE   = Path(__file__).parent.parent
BS_BASE = "https://learn.okanagancollege.ca"


def _parse_ai_response(text: str, gradebook_items: list[str]) -> dict:
    """
    Parse the AI's JSON reply into a structure dict.
    Drops items the AI invented; real items the AI missed go to "uncategorized".
    Raises ValueError if no usable JSON or no categories found.
    """
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in AI response")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"AI response is not valid JSON: {e}")

    raw_cats = data.get("categories") or []
    if not raw_cats:
        raise ValueError("AI response contained no categories")

    known = set(gradebook_items)
    seen: set[str] = set()
    categories = []
    for c in raw_cats:
        items = [i for i in c.get("items", []) if i in known]
        seen.update(items)
        categories.append({
            "name":   str(c.get("name", "")).strip() or "Unnamed",
            "weight": float(c.get("weight", 0)),
            "items":  items,
        })
    uncategorized = [i for i in gradebook_items if i not in seen]
    return {"categories": categories, "uncategorized": uncategorized}
