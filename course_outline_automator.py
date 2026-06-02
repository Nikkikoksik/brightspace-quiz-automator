#!/usr/bin/env python3
"""
Course Outline Automator

Usage:
  python course_outline_automator.py              # full run
  python course_outline_automator.py --dry-run   # download + convert only, no paste
"""

import asyncio
import os
import re
import sys
import argparse
import tempfile
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright, Page

# ── Config defaults (overridable via run() parameters or GUI) ─────────────────
BRIGHTSPACE_BASE      = "https://learn.okanagancollege.ca"
COURSEBRIDGE_URL      = "https://lms.harshsaw.ca/content-converter"
COURSEBRIDGE_EMAIL    = ""   # set via GUI — saved to outline_config.json
COURSEBRIDGE_PASSWORD = ""   # set via GUI — saved to outline_config.json

OUTLINE_SEARCH_TERMS = ["syllabus", "outline", "guideline"]
SYLLABUS_TOPIC_NAME  = "Course Syllabus"

_HERE = Path(__file__).parent
BS_SESSION_FILE = str(_HERE / "session.json")   # shared with quiz automator
CB_SESSION_FILE = str(_HERE / "cb_session.json")

COURSE_URL = ""


# ── Step 1: Find and download course outline ──────────────────────────────────
async def find_and_download_outline(page: Page, prompt_fn=input) -> Path:
    """Scan content tree for the outline, confirm with user, download it."""
    print("\nStep 1 — Finding course outline...")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(1000)

    found_link  = None
    found_title = None

    # Debug: show all links on the page so we can see what's there
    all_links = await page.locator("a[href]").all()
    print(f"  [DEBUG] Total links on page: {len(all_links)}")
    for lnk in all_links[:30]:
        try:
            txt  = (await lnk.inner_text()).strip().replace("\n", " ")[:60]
            href = (await lnk.get_attribute("href") or "")[:80]
            if txt:
                print(f"    LINK: {txt!r:40s}  href={href}")
        except Exception:
            pass

    # Scan the content tree directly — no search box needed
    for term in OUTLINE_SEARCH_TERMS:
        print(f"  Scanning for '{term}'...")
        links = page.locator(f"a:has-text('{term}')")
        count = await links.count()
        print(f"    {count} link(s) found")
        if count:
            found_link  = links.first
            found_title = (await found_link.inner_text()).strip()
            print(f"    Candidate: {found_title[:80]}")
            break

    if found_title:
        confirm = prompt_fn(
            f"Found: {found_title}\n\nIs this the correct outline? (y/n)"
        ).strip().lower()
        if confirm != "y":
            found_link  = None
            found_title = None

    download_dir = Path(tempfile.mkdtemp())

    if found_link:
        # Strategy 1: check the topic's 3-dot actions menu for a Download option
        print("  Checking topic actions menu for Download...")
        short_title = found_title[:40]
        topic_row = page.locator(
            f"li:has(a:has-text('{short_title}')), "
            f"d2l-list-item:has(a:has-text('{short_title}'))"
        ).first
        actions_btn = topic_row.locator(
            "button[aria-haspopup='true'], button[aria-label*='More'], button[aria-label*='Actions']"
        ).first

        downloaded = False
        if await actions_btn.count():
            await actions_btn.click()
            await page.wait_for_timeout(400)
            dl_option = page.locator("d2l-menu-item[text='Download'], li:has-text('Download')")
            if await dl_option.count():
                print("  Downloading via actions menu...")
                async with page.expect_download(timeout=30000) as dl_info:
                    await dl_option.first.click()
                download = await dl_info.value
                dest = download_dir / download.suggested_filename
                await download.save_as(dest)
                downloaded = True
            else:
                print("  No Download option in menu — trying link click...")
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(300)

        if not downloaded:
            # Strategy 2: click the link → open viewer → find download button
            print("  Opening topic viewer...")
            await found_link.click()
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(1000)

            dl_btn = page.locator(
                "a[download], a:has-text('Download'), button:has-text('Download'), "
                "[aria-label*='Download']"
            ).first
            if await dl_btn.count():
                print("  Found Download button in viewer, clicking...")
                async with page.expect_download(timeout=30000) as dl_info:
                    await dl_btn.click()
                download = await dl_info.value
                dest = download_dir / download.suggested_filename
                await download.save_as(dest)
                downloaded = True
            else:
                print("  No download button in viewer — falling back to manual...")

        if downloaded:
            print(f"  ✓ Downloaded: {dest.name}")
            return dest

    # Manual fallback: user clicks the download, we capture it
    print("  Manual download: waiting for you to click the file in the browser...")
    prompt_fn(
        "Could not auto-download. In the browser, find the outline file and click its "
        "Download option. Then click OK here."
    )
    # Capture whatever download just happened (event is buffered by browser)
    try:
        async with page.expect_download(timeout=10000) as dl_info:
            pass
        download = await dl_info.value
        dest = download_dir / download.suggested_filename
        await download.save_as(dest)
        print(f"  ✓ Downloaded: {dest.name}")
        return dest
    except Exception:
        raise RuntimeError(
            "No download detected. Please run again and use the Download option "
            "for the file before clicking OK."
        )


