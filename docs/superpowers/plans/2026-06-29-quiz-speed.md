# Quiz & Assignment Speed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce per-quiz wall-clock time from ~10s to ~1.2s throughput via parallel worker pool, direct URL harvesting, and smart waits replacing fixed sleeps.

**Architecture:** A one-time harvest phase reads all quiz edit URLs from the list page shadow DOM. Three async worker coroutines pull from an `asyncio.Queue`, each navigating directly to edit URLs on independent `Page` objects. Smart waits replace every fixed `wait_for_timeout` with condition-driven waits.

**Tech Stack:** Python 3.11+, Playwright async API, asyncio

## Global Constraints

- Never modify `gui.py`, `run.bat`, or `quiz_automator.py` — production is untouched
- All changes on `nick` branch only
- Working directory for all commands: repo root (`brightspace-quiz-automator/`)
- Python path for src imports: `src/` is on sys.path (see `quiz_automator.py` for pattern)
- Session file: `%APPDATA%/BrightspaceAutomator/session.json`
- Stats file: `%APPDATA%/BrightspaceAutomator/timing_stats.json`

---

### Task 1: Remove slow_mo from all browser launches

**Files:**
- Modify: `src/browser.py`

**Interfaces:**
- Produces: browser launches with no artificial per-action delay

- [ ] **Step 1: Remove slow_mo from all four launch calls**

In `src/browser.py`, find every `p.chromium.launch(` call. There are four: in `run_bs_login()`, `run()`, `run_verify()`, `run_timer_fix()`, and `run_assignments()`. Remove `slow_mo=80` from each.

```python
# Before (example from run()):
browser = await p.chromium.launch(headless=False, slow_mo=80, args=["--start-maximized"])

# After:
browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
```

Apply the same change to all five occurrences.

- [ ] **Step 2: Verify change**

```bash
grep -n "slow_mo" src/browser.py
```

Expected output: no results (empty).

- [ ] **Step 3: Commit**

```bash
git add src/browser.py
git commit -m "perf: remove slow_mo=80 from all browser launches"
```

---

### Task 2: Smart waits in actions.py

**Files:**
- Modify: `src/actions.py`

**Interfaces:**
- Produces: `apply_gradebook(page, dry_run) -> bool | None` — now returns `True` if changed, `False` if already set, `None` if not found
- Produces: `apply_auto_submit(page, dry_run) -> bool | None` — existing return semantics unchanged
- Produces: `save_quiz(page, dry_run)` — unchanged signature

- [ ] **Step 1: Make apply_gradebook return a change indicator**

Replace the `apply_gradebook` function body. Key changes:
- Remove `wait_for_timeout(800)` after `option.click()` → use `wait_for_function` checking label changed
- Return `True` when changed, `False` when already set, `None` when not found

```python
async def apply_gradebook(page: Page, dry_run: bool) -> bool | None:
    """Switch quiz from Not in Grade Book → In Grade Book. Returns True if changed, False if already set, None if not found."""
    try:
        try:
            await page.wait_for_function("""
                () => {
                    function find(root) {
                        for (const el of root.querySelectorAll('button.d2l-grade-info, [class*="grade-info"]')) {
                            if (el.getBoundingClientRect().width > 0) return true;
                        }
                        for (const el of root.querySelectorAll('*')) {
                            if (el.shadowRoot && find(el.shadowRoot)) return true;
                        }
                        return false;
                    }
                    return find(document);
                }
            """, timeout=30000)
        except Exception:
            pass

        grade_btn = page.locator("button.d2l-grade-info").first

        if not await grade_btn.count():
            print("    Gradebook : not found — skipping")
            return None

        div_text = await grade_btn.locator("div").first.inner_text()

        if "Not in Grade Book" not in div_text:
            print("    Gradebook : already In Grade Book — skipping")
            return False

        if dry_run:
            print("    Gradebook : [DRY RUN] Would switch to In Grade Book")
            return False

        print("    Gradebook : Not in Grade Book → switching...")
        await grade_btn.click()
        await page.wait_for_selector(
            "d2l-menu-item[text='Add to Grade Book'], li:has-text('Add to Grade Book')",
            timeout=5000,
        )
        option = page.locator(
            "d2l-menu-item[text='Add to Grade Book'], li:has-text('Add to Grade Book')"
        ).first
        await option.click()
        # Wait for grade button label to change instead of fixed sleep
        try:
            await page.wait_for_function("""
                () => {
                    const btn = document.querySelector('button.d2l-grade-info');
                    if (!btn) return false;
                    const div = btn.querySelector('div');
                    return div && !div.textContent.includes('Not in Grade Book');
                }
            """, timeout=5000)
        except Exception:
            pass
        await _set_points_if_zero(page)
        print("    Gradebook : ✓ Added to Grade Book")
        return True

    except Exception as e:
        print(f"    Gradebook : ✗ {e}")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
        return None
```

