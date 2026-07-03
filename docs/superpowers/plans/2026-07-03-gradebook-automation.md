# Gradebook Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New "Gradebook" tab that reads a course outline, AI-proposes categories/weights/item assignments, lets the user correct them on a drag-and-drop board, then applies to Brightspace one category at a time.

**Architecture:** Backend logic in `src/gradebook_automator.py` (outline fetch, AI extraction, two stubbed Brightspace-DOM functions). Drag-and-drop board as a standalone widget in `gui/gradebook_board.py`. Panel mixin in `gui/panels/gradebook.py` follows the existing staging-panel pattern (worker thread + `_log_queue` + `_ThreadBridge`). Settings tab gains an AI provider dropdown + 3 API-key fields persisted in `outline_config.json`.

**Tech Stack:** Python 3.11+, PyQt6, Playwright (async), stdlib `urllib.request` for AI HTTP calls (no new dependencies), pytest.

## Global Constraints

- Working style: implementer commits after each task; user confirms before merging nick→dev (repo rule).
- No new pip dependencies — AI providers called via stdlib `urllib.request`.
- `fetch_gradebook_items` and `apply_categories` are STUBS in this plan (spec: real implementations come from a live Brightspace walkthrough with the user; do not guess selectors).
- Follow existing conventions: panel = mixin class in `gui/panels/`, worker threads redirect `sys.stdout` to `_log_queue` with a panel tag, config persisted via `_save_config`/`_load_config` in `gui_pyqt6.py` (`outline_config.json`).
- Log tag for the new panel: `"gradebook"`.
- Canned comment texts must be copied verbatim from the spec (Tasks 8/9).
- Structure dict shape used everywhere:
  ```python
  {"categories": [{"name": str, "weight": float, "items": [str, ...]}],
   "uncategorized": [str, ...]}
  ```

## Open question (flag to user before Task 8)

Spec says scenario 1 and 3 "add the comment" but not WHERE the comment goes (Brightspace? tracking sheet?). Plan implements: comment printed to log + copied to clipboard. Confirm destination with user during Task 8 review.

---

### Task 1: AI response parsing + validation

**Files:**
- Create: `src/gradebook_automator.py`
- Create: `tests/test_gradebook.py`

