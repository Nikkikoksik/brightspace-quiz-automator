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

_HERE   = Path(__file__).parent
BS_BASE = "https://learn.okanagancollege.ca"


def _extract_ou(href: str) -> str | None:
    """Extract org-unit ID from /d2l/home/{ou} or full URL."""
    m = re.search(r'/d2l/home/(\d+)', href)
    return m.group(1) if m else None


async def hide_blueprint_module(page, dry_run: bool = False) -> bool:
    """
    Toggle off the first d2l-switch on the Content page (the blueprint module).
    Returns True if hidden (or already hidden), False if switch not found.
    """
    result = await page.evaluate("""
        () => {
            function walk(root) {
                for (const el of root.querySelectorAll('d2l-switch')) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0) {
                        return {
                            x:       r.left + r.width  / 2,
                            y:       r.top  + r.height / 2,
                            checked: el.getAttribute('aria-checked') === 'true',
                            label:   el.getAttribute('aria-label') || el.getAttribute('text') || '',
                        };
                    }
                }
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) {
                        const c = walk(el.shadowRoot);
                        if (c) return c;
                    }
                }
                return null;
            }
            return walk(document);
        }
    """)

    if not result:
        print("  ✗ No d2l-switch found on this page")
        return False

    label = result["label"] or "(no label)"
    print(f"  Found switch: {label!r}  checked={result['checked']}")

    if not result["checked"]:
        print("  ✓ Already hidden — nothing to do")
        return True

    if dry_run:
        print("  ⚠ DRY RUN — would click switch to hide")
        return True

    await page.mouse.click(result["x"], result["y"])
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


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Staging automator — Step 1")
    parser.add_argument("crn", help="CRN or full course code")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(run_step1(args.crn, dry_run=args.dry_run))