- [ ] **Step 2: Replace fixed sleeps in apply_auto_submit**

In `apply_auto_submit`, replace:
- `wait_for_timeout(600)` after `timing_btn.click()` → `wait_for_selector("text=Timer Settings", timeout=5000)`
- `wait_for_timeout(600)` after radio `_flash_click` → remove (dialog-closed `wait_for_function` handles it)
- `wait_for_timeout(1000)` after OK `_flash_click` → remove (already covered by dialog-closed check)
- `wait_for_timeout(800)` after `wait_for_load_state("networkidle")` → remove

Find these lines and make the replacements:

```python
# BEFORE — after timing_btn.click():
await timing_btn.click()
await page.wait_for_timeout(600)

# AFTER:
await timing_btn.click()
await page.wait_for_selector("text=Timer Settings", timeout=5000)
```

```python
# BEFORE — after radio _flash_click:
await _flash_click(page, radio_coords["x"], radio_coords["y"])
await page.wait_for_timeout(600)
radio_state = await radio.is_checked()

# AFTER:
await _flash_click(page, radio_coords["x"], radio_coords["y"])
radio_state = await radio.is_checked()
```

```python
# BEFORE — after OK _flash_click:
await _flash_click(page, ok_coords["x"], ok_coords["y"])
# ...
print("    Timer     : waiting for API to settle...")
await page.wait_for_timeout(1000)
try:
    await page.wait_for_load_state("networkidle", timeout=10000)
except Exception:
    pass
await page.wait_for_timeout(800)
print("    Timer     : network idle ✓")

# AFTER:
await _flash_click(page, ok_coords["x"], ok_coords["y"])
# ...
print("    Timer     : waiting for dialog to close...")
# (keep the existing wait_for_function dialog-closed check as-is)
# remove the wait_for_timeout(1000), networkidle, and wait_for_timeout(800) AFTER the dialog check
```

The existing `wait_for_function` that checks `!hasOk(document)` stays. Remove only the three sleeps that come after the dialog-closed check:

```python
# Delete these three lines that appear after the dialog-closed wait_for_function:
await page.wait_for_timeout(1000)
try:
    await page.wait_for_load_state("networkidle", timeout=10000)
except Exception:
    pass
await page.wait_for_timeout(800)
```

- [ ] **Step 3: Replace fixed sleeps in save_quiz**

```python
# BEFORE — after Save _flash_click:
await _flash_click(page, save_coords["x"], save_coords["y"])
await page.wait_for_timeout(1500)
try:
    await page.wait_for_load_state("networkidle", timeout=8000)
except Exception:
    pass
await page.wait_for_timeout(800)
print("    Save      : Save clicked ✓")

# AFTER:
await _flash_click(page, save_coords["x"], save_coords["y"])
try:
    await page.wait_for_load_state("networkidle", timeout=8000)
except Exception:
    pass
print("    Save      : Save clicked ✓")
```

- [ ] **Step 4: Apply same sleep removal to save_assignment**

`save_assignment` is identical in structure to `save_quiz`. Apply the same removal of `wait_for_timeout(1500)` and `wait_for_timeout(800)` after the Save click.

