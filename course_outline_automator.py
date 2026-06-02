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
import subprocess
import sys
import argparse
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
async def find_and_download_outline(page: Page, course_id: str = "", prompt_fn=input) -> Path:
    """Find course outline via Brightspace API and download it."""
    print("\nStep 1 — Finding course outline...")
    await page.wait_for_timeout(2000)

    # ── Find topic via Brightspace content API ────────────────────────────────
    print("  Fetching content list from Brightspace API...")
    toc = None
    for api_ver in ["1.70", "1.67", "1.68", "1.69"]:
        toc = await page.evaluate(f"""
            async () => {{
                try {{
                    const r = await fetch(
                        '{BRIGHTSPACE_BASE}/d2l/api/le/{api_ver}/{course_id}/content/toc'
                    );
                    if (!r.ok) return null;
                    return await r.json();
                }} catch(e) {{ return null; }}
            }}
        """)
        if toc:
            print(f"  ✓ API v{api_ver}")
            break

    matches = []   # list of (title, full_url)

    if toc:
        def flatten(node):
            items = []
            for topic in node.get("Topics", []):
                items.append((topic.get("Title", ""), topic.get("Url", "")))
            for mod in node.get("Modules", []):
                items.extend(flatten(mod))
            return items

        all_topics = flatten(toc)
        print(f"  {len(all_topics)} topic(s) in course — scanning for matches...")
        for title, url in all_topics:
            for term in OUTLINE_SEARCH_TERMS:
                if term.lower() in title.lower():
                    full_url = url if url.startswith("http") else BRIGHTSPACE_BASE + url
                    matches.append((title, full_url))
                    print(f"    Candidate: {title}")
                    break
        if not matches:
            print("  No topics matched search terms")
    else:
        print("  ✗ API unavailable")

    download_dir = _HERE / "downloads"
    download_dir.mkdir(exist_ok=True)

    # ── Loop through candidates until user confirms one ───────────────────────
    for i, (title, url) in enumerate(matches):
        print(f"  Downloading candidate {i+1}/{len(matches)}: {title}...")
        await page.goto(url)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)

        # Auto-download it first so the user can open and inspect it
        dl_btn = page.locator(
            "a[download], a[href$='.pdf'], a[href$='.docx'], a[href$='.doc'], "
            "a:has-text('Download'), button:has-text('Download'), [aria-label*='Download']"
        ).first

        dest = None
        if await dl_btn.count():
            print("  Clicking Download button...")
            async with page.expect_download(timeout=30000) as dl_info:
                await dl_btn.click()
            download = await dl_info.value
            raw_dest = download_dir / download.suggested_filename
            await download.save_as(raw_dest)
            dest = ensure_extension(raw_dest)
            print(f"  ✓ Saved: {dest}")
            # Open file in default Windows app so user can inspect it
            os.startfile(str(dest))
        else:
            print(f"  ⚠ No download button found for '{title}' — showing page in browser")

        confirm = prompt_fn(
            f"[{i+1}/{len(matches)}] \"{title}\" has been opened.\n\n"
            f"Is this the correct course outline file? (y/n)"
        ).strip().lower()

        if confirm == "y" and dest:
            return dest
        elif confirm == "y" and not dest:
            # No file yet — fall through to manual
            break
        else:
            if dest:
                print(f"  Skipping '{title}' (file kept at {dest.name})...")
            else:
                print(f"  Skipping '{title}'...")
            continue

    # ── Manual fallback ───────────────────────────────────────────────────────
    print("  No matching file confirmed — waiting for manual download...")
    prompt_fn(
        "In the browser, find the course outline file, click its Download option, "
        "and wait for it to save. Then click OK here."
    )
    # Listen for a download that was triggered while the dialog was open
    try:
        dl = await page.context.wait_for_event("download", timeout=30000)
        raw_dest = download_dir / dl.suggested_filename
        await dl.save_as(raw_dest)
        dest = ensure_extension(raw_dest)
        print(f"  ✓ Downloaded: {dest.name}")
        os.startfile(str(dest))
        return dest
    except Exception:
        raise RuntimeError(
            "No download detected. Click the Download option in the browser "
            "before clicking OK in the dialog."
        )