**Interfaces:**
- Produces: `_parse_ai_response(text: str, gradebook_items: list[str]) -> dict` (structure dict per Global Constraints). Raises `ValueError` on unparseable input. Items the AI invents are dropped; real items the AI missed go to `"uncategorized"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_gradebook.py
"""Tests for src/gradebook_automator.py — AI parsing, prompt, outline text helpers."""
import pytest
import gradebook_automator as ga


ITEMS = ["Quiz 1", "Quiz 2", "Final Exam", "Project"]

GOOD_JSON = '''
{"categories": [
  {"name": "Quizzes", "weight": 20, "items": ["Quiz 1", "Quiz 2"]},
  {"name": "Final Exam", "weight": 50, "items": ["Final Exam"]},
  {"name": "Project", "weight": 30, "items": ["Project"]}
]}
'''


def test_parse_plain_json():
    s = ga._parse_ai_response(GOOD_JSON, ITEMS)
    assert [c["name"] for c in s["categories"]] == ["Quizzes", "Final Exam", "Project"]
    assert s["categories"][0]["weight"] == 20.0
    assert s["uncategorized"] == []


def test_parse_markdown_fenced_json():
    fenced = "Here you go:\n```json\n" + GOOD_JSON + "\n```\nDone."
    s = ga._parse_ai_response(fenced, ITEMS)
    assert len(s["categories"]) == 3


def test_hallucinated_item_dropped():
    bad = '{"categories": [{"name": "Quizzes", "weight": 100, "items": ["Quiz 1", "Ghost Quiz"]}]}'
    s = ga._parse_ai_response(bad, ["Quiz 1"])
    assert s["categories"][0]["items"] == ["Quiz 1"]


def test_missed_item_goes_uncategorized():
    partial = '{"categories": [{"name": "Quizzes", "weight": 100, "items": ["Quiz 1"]}]}'
    s = ga._parse_ai_response(partial, ["Quiz 1", "Forgotten"])
    assert s["uncategorized"] == ["Forgotten"]


def test_unparseable_raises():
    with pytest.raises(ValueError):
        ga._parse_ai_response("no json here at all", ITEMS)


def test_no_categories_raises():
    with pytest.raises(ValueError):
        ga._parse_ai_response('{"categories": []}', ITEMS)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest tests/test_gradebook.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gradebook_automator'` (conftest.py already puts `src/` on the path for existing tests — check `tests/conftest.py`; if it doesn't, add `src` to `sys.path` there the same way the other test files get `config`/`browser`).

- [ ] **Step 3: Write minimal implementation**

```python
# src/gradebook_automator.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -m pytest tests/test_gradebook.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/gradebook_automator.py tests/test_gradebook.py
git commit -m "feat(gradebook): AI response parsing with item validation"
```

---

### Task 2: extract_categories + provider calls (Claude / GPT / Gemini)

**Files:**
- Modify: `src/gradebook_automator.py`
- Modify: `tests/test_gradebook.py`

**Interfaces:**
- Consumes: `_parse_ai_response` (Task 1)
- Produces: `extract_categories(outline_text: str, gradebook_items: list[str], provider: str, api_key: str) -> dict` — provider is `"claude" | "gpt" | "gemini"`; raises `ValueError` for unknown provider or unparseable reply. Also `_build_prompt(outline_text, gradebook_items) -> str` and `_call_claude/_call_gpt/_call_gemini(prompt: str, api_key: str) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gradebook.py`:

```python
def test_build_prompt_mentions_items_and_table_hint():
    p = ga._build_prompt("outline text", ["Quiz 1"])
    assert "Quiz 1" in p
    assert "100" in p          # sums-to-~100% guidance
    assert "JSON" in p


def test_extract_categories_dispatch(monkeypatch):
    calls = {}
    def fake_claude(prompt, api_key):
        calls["key"] = api_key
        return GOOD_JSON
    monkeypatch.setattr(ga, "_call_claude", fake_claude)
    s = ga.extract_categories("outline", ITEMS, "claude", "sk-test")
    assert calls["key"] == "sk-test"
    assert len(s["categories"]) == 3


def test_extract_categories_unknown_provider():
    with pytest.raises(ValueError):
        ga.extract_categories("outline", ITEMS, "grok", "k")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest tests/test_gradebook.py -v`
Expected: 3 new FAIL — `AttributeError: module 'gradebook_automator' has no attribute '_build_prompt'`

- [ ] **Step 3: Write implementation**

Append to `src/gradebook_automator.py`:

```python
import urllib.request


def _build_prompt(outline_text: str, gradebook_items: list[str]) -> str:
    items_list = "\n".join(f"- {i}" for i in gradebook_items)
    return f"""You are helping set up a Brightspace gradebook from a course outline.

Most outlines contain a two-column weighting table ("Course Component" /
"Percentage of Final Grade") with one row per component and a Total of ~100%.
Find that structure (it may also be free-form text).

The gradebook currently contains these items (use these EXACT names):
{items_list}

Course outline text:
---
{outline_text}
---

Reply with ONLY a JSON object, no other text:
{{"categories": [{{"name": "<category name>", "weight": <number>, "items": ["<exact item name>", ...]}}]}}

Rules:
- Weights should sum to approximately 100.
- Assign every gradebook item to the best-fitting category.
- Only use item names from the list above. If an item fits nowhere, omit it.
- If you cannot find any weighting information at all, reply: {{"categories": []}}
"""


def _http_json(url: str, headers: dict, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _call_claude(prompt: str, api_key: str) -> str:
    data = _http_json(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        {"model": "claude-sonnet-5", "max_tokens": 4096,
         "messages": [{"role": "user", "content": prompt}]},
    )
    return data["content"][0]["text"]


def _call_gpt(prompt: str, api_key: str) -> str:
    data = _http_json(
        "https://api.openai.com/v1/chat/completions",
        {"Authorization": f"Bearer {api_key}"},
        {"model": "gpt-4o", "messages": [{"role": "user", "content": prompt}]},
    )
    return data["choices"][0]["message"]["content"]


def _call_gemini(prompt: str, api_key: str) -> str:
    data = _http_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
        {},
        {"contents": [{"parts": [{"text": prompt}]}]},
    )
    return data["candidates"][0]["content"]["parts"][0]["text"]


_PROVIDERS = {"claude": _call_claude, "gpt": _call_gpt, "gemini": _call_gemini}


def extract_categories(outline_text: str, gradebook_items: list[str],
                       provider: str, api_key: str) -> dict:
    """One provider-agnostic entry point — nothing else touches a specific API."""
    call = _PROVIDERS.get(provider)
    if call is None:
        raise ValueError(f"Unknown AI provider: {provider!r}")
    prompt = _build_prompt(outline_text, gradebook_items)
    reply = call(prompt, api_key)
    return _parse_ai_response(reply, gradebook_items)
```

NOTE: `extract_categories` looks up `_PROVIDERS` at call time via `ga._call_claude`? No — the dict captures the original functions, so monkeypatching `ga._call_claude` would NOT be seen. To keep the test working, resolve dynamically instead:

```python
def extract_categories(outline_text, gradebook_items, provider, api_key):
    names = {"claude": "_call_claude", "gpt": "_call_gpt", "gemini": "_call_gemini"}
    fn_name = names.get(provider)
    if fn_name is None:
        raise ValueError(f"Unknown AI provider: {provider!r}")
    call = globals()[fn_name]
    prompt = _build_prompt(outline_text, gradebook_items)
    reply = call(prompt, api_key)
    return _parse_ai_response(reply, gradebook_items)
```

Use the dynamic version; delete the `_PROVIDERS` dict.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -m pytest tests/test_gradebook.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/gradebook_automator.py tests/test_gradebook.py
git commit -m "feat(gradebook): extract_categories with Claude/GPT/Gemini providers"
```

---

### Task 3: fetch_outline_text (live syllabus scrape) + local-file fallback

**Files:**
- Modify: `src/gradebook_automator.py`
- Modify: `tests/test_gradebook.py`

**Interfaces:**
- Consumes: Brightspace TOC API pattern from `course_outline_automator._get_topic_id` (`/d2l/api/le/1.4/{ou}/content/toc`, topic title `"Course Syllabus"`).
- Produces:
  - `_html_to_text(html: str) -> str` (pure, tested)
  - `async fetch_outline_text(page, course_id: str) -> str` — returns `""` when topic missing/empty
  - `extract_text_from_file(path: Path) -> str` — `.pdf` via `pdf2docx` → docx, `.docx` via `mammoth.extract_raw_text`
  - `is_placeholder(text: str) -> bool` — True when stripped text < 100 chars

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gradebook.py`:

```python
def test_html_to_text_strips_tags_and_scripts():
    html = "<html><head><style>x{}</style></head><body><h1>Weights</h1><script>bad()</script><p>Quiz 10%</p></body></html>"
    text = ga._html_to_text(html)
    assert "Weights" in text and "Quiz 10%" in text
    assert "bad()" not in text and "x{}" not in text


def test_is_placeholder():
    assert ga.is_placeholder("")
    assert ga.is_placeholder("   \n  short  ")
    assert not ga.is_placeholder("x" * 200)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest tests/test_gradebook.py -v`
Expected: 2 new FAIL — missing attributes

- [ ] **Step 3: Write implementation**

Append to `src/gradebook_automator.py`:

```python
import html as _htmllib


def _html_to_text(html: str) -> str:
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<[^>]+>', ' ', html)
    text = _htmllib.unescape(html)
    return re.sub(r'[ \t]+', ' ', text).strip()


def is_placeholder(text: str) -> bool:
    return len(text.strip()) < 100


async def fetch_outline_text(page, course_id: str) -> str:
    """
    Scrape the live Course Syllabus topic HTML via the Brightspace TOC API
    (same lookup course_outline_automator uses) and return plain text.
    Returns "" when the topic doesn't exist or its content is empty.
    """
    toc_url = f"{BS_BASE}/d2l/api/le/1.4/{course_id}/content/toc"
    toc = await page.evaluate(f"""
        async () => {{
            const r = await fetch('{toc_url}');
            return r.ok ? await r.json() : null;
        }}
    """)
    if not toc:
        return ""

    def find_topic(node):
        for t in node.get("Topics", []):
            if t.get("Title", "").strip() == "Course Syllabus":
                return t
        for m in node.get("Modules", []):
            r = find_topic(m)
            if r:
                return r
        return None

    topic = find_topic(toc)
    if not topic:
        print("  No 'Course Syllabus' topic found")
        return ""
    topic_url = topic.get("Url", "")
    if not topic_url:
        return ""
    html = await page.evaluate(f"""
        async () => {{
            const r = await fetch('{BS_BASE}{topic_url}');
            return r.ok ? await r.text() : '';
        }}
    """)
    return _html_to_text(html)


def extract_text_from_file(path: Path) -> str:
    """Local-file fallback: .pdf converted via pdf2docx first, then mammoth."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        from pdf2docx import Converter
        docx_path = path.with_suffix(".docx")
        cv = Converter(str(path))
        cv.convert(str(docx_path))
        cv.close()
        path = docx_path
    import mammoth
    with open(path, "rb") as f:
        return mammoth.extract_raw_text(f).value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -m pytest tests/test_gradebook.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/gradebook_automator.py tests/test_gradebook.py
git commit -m "feat(gradebook): outline text fetch (live syllabus + local file fallback)"
```

---

### Task 4: Stub the two Brightspace-DOM functions

**Files:**
- Modify: `src/gradebook_automator.py`

**Interfaces:**
- Produces (STUBS — real bodies come from live walkthrough):
  - `async fetch_gradebook_items(page, course_id: str) -> list[str]`
  - `async apply_categories(page, structure: dict, step_fn) -> None` — `step_fn(category_name: str)` called before each category, may block (mirrors staging `prompt_fn`)

- [ ] **Step 1: Write the stubs**

Append to `src/gradebook_automator.py`:

```python
# ─── STUBS — to be implemented via live Brightspace walkthrough ──────────────
# (spec 2026-07-02: do NOT guess Grades-page selectors; the user demonstrates
# the real click-path and that becomes the implementation.)

async def fetch_gradebook_items(page, course_id: str) -> list[str]:
    """STUB: read existing gradebook item names from the Grades page."""
    print("  ⚠ STUB fetch_gradebook_items — returning sample data")
    return ["[STUB] Quiz 1", "[STUB] Assignment 1", "[STUB] Final Exam"]


async def apply_categories(page, structure: dict, step_fn) -> None:
    """STUB: create categories and move items via the Grades UI, one category
    at a time; step_fn(name) pauses before each category."""
    for cat in structure["categories"]:
        step_fn(cat["name"])
        print(f"  ⚠ STUB apply_categories — would create '{cat['name']}' "
              f"({cat['weight']}%) with {len(cat['items'])} item(s)")
```

- [ ] **Step 2: Verify imports still clean**

Run: `py -m pytest tests/test_gradebook.py -q`
Expected: 11 passed

- [ ] **Step 3: Commit**

```bash
git add src/gradebook_automator.py
git commit -m "feat(gradebook): stub fetch_gradebook_items and apply_categories"
```

---

### Task 5: Settings — AI provider dropdown + API key fields

**Files:**
- Modify: `gui/panels/settings.py`
- Modify: `gui_pyqt6.py` (`_load_config` ~line 405, `_save_config` ~line 422)

**Interfaces:**
- Produces: config keys in `outline_config.json`: `ai_provider` (`"claude"|"gpt"|"gemini"`), `claude_api_key`, `gpt_api_key`, `gemini_api_key`. Panel reads them via `self._ai_provider_combo.currentText().lower()` etc. Gradebook panel (Task 7) consumes these via `self._load_gradebook_creds()` helper added here.

- [ ] **Step 1: Add the AI PROVIDER card to `_build_settings_panel`**

In `gui/panels/settings.py`, add `QComboBox` to imports, then insert after the Sentry card (before the Save button):

```python
        self._section_label(layout, "AI PROVIDER (GRADEBOOK)")
        ai_frame  = QFrame()
        ai_frame.setStyleSheet(_card())
        ai_layout = QVBoxLayout(ai_frame)
        ai_layout.setContentsMargins(16, 16, 16, 16)
        ai_layout.setSpacing(8)
        ai_layout.addWidget(QLabel("Provider"))
        self._ai_provider_combo = QComboBox()
        self._ai_provider_combo.addItems(["Claude", "GPT", "Gemini"])
        self._ai_provider_combo.setFixedHeight(36)
        self._ai_provider_combo.setStyleSheet(_entry_style())
        ai_layout.addWidget(self._ai_provider_combo)
        self._ai_key_fields = {}
        for label, key in [("Claude API key", "claude"), ("GPT API key", "gpt"),
                           ("Gemini API key", "gemini")]:
            ai_layout.addWidget(QLabel(label))
            field = QLineEdit()
            field.setFixedHeight(36)
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setStyleSheet(_entry_style())
            ai_layout.addWidget(field)
            self._ai_key_fields[key] = field
        layout.addWidget(ai_frame)
        layout.addSpacing(16)
```

- [ ] **Step 2: Extend `_save_settings` in the same file**

```python
    def _save_settings(self):
        dsn = self._sentry_dsn.text().strip()
        self._save_config(
            email=self._cb_email.text().strip(),
            password=self._cb_password.text().strip(),
            sentry_dsn=dsn,
            bs_username=self._bs_username.text().strip(),
            bs_password=self._bs_password.text().strip(),
            ai_provider=self._ai_provider_combo.currentText().lower(),
            claude_api_key=self._ai_key_fields["claude"].text().strip(),
            gpt_api_key=self._ai_key_fields["gpt"].text().strip(),
            gemini_api_key=self._ai_key_fields["gemini"].text().strip(),
        )
        _init_sentry(dsn)
        self._save_settings_btn.setText("✓  Saved")
        QTimer.singleShot(1500, lambda: self._save_settings_btn.setText("Save Settings"))
```

- [ ] **Step 3: Extend `_save_config` / `_load_config` in `gui_pyqt6.py`**

Add the four parameters to `_save_config` (same `if X is not None: cfg["x"] = X` pattern as the existing keys) and mirror reads in `_load_config`:

```python
            if cfg.get("ai_provider"):
                idx = {"claude": 0, "gpt": 1, "gemini": 2}.get(cfg["ai_provider"], 0)
                self._ai_provider_combo.setCurrentIndex(idx)
            for k in ("claude", "gpt", "gemini"):
                if cfg.get(f"{k}_api_key"):
                    self._ai_key_fields[k].setText(cfg[f"{k}_api_key"])
```

Also add a helper next to `_load_config` for the gradebook panel:

```python
    def _load_gradebook_creds(self) -> tuple[str, str]:
        """Return (provider, api_key) from saved config."""
        try:
            with open(OUTLINE_CFG) as f:
                cfg = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            cfg = {}
        provider = cfg.get("ai_provider", "claude")
        return provider, cfg.get(f"{provider}_api_key", "")
```

- [ ] **Step 4: Manual check**

Run: `dev.bat` → Settings tab shows AI PROVIDER card; save, restart, values persist in `outline_config.json`.

- [ ] **Step 5: Commit**

```bash
git add gui/panels/settings.py gui_pyqt6.py
git commit -m "feat(settings): AI provider dropdown and API key fields"
```

---

### Task 6: Drag-and-drop review board widget

**Files:**
- Create: `gui/gradebook_board.py`
- Modify: `tests/test_gradebook.py`

**Interfaces:**
- Produces: `GradebookBoard(QWidget)` with:
  - `load_structure(structure: dict) -> None` — rebuilds columns (incl. an "Uncategorized" column when `uncategorized` non-empty)
  - `to_structure() -> dict` — reads current columns/weights back into a structure dict (Uncategorized column maps to `"uncategorized"`)
  - `add_category(name: str = "New Category", weight: float = 0.0)` — also wired to a "+ Add Category" button inside the widget
  - **No auto-rebalancing anywhere** (spec).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gradebook.py`:

```python
def test_board_round_trip(qapp):
    from gui.gradebook_board import GradebookBoard
    s = {"categories": [{"name": "Quizzes", "weight": 25.0, "items": ["Q1", "Q2"]}],
         "uncategorized": ["Orphan"]}
    board = GradebookBoard()
    board.load_structure(s)
    out = board.to_structure()
    assert out["categories"][0]["name"] == "Quizzes"
    assert out["categories"][0]["weight"] == 25.0
    assert set(out["categories"][0]["items"]) == {"Q1", "Q2"}
    assert out["uncategorized"] == ["Orphan"]
```

And add the fixture at the top of the file (after imports):

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -m pytest tests/test_gradebook.py::test_board_round_trip -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gui.gradebook_board'`

- [ ] **Step 3: Write implementation**

```python
# gui/gradebook_board.py
"""Drag-and-drop review board: columns = categories, cards = gradebook items.
No auto-rebalancing — weights only change when the user types them."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QPushButton, QScrollArea, QVBoxLayout, QWidget, QFrame,
)

from gui.theme import T, _btn, _card, _entry_style

UNCATEGORIZED = "Uncategorized"


class _Column(QFrame):
    def __init__(self, name: str, weight: float | None, on_remove=None):
        super().__init__()
        self.setStyleSheet(_card())
        self.setFixedWidth(210)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        self.name_edit = QLineEdit(name)
        self.name_edit.setStyleSheet(_entry_style())
        self.name_edit.setFixedHeight(30)
        lay.addWidget(self.name_edit)

        self.weight_edit = None
        if weight is not None:                      # Uncategorized has no weight
            row = QHBoxLayout()
            self.weight_edit = QLineEdit(f"{weight:g}")
            self.weight_edit.setStyleSheet(_entry_style())
            self.weight_edit.setFixedHeight(28)
            self.weight_edit.setFixedWidth(60)
            row.addWidget(self.weight_edit)
            row.addWidget(QLabel("%"))
            row.addStretch()
            lay.addLayout(row)

        self.items = QListWidget()
        self.items.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.items.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.items.setMinimumHeight(160)
        lay.addWidget(self.items)

    def weight(self) -> float:
        if self.weight_edit is None:
            return 0.0
        try:
            return float(self.weight_edit.text())
        except ValueError:
            return 0.0

    def item_names(self) -> list[str]:
        return [self.items.item(i).text() for i in range(self.items.count())]


class GradebookBoard(QWidget):
    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._add_btn = QPushButton("+  Add Category")
        self._add_btn.setFixedHeight(32)
        self._add_btn.setStyleSheet(_btn(T["btn_muted"], T["btn_muted_h"]))
        self._add_btn.clicked.connect(lambda: self.add_category())
        outer.addWidget(self._add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(280)
        inner = QWidget()
        self._cols_layout = QHBoxLayout(inner)
        self._cols_layout.setSpacing(10)
        self._cols_layout.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        self._columns: list[_Column] = []

    def _clear(self):
        for col in self._columns:
            col.setParent(None)
        self._columns = []

    def add_category(self, name: str = "New Category", weight: float = 0.0,
                     items: list[str] | None = None, uncategorized: bool = False):
        col = _Column(name, None if uncategorized else weight)
        for it in items or []:
            col.items.addItem(it)
        self._cols_layout.insertWidget(self._cols_layout.count() - 1, col)
        self._columns.append(col)
        return col

    def load_structure(self, structure: dict):
        self._clear()
        for cat in structure.get("categories", []):
            self.add_category(cat["name"], cat["weight"], cat["items"])
        unc = structure.get("uncategorized", [])
        if unc:
            self.add_category(UNCATEGORIZED, items=unc, uncategorized=True)

    def to_structure(self) -> dict:
        categories, uncategorized = [], []
        for col in self._columns:
            if col.name_edit.text().strip() == UNCATEGORIZED:
                uncategorized.extend(col.item_names())
            else:
                categories.append({
                    "name":   col.name_edit.text().strip(),
                    "weight": col.weight(),
                    "items":  col.item_names(),
                })
        return {"categories": categories, "uncategorized": uncategorized}
```

Check `gui/theme.py` exposes `btn_muted`/`btn_muted_h` (used by `_gear_button` styling already); if named differently, match existing names.

- [ ] **Step 4: Run tests**

Run: `py -m pytest tests/test_gradebook.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add gui/gradebook_board.py tests/test_gradebook.py
git commit -m "feat(gradebook): drag-and-drop review board widget"
```

---

### Task 7: Gradebook panel skeleton + app registration

**Files:**
- Create: `gui/panels/gradebook.py`
- Modify: `gui_pyqt6.py` (panel registry, sidebar nav list after "Course Outline", `_poll_log` box map + `__DONE__` handling for tag `"gradebook"`)

**Interfaces:**
- Consumes: `GradebookBoard` (Task 6), `self._panel_scroll/_panel_header/_section_label/_make_log/_log_append` helpers, `self._log_queue`, `self._bridge`.
- Produces: `GradebookPanelMixin._build_gradebook_panel(parent)`; instance attrs `self._gradebook_log`, `self._gb_fetch_btn`, `self._gb_apply_btn`, `self._gb_board`, `self._gb_course` (QLineEdit); log tag `"gradebook"`.

- [ ] **Step 1: Create the panel skeleton**

```python
# gui/panels/gradebook.py
import asyncio
import sys
import threading

from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget,
)

from gui.gradebook_board import GradebookBoard
from gui.telemetry import _sentry_capture, _sentry_context
from gui.theme import T, _btn, _entry_style


class GradebookPanelMixin:

    def _build_gradebook_panel(self, parent: QWidget):
        layout = self._panel_scroll(parent)
        self._panel_header(layout, "Gradebook",
                           "AI-assisted gradebook categories from the course outline")

        self._section_label(layout, "COURSE  —  CRN OR BRIGHTSPACE URL")
        self._gb_course = QLineEdit()
        self._gb_course.setPlaceholderText(
            "e.g. 31899  or  https://learn.okanagancollege.ca/d2l/home/…")
        self._gb_course.setFixedHeight(40)
        self._gb_course.setStyleSheet(_entry_style())
        layout.addWidget(self._gb_course)
        layout.addSpacing(10)

        btn_row = QHBoxLayout()
        self._gb_fetch_btn = QPushButton("▶   Fetch Outline + Gradebook")
        self._gb_fetch_btn.setFixedHeight(44)
        self._gb_fetch_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"]))
        self._gb_fetch_btn.clicked.connect(self._start_gb_fetch)
        btn_row.addWidget(self._gb_fetch_btn)

        self._gb_file_btn = QPushButton("Use Local File…")
        self._gb_file_btn.setFixedHeight(44)
        self._gb_file_btn.setStyleSheet(_btn(T["btn_muted"], T["btn_muted_h"]))
        self._gb_file_btn.clicked.connect(self._gb_pick_file)
        btn_row.addWidget(self._gb_file_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addSpacing(12)

        # Scenario banner (hidden until fetch decides which scenario applies)
        self._gb_banner = QLabel("")
        self._gb_banner.setWordWrap(True)
        self._gb_banner.setStyleSheet(f"color: {T['warn']}; font-size: 12px;")
        self._gb_banner.hide()
        layout.addWidget(self._gb_banner)

        banner_row = QHBoxLayout()
        self._gb_termwork_btn = QPushButton("Create Term Work category (100%)")
        self._gb_termwork_btn.setFixedHeight(36)
        self._gb_termwork_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"]))
        self._gb_termwork_btn.clicked.connect(self._gb_term_work)
        self._gb_termwork_btn.hide()
        banner_row.addWidget(self._gb_termwork_btn)

        self._gb_skip_btn = QPushButton("Not a standard outline — skip gradebook")
        self._gb_skip_btn.setFixedHeight(36)
        self._gb_skip_btn.setStyleSheet(_btn(T["btn_danger"], T["btn_danger_h"]))
        self._gb_skip_btn.clicked.connect(self._gb_skip_nonstandard)
        self._gb_skip_btn.hide()
        banner_row.addWidget(self._gb_skip_btn)
        banner_row.addStretch()
        layout.addLayout(banner_row)
        layout.addSpacing(12)

        self._section_label(layout, "REVIEW BOARD")
        self._gb_board = GradebookBoard()
        layout.addWidget(self._gb_board)
        layout.addSpacing(12)

        self._gb_apply_btn = QPushButton("▶   Apply to Brightspace (step-by-step)")
        self._gb_apply_btn.setFixedHeight(44)
        self._gb_apply_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"]))
        self._gb_apply_btn.clicked.connect(self._start_gb_apply)
        self._gb_apply_btn.setEnabled(False)
        layout.addWidget(self._gb_apply_btn)
        layout.addSpacing(16)

        self._section_label(layout, "LOG")
        self._gradebook_log = self._make_log(layout, min_height=200)
        layout.addStretch()

    # Worker methods land in Task 8/9 — temporary placeholders so the app runs:
    def _start_gb_fetch(self):
        self._log_append(self._gradebook_log, "Fetch flow arrives in Task 8.")

    def _gb_pick_file(self):
        self._log_append(self._gradebook_log, "Local-file flow arrives in Task 8.")

    def _gb_term_work(self):
        pass

    def _gb_skip_nonstandard(self):
        pass

    def _start_gb_apply(self):
        self._log_append(self._gradebook_log, "Apply flow arrives in Task 9.")
```

(These four placeholders are the ONLY permitted "later task" stubs — they are replaced wholesale in Tasks 8–9, and the panel is not user-visible-broken: buttons log a clear message.)

- [ ] **Step 2: Register in `gui_pyqt6.py`**

1. Import: `from gui.panels.gradebook import GradebookPanelMixin` (match how other panel mixins are imported) and add `GradebookPanelMixin` to the main window's base-class list.
2. Sidebar: in `_build_sidebar`, add `("Gradebook", "Gradebook"),` after `("Course Outline", "Course Outline"),`.
3. Panel registry: wherever panels are built (`self._panels[key] = panel` loop near line 100), add `"Gradebook"` → `self._build_gradebook_panel`.
4. `_poll_log` box map: add `"gradebook": getattr(self, "_gradebook_log", None),`.
5. `__DONE__` handling: add branch

```python
                    elif tag == "gradebook":
                        self._gb_fetch_btn.setEnabled(True)
                        self._gb_fetch_btn.setText("▶   Fetch Outline + Gradebook")
```

- [ ] **Step 3: Manual check**

Run: `dev.bat` → new Gradebook tab renders: course field, fetch/file buttons, empty board with "+ Add Category", disabled Apply, log. Clicking Fetch logs the Task-8 placeholder line.

- [ ] **Step 4: Run full test suite**

Run: `py -m pytest tests/ -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add gui/panels/gradebook.py gui_pyqt6.py
git commit -m "feat(gradebook): panel skeleton and app registration"
```

---

### Task 8: Fetch flow + scenario handling + selection fallback

**Files:**
- Modify: `gui/panels/gradebook.py` (replace the four placeholders from Task 7)

**Interfaces:**
- Consumes: `fetch_outline_text`, `fetch_gradebook_items`, `extract_categories`, `is_placeholder`, `extract_text_from_file` (Tasks 1–4); `self._load_gradebook_creds()` (Task 5); `_resolve_ou` pattern from `staging_automator`.
- Produces: `self._gb_structure` (dict) loaded into board; `self._gb_outline_text` (str) kept for the selection fallback; `self._gb_items` (list[str]).

**Behavior map (from spec):**
- Scenario 1 (no/placeholder syllabus): banner + show Term Work button. Term Work button builds `{"categories":[{"name":"Term Work","weight":100.0,"items":<all items>}],"uncategorized":[]}`, loads board, enables Apply, and logs + copies to clipboard the exact comment: *"Grade items present in gradebook so made one category weighted 100% and all items have been placed in this category."*
- Scenario 2 (outline found): run `extract_categories`; on success load board, enable Apply.
- Scenario 3 (skip button — ALWAYS visible once a fetch ran): logs + copies the exact comment: *"Material and resources have been successfully migrated. The course syllabus included supplementary materials so we did not apply this to the course syllabus template. Grade Book also not configured, please reach out for support, if desired."* Then disables Apply.
- AI-failure fallback: when `extract_categories` raises `ValueError`, show a `QTextEdit` (read-only=False selection, `setReadOnly(True)` still allows selection) containing `self._gb_outline_text` with prompt label "AI couldn't find the weighting table — highlight it below." plus **"Extract from Selection"** button → re-runs `extract_categories(selected_text, ...)`.

- [ ] **Step 1: Implement `_start_gb_fetch` worker**

Follows the staging worker pattern exactly (stdout → `("gradebook", line)`, `__DONE__` in `finally`). Async body: launch browser with `SESSION_FILE_GUI` storage state, `_wait_for_login`, resolve OU (reuse `staging_automator._resolve_ou(page, course_input)`), then:

```python
                items = await fetch_gradebook_items(page, ou)
                text  = await fetch_outline_text(page, ou)
```

Then via `QTimer.singleShot(0, ...)` hand results to `self._gb_on_fetched(items, text)`.

- [ ] **Step 2: Implement `_gb_on_fetched(items, text)` (GUI thread)**

```python
    def _gb_on_fetched(self, items, text):
        import gradebook_automator as ga
        self._gb_items, self._gb_outline_text = items, text
        self._gb_skip_btn.show()
        if ga.is_placeholder(text):
            self._gb_banner.setText(
                "No syllabus content found — create a single Term Work category?")
            self._gb_banner.show()
            self._gb_termwork_btn.show()
            return
        self._gb_run_extraction(text)
```

- [ ] **Step 3: Implement `_gb_run_extraction(text)`**

Worker thread: `provider, key = self._load_gradebook_creds()`; missing key → log "⚠ No API key for <provider> — set it in Settings." and stop. Call `extract_categories(text, self._gb_items, provider, key)`; success → `QTimer.singleShot(0, lambda: (self._gb_board.load_structure(s), self._gb_apply_btn.setEnabled(True)))`; `ValueError` → `QTimer.singleShot(0, self._gb_show_selection_fallback)`.

- [ ] **Step 4: Implement selection fallback + Term Work + skip + local file**

```python
    def _gb_show_selection_fallback(self):
        from PyQt6.QtWidgets import QTextEdit
        if getattr(self, "_gb_fallback_box", None) is None:
            self._gb_fallback_label = QLabel(
                "AI couldn't find the weighting table — highlight it below.")
            self._gb_fallback_box = QTextEdit()
            self._gb_fallback_box.setReadOnly(True)      # selection still works
            self._gb_fallback_box.setMinimumHeight(200)
            self._gb_extract_sel_btn = QPushButton("Extract from Selection")
            self._gb_extract_sel_btn.setFixedHeight(36)
            self._gb_extract_sel_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"]))
            self._gb_extract_sel_btn.clicked.connect(self._gb_extract_from_selection)
            lay = self._gb_board.parentWidget().layout()   # insert above board
            idx = lay.indexOf(self._gb_board)
            lay.insertWidget(idx, self._gb_fallback_label)
            lay.insertWidget(idx + 1, self._gb_fallback_box)
            lay.insertWidget(idx + 2, self._gb_extract_sel_btn)
        self._gb_fallback_box.setPlainText(self._gb_outline_text)
        self._gb_fallback_label.show(); self._gb_fallback_box.show(); self._gb_extract_sel_btn.show()

    def _gb_extract_from_selection(self):
        sel = self._gb_fallback_box.textCursor().selectedText()
        if not sel.strip():
            self._log_append(self._gradebook_log, "⚠  Select the weighting text first.")
            return
        self._gb_run_extraction(sel)

    TERM_WORK_COMMENT = ("Grade items present in gradebook so made one category "
                         "weighted 100% and all items have been placed in this category.")
    SKIP_COMMENT = ("Material and resources have been successfully migrated. The course "
                    "syllabus included supplementary materials so we did not apply this "
                    "to the course syllabus template. Grade Book also not configured, "
                    "please reach out for support, if desired.")

    def _gb_term_work(self):
        s = {"categories": [{"name": "Term Work", "weight": 100.0,
                             "items": list(self._gb_items)}], "uncategorized": []}
        self._gb_board.load_structure(s)
        self._gb_apply_btn.setEnabled(True)
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.TERM_WORK_COMMENT)
        self._log_append(self._gradebook_log, f"Comment (copied to clipboard): {self.TERM_WORK_COMMENT}")

    def _gb_skip_nonstandard(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.SKIP_COMMENT)
        self._log_append(self._gradebook_log, f"Comment (copied to clipboard): {self.SKIP_COMMENT}")
        self._gb_apply_btn.setEnabled(False)

    def _gb_pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            None, "Choose outline file", "", "Documents (*.pdf *.docx)")
        if not path:
            return
        import gradebook_automator as ga
        try:
            text = ga.extract_text_from_file(path)
        except Exception as e:
            self._log_append(self._gradebook_log, f"✗  Could not read file: {e}")
            return
        self._gb_outline_text = text
        if not getattr(self, "_gb_items", None):
            self._log_append(self._gradebook_log,
                             "⚠  No gradebook items fetched yet — run Fetch first (items come from Brightspace).")
            return
        self._gb_run_extraction(text)
```

- [ ] **Step 5: Manual check with stub data**

Run: `dev.bat` → Fetch on a real course: stub items appear, live syllabus text fetched; board populates via AI (needs API key in Settings) OR selection fallback appears. Term Work and Skip buttons behave per spec.

- [ ] **Step 6: Run full test suite + commit**

Run: `py -m pytest tests/ -q` — all pass.

```bash
git add gui/panels/gradebook.py
git commit -m "feat(gradebook): fetch flow, scenario banners, AI selection fallback"
```

---

### Task 9: Step-by-step Apply flow

**Files:**
- Modify: `gui/panels/gradebook.py` (replace `_start_gb_apply` placeholder)

**Interfaces:**
- Consumes: `apply_categories(page, structure, step_fn)` stub (Task 4), `self._bridge.prompt` (same cross-thread prompt the staging tab uses), `self._gb_board.to_structure()`.

- [ ] **Step 1: Implement `_start_gb_apply`**

Worker thread, staging pattern: disable button, read `structure = self._gb_board.to_structure()` BEFORE starting the thread (GUI objects must not be touched from the worker), launch browser + login + resolve OU, then:

```python
                def step_fn(name):
                    bridge.prompt(f"Next: create category '{name}'. OK to continue…")
                await apply_categories(page, structure, step_fn)
```

`finally:` → `q.put(("gradebook", "__DONE__"))` (also re-enable Apply in the `__DONE__` branch of `_poll_log` — extend the Task 7 branch:

```python
                    elif tag == "gradebook":
                        self._gb_fetch_btn.setEnabled(True)
                        self._gb_fetch_btn.setText("▶   Fetch Outline + Gradebook")
                        self._gb_apply_btn.setEnabled(True)
```
)

- [ ] **Step 2: Manual check**

Run: `dev.bat` → load structure (Term Work path is fastest), click Apply → per-category OK dialogs appear, stub logs "would create …" lines.

- [ ] **Step 3: Run full test suite + commit**

Run: `py -m pytest tests/ -q` — all pass.

```bash
git add gui/panels/gradebook.py gui_pyqt6.py
git commit -m "feat(gradebook): step-by-step apply flow (stubbed Brightspace calls)"
```

---

### Task 10 (SEPARATE SESSION — live walkthrough): real fetch_gradebook_items / apply_categories

Not plannable now by design. Process: user opens a real course's Grades page; agent uses claude-in-chrome or Playwright inspection WITH the user narrating the click-path; selectors captured become the real bodies of the two stubs in `src/gradebook_automator.py`. Signatures must not change. Expect D2L shadow-DOM patterns (see CLAUDE.md "Critical: D2L shadow DOM" — coordinate-click via recursive shadow walk).

---

## Self-review notes

- Spec coverage: entry point (T7), outline source primary+fallback (T3, T8 local file), scenario 1/2/3 (T8), AI extraction + 3 providers + Settings (T2, T5), selection fallback (T8), review board no-rebalance + Add Category (T6), step-by-step apply (T9), stubs isolated (T4, T10). Out-of-scope items untouched.
- Comment destination is an open question (top of plan) — surfaced to user before Task 8.
- Type consistency: structure dict identical shape in Tasks 1, 4, 6, 8, 9; `step_fn(name: str)` consistent between T4 and T9; config keys consistent between T5 and `_load_gradebook_creds`.