- [ ] **Step 5: Commit**

```bash
git add src/actions.py
git commit -m "perf: replace fixed sleeps with condition waits in actions.py"
```

---

### Task 3: Smart waits in navigation.py

**Files:**
- Modify: `src/navigation.py`

**Interfaces:**
- Produces: `open_quiz_edit(page, name)` — unchanged signature, faster execution
- Produces: `open_assignment_edit(page, name)` — unchanged signature, faster execution
- Produces: `set_per_page_200(page)` — unchanged signature, smarter wait

- [ ] **Step 1: Fix open_quiz_edit waits**

```python
# BEFORE:
async def open_quiz_edit(page: Page, name: str):
    coords = await _find_action_button(page, name)
    if coords is None:
        raise Exception(f"Actions button for '{name}' not found")
    await page.mouse.click(coords["x"], coords["y"])
    await page.wait_for_timeout(400)
    edit_coords = await _find_menu_item(page, "Edit")
    if edit_coords is None:
        items = await _dump_menu_items(page)
        print(f"  DEBUG menu items found: {items}")
        raise Exception(f"Edit menu item for '{name}' not found")
    await page.mouse.click(edit_coords["x"], edit_coords["y"])
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(800)

# AFTER (remove wait_for_timeout(400) — _find_menu_item already retries 8×200ms):
async def open_quiz_edit(page: Page, name: str):
    coords = await _find_action_button(page, name)
    if coords is None:
        raise Exception(f"Actions button for '{name}' not found")
    await page.mouse.click(coords["x"], coords["y"])
    edit_coords = await _find_menu_item(page, "Edit")
    if edit_coords is None:
        items = await _dump_menu_items(page)
        print(f"  DEBUG menu items found: {items}")
        raise Exception(f"Edit menu item for '{name}' not found")
    await page.mouse.click(edit_coords["x"], edit_coords["y"])
    await page.wait_for_load_state("domcontentloaded")
    # Wait for edit page to be interactive instead of fixed sleep
    try:
        await page.wait_for_selector(
            "button.d2l-grade-info, button.d2l-collapsible-panel-opener",
            timeout=15000,
        )
    except Exception:
        pass
```

- [ ] **Step 2: Fix open_assignment_edit waits**

```python
# BEFORE:
async def open_assignment_edit(page: Page, name: str):
    coords = await _find_action_button(page, name)
    if coords is None:
        raise Exception(f"Actions button for '{name}' not found")
    await page.mouse.click(coords["x"], coords["y"])
    await page.wait_for_timeout(400)
    edit_coords = await _find_menu_item(page, "Edit Folder") or await _find_menu_item(page, "Edit Assignment")
    if edit_coords is None:
        raise Exception(f"Edit menu item for '{name}' not found")
    await page.mouse.click(edit_coords["x"], edit_coords["y"])
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(800)

# AFTER:
async def open_assignment_edit(page: Page, name: str):
    coords = await _find_action_button(page, name)
    if coords is None:
        raise Exception(f"Actions button for '{name}' not found")
    await page.mouse.click(coords["x"], coords["y"])
    edit_coords = await _find_menu_item(page, "Edit Folder") or await _find_menu_item(page, "Edit Assignment")
    if edit_coords is None:
        raise Exception(f"Edit menu item for '{name}' not found")
    await page.mouse.click(edit_coords["x"], edit_coords["y"])
    await page.wait_for_load_state("domcontentloaded")
    try:
        await page.wait_for_selector(
            "button.d2l-grade-info, button.d2l-collapsible-panel-opener, [class*='grade-info']",
            timeout=15000,
        )
    except Exception:
        pass
```

- [ ] **Step 3: Fix set_per_page_200 wait**

```python
# BEFORE:
async def set_per_page_200(page: Page):
    selected = await page.evaluate("""...""")
    if selected:
        await page.wait_for_timeout(1500)

# AFTER — wait for list to reload after dropdown change:
async def set_per_page_200(page: Page):
    selected = await page.evaluate("""...""")
    if selected:
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
```