# ── Step 2: PDF → docx if needed ─────────────────────────────────────────────
def convert_pdf_to_docx(pdf_path: Path) -> Path:
    """Convert PDF to docx locally using pdf2docx."""
    try:
        from pdf2docx import Converter
    except ImportError:
        print("  Installing pdf2docx...")
        os.system(f"{sys.executable} -m pip install pdf2docx")
        from pdf2docx import Converter

    docx_path = pdf_path.with_suffix(".docx")
    print("  Converting PDF → docx...")
    cv = Converter(str(pdf_path))
    cv.convert(str(docx_path))
    cv.close()
    print(f"  ✓ Converted: {docx_path.name}")
    return docx_path


# ── Step 3: CourseBridge conversion ──────────────────────────────────────────
async def convert_with_coursebridge(file_path: Path, email: str, password: str) -> str:
    """Upload docx to CourseBridge, return HTML string.

    NOTE: internals will be replaced with a single API call once the
    CourseBridge developer provides an endpoint.
    Signature stays: convert_with_coursebridge(file_path, email, password) -> str
    """
    print("\nStep 3 — CourseBridge conversion...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=60)
        context = await browser.new_context(
            storage_state=CB_SESSION_FILE if os.path.exists(CB_SESSION_FILE) else None
        )
        page = await context.new_page()
        await page.goto(COURSEBRIDGE_URL)

        if await page.locator("input[type='email'], input[name='email']").count():
            print("  Logging into CourseBridge...")
            await page.locator("input[type='email'], input[name='email']").first.fill(email)
            await page.locator("input[type='password']").first.fill(password)
            await page.locator("button[type='submit']").first.click()
            await page.wait_for_load_state("networkidle")
            await context.storage_state(path=CB_SESSION_FILE)

        await page.wait_for_load_state("networkidle")

        print(f"  Uploading {file_path.name}...")
        await page.locator("input[accept='.pdf,.doc,.docx']").set_input_files(str(file_path))
        await page.wait_for_timeout(500)

        trigger = page.locator("button[data-slot='select-trigger']").first
        template_text = await trigger.inner_text()
        if "Course Syllabus" not in template_text:
            print(f"  ⚠ Template shows '{template_text.strip()}' — setting Course Syllabus...")
            await trigger.click()
            await page.locator("text=Course Syllabus").first.click()
            await page.wait_for_timeout(300)

        print("  Converting...")
        await page.locator("button:has-text('Convert Document')").first.click()

        await page.wait_for_function(
            "() => document.querySelector('div.font-mono')?.innerText?.includes('Done!')",
            timeout=120000
        )
        print("  ✓ Conversion complete")

        html = await page.locator("pre.font-mono").first.inner_text()

        await context.storage_state(path=CB_SESSION_FILE)
        await browser.close()

    print(f"  ✓ HTML captured ({len(html)} chars)")
    return html


# ── Step 4: Paste HTML into Brightspace ───────────────────────────────────────
async def paste_html_to_syllabus(page: Page, html: str, prompt_fn=input):
    """Navigate to Welcome Module → Course Syllabus topic and replace HTML."""
    print("\nStep 4 — Pasting HTML into Brightspace...")

    topic = page.locator(f"text={SYLLABUS_TOPIC_NAME}").first
    if not await topic.count():
        print(f"  ⚠ Topic '{SYLLABUS_TOPIC_NAME}' not found.")
        choice = prompt_fn(f"Topic '{SYLLABUS_TOPIC_NAME}' not found. Continue anyway? (y/n)").strip().lower()
        if choice != "y":
            print("  Aborted.")
            return

    print(f"  Opening '{SYLLABUS_TOPIC_NAME}' actions menu...")
    dots_btn = page.locator(
        f"button[aria-label*='{SYLLABUS_TOPIC_NAME}'], "
        f"d2l-dropdown-button-subtle[text='{SYLLABUS_TOPIC_NAME}']"
    ).first
    if not await dots_btn.count():
        topic_row = page.locator(
            f"li:has-text('{SYLLABUS_TOPIC_NAME}'), d2l-list-item:has-text('{SYLLABUS_TOPIC_NAME}')"
        ).first
        dots_btn = topic_row.locator("button[aria-haspopup='true'], button[aria-label*='Actions']").first

    await dots_btn.click()
    await page.wait_for_timeout(400)
    await page.locator("d2l-menu-item[text='Edit'], li:has-text('Edit')").first.click()

    async with page.context.expect_page() as new_page_info:
        pass
    edit_page = await new_page_info.value
    await edit_page.wait_for_load_state("networkidle")
    print("  Edit page opened")

    await edit_page.wait_for_selector("iframe[id*='tinymce'], .tox-tinymce", timeout=20000)
    await edit_page.wait_for_timeout(1000)

    source_btn = edit_page.locator("button[aria-label='Source code'], button[title='Source code']").first
    if not await source_btn.count():
        source_btn = edit_page.locator("button:has-text('</>'), button[data-mce-name='code']").first
    await source_btn.click()
    await edit_page.wait_for_timeout(500)

    print("  Replacing HTML in source dialog...")
    textarea = edit_page.locator("div.tox-dialog textarea, textarea.tox-textarea").first
    await textarea.click()
    await edit_page.keyboard.press("Control+a")
    await textarea.fill(html)
    await edit_page.wait_for_timeout(300)

    await edit_page.locator("button:has-text('Save'), button[title='Save']").last.click()
    await edit_page.wait_for_timeout(500)

    await edit_page.locator("button:has-text('Save'), d2l-button:has-text('Save')").last.click()
    await edit_page.wait_for_load_state("networkidle", timeout=15000)
    print("  ✓ Saved")


# ── Main orchestrator ─────────────────────────────────────────────────────────
async def run(
    dry_run: bool = False,
    course_url: str = "",
    email: str = "",
    password: str = "",
    prompt_fn=input,
):
    _course_url = course_url or COURSE_URL
    _email      = email or COURSEBRIDGE_EMAIL
    _password   = password or COURSEBRIDGE_PASSWORD

    if not _course_url:
        print("✗ Course URL is not set.")
        sys.exit(1)

    # Extract course ID from any Brightspace course URL (lessons, content, quizzes, etc.)
    match = re.search(r'/(?:le|content|lessons|quizzing)/(\d+)/', _course_url)
    if not match:
        print(f"✗ Could not extract course ID from URL: {_course_url}")
        sys.exit(1)
    course_id = match.group(1)
    content_url = f"{BRIGHTSPACE_BASE}/d2l/le/content/{course_id}/Home"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80)
        context = await browser.new_context(
            storage_state=BS_SESSION_FILE if os.path.exists(BS_SESSION_FILE) else None
        )
        page = await context.new_page()

        print(f"Navigating to course (ID: {course_id})...")
        await page.goto(_course_url)
        print("Waiting for login (log in if prompted, then script will continue)...")
        await page.wait_for_url("**/learn.okanagancollege.ca/**", timeout=120000)
        print("✓ Logged in — saving session...")
        await context.storage_state(path=BS_SESSION_FILE)

        print(f"Navigating to Content tab...")
        await page.goto(content_url)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)

        if dry_run:
            print("⚠  DRY RUN MODE — HTML will not be pasted into Brightspace")

        file_path = await find_and_download_outline(page, prompt_fn=prompt_fn)

        if file_path.suffix.lower() == ".pdf":
            print("\nStep 2 — PDF detected, converting...")
            file_path = convert_pdf_to_docx(file_path)
        else:
            print(f"\nStep 2 — {file_path.suffix} file, no conversion needed")

        html = await convert_with_coursebridge(file_path, email=_email, password=_password)

        if dry_run:
            print("\n✓ Dry run complete. HTML output preview:")
            print("─" * 60)
            print(html[:1000])
            print("─" * 60)
            await browser.close()
            return

        await page.goto(content_url)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)
        await paste_html_to_syllabus(page, html, prompt_fn=prompt_fn)

        print("\n✓ All done!")
        await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert and paste course outline into Brightspace")
    parser.add_argument("--dry-run", action="store_true", help="Download + convert only, no paste")
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))
