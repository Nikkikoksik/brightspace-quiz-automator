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
    sys.stdout.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright
from browser import SESSION_FILE, _wait_for_login, run as browser_run, run_assignments as browser_run_assignments
from staging_scraper import extract_crn, find_staging_shell

_HERE   = Path(__file__).parent
BS_BASE = "https://learn.okanagancollege.ca"


def _extract_ou(href: str) -> str | None:
    """Extract org-unit ID from /d2l/home/{ou} or full URL."""
    m = re.search(r'/d2l/home/(\d+)', href)
    return m.group(1) if m else None


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


async def run_step1(course_input: str, dry_run: bool = False):
    """
    Step 1: Find the staging shell for a CRN and hide the blueprint module.
    course_input can be a CRN ('80147') or full course code ('BOOK-110-MAR-80147.202611').
    """
    crn = extract_crn(course_input) if "." in course_input else course_input.strip()
    if not crn:
        print(f"✗ Could not extract CRN from {course_input!r}")
        return

    print(f"CRN: {crn}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80)
        context = await browser.new_context(
            storage_state=SESSION_FILE if os.path.exists(SESSION_FILE) else None,
        )
        page = await context.new_page()

        await _wait_for_login(page, context)

        # Find the _Staged shell
        href = await find_staging_shell(page, crn)
        if not href:
            print(f"✗ No staging shell found for CRN {crn}")
            await browser.close()
            return

        ou = _extract_ou(href)
        if not ou:
            print(f"✗ Could not extract OU from href {href!r}")
            await browser.close()
            return

        print(f"  OU: {ou}")

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


async def run_step2(course_input: str, source_course: str = "", dry_run: bool = False):
    """
    Step 2: Open Course Admin → Import/Export/Copy Components → Search for offering.
    course_input: CRN or full code for the staging shell.
    source_course: optional override. If not provided, opens platform tools so user can pick manually.
    """
    crn = extract_crn(course_input) if "." in course_input else course_input.strip()
    if not crn:
        print(f"✗ Could not extract CRN from {course_input!r}")
        return

    print(f"CRN: {crn}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80)
        context = await browser.new_context(
            storage_state=SESSION_FILE if os.path.exists(SESSION_FILE) else None,
        )
        page = await context.new_page()

        await _wait_for_login(page, context)

        href = await find_staging_shell(page, crn)
        if not href:
            print(f"✗ No staging shell found for CRN {crn}")
            await browser.close()
            return

        ou = _extract_ou(href)
        if not ou:
            print(f"✗ Could not extract OU from href {href!r}")
            await browser.close()
            return

        print(f"  OU: {ou}")

        # If no source course provided, open platform tools so user can pick
        if not source_course:
            print(f"\n  Opening course list for CRN {crn}...")
            await page.goto(f"{BS_BASE}/d2l/platformTools/courses/6606?coursesTab=1", wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle", timeout=20000)
            search = page.locator("input[aria-label='Search Courses']")
            await search.fill(crn)
            await search.press("Enter")
            await page.wait_for_timeout(2000)
            print("  ─" * 25)
            print("  Look through the courses in the browser.")
            print("  Find the source course (not _Staged, not _Ready).")
            source_course = input("  Type the offering code of the source course: ").strip()

        # Course Admin
        print("  Navigating to Course Admin...")
        await page.goto(f"{BS_BASE}/d2l/lp/cmc/main.d2l?ou={ou}", wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=20000)

        # Import/Export/Copy Components
        print("  Clicking Import / Export / Copy Components...")
        await page.locator(f"a[href*='import_export.d2l?ou={ou}']").first.click()
        await page.wait_for_load_state("domcontentloaded", timeout=20000)

        # Search for offering — opens a popup
        print("  Clicking Search for offering...")
        async with page.expect_popup() as popup_info:
            await page.locator("button#z_j").click()
        popup = await popup_info.value
        await popup.wait_for_load_state("networkidle", timeout=15000)

        print(f"  Popup URL: {popup.url}")
        print(f"  Typing source course: {source_course!r}")
        body_frame = None
        for frame in popup.frames:
            try:
                await frame.wait_for_selector("#z_b", timeout=2000)
                body_frame = frame
                break
            except Exception:
                continue
        if body_frame is None:
            raise Exception("Could not find search input (#z_b) in any popup frame")
        await body_frame.locator("#z_b").fill(source_course)

        # Click Search button
        print("  Clicking Search...")
        await body_frame.locator("input[value='Search'], button:has-text('Search')").first.click()
        await body_frame.wait_for_load_state("domcontentloaded", timeout=15000)
        await body_frame.wait_for_timeout(1000)

        # Select matching result radio button (match by full source course name)
        print("  Selecting matching result...")
        rows = await body_frame.locator("tr").all()
        selected = False
        for row in rows:
            text = await row.inner_text()
            if source_course in text:
                radio = row.locator("input[type='radio']")
                if await radio.count() > 0:
                    await radio.first.click()
                    print(f"  ✓ Selected row: {text.strip()[:80]}")
                    selected = True
                    break
        if not selected:
            print("  ⚠ No matching row found — check the popup manually")

        # Click Add Selected button (in Footer frame)
        print("  Clicking Add Selected...")
        add_frame = None
        for frame in popup.frames:
            try:
                await frame.wait_for_selector("button:has-text('Add Selected')", timeout=2000)
                add_frame = frame
                break
            except Exception:
                continue
        if add_frame is None:
            raise Exception("Could not find 'Add Selected' button in any popup frame")
        await add_frame.locator("button:has-text('Add Selected')").first.click()
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        await page.wait_for_timeout(1000)

        # Click Copy All Components
        print("  Clicking Copy All Components...")
        await page.locator("button:has-text('Copy All Components')").first.click()

        # Wait for copy to finish — can take a long time
        print("  Waiting for copy to complete (this may take a while)...")
        await page.wait_for_selector("button:has-text('View Content')", timeout=300000)
        print("  ✓ Copy complete — clicking View Content...")
        await page.locator("button:has-text('View Content')").first.click()
        await page.wait_for_load_state("domcontentloaded", timeout=15000)

        print(f"\n{'─' * 50}")
        print("✓ Step 2 — components copied. Ready for next step.")
        input("  Press Enter to close...")
        await browser.close()


async def run_step2_gradebook(course_input: str, dry_run: bool = False, pause_fn=None, ask_fn=None):
    """
    Step 2b: Run quiz + assignment automator on the staged course to link everything to gradebook.
    course_input: CRN or full code for the staging shell.
    """
    crn = extract_crn(course_input) if "." in course_input else course_input.strip()
    if not crn:
        print(f"✗ Could not extract CRN from {course_input!r}")
        return

    print(f"CRN: {crn}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80)
        context = await browser.new_context(
            storage_state=SESSION_FILE if os.path.exists(SESSION_FILE) else None,
        )
        page = await context.new_page()

        await _wait_for_login(page, context)

        href = await find_staging_shell(page, crn)
        if not href:
            print(f"✗ No staging shell found for CRN {crn}")
            await browser.close()
            return

        ou = _extract_ou(href)
        if not ou:
            print(f"✗ Could not extract OU from href {href!r}")
            await browser.close()
            return

        print(f"  OU: {ou}")
        await browser.close()

    quiz_url = f"{BS_BASE}/d2l/lms/quizzing/admin/quizzes_manage.d2l?ou={ou}"
    assign_url = f"{BS_BASE}/d2l/lms/dropbox/user/folders_list.d2l?ou={ou}"

    print(f"\n{'─' * 50}")
    print("Step 2b — Quizzes (gradebook + auto-submit)...")
    await browser_run(
        [quiz_url],
        dry_run=dry_run,
        settings={"set_in_gradebook": True, "set_auto_submit": True},
        pause_fn=pause_fn,
        ask_fn=ask_fn,
    )

    print(f"\n{'─' * 50}")
    print("Step 2b — Assignments (gradebook)...")
    await browser_run_assignments(
        [assign_url],
        dry_run=dry_run,
        settings={"set_in_gradebook": True},
        pause_fn=pause_fn,
        ask_fn=ask_fn,
    )

    print(f"\n{'─' * 50}")
    print("✓ Step 2b complete — quizzes and assignments linked to gradebook.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Staging automator")
    parser.add_argument("step", choices=["1", "2", "2g"], help="Step to run (2g = gradebook)")
    parser.add_argument("crn", help="CRN or full course code for the staging shell")
    parser.add_argument("--source", help="Source course code (Step 2 only)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.step == "1":
        asyncio.run(run_step1(args.crn, dry_run=args.dry_run))
    elif args.step == "2":
        asyncio.run(run_step2(args.crn, args.source or "", dry_run=args.dry_run))
    elif args.step == "2g":
        asyncio.run(run_step2_gradebook(args.crn, dry_run=args.dry_run))