- [ ] **Step 4: Commit**

```bash
git add src/navigation.py
git commit -m "perf: replace fixed sleeps with condition waits in navigation.py"
```

---

### Task 4: Add harvest_quiz_edit_urls() to navigation.py

**Files:**
- Modify: `src/navigation.py`

**Interfaces:**
- Produces: `harvest_quiz_edit_urls(page, quiz_url) -> list[tuple[str, str]]`
  - Returns `[(name, edit_url), ...]` in list-page order
  - Returns `[]` if passive href reading fails (workers will fall back to action menu)

- [ ] **Step 1: Add harvest function**

Add this function to `src/navigation.py` after `set_per_page_200`:

```python
async def harvest_quiz_edit_urls(page: Page, quiz_url: str) -> list[tuple[str, str]]:
    """
    Read all quiz edit URLs from the list page without clicking.
    Walks shadow DOM for quiz_summary.d2l hrefs, zips with quiz names.
    Returns [] if passive reading finds no URLs (workers fall back to action menu).
    """
    await page.goto(quiz_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_selector(
        "button[aria-haspopup='true'][aria-label*='Actions for']", timeout=30000
    )

    # Get names in DOM order (reuse existing scraper)
    names = await get_quiz_names(page)
    if not names:
        return []

    # Try passive href harvest — walk shadow DOM for quiz_summary.d2l links
    hrefs = await page.evaluate("""
        () => {
            const seen = new Set();
            const results = [];
            function walk(root) {
                for (const el of root.querySelectorAll(
                    'a[href*="quiz_summary.d2l"], d2l-menu-item[href*="quiz_summary.d2l"]'
                )) {
                    const href = el.getAttribute('href');
                    if (href && !seen.has(href)) {
                        seen.add(href);
                        results.push(new URL(href, location.origin).href);
                    }
                }
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) walk(el.shadowRoot);
                }
            }
            walk(document);
            return results;
        }
    """)

    if not hrefs or len(hrefs) != len(names):
        print(f"  Harvest   : passive href read got {len(hrefs)} URLs for {len(names)} quizzes — falling back to action menu per worker")
        return []

    pairs = list(zip(names, hrefs))
    print(f"  Harvest   : ✓ {len(pairs)} quiz edit URLs read passively")
    return pairs
```

- [ ] **Step 2: Verify function is importable**

```bash
cd src && python -c "from navigation import harvest_quiz_edit_urls; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/navigation.py
git commit -m "feat: add harvest_quiz_edit_urls() passive shadow-DOM URL reader"
```

---

### Task 5: Update timing stats schema

**Files:**
- Modify: `src/browser.py`

**Interfaces:**
- Produces: `_save_timing(course_url, quiz_name, elapsed_s, phases, changed, worker_id)` — new signature
  - `phases: dict` — keys: `navigate`, `gradebook`, `timer`, `save`; values: float seconds
  - `changed: dict` — keys: `gradebook`, `timer`; values: bool
  - `worker_id: int`

- [ ] **Step 1: Update _save_timing signature and schema**

Replace the existing `_save_timing` function in `src/browser.py`:

```python
def _save_timing(course_url: str, quiz_name: str, elapsed_s: float,
                 phases: dict | None = None, changed: dict | None = None,
                 worker_id: int = 0):
    try:
        try:
            with open(STATS_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = []
        entry = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%H:%M"),
            "course": course_url,
            "quiz": quiz_name,
            "phases": phases or {},
            "total": round(elapsed_s, 1),
            "changed": changed or {},
            "worker": worker_id,
        }
        data.append(entry)
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
```

- [ ] **Step 2: Update _print_run_summary to show phase breakdown**

After the existing summary block in `_print_run_summary`, add average phase breakdown:

