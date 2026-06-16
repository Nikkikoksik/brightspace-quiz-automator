## Working Style (mandatory)
- Make ONE change at a time
- Before making any change, explain what you're going to do and why
- After making the change, stop and wait for me to confirm it worked
- Never rewrite working code
- Never change more than one file at a time unless I explicitly ask


# Brightspace Quiz Automator

Playwright-based GUI tool that bulk-updates quiz settings in Brightspace (D2L LMS) for Okanagan College instructors.

## What it does
- Sets quizzes from "Not in Grade Book" → "In Grade Book"
- Sets timer expiry action → "Automatically submit the quiz attempt"
  - Timer OK button: after clicking radio, use `await page.keyboard.press("Enter")` — d2l-button visibility checks fail all other approaches
- Processes every quiz in a course in one run
- Supports multiple courses via `courses.txt`

## How to run
```
python gui.py          # GUI (normal use)
python quiz_automator.py   # CLI fallback
```

## File structure
- `gui.py` — CustomTkinter GUI app (primary interface, production)
- `gui_pyqt6.py` — PyQt6 GUI rebuild (WIP on `nick` branch — see section below)
- `quiz_automator.py` — CLI entry point, reads URLs from `courses.txt`
- `config.py` — default settings toggles for CLI
- `browser.py` — browser session setup, loops over courses and quizzes
- `navigation.py` — `get_quiz_names()`, `open_quiz_edit()`
- `actions.py` — `apply_gradebook()`, `apply_auto_submit()`, `save_quiz()`
- `courses.txt` — one quiz page URL per line (gitignored user data)
- `setup.bat` — one-time install for co-workers
- `run.bat` — launches gui.py (still points at old GUI — do not change until PyQt6 version is confirmed working)
- `update.bat` — downloads latest ZIP from GitHub (no Git needed)

## GitHub
https://github.com/Nikkikoksik/brightspace-quiz-automator

## Critical: D2L shadow DOM
All buttons on the quiz edit page are inside deeply nested shadow DOMs
(`d2l-activity-quiz-editor`). Standard Playwright clicks fail silently.

**The only approach that works:**
```python
coords = await page.evaluate("""
    () => {
        function find(root) {
            for (const el of root.querySelectorAll('SELECTOR')) {
                const r = el.getBoundingClientRect();
                if (r.width > 0) return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
            }
            for (const el of root.querySelectorAll('*')) {
                if (el.shadowRoot) { const c = find(el.shadowRoot); if (c) return c; }
            }
            return null;
        }
        return find(document);
    }
""")
await page.mouse.click(coords["x"], coords["y"])
```

Use `page.evaluate()` with recursive shadow DOM walk to get real viewport
coordinates, then `page.mouse.click()`. Never use `locator.click()`,
`force=True`, `bounding_box()`, or `el.click()` via evaluate — all fail.

For confirming a dialog closed, use the same recursive walk in
`page.wait_for_function()` checking `getBoundingClientRect().width === 0`.

## Adding new quiz actions
1. Add a function to `actions.py`
2. Add a toggle key to `SETTINGS` in `config.py`
3. Add a checkbox in `gui.py` `_build_ui()`
4. Wire it into the loop in `browser.py`

---

## CourseBridge Selectors (from live HTML)
CourseBridge is a Next.js/React app — no shadow DOM, standard selectors work fine.

- **File upload:** `input[type='file']` with `state="attached"` (input is hidden, so never use default visible wait). Current accept value: `.pdf,.docx,.pptx,.txt,.md,.markdown,.text,.html,.htm,.csv,.tsv,.rtf,.json` — use `set_input_files()` directly, no clicking needed
- **Template dropdown:** `button[data-slot="select-trigger"]` — defaults to "Course Syllabus", verify before clicking Convert
- **Convert button:** `button:has-text("Convert Document")`
- **Wait for completion:** poll status log `div.font-mono` for text containing "Done!"
- **Grab HTML output:** `pre.font-mono` → `.inner_text()` — more reliable than clipboard
- **Copy HTML button:** `button:has-text("Copy HTML")` — fallback only


# Course Outline Automator — Planned Tool

Playwright-based script to convert a course outline document into a Brightspace-ready HTML page and paste it into the correct topic.

