# Brightspace Quiz Automator

Playwright-based GUI tool that bulk-updates quiz settings in Brightspace (D2L LMS) for Okanagan College instructors.

## What it does
- Sets quizzes from "Not in Grade Book" → "In Grade Book"
- Sets timer expiry action → "Automatically submit the quiz attempt"
- Processes every quiz in a course in one run
- Supports multiple courses via `courses.txt`

## How to run
```
python gui.py          # GUI (normal use)
python quiz_automator.py   # CLI fallback
```

## File structure
- `gui.py` — CustomTkinter GUI app (primary interface)
- `quiz_automator.py` — CLI entry point, reads URLs from `courses.txt`
- `config.py` — default settings toggles for CLI
- `browser.py` — browser session setup, loops over courses and quizzes
- `navigation.py` — `get_quiz_names()`, `open_quiz_edit()`
- `actions.py` — `apply_gradebook()`, `apply_auto_submit()`, `save_quiz()`
- `courses.txt` — one quiz page URL per line (gitignored user data)
- `setup.bat` — one-time install for co-workers
- `run.bat` — launches gui.py
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