```python
def _print_run_summary(results: list, kind: str = "item"):
    W = 54
    errors   = [r for r in results if r["failed"]]
    ok_times = [r["elapsed"] for r in results if not r["failed"]]
    print(f"\n{'─' * W}")
    print(f"  SUMMARY  ·  {len(results)} {kind}(s)")
    print(f"{'─' * W}")
    for r in results:
        status = "✗" if r["failed"] else "✓"
        name = r["name"] if len(r["name"]) <= 38 else r["name"][:37] + "…"
        note = "FAILED" if r["failed"] else f"{r['elapsed']:.1f}s"
        print(f"  {status}  {name:<39}{note}")
    print(f"{'─' * W}")
    parts = [f"Avg time : {sum(ok_times)/len(ok_times):.1f}s"] if ok_times else []
    parts.append(f"Errors : {len(errors)}" if errors else "All OK ✓")
    print("  " + "   ·   ".join(parts))

    # Phase breakdown
    phase_keys = ["navigate", "gradebook", "timer", "save"]
    ok_results = [r for r in results if not r["failed"] and r.get("phases")]
    if ok_results:
        avgs = {
            k: sum(r["phases"].get(k, 0) for r in ok_results) / len(ok_results)
            for k in phase_keys
        }
        breakdown = "  |  ".join(f"{k} {v:.1f}s" for k, v in avgs.items() if v > 0)
        if breakdown:
            print(f"  Phase avg : {breakdown}")
    print(f"{'─' * W}")
```

- [ ] **Step 3: Commit**

```bash
git add src/browser.py
git commit -m "feat: add per-phase timing schema and breakdown to run summary"
```

---

### Task 6: Refactor run() with parallel worker pool

**Files:**
- Modify: `src/browser.py`

**Interfaces:**
- Consumes: `harvest_quiz_edit_urls(page, quiz_url) -> list[tuple[str, str]]` from `navigation.py`
- Consumes: `apply_gradebook(page, dry_run) -> bool | None` (now returns bool)
- Consumes: `_save_timing(course_url, quiz_name, elapsed_s, phases, changed, worker_id)`
- Produces: `run(urls, dry_run, settings, limit, ask_fn, review_fn, rename_fn)` — unchanged external signature

- [ ] **Step 1: Add WORKER_COUNT constant and import**

At the top of `src/browser.py`, after existing imports:

```python
from navigation import get_quiz_names, open_quiz_edit, get_assignment_names, open_assignment_edit, discover_course_urls, set_per_page_200, harvest_quiz_edit_urls

WORKER_COUNT = 3
```

- [ ] **Step 2: Add _quiz_worker coroutine**

Add this function to `src/browser.py` before `run()`:

```python
async def _quiz_worker(
    worker_id: int,
    queue: asyncio.Queue,
    context,
    quiz_url: str,
    settings: dict,
    dry_run: bool,
    results: list,
    lock: asyncio.Lock,
    total: int,
):
    page = await context.new_page()
    try:
        while True:
            try:
                idx, name, edit_url = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            print(f"\n[{idx}/{total}]  [W{worker_id}]  [{name}]")
            t_start = time.time()
            phases: dict = {}
            changed: dict = {}
            failed = False

            try:
                t = time.time()
                if edit_url:
                    await page.goto(edit_url, wait_until="domcontentloaded", timeout=30000)
                    try:
                        await page.wait_for_selector(
                            "button.d2l-grade-info, button.d2l-collapsible-panel-opener",
                            timeout=15000,
                        )
                    except Exception:
                        pass
                else:
                    await page.goto(quiz_url, wait_until="commit")
                    await page.wait_for_selector(
                        "button[aria-haspopup='true'][aria-label*='Actions for']",
                        timeout=30000,
                    )
                    await open_quiz_edit(page, name)
                phases["navigate"] = round(time.time() - t, 2)

                if settings.get("set_in_gradebook"):
                    t = time.time()
                    gb_result = await apply_gradebook(page, dry_run)
                    phases["gradebook"] = round(time.time() - t, 2)
                    changed["gradebook"] = gb_result is True

                if settings.get("set_auto_submit"):
                    t = time.time()
                    ok = await apply_auto_submit(page, dry_run)
                    phases["timer"] = round(time.time() - t, 2)
                    changed["timer"] = ok is True
                    if ok is False:
                        failed = True

                t = time.time()
                await save_quiz(page, dry_run)
                phases["save"] = round(time.time() - t, 2)

            except Exception as e:
                failed = True
                print(f"  [W{worker_id}] ✗ {name}: {e}")

            elapsed = round(time.time() - t_start, 1)
            print(f"  [W{worker_id}]  Timing: {elapsed}s  phases: {phases}")

            async with lock:
                results.append({
                    "name": name,
                    "elapsed": elapsed,
                    "failed": failed,
                    "phases": phases,
                    "changed": changed,
                    "worker": worker_id,
                })
                if not failed and not dry_run:
                    _save_timing(quiz_url, name, elapsed, phases, changed, worker_id)

            queue.task_done()
    finally:
        await page.close()
```

