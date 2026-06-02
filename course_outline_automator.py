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
BS_SESSION_FILE = str(_HERE / "session.json")
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
        print(f"  Opening candidate {i+1}/{len(matches)}: {title}...")
        await page.goto(url)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)

        confirm = prompt_fn(
            f"[{i+1}/{len(matches)}] Browser is showing: \"{title}\"\n\n"
            f"Is this the correct course outline file? (y/n)"
        ).strip().lower()

        if confirm != "y":
            print(f"  Skipping '{title}'...")
            continue

        # User confirmed — now download and open it
        dl_btn = page.locator(
            "a[download], a[href$='.pdf'], a[href$='.docx'], a[href$='.doc'], "
            "a:has-text('Download'), button:has-text('Download'), [aria-label*='Download']"
        ).first

        if await dl_btn.count():
            print("  Clicking Download button...")
            async with page.expect_download(timeout=30000) as dl_info:
                await dl_btn.click()
            download = await dl_info.value
            raw_dest = download_dir / download.suggested_filename
            await download.save_as(raw_dest)
            dest = ensure_extension(raw_dest)
            print(f"  ✓ Saved: {dest.name}")
            os.startfile(str(dest))
            return dest
        else:
            print(f"  ⚠ No download button found for '{title}' — falling back to manual download")
            break

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
async def paste_html_to_syllabus(page: Page, html: str, course_id: str):
    """Stay on the lessons page, hover Course Syllabus row, click Edit, replace HTML."""
    print("\nStep 4 — Pasting HTML into Brightspace...")

    # 4a: Get TopicId from API, then navigate via viewer URL which redirects to
    #     lessons/{courseId}/topics/{topicId} — the correct page with D2L chrome.
    print("  [4a] Looking up Course Syllabus TopicId from API...")
    toc = None
    for api_ver in ["1.70", "1.67", "1.68", "1.69"]:
        toc = await page.evaluate(f"""
            async () => {{
                try {{
                    const r = await fetch('{BRIGHTSPACE_BASE}/d2l/api/le/{api_ver}/{course_id}/content/toc');
                    if (!r.ok) return null;
                    return await r.json();
                }} catch(e) {{ return null; }}
            }}
        """)
        if toc:
            print(f"  [4a] ✓ API v{api_ver}")
            break

    def find_topic(node, target):
        for t in node.get("Topics", []):
            if t.get("Title", "").strip().lower() == target.lower():
                return t
        for m in node.get("Modules", []):
            r = find_topic(m, target)
            if r:
                return r
        return None

    topic_data = find_topic(toc, SYLLABUS_TOPIC_NAME) if toc else None
    if not topic_data:
        raise RuntimeError(f"Could not find '{SYLLABUS_TOPIC_NAME}' topic via API.")
    topic_id = topic_data.get("TopicId")
    print(f"  [4a] ✓ Found '{SYLLABUS_TOPIC_NAME}' — TopicId: {topic_id}")

    # Navigate via viewContent — D2L redirects this to lessons/{courseId}/topics/{topicId}
    viewer_url = f"{BRIGHTSPACE_BASE}/d2l/le/content/{course_id}/viewContent/{topic_id}/View"
    print(f"  [4a] Navigating to: {viewer_url}")
    await page.goto(viewer_url)
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(4000)
    print(f"  [4a] ✓ Landed on: {page.url}")

    # 4b: Dump every visible button on the page so we can identify the 3-dots
    print("  [4b] Dumping all visible buttons on the page...")
    all_btns = await page.evaluate("""
        () => {
            const found = [];
            function walk(root) {
                for (const el of root.querySelectorAll('button, [role="button"]')) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {
                        found.push({
                            label: el.getAttribute('aria-label') || el.getAttribute('title') || (el.textContent||'').trim().slice(0,50),
                            x: Math.round(r.left + r.width/2),
                            y: Math.round(r.top + r.height/2),
                        });
                    }
                }
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) walk(el.shadowRoot);
                }
            }
            walk(document);
            return found;
        }
    """)
    print(f"  [4b] Found {len(all_btns)} button(s):")
    for b in all_btns:
        print(f"       '{b['label']}'  ({b['x']},{b['y']})")

    # 4c: Find the 3-dots / More button (any button with "more"/"action"/"option" in label)
    print("  [4c] Looking for 3-dots / More button...")
    dots = next(
        (b for b in all_btns if any(
            h in b["label"].lower()
            for h in ["more", "action", "option", "..."]
        )),
        None,
    )
    if not dots:
        raise RuntimeError(
            f"Could not find a More/Actions button on the page.\n"
            f"  Page: {page.url}\n"
            f"  Buttons found: {[b['label'] for b in all_btns]}"
        )
    print(f"  [4c] ✓ Using '{dots['label']}' at ({dots['x']},{dots['y']}) — clicking...")
    await page.mouse.click(dots["x"], dots["y"])
    await page.wait_for_timeout(600)

    # 4e: Click Edit in the dropdown (shadow DOM)
    print("  [4e] Looking for Edit in dropdown...")
    edit = await page.evaluate("""
        () => {
            function walk(root) {
                for (const el of root.querySelectorAll(
                    'd2l-menu-item, [role="menuitem"], button, a, li'
                )) {
                    const text = (el.textContent || '').trim();
                    if (text === 'Edit' || text === 'Edit Topic' || text === 'Edit HTML') {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0)
                            return { x: r.left + r.width/2, y: r.top + r.height/2, text };
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
    if not edit:
        raise RuntimeError("Could not find Edit option in the dropdown.")
    print(f"  [4e] ✓ Found '{edit.get('text','Edit')}' — clicking (new tab expected)...")

    # 4f: Click Edit — opens new tab with the HTML editor
    async with page.context.expect_page() as new_page_info:
        await page.mouse.click(edit["x"], edit["y"])
    edit_page = await new_page_info.value
    await edit_page.wait_for_load_state("domcontentloaded")
    await edit_page.wait_for_timeout(3000)
    print(f"  [4f] ✓ Edit page opened: {edit_page.url}")

    # 4g: Click Source Code button (aria-label="Source Code" confirmed from live HTML)
    print("  [4g] Looking for Source Code button...")
    source_btn = edit_page.locator('button[aria-label="Source Code"]').first
    if await source_btn.count() and await source_btn.is_visible():
        print("  [4g] ✓ Found via aria-label — clicking...")
        await source_btn.click()
    else:
        print("  [4g] Not found via locator — shadow DOM walk...")
        sc = await edit_page.evaluate("""
            () => {
                function walk(root) {
                    for (const el of root.querySelectorAll('button')) {
                        const lbl = el.getAttribute('aria-label') || el.getAttribute('title') || '';
                        if (lbl === 'Source Code' || lbl === 'Source code') {
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
        if not sc:
            raise RuntimeError("Could not find Source Code button in the editor.")
        print(f"  [4g] ✓ Found at ({sc['x']:.0f},{sc['y']:.0f}) — clicking...")
        await edit_page.mouse.click(sc["x"], sc["y"])
    await edit_page.wait_for_timeout(800)

    # 4h: Replace HTML in the Source Code dialog textarea
    print("  [4h] Waiting for Source Code dialog...")
    textarea = edit_page.locator("textarea").first
    try:
        await textarea.wait_for(timeout=10000)
    except Exception:
        raise RuntimeError("Source Code dialog did not open — textarea not found.")
    print(f"  [4h] ✓ Textarea ready — replacing with {len(html):,} chars...")
    await textarea.click()
    await edit_page.keyboard.press("Control+a")
    await edit_page.keyboard.press("Delete")
    await textarea.fill(html)
    await edit_page.wait_for_timeout(400)

    # 4i: Click OK to close dialog
    print("  [4i] Clicking OK...")
    ok_btn = edit_page.locator("button:has-text('OK'), button:has-text('Save')").first
    if not await ok_btn.count():
        raise RuntimeError("Could not find OK button in Source Code dialog.")
    await ok_btn.click()
    await edit_page.wait_for_timeout(600)
    print("  [4i] ✓ Dialog closed")

    # 4j: Save topic (shadow DOM — d2l-button)
    print("  [4j] Looking for Save button...")
    save = await edit_page.evaluate("""
        () => {
            function walk(root) {
                for (const el of root.querySelectorAll('button, d2l-button')) {
                    const text = (el.textContent || '').trim();
                    const lbl  = el.getAttribute('aria-label') || '';
                    if (text === 'Save' || lbl === 'Save') {
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
    if save:
        print(f"  [4j] ✓ Found Save at ({save['x']:.0f},{save['y']:.0f}) — clicking...")
        await edit_page.mouse.click(save["x"], save["y"])
    else:
        print("  [4j] Falling back to locator...")
        await edit_page.locator("button:has-text('Save')").last.click()
    await edit_page.wait_for_load_state("domcontentloaded", timeout=15000)
    print("  ✓ Course Syllabus updated successfully!")


# ── CRN → course ID lookup ────────────────────────────────────────────────────
async def find_course_id_by_crn(page, crn: str) -> str:
    """Navigate to the Brightspace home page and find the course ID for a CRN."""
    print(f"  Looking up CRN {crn} on Brightspace home...")

    # Course cards live inside d2l-my-courses shadow DOM — standard locators can't see them.
    # Use JS to walk all shadow roots and collect every /d2l/home/ link.
    _js = """
        (crn) => {
            const results = [];
            function walk(root) {
                for (const el of root.querySelectorAll('a')) {
                    const href = el.getAttribute('href') || '';
                    if (href.includes('/d2l/home/') && el.textContent.includes(crn)) {
                        results.push({ href: el.href || href, text: (el.textContent || '').trim().slice(0, 100) });
                    }
                }
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) walk(el.shadowRoot);
                }
            }
            walk(document);
            return results;
        }
    """

    for nav_url in [f"{BRIGHTSPACE_BASE}/d2l/home", f"{BRIGHTSPACE_BASE}/d2l/lp/courses/list"]:
        await page.goto(nav_url)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(3000)

        links = await page.evaluate(_js, crn)
        print(f"  [{nav_url.split('/')[-1]}] found {len(links)} link(s) containing '{crn}'")
        for lnk in links:
            print(f"    {lnk['text'][:80]}  →  {lnk['href']}")

        if links:
            href = links[0]["href"]
            title = links[0]["text"]
            m = re.search(r'/d2l/home/(\d+)', href)
            if m:
                course_id = m.group(1)
                print(f"  ✓ Found: {title[:60]}  (Brightspace ID: {course_id})")
                return course_id

    raise RuntimeError(
        f"Could not find a course with CRN {crn} on Brightspace. "
        "Make sure you are enrolled/teaching that course."
    )


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

        print("Opening Brightspace...")
        await page.goto(BRIGHTSPACE_BASE)
        print("Waiting for login (log in if prompted, then script will continue)...")
        # Wait until we land on Brightspace proper — the SAML redirect may bounce
        # through Microsoft a few times before settling, so keep waiting until
        # the final URL is on learn.okanagancollege.ca (not microsoftonline.com).
        for _ in range(60):
            await page.wait_for_url("**/learn.okanagancollege.ca/**", timeout=120000)
            await page.wait_for_timeout(1500)
            if "microsoftonline.com" not in page.url and "microsoft.com" not in page.url:
                break
        await page.wait_for_load_state("networkidle", timeout=30000)
        await page.wait_for_timeout(1000)
        print(f"✓ Logged in — saving session...")
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
        await paste_html_to_syllabus(page, html, course_id=course_id)

        print("\n✓ All done!")
        await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert and paste course outline into Brightspace")
    parser.add_argument("--dry-run", action="store_true", help="Download + convert only, no paste")
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))
