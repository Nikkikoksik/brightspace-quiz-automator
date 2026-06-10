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

_HERE           = Path(__file__).parent.parent
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


async def scrape(search_terms: list[str] | None = None) -> list[str]:
    email, password = load_credentials()
    if not email or not password:
        print("✗ CourseBridge credentials not found.")
        print("  Open the GUI → Course Outline tab and enter your credentials first.")
        return []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
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

        # Click staging sub-tab (was "Ready to Send", renamed to "Staging in Process")
        print("Clicking staging sub-tab...")
        ready_tab = page.locator(
            "button[id*='trigger-staging_in_progress'], button[id*='trigger-ready_to_send'], "
            "button:has-text('Staging in Process'), button:has-text('Ready to Send')"
        ).first
        await ready_tab.click()
        await page.wait_for_timeout(2000)

        # Clear any active search/filter left over from a previous session
        search_inputs = await page.locator("input[type='search'], input[placeholder*='earch'], input[placeholder*='ilter']").all()
        for inp in search_inputs:
            if await inp.is_visible():
                await inp.click(click_count=3)
                await inp.press("Delete")
                await inp.press("Escape")
        if search_inputs:
            await page.wait_for_timeout(800)

        # Find the search input on the staging tab
        search_input = page.locator(
            "input[type='search'], input[placeholder*='earch'], input[placeholder*='ilter'], input[placeholder*='course']"
        ).first

        # Use provided search terms if given, otherwise fall back to dept codes
        terms = search_terms if search_terms else sorted(TRADES_CODES)
        print(f"Searching {len(terms)} term(s): {terms if len(terms) <= 5 else str(terms[:5])[:-1] + ', …]'}")
        all_codes: dict[str, None] = {}  # dict preserves insertion order, deduplicates
        for term in terms:
            await search_input.click(click_count=3)
            await search_input.type(term, delay=50)
            await page.wait_for_timeout(1000)

            # Scroll to load all results (virtual scroll renders rows lazily)
            seen: dict[str, None] = {}
            stale = 0
            while stale < 2:
                batch = await page.evaluate("""
                    () => {
                        const pattern = /[A-Z][A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+-[0-9]+\\.[0-9]+/g;
                        return [...document.body.innerText.matchAll(pattern)].map(m => m[0]);
                    }
                """)
                new_this_pass = [c for c in batch if c not in seen]
                if not new_this_pass:
                    stale += 1
                else:
                    stale = 0
                    seen.update(dict.fromkeys(new_this_pass))
                await page.evaluate("""
                    () => {
                        for (const el of document.querySelectorAll(
                            '[data-radix-scroll-area-viewport], .overflow-y-auto, .overflow-auto'
                        )) {
                            if (el.scrollHeight > el.clientHeight) el.scrollTop = el.scrollHeight;
                        }
                        window.scrollTo(0, document.body.scrollHeight);
                    }
                """)
                await page.wait_for_timeout(800)

            before = len(all_codes)
            all_codes.update(dict.fromkeys(c for c in seen if c not in all_codes))
            found = len(all_codes) - before
            if found:
                print(f"  {term}: +{found} course(s)")

        print(f"Scraping complete — {len(all_codes)} total courses found")
        course_codes = list(all_codes.keys())

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
    await page.wait_for_timeout(400)
    await page.keyboard.press("Control+a")
    await page.keyboard.type(crn, delay=80)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(3000)        # wait for filtered results

    # Results are plain <a> tags in light DOM — find the _Staged one
    links = await page.locator("a.d2l-datalist-item-actioncontrol").all()
    if not links:
        print(f"  ⚠ Search returned no results at all for CRN {crn}")
    else:
        print(f"  Search returned {len(links)} result(s):")
        for link in links:
            print(f"    · {(await link.inner_text()).strip()[:80]}")

    staged_href = None
    for link in links:
        text = (await link.inner_text()).strip()
        if "_Staged" in text and crn in text:
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
