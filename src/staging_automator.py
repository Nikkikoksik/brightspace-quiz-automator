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
from browser import SESSION_FILE, _wait_for_login
from staging_scraper import extract_crn, find_staging_shell

_HERE   = Path(__file__).parent.parent
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


async def run_step2(course_input: str, dry_run: bool = False):
    """
    Step 2: Open Course Admin → Import/Export/Copy Components.
    Leaves the browser open so the user can select the source course and click Copy Components manually.
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
        print("   3. Click 'Copy All Components'")
        print("   4. Close the browser when done")
        print("─" * 50)

        await page.wait_for_event("close", timeout=0)
        print("✓ Step 2 complete")


async def run_steps_1_2(course_input: str, dry_run: bool = False):
    """
    Steps 1 + 2 in a single browser session.
    Hides the blueprint module automatically, then leaves the browser open
    for the user to select the source course and click Copy Components.
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
        print("   3. Click 'Copy All Components'")
        print("   4. Close the browser when done")
        print("─" * 50)

        await page.wait_for_event("close", timeout=0)
        print("✓ Steps 1 + 2 complete")


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