## What it does (full flow)
1. **Find outline** — searches course Content tab for `syllabus` → `outline` → `guideline`; pauses for user confirmation before downloading
2. **PDF check** — if `.pdf`, converts locally with `pdf2docx`; if `.docx`, proceeds as-is
3. **CourseBridge conversion** — logs into `https://lms.harshsaw.ca/content-converter`, uploads `.docx`, sets template to "Course Syllabus", clicks Convert, grabs HTML output
4. **Paste into Brightspace** — navigates to Welcome Module → "Course Syllabus" topic → opens TinyMCE editor → replaces HTML via Source Code dialog → saves

## How to run
```
python course_outline_automator.py            # full run
python course_outline_automator.py --dry-run  # download + convert only, no paste
```

## Config (top of file)
```python
BRIGHTSPACE_BASE = "https://learn.okanagancollege.ca"
COURSEBRIDGE_URL = "https://lms.harshsaw.ca/content-converter"
COURSEBRIDGE_EMAIL = ""
COURSEBRIDGE_PASSWORD = ""
OUTLINE_SEARCH_TERMS = ["syllabus", "outline", "guideline"]
SYLLABUS_TOPIC_NAME = "Course Syllabus"
```

## Session files
- `bs_session.json` — Brightspace login (same pattern as quiz automator)
- `cb_session.json` — CourseBridge login (separate browser context)

## Key functions
| Function | What it does |
|---|---|
| `find_and_download_outline(page)` | Searches content tab, pauses for confirm, downloads file |
| `convert_pdf_to_docx(pdf_path)` | Converts PDF → docx locally via pdf2docx |
| `convert_with_coursebridge(file_path) -> str` | Uploads docx, returns HTML string |
| `paste_html_to_syllabus(page, html)` | Finds Course Syllabus topic, replaces HTML in TinyMCE |
| `run(dry_run)` | Main orchestrator |

## Critical: CourseBridge API swap
`convert_with_coursebridge` is intentionally isolated. Once the CourseBridge developer provides an API endpoint, only the internals of that function change — signature stays `convert_with_coursebridge(file_path) -> str`.

## --dry-run behavior
Stops before pasting HTML into Brightspace. Still does download + conversion so user can preview the HTML output.

## Not built yet
File does not exist as of 2026-06-02. Spec is in `COURSE_OUTLINE_AUTOMATOR_SPEC.md` (user's Downloads folder).

---

# PyQt6 GUI Rebuild — WIP (`nick` branch)

`gui_pyqt6.py` is a full rebuild of `gui.py` using PyQt6 instead of CustomTkinter. It is a surprise for co-workers — keep it on the `nick` branch until ready to ship.

## How to run
```
python gui_pyqt6.py
```
To compare with old GUI side by side (PowerShell):
```
Start-Process python -ArgumentList "gui.py"; Start-Process python -ArgumentList "gui_pyqt6.py"
```

## Current state (as of 2026-06-15)
- All 9 panels built and wired up (Staging, Quizzes, Assignments, Course Outline, Notes, Timer Fix, Queue, History, Settings)
- Slate theme applied: bg `#0d1117`, sidebar `#010409`, accent `#0ea5e9`
- App icon wired up from `installer/assets/icon.ico` (shows in Windows taskbar)
- Checkboxes: white checkmark SVG written to `%APPDATA%/BrightspaceAutomator/check.svg` at startup
- Cross-thread UI (dialogs from worker threads) handled by `_ThreadBridge` QObject using `pyqtSignal`
- `run.bat` still points at `gui.py` — production is untouched

## What still needs work
- **Collapsible sidebar** — user requested, not built yet
- **Visual polish** — layout is a 1:1 port of the old design; needs proper redesign (not just a re-skin)
  - Ideas discussed: progress indicators, colored log prefixes (✓/⚠/✗), cards with icons, inline session status, run history badge on nav
- **Functional testing** — all panels are wired to the same backend as `gui.py` but have not been tested end-to-end
- **Timer Fix panel** — `_add_url_row` call has a bug (passes wrong container arg — `self._tfix_url_rows` instead of `self._tfix_url_container`); needs fixing before testing

## Key architecture differences vs gui.py
- `QTimer` replaces tkinter's `.after()` for the log polling loop
- `QStackedWidget` replaces the grid show/hide panel pattern
- `_ThreadBridge(QObject)` with `pyqtSignal` replaces `root.after(0, show)` for cross-thread dialogs
- `_RangeDialog(QDialog)` replaces the CTkToplevel ask-range popup
- All persistence files and paths are identical — same `%APPDATA%/BrightspaceAutomator/` location
