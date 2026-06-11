#!/usr/bin/env python3
"""
Staging Automator — Step-by-step Brightspace staging process.
Each step is a standalone async function; run_step1 handles Step 1.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from playwright.async_api import async_playwright
from browser import SESSION_FILE, _wait_for_login
from staging_scraper import extract_crn, find_staging_shell

_HERE   = Path(__file__).parent.parent
BS_BASE = "https://learn.okanagancollege.ca"


def _extract_ou(href: str) -> str | None:
    """Extract org-unit ID from /d2l/home/{ou} or full URL."""
    m = re.search(r'/d2l/home/(\d+)', href)
    return m.group(1) if m else None


async def _resolve_ou(page, course_input: str) -> tuple[str | None, str | None]:
    """
    Return (crn, ou) from a URL, CRN, or full course code.
    If a Brightspace URL containing /d2l/home/{ou} is given, the OU is extracted
    directly and the staging shell search is skipped (crn will be None).
    """
    course_input = course_input.strip()

    # Direct URL — extract OU immediately, no CRN needed
    ou = _extract_ou(course_input)
    if ou:
        print(f"  URL detected — OU: {ou}")
        return None, ou

    # If it looks like a URL but has no course ID, give a clear error
    if course_input.startswith("http"):
        print(f"✗ URL is missing a course ID — expected format: https://learn.okanagancollege.ca/d2l/home/12345")
        return None, None

    # CRN or full course code — find the staging shell
    crn = extract_crn(course_input) if "." in course_input else course_input
    if not crn:
        print(f"✗ Could not extract CRN from {course_input!r}")
        return None, None

    print(f"CRN: {crn}")
    href = await find_staging_shell(page, crn)
    if not href:
        print(f"✗ No staging shell found for CRN {crn}")
        return crn, None

    ou = _extract_ou(href)
    if not ou:
        print(f"✗ Could not extract OU from href {href!r}")
        return crn, None

    print(f"  OU: {ou}")
    return crn, ou


_FIND_SWITCH_JS = """
    () => {
        function walk(root) {
            for (const el of root.querySelectorAll('d2l-switch')) {
                const r = el.getBoundingClientRect();
                if (r.width > 0) {
                    return {
                        x:     r.left + r.width  / 2,
                        y:     r.top  + r.height / 2,
                        on:    el.hasAttribute('on'),
                        label: el.getAttribute('aria-label') || el.getAttribute('text') || '',
                    };
                }
            }
            for (const el of root.querySelectorAll('*')) {
                if (el.shadowRoot) { const c = walk(el.shadowRoot); if (c) return c; }
            }
            return null;
        }
        return walk(document);
    }