- [ ] **Step 3: Rewrite run() to use harvest + worker pool**

Replace the `for i, name in enumerate(names, start_from):` loop inside `run()` with:

```python
            # Harvest edit URLs (passive shadow-DOM read, falls back gracefully)
            harvest_page = await context.new_page()
            try:
                quiz_pairs = await harvest_quiz_edit_urls(harvest_page, quiz_url)
            finally:
                await harvest_page.close()

            # Align harvested pairs with selected range
            if not quiz_pairs:
                # Fallback: workers navigate via action menu
                quiz_pairs = [(n, None) for n in names]
            else:
                quiz_pairs = list(zip(names, [url for _, url in quiz_pairs]))

            # Fill queue
            queue: asyncio.Queue = asyncio.Queue()
            for i, (name, edit_url) in enumerate(quiz_pairs, start_from):
                await queue.put((i, name, edit_url))

            lock = asyncio.Lock()
            results: list = []
            failed_timer: list = []

            workers = [
                _quiz_worker(
                    worker_id=w,
                    queue=queue,
                    context=context,
                    quiz_url=quiz_url,
                    settings=settings,
                    dry_run=dry_run,
                    results=results,
                    lock=lock,
                    total=total,
                )
                for w in range(1, WORKER_COUNT + 1)
            ]
            await asyncio.gather(*workers)

            # Collect failed timers from results
            failed_timer = [
                f"[{r['name']}]"
                for r in results
                if r["failed"] and not r["changed"].get("timer")
            ]
```

Remove the old `failed_timer = []` and `results = []` declarations that came before the old `for` loop, and remove the old `for i, name in enumerate(names, start_from):` block entirely.

- [ ] **Step 4: Keep the rest of run() unchanged**

The blocks after the loop (`if failed_timer`, `if results: _print_run_summary(results, "quiz")`) stay as-is. They now consume the results list populated by workers.

- [ ] **Step 5: Test run() manually**

Run against a real course with 3+ quizzes in dry-run mode:

```bash
cd src && python -c "
import asyncio
from browser import run
asyncio.run(run(
    urls=['https://learn.okanagancollege.ca/d2l/home/YOUR_COURSE_ID'],
    dry_run=True,
    settings={'set_in_gradebook': True, 'set_auto_submit': True},
))
"
```

Expected: log shows `[W1]`, `[W2]`, `[W3]` interleaved, phase breakdown in summary, total time significantly less than `N × 10s`.

- [ ] **Step 6: Commit**

```bash
git add src/browser.py
git commit -m "feat: parallel worker pool for quiz processing (3 concurrent tabs)"
```

---

### Task 7: Apply worker pool to run_assignments()

**Files:**
- Modify: `src/browser.py`
- Modify: `src/navigation.py`

**Interfaces:**
- Produces: `harvest_assignment_edit_urls(page, asgn_url) -> list[tuple[str, str]]`
  - Same contract as `harvest_quiz_edit_urls` but for `folders_list.d2l` / `dropbox` edit URLs
- Produces: `_assignment_worker(...)` — same structure as `_quiz_worker`

- [ ] **Step 1: Add harvest_assignment_edit_urls() to navigation.py**

