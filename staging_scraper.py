#!/usr/bin/env python3
"""
Staging Scraper
Logs into lms.harshsaw.ca, scrapes the Ready to Send course list,
filters for semester codes ending in 10/20/30, saves to staging_queue.txt
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

_HERE           = Path(__file__).parent
CB_SESSION_FILE = str(_HERE / "cb_session.json")
CONFIG_FILE     = str(_HERE / "outline_config.json")
QUEUE_FILE      = str(_HERE / "staging_queue.txt")
COURSEBRIDGE_URL = "https://lms.harshsaw.ca"


def load_credentials():
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        return cfg.get("cb_email", ""), cfg.get("cb_password", "")
    except (FileNotFoundError, json.JSONDecodeError):
        return "", ""


# Trades department codes to process (without the -Migrated suffix)
TRADES_CODES = {
    "AMEC", "AMEM", "AMES", "ASTF", "AUME", "CAFD", "CARP", "CJFD",
    "DCGA", "ELEC", "HMET", "HMFP", "HMTM", "PLMB", "PPTF", "RACM",
    "RVTE", "SHMT", "WELD", "WDFD", "CLSN", "CRRD",
}


def get_dept(course_code: str) -> str:
    """Extract department code — first segment before the first '-'."""
    return course_code.split("-")[0].upper()


def should_process(course_code: str) -> bool:
    """Return True if semester ends in 10/20/30 AND department is a trades code."""
    m = re.search(r'\.(\d+)$', course_code)
    if not m:
        return False
    semester = m.group(1)
    ends_ok = semester.endswith("10") or semester.endswith("20") or semester.endswith("30")
    return ends_ok and get_dept(course_code) in TRADES_CODES


def sort_key(course_code: str) -> tuple:
    """Sort 202530 courses first, then alphabetically."""
    m = re.search(r'\.(\d+)$', course_code)
    semester = m.group(1) if m else ""
    return (0 if semester == "202530" else 1, course_code)


async def scrape() -> list[str]:
    email, password = load_credentials()
    if not email or not password:
        print("✗ CourseBridge credentials not found.")
        print("  Open the GUI → Course Outline tab and enter your credentials first.")
        return []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=60)
        context = await browser.new_context(
            storage_state=CB_SESSION_FILE if os.path.exists(CB_SESSION_FILE) else None
        )
        page = await context.new_page()

        print("Opening CourseBridge...")
        await page.goto(COURSEBRIDGE_URL)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)

        # Login if needed
        if await page.locator("input[type='email'], input[name='email']").count():
            print("Logging in...")
            await page.locator("input[type='email'], input[name='email']").first.fill(email)
            await page.locator("input[type='password']").first.fill(password)
            await page.locator("button[type='submit']").first.click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(2000)
            await context.storage_state(path=CB_SESSION_FILE)

        # Click Staging tab
        print("Clicking Staging tab...")
        staging_tab = page.locator("button[id*='trigger-staging'], button:has-text('Staging')").first
        await staging_tab.click()
        await page.wait_for_timeout(1500)

        # Click Ready to Send sub-tab
        print("Clicking Ready to Send...")
        ready_tab = page.locator(
            "button[id*='trigger-ready_to_send'], button:has-text('Ready to Send')"
        ).first
        await ready_tab.click()
        await page.wait_for_timeout(2000)

        # Scrape course codes — regex match against all visible text
        print("Scraping course list...")
        course_codes = await page.evaluate("""
            () => {
                // Match codes like BOOK-110-MAR-80147.202611
                const pattern = /[A-Z][A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+-[0-9]+\\.[0-9]+/g;
                const text = document.body.innerText || '';
                const matches = text.match(pattern) || [];
                return [...new Set(matches)];
            }
        """)

        await context.storage_state(path=CB_SESSION_FILE)
        await browser.close()

    return course_codes


def extract_crn(course_code: str) -> str | None:
    """Extract CRN from course code like BOOK-110-MAR-80147.202611 → '80147'."""
    m = re.search(r'-(\d+)\.\d+$', course_code)
    return m.group(1) if m else None


async def find_staging_shell(page, crn: str) -> str | None:
    """
    Use Brightspace's course search to find the _Staged shell for a given CRN.
    Returns the /d2l/home/{id} href, or None if not found.
    """
    print(f"  Searching Brightspace for CRN {crn}...")

    # Wait for the navigation bar to render the course picker button
    try:
        await page.wait_for_function("""
            () => {
                function walk(root) {
                    for (const el of root.querySelectorAll('button')) {
                        if (el.getAttribute('aria-label') === 'Select a course...')
                            return el.getBoundingClientRect().width > 0;
                    }
                    for (const el of root.querySelectorAll('*')) {
                        if (el.shadowRoot && walk(el.shadowRoot)) return true;
                    }
                    return false;
                }
                return walk(document);
            }
        """, timeout=15000)
    except Exception:
        print("  ✗ Course picker button did not appear within 15s")
        return None

    # Click the "Select a course..." button
    btn = await page.evaluate("""
        () => {
            function walk(root) {
                for (const el of root.querySelectorAll('button')) {
                    if (el.getAttribute('aria-label') === 'Select a course...') {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0) return { x: r.left + r.width/2, y: r.top + r.height/2 };
                    }
                }
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) { const c = walk(el.shadowRoot); if (c) return c; }
                }
                return null;
            }
            return walk(document);
        }
    """)
    if not btn:
        print("  ✗ Could not find course picker button after wait")
        return None

    await page.mouse.click(btn["x"], btn["y"])
    await page.wait_for_timeout(1000)

    # Find the search input (deeply nested in shadow DOM) — click by coords then type
    inp = await page.evaluate("""
        () => {
            function walk(root) {
                for (const el of root.querySelectorAll('input[aria-label="Search"][type="search"]')) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0) return { x: r.left + r.width/2, y: r.top + r.height/2 };
                }
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) { const c = walk(el.shadowRoot); if (c) return c; }
                }
                return null;
            }
            return walk(document);
        }
    """)
    if not inp:
        print("  ✗ Could not find search input")
        await page.keyboard.press("Escape")
        return None

    await page.mouse.click(inp["x"], inp["y"])
    await page.wait_for_timeout(300)
    await page.keyboard.type(crn)
    await page.wait_for_timeout(2000)   # wait for results

    # Results are plain <a> tags in light DOM — find the _Staged one
    links = await page.locator("a.d2l-datalist-item-actioncontrol").all()
    staged_href = None
    for link in links:
        text = (await link.inner_text()).strip()
        if "_Staged" in text:
            staged_href = await link.get_attribute("href")
            print(f"  ✓ Found: {text[:80]}")
            break

    await page.keyboard.press("Escape")
    await page.wait_for_timeout(300)

    if not staged_href:
        print(f"  ⚠ No _Staged shell found for CRN {crn}")

    return staged_href


async def main():
    courses = await scrape()

    if not courses:
        print("No courses found.")
        return

    filtered = sorted([c for c in courses if should_process(c)], key=sort_key)
    skipped  = [c for c in sorted(courses) if not should_process(c)]

    print(f"\n{'─' * 50}")
    print(f"Total courses found  : {len(courses)}")
    print(f"Trades to process    : {len(filtered)}  (202530 first)")
    print(f"Skipped              : {len(skipped)}")
    print(f"{'─' * 50}")

    print("\n✓ Courses to process:")
    for c in filtered:
        m = re.search(r'\.(\d+)$', c)
        tag = " ← 202530" if m and m.group(1) == "202530" else ""
        print(f"   {c}{tag}")

    print("\n✗ Skipped:")
    for c in skipped:
        print(f"   {c}")

    # Save filtered list to file
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        for c in filtered:
            f.write(c + "\n")

    print(f"\n✓ Saved {len(filtered)} courses to staging_queue.txt")


if __name__ == "__main__":
    asyncio.run(main())