"""


async def hide_blueprint_module(page, dry_run: bool = False) -> bool:
    """
    Toggle off the first d2l-switch on the Content page (the blueprint module).
    Searches the main document and all iframes. Returns True if hidden (or already hidden).
    """
    await page.wait_for_load_state("networkidle", timeout=20000)
    await page.wait_for_timeout(2000)

    frames = page.frames

    # Search main frame and every iframe
    result = None
    found_frame = None
    for frame in frames:
        try:
            r = await frame.evaluate(_FIND_SWITCH_JS)
            if r:
                result = r
                found_frame = frame
                break
        except Exception:
            continue

    if not result:
        print("  ✗ No d2l-switch found in any frame")
        return False

    label = result["label"] or "(no label)"
    print(f"  Found switch: {label!r}  on={result['on']}  frame={found_frame.url[:60]}")

    if not result["on"]:
        print("  ✓ Already hidden — nothing to do")
        return True

    if dry_run:
        print("  ⚠ DRY RUN — would click switch to hide")
        return True

    # For iframes, getBoundingClientRect coords are relative to the iframe viewport.
    # Add the iframe's page-level offset to get the true page coordinates.
    x, y = result["x"], result["y"]
    if found_frame != page.main_frame:
        frame_el = await found_frame.frame_element()
        box = await frame_el.bounding_box()
        if box:
            x += box["x"]
            y += box["y"]

    await page.mouse.click(x, y)
    await page.wait_for_timeout(1500)
    print("  ✓ Module hidden")
    return True


async def maybe_rename_staged(page, popup_fn) -> bool:
    """
    Check if the currently open Brightspace course is _Staged.
    If so, ask via popup_fn and rename _Staged → _Ready if confirmed.
    Returns True if renamed, False otherwise. Safe to call on any page.
    """
    try:
        nav = page.locator("a.d2l-navigation-s-link").first
        if not await nav.count():
            print("  Rename check: nav link not found on this page — skipping")
            return False
        title = await nav.get_attribute("title") or ""
        href  = await nav.get_attribute("href")  or ""
        print(f"  Rename check: course = '{title}'")
        if "_Staged" not in title:
            print("  Rename check: not a _Staged course — skipping")
            return False

        new_title = title.replace("_Staged", "_Ready")
        m = re.search(r'/d2l/home/(\d+)', href)
        if not m:
            print("  ⚠ Could not extract OU from nav link — skipping rename")
            return False
        ou = m.group(1)

        loop = asyncio.get_running_loop()
        confirmed = await loop.run_in_executor(None, lambda: popup_fn(
            "Mark as Ready?",
            f"Rename this course from:\n\n  {title}\n\nto:\n\n  {new_title}?"
        ))
        if not confirmed:
            print("  Skipping rename — user declined")
            return False

        print(f"  Renaming {title} → {new_title}...")
        settings_url = f"{BS_BASE}/d2l/lms/coursesettings/main_frame.d2l?ou={ou}"
        await page.goto(settings_url)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)

        name_field = page.locator("input[name='courseOffName']")
        code_field = page.locator("input[name='courseOffCode']")
        name_val = await name_field.input_value()
        code_val = await code_field.input_value()

        await name_field.triple_click()
        await name_field.fill(name_val.replace("_Staged", "_Ready"))
        await code_field.triple_click()
        await code_field.fill(code_val.replace("_Staged", "_Ready"))

        await page.locator("button.d2l-button[primary]").first.click()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(1000)
        print("  ✓ Renamed to _Ready")
        return True

    except Exception as e:
        print(f"  ⚠ Rename check failed: {e}")
        return False


async def run_mark_ready(course_input: str, dry_run: bool = False):
    """
    Find the _Staged shell for the given CRN/URL and rename _Staged → _Ready
    in both Course Offering Name and Code fields, then save.
    Skips silently if already _Ready. Leaves the browser open for verification.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80, args=["--start-maximized"])
        context = await browser.new_context(
            storage_state=SESSION_FILE if os.path.exists(SESSION_FILE) else None,
            no_viewport=True,
        )
        page = await context.new_page()
        await _wait_for_login(page, context)

        crn, ou = await _resolve_ou(page, course_input)
        if not ou:
            await browser.close()
            return

        settings_url = f"{BS_BASE}/d2l/lms/coursesettings/main_frame.d2l?ou={ou}"
        print(f"  Navigating to Course Offering Information...")
        await page.goto(settings_url)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)

        name_field = page.locator("input[name='courseOffName']")
        code_field = page.locator("input[name='courseOffCode']")
        name_val = await name_field.input_value()
        code_val = await code_field.input_value()
        print(f"  Name : {name_val}")
        print(f"  Code : {code_val}")

        if "_Ready" in name_val and "_Ready" in code_val:
            print("  ✓ Already marked as Ready — nothing to do")
            await browser.close()
            return

        if "_Staged" not in name_val and "_Staged" not in code_val:
            print("  ⚠ Neither _Staged nor _Ready found — check the course manually")
            await browser.close()
            return

        new_name = name_val.replace("_Staged", "_Ready")
        new_code = code_val.replace("_Staged", "_Ready")
        print(f"  Renaming to:")
        print(f"    Name : {new_name}")
        print(f"    Code : {new_code}")

        if dry_run:
            print("  [DRY RUN] Would save — skipping")
            await browser.close()
            return

        await name_field.triple_click()
        await name_field.fill(new_name)
        await code_field.triple_click()
        await code_field.fill(new_code)

        await page.locator("button.d2l-button[primary]").first.click()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(1000)
        print("  ✓ Saved")
        await browser.close()