Add after `harvest_quiz_edit_urls` in `src/navigation.py`:

```python
async def harvest_assignment_edit_urls(page: Page, asgn_url: str) -> list[tuple[str, str]]:
    """
    Read all assignment edit URLs from the list page without clicking.
    Walks shadow DOM for dropbox/folder edit hrefs, zips with assignment names.
    Returns [] if passive reading fails.
    """
    await page.goto(asgn_url, wait_until="domcontentloaded", timeout=30000)
    try:
        await page.wait_for_selector(
            "button[aria-haspopup='true'][aria-label*='Actions for']", timeout=8000
        )
    except Exception:
        return []

    await set_per_page_200(page)
    names = await get_assignment_names(page)
    if not names:
        return []

    hrefs = await page.evaluate("""
        () => {
            const seen = new Set();
            const results = [];
            function walk(root) {
                for (const el of root.querySelectorAll(
                    'a[href*="dropbox"], a[href*="folder"], d2l-menu-item[href*="dropbox"], d2l-menu-item[href*="folder"]'
                )) {
                    const href = el.getAttribute('href');
                    const text = (el.getAttribute('text') || el.textContent || '').trim();
                    if (href && (text === 'Edit Folder' || text === 'Edit Assignment') && !seen.has(href)) {
                        seen.add(href);
                        results.push(new URL(href, location.origin).href);
                    }
                }
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) walk(el.shadowRoot);
                }
            }
            walk(document);
            return results;
        }
    """)

    if not hrefs or len(hrefs) != len(names):
        print(f"  Harvest   : assignment href read got {len(hrefs)} for {len(names)} — falling back to action menu per worker")
        return []

    pairs = list(zip(names, hrefs))
    print(f"  Harvest   : ✓ {len(pairs)} assignment edit URLs read passively")
    return pairs
```

Update the import in `browser.py`:

```python
from navigation import (
    get_quiz_names, open_quiz_edit,
    get_assignment_names, open_assignment_edit,
    discover_course_urls, set_per_page_200,
    harvest_quiz_edit_urls, harvest_assignment_edit_urls,
)
```

- [ ] **Step 2: Add _assignment_worker coroutine to browser.py**

Add before `run_assignments()`:

```python
async def _assignment_worker(
    worker_id: int,
    queue: asyncio.Queue,
    context,
    asgn_url: str,
    settings: dict,
    dry_run: bool,
    results: list,
    lock: asyncio.Lock,
    total: int,
):
    page = await context.new_page()
    try:
        while True:
            try:
                idx, name, edit_url = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            print(f"\n[{idx}/{total}]  [W{worker_id}]  [{name}]")
            t_start = time.time()
            phases: dict = {}
            changed: dict = {}
            failed = False

            try:
                t = time.time()
                if edit_url:
                    await page.goto(edit_url, wait_until="domcontentloaded", timeout=30000)
                    try:
                        await page.wait_for_selector(
                            "button.d2l-grade-info, button.d2l-collapsible-panel-opener, [class*='grade-info']",
                            timeout=15000,
                        )
                    except Exception:
                        pass
                else:
                    await page.goto(asgn_url, wait_until="commit")
                    await page.wait_for_selector(
                        "button[aria-haspopup='true'][aria-label*='Actions for']",
                        timeout=30000,
                    )
                    await open_assignment_edit(page, name)
                phases["navigate"] = round(time.time() - t, 2)
                print(f"  Edit URL : {page.url[:100]}")

                if settings.get("set_in_gradebook"):
                    t = time.time()
                    gb_result = await apply_assignment_gradebook(page, dry_run)
                    phases["gradebook"] = round(time.time() - t, 2)
                    changed["gradebook"] = gb_result is True

                t = time.time()
                await apply_pdf_only_file_type(page, dry_run)
                phases["filetype"] = round(time.time() - t, 2)

                t = time.time()
                await save_assignment(page, dry_run)
                phases["save"] = round(time.time() - t, 2)

            except Exception as e:
                failed = True
                print(f"  [W{worker_id}] ✗ {name}: {e}")

            elapsed = round(time.time() - t_start, 1)
            print(f"  [W{worker_id}]  Timing: {elapsed}s  phases: {phases}")

            async with lock:
                results.append({
                    "name": name,
                    "elapsed": elapsed,
                    "failed": failed,
                    "phases": phases,
                    "changed": changed,
                    "worker": worker_id,
                })

            queue.task_done()
    finally:
        await page.close()
```