# ── Fix missing extension (Brightspace stores files as UUIDs) ────────────────
def ensure_extension(path: Path) -> Path:
    """Detect file type from magic bytes and add .pdf / .docx if missing."""
    if path.suffix.lower() in (".pdf", ".docx", ".doc"):
        return path
    with open(path, "rb") as f:
        header = f.read(8)
    if header.startswith(b"%PDF"):
        new_path = path.with_suffix(".pdf")
    elif header.startswith(b"PK"):
        new_path = path.with_suffix(".docx")
    else:
        print(f"  ⚠ Unknown file type (header: {header[:4].hex()}) — keeping as-is")
        return path
    path.rename(new_path)
    print(f"  Detected file type → {new_path.suffix}")
    return new_path


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
    """Upload docx to CourseBridge (doc→HTML converter), return HTML string."""
    print("\nStep 3 — CourseBridge conversion...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=60)
        context = await browser.new_context(
            storage_state=CB_SESSION_FILE if os.path.exists(CB_SESSION_FILE) else None
        )
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await context.new_page()
        await page.goto(COURSEBRIDGE_URL)

        if await page.locator("input[type='email'], input[name='email']").count():
            print("  Logging into CourseBridge...")
            await page.locator("input[type='email'], input[name='email']").first.fill(email)
            await page.locator("input[type='password']").first.fill(password)
            await page.locator("button[type='submit']").first.click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(2000)
            await context.storage_state(path=CB_SESSION_FILE)

        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(1000)

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

        # Wait for the "Copy HTML" button to appear — that signals conversion is done
        print("  Waiting for conversion to complete...")
        copy_btn = page.locator("button:has-text('Copy HTML')").first
        for elapsed in range(0, 120, 3):
            await page.wait_for_timeout(3000)
            if await copy_btn.count() and await copy_btn.is_visible():
                print("  ✓ Conversion complete")
                break
            if elapsed % 15 == 0 and elapsed > 0:
                print(f"  Still waiting... ({elapsed}s)")
        else:
            raise RuntimeError("CourseBridge: 'Copy HTML' button never appeared after 2 minutes")

        # Click "Copy HTML" → puts HTML on clipboard
        await copy_btn.click()
        await page.wait_for_timeout(500)

        # Read from clipboard first; fall back to scraping the pre element
        html = ""
        try:
            html = await page.evaluate("() => navigator.clipboard.readText()")
        except Exception:
            pass

        if not html.strip():
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


# ── CRN → course ID lookup ────────────────────────────────────────────────────
async def find_course_id_by_crn(page, crn: str) -> str:
    """Navigate to the Brightspace home page and find the course ID for a CRN."""
    print(f"  Looking up CRN {crn} on Brightspace home...")
    await page.goto(f"{BRIGHTSPACE_BASE}/d2l/home")
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(2000)

    # Course cards/links on the home page contain the CRN in their text
    link = page.locator(f"a[href*='/d2l/home/']:has-text('{crn}')").first
    if not await link.count():
        # Try the full course list page
        await page.goto(f"{BRIGHTSPACE_BASE}/d2l/lp/courses/list")
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)
        link = page.locator(f"a[href*='/d2l/home/']:has-text('{crn}')").first

    if not await link.count():
        raise RuntimeError(
            f"Could not find a course with CRN {crn} on Brightspace. "
            "Make sure you are enrolled/teaching that course."
        )

    href = await link.get_attribute("href")
    title = (await link.inner_text()).strip()
    m = re.search(r'/d2l/home/(\d+)', href)
    if not m:
        raise RuntimeError(f"Unexpected href format: {href}")
    course_id = m.group(1)
    print(f"  ✓ Found: {title[:60]}  (Brightspace ID: {course_id})")
    return course_id


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
        print("✗ Course CRN or URL is not set.")
        sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80)
        context = await browser.new_context(
            storage_state=BS_SESSION_FILE if os.path.exists(BS_SESSION_FILE) else None
        )
        page = await context.new_page()

        # Login first (navigate to base URL so session can be restored)
        print("Opening Brightspace...")
        await page.goto(BRIGHTSPACE_BASE)
        print("Waiting for login (log in if prompted, then script will continue)...")
        await page.wait_for_url("**/learn.okanagancollege.ca/**", timeout=120000)
        print("✓ Logged in — saving session...")
        await context.storage_state(path=BS_SESSION_FILE)

        # Accept CRN (5-digit number) or a full URL
        if re.fullmatch(r'\d{4,6}', _course_url.strip()):
            crn = _course_url.strip()
            print(f"CRN entered: {crn} — looking up course...")
            course_id = await find_course_id_by_crn(page, crn)
        else:
            match = re.search(r'/(?:le|content|lessons|quizzing|home)/(\d+)', _course_url)
            if not match:
                print(f"✗ Could not extract course ID from: {_course_url}")
                sys.exit(1)
            course_id = match.group(1)
            print(f"Course ID from URL: {course_id}")

        content_url = f"{BRIGHTSPACE_BASE}/d2l/le/lessons/{course_id}"
        print(f"Navigating to Content tab...")
        await page.goto(content_url)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(5000)

        if dry_run:
            print("⚠  DRY RUN MODE — HTML will not be pasted into Brightspace")

        file_path = await find_and_download_outline(page, course_id=course_id, prompt_fn=prompt_fn)

        if file_path.suffix.lower() == ".pdf":
            print("\nStep 2 — PDF detected, converting...")
            file_path = convert_pdf_to_docx(file_path)
        else:
            print(f"\nStep 2 — {file_path.suffix} file, no conversion needed")

        html = await convert_with_coursebridge(file_path, email=_email, password=_password)

        # Save HTML to a temp file and open in Notepad for review
        preview_path = _HERE / "coursebridge_preview.html"
        preview_path.write_text(html, encoding="utf-8")
        print(f"\n  Opening HTML preview in Notepad: {preview_path}")
        subprocess.Popen(["notepad.exe", str(preview_path)])
        prompt_fn("Review the HTML in Notepad. Click OK when you're ready to continue (or close Notepad to abort).")

        if dry_run:
            print("\n✓ Dry run complete — HTML saved to coursebridge_preview.html")
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