async def run_step1(course_input: str, dry_run: bool = False):
    """
    Step 1: Find the staging shell for a CRN, URL, or full course code and hide the blueprint module.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80, args=["--start-maximized"])
        context = await browser.new_context(
            storage_state=SESSION_FILE if os.path.exists(SESSION_FILE) else None,
            no_viewport=True,
        )
        page = await context.new_page()

        await _wait_for_login(page, context)

        _, ou = await _resolve_ou(page, course_input)
        if not ou:
            await browser.close()
            return

        # Navigate to the Content page
        content_url = f"{BS_BASE}/d2l/le/content/{ou}/Home"
        print(f"  Navigating to Content: {content_url}")
        await page.goto(content_url, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=30000)

        print("\nStep 1 — Hide blueprint module")
        await hide_blueprint_module(page, dry_run=dry_run)

        print(f"\n{'─' * 50}")
        print("✓ Step 1 complete")
        await browser.close()


async def run_step2(course_input: str, dry_run: bool = False):
    """
    Step 2: Open Course Admin → Import/Export/Copy Components.
    Accepts a CRN, full course code, or Brightspace URL.
    Leaves the browser open so the user can select the source course and click Copy Components manually.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80, args=["--start-maximized"])
        context = await browser.new_context(
            storage_state=SESSION_FILE if os.path.exists(SESSION_FILE) else None,
            no_viewport=True,
        )
        page = await context.new_page()

        await _wait_for_login(page, context)

        _, ou = await _resolve_ou(page, course_input)
        if not ou:
            await browser.close()
            return

        print("  Navigating to Course Admin...")
        await page.goto(f"{BS_BASE}/d2l/lp/cmc/main.d2l?ou={ou}", wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=20000)

        print("  Clicking Import / Export / Copy Components...")
        await page.locator(f"a[href*='import_export.d2l?ou={ou}']").first.click()
        await page.wait_for_load_state("domcontentloaded", timeout=20000)

        print(f"\n{'─' * 50}")
        print("✋ Browser is ready.")
        print("   1. Click 'Search for offering' and find your source course")
        print("   2. Select it and click 'Add Selected'")
        print("   3. Click 'Select Components'")
        print("   4. Click 'Select All Components', then unselect 'Grades' and 'Grade Settings'")
        print("   5. Click 'Continue'")
        print("   6. Click 'Finish'")
        print("   7. Close the browser when done")
        print("─" * 50)

        await page.wait_for_event("close", timeout=0)
        print("✓ Step 2 complete")