Note: `apply_assignment_gradebook` needs the same return-value treatment as `apply_gradebook` (Task 2). Add `return True` after "✓ Added to Grade Book", `return False` for "already In Grade Book", `return None` on error.

- [ ] **Step 3: Rewrite run_assignments() loop**

Replace the `for i, name in enumerate(names, start_from):` loop in `run_assignments()` with:

```python
            # Harvest edit URLs
            harvest_page = await context.new_page()
            try:
                asgn_pairs = await harvest_assignment_edit_urls(harvest_page, asgn_url)
            finally:
                await harvest_page.close()

            if not asgn_pairs:
                asgn_pairs = [(n, None) for n in names]
            else:
                asgn_pairs = list(zip(names, [url for _, url in asgn_pairs]))

            queue: asyncio.Queue = asyncio.Queue()
            for i, (name, edit_url) in enumerate(asgn_pairs, start_from):
                await queue.put((i, name, edit_url))

            lock = asyncio.Lock()
            results: list = []

            workers = [
                _assignment_worker(
                    worker_id=w,
                    queue=queue,
                    context=context,
                    asgn_url=asgn_url,
                    settings=settings,
                    dry_run=dry_run,
                    results=results,
                    lock=lock,
                    total=total,
                )
                for w in range(1, WORKER_COUNT + 1)
            ]
            await asyncio.gather(*workers)
```

- [ ] **Step 4: Test run_assignments() manually in dry-run mode**

```bash
cd src && python -c "
import asyncio
from browser import run_assignments
asyncio.run(run_assignments(
    urls=['https://learn.okanagancollege.ca/d2l/home/YOUR_COURSE_ID'],
    dry_run=True,
    settings={'set_in_gradebook': True},
))
"
```

Expected: workers interleave, phase breakdown shown in summary.

- [ ] **Step 5: Commit**

```bash
git add src/browser.py src/navigation.py
git commit -m "feat: parallel worker pool for assignment processing + harvest_assignment_edit_urls()"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| Remove slow_mo=80 | Task 1 ✓ |
| Replace fixed sleeps in actions.py | Task 2 ✓ |
| Replace fixed sleeps in navigation.py | Task 3 ✓ |
| harvest_quiz_edit_urls() passive read | Task 4 ✓ |
| Fallback to action menu if harvest fails | Task 6 (_quiz_worker edit_url=None branch) ✓ |
| asyncio.Queue + worker pool for quizzes | Task 6 ✓ |
| asyncio.Lock for shared results | Task 6 ✓ |
| Per-worker error isolation | Task 6 (_quiz_worker try/except) ✓ |
| Per-phase timing stats schema | Task 5 ✓ |
| changed booleans in timing stats | Task 5 + Task 6 ✓ |
| worker_id in timing stats | Task 5 ✓ |
| Phase breakdown in run summary | Task 5 ✓ |
| Worker pool for assignments | Task 7 ✓ |
| harvest_assignment_edit_urls() | Task 7 ✓ |
| apply_assignment_gradebook return value | Task 7 (Step 2 note) ✓ |

**Type consistency check:**

- `harvest_quiz_edit_urls` → `list[tuple[str, str]]` used in Task 6 as `list(zip(names, [url for _, url in quiz_pairs]))` ✓
- `apply_gradebook` → `bool | None` consumed in Task 6 as `gb_result is True` ✓
- `_save_timing` new signature consumed in Task 6 with matching args ✓
- `WORKER_COUNT` defined in Task 6 Step 1, consumed in Task 6 Step 3 and Task 7 Step 3 ✓