async def run_steps_1_2(course_input: str, dry_run: bool = False, prompt_fn=None, note_fn=None):
    """
    Steps 1 + 2 in a single browser session.
    Hides the blueprint module automatically, then leaves the browser open
    for the user to select the source course and click Copy Components.
    After step 2, optionally continues through Quiz, Assignment, and Course Outline automators.
    prompt_fn: callable(str) -> str  (defaults to built-in input)
    note_fn:   callable(str)         (called when a note should be added to the Notes tab)
    """
    _prompt = prompt_fn if prompt_fn else input
    _note   = note_fn if note_fn else lambda t: print(f"[NOTE] {t}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80, args=["--start-maximized"])
        context = await browser.new_context(
            storage_state=SESSION_FILE if os.path.exists(SESSION_FILE) else None,
            no_viewport=True,
        )
        page = await context.new_page()

        await _wait_for_login(page, context)

        _, ou = await _resolve_ou(page, course_input)
        if not ou:
            await browser.close()
            return

        print(f"  OU: {ou}")

        # --- Step 1 ---
        content_url = f"{BS_BASE}/d2l/le/content/{ou}/Home"
        print(f"\nStep 1 — Hide blueprint module")
        print(f"  Navigating to Content: {content_url}")
        await page.goto(content_url, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=30000)
        await hide_blueprint_module(page, dry_run=dry_run)
        print("✓ Step 1 complete")

        # --- Step 2 ---
        print(f"\nStep 2 — Copy components")
        print("  Navigating to Course Admin...")
        await page.goto(f"{BS_BASE}/d2l/lp/cmc/main.d2l?ou={ou}", wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=20000)

        print("  Clicking Import / Export / Copy Components...")
        await page.locator(f"a[href*='import_export.d2l?ou={ou}']").first.click()
        await page.wait_for_load_state("domcontentloaded", timeout=20000)

        print(f"\n{'─' * 50}")
        print("✋ Browser is ready.")
        print("   1. Click 'Search for offering' and find your source course")
        print("   2. Select it and click 'Add Selected'")
        print("   3. Click 'Select Components'")
        print("   4. Click 'Select All Components', then unselect 'Grades' and 'Grade Settings'")
        print("   5. Click 'Continue'")
        print("   6. Click 'Finish'")
        print("   7. Close the browser when done")
        print("─" * 50)

        await page.wait_for_event("close", timeout=0)
        print("✓ Steps 1 + 2 complete")

    # Ask about quizzes outside the playwright context so a new session can open
    course_url = f"{BS_BASE}/d2l/home/{ou}"
    loop = asyncio.get_event_loop()

    def _review_fn(label):
        print(f"\n{'─' * 50}")
        print(f"✋ {label} done — browser is still open.")
        print("   Review any missed items, make manual corrections, then close the browser.")
        print("─" * 50)
        _prompt("Press Enter when you are done reviewing…")

    answer = await loop.run_in_executor(None, _prompt, "Continue with Quiz Automator? (y/n): ")
    if answer.strip().lower() in ("y", "yes"):
        print("\nStarting Quiz Automator...")
        from browser import run as run_quiz
        settings = {"set_in_gradebook": True, "set_auto_submit": True}
        await run_quiz([course_url], dry_run=dry_run, settings=settings,
                       review_fn=lambda: _review_fn("Quiz Automator"))

    answer = await loop.run_in_executor(None, _prompt, "Continue with Assignment Automator? (y/n): ")
    if answer.strip().lower() in ("y", "yes"):
        print("\nStarting Assignment Automator...")
        from browser import run_assignments
        settings = {"set_in_gradebook": True}
        await run_assignments([course_url], dry_run=dry_run, settings=settings,
                              review_fn=lambda: _review_fn("Assignment Automator"))

    answer = await loop.run_in_executor(None, _prompt, "Continue with Course Outline? (y/n): ")
    if answer.strip().lower() in ("y", "yes"):
        print("\nStarting Course Outline Automator...")
        from course_outline_automator import run as run_outline
        await run_outline(dry_run=dry_run, course_url=course_url, prompt_fn=_prompt)

        answer = await loop.run_in_executor(None, _prompt, "Was the course outline found? (y/n): ")
        if answer.strip().lower() not in ("y", "yes"):
            _note("No syllabus present in course shell - syllabus not applied to syllabus template. Gradebook not set up.")
        else:
            answer = await loop.run_in_executor(None, _prompt, "Were there grade categories in the gradebook? (y/n): ")
            if answer.strip().lower() not in ("y", "yes"):
                _note("Grade items present in gradebook so made one category weighted 100% and all items have been placed in this category")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Staging automator")
    parser.add_argument("step", choices=["1", "2", "1+2"], help="Step to run")
    parser.add_argument("crn", help="CRN or full course code for the staging shell")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.step == "1":
        asyncio.run(run_step1(args.crn, dry_run=args.dry_run))
    elif args.step == "2":
        asyncio.run(run_step2(args.crn, dry_run=args.dry_run))
    elif args.step == "1+2":
        asyncio.run(run_steps_1_2(args.crn, dry_run=args.dry_run))
