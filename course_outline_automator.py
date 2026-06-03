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

OUTLINE_SEARCH_TERMS = ["outline"]
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
        result = await page.evaluate(f"""
            async () => {{
                try {{
                    const r = await fetch(
                        '{BRIGHTSPACE_BASE}/d2l/api/le/{api_ver}/{course_id}/content/toc'
                    );
                    if (!r.ok) return {{ status: r.status, data: null }};
                    return {{ status: r.status, data: await r.json() }};
                }} catch(e) {{ return {{ status: -1, error: e.toString() }}; }}
            }}
        """)
        status = result.get("status") if result else -1
        print(f"  API v{api_ver}: HTTP {status}")
        toc = result.get("data") if result else None
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
        print("  ✗ API unavailable — scraping content page DOM...")
        terms_js = str(OUTLINE_SEARCH_TERMS).lower()
        links = await page.evaluate(f"""
            () => {{
                const terms = {terms_js};
                const results = [];
                function walk(root) {{
                    for (const a of root.querySelectorAll('a[href]')) {{
                        const text = (a.textContent || '').trim();
                        const href = a.getAttribute('href') || '';
                        if (text && terms.some(t => text.toLowerCase().includes(t))) {{
                            results.push({{ text, href: a.href || href }});
                        }}
                    }}
                    for (const el of root.querySelectorAll('*')) {{
                        if (el.shadowRoot) walk(el.shadowRoot);
                    }}
                }}
                walk(document);
                return results;
            }}
        """)
        print(f"  Found {len(links)} matching link(s) on content page")
        seen = set()
        for lnk in links:
            href = lnk.get("href", "")
            text = lnk.get("text", "")
            if href and href not in seen:
                seen.add(href)
                full_url = href if href.startswith("http") else BRIGHTSPACE_BASE + href
                matches.append((text, full_url))
                print(f"    Candidate: {text}")

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

        # User confirmed — find Download button via shadow DOM and click via coordinates
        print("  Looking for Download button...")
        dl_coords = await page.evaluate("""
            () => {
                function walk(root) {
                    for (const el of root.querySelectorAll('button, a, [role="button"]')) {
                        const label = (
                            el.getAttribute('aria-label') || el.getAttribute('title') ||
                            el.textContent || ''
                        ).toLowerCase().trim();
                        if (label.includes('download')) {
                            const r = el.getBoundingClientRect();
                            if (r.width > 0 && r.height > 0)
                                return { x: r.left + r.width/2, y: r.top + r.height/2, label };
                        }
                    }
                    for (const el of root.querySelectorAll('*')) {
                        if (el.shadowRoot) { const c = walk(el.shadowRoot); if (c) return c; }
                        if (el.tagName === 'IFRAME') {
                            try {
                                const ir = el.getBoundingClientRect();
                                const c = walk(el.contentDocument);
                                if (c) return { x: c.x + ir.left, y: c.y + ir.top, label: c.label };
                            } catch(e) {}
                        }
                    }
                    return null;
                }
                return walk(document);
            }
        """)

        if dl_coords:
            print(f"  ✓ Found '{dl_coords['label']}' at ({dl_coords['x']:.0f},{dl_coords['y']:.0f}) — clicking...")
            async with page.expect_download(timeout=30000) as dl_info:
                await page.mouse.click(dl_coords["x"], dl_coords["y"])
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
        browser = await p.chromium.launch(
            headless=False, slow_mo=60,
            args=["--start-maximized"],
        )
        context = await browser.new_context(
            storage_state=CB_SESSION_FILE if os.path.exists(CB_SESSION_FILE) else None,
            no_viewport=True,
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

    # Helper JS: walk main page + shadow DOM + same-origin iframes.
    # Coordinates are adjusted so they're always relative to the main viewport
    # (getBoundingClientRect inside an iframe is relative to that iframe's origin).
    _WALK_JS = """
        (opts) => {
            const hints   = opts && opts.hints   ? opts.hints   : null;
            const editMode = opts && opts.editMode ? true : false;
            const found = [];

            function walkRoot(root, ox, oy) {
                const sel = editMode
                    ? 'd2l-menu-item, [role="menuitem"], button, a, li'
                    : 'button, [role="button"]';
                for (const el of root.querySelectorAll(sel)) {
                    const r = el.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0) continue;

                    let label;
                    if (editMode) {
                        // d2l-menu-item stores visible text in the 'text' attribute
                        label = el.getAttribute('text') || el.getAttribute('aria-label')
                              || (el.textContent||'').trim().slice(0,50);
                    } else {
                        label = el.getAttribute('aria-label') || el.getAttribute('title')
                              || (el.textContent||'').trim().slice(0,50);
                    }

                    const x = Math.round(ox + r.left + r.width/2);
                    const y = Math.round(oy + r.top  + r.height/2);

                    if (hints) {
                        if (hints.some(h => label.toLowerCase().includes(h)))
                            return { label, x, y };
                    } else {
                        found.push({ label, x, y });
                    }
                }

                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) {
                        const c = walkRoot(el.shadowRoot, ox, oy);
                        if (hints && c) return c;
                    }
                    if (el.tagName === 'IFRAME') {
                        try {
                            const ir = el.getBoundingClientRect();
                            const c = walkRoot(el.contentDocument, ox + ir.left, oy + ir.top);
                            if (hints && c) return c;
                        } catch(e) {}
                    }
                }
                return hints ? null : found;
            }

            return walkRoot(document, 0, 0);
        }
    """

    # 4b: Dump every visible button (main page + iframes) for debugging
    print("  [4b] Dumping all visible buttons (including iframes)...")
    all_btns = await page.evaluate(_WALK_JS, {"hints": None})
    print(f"  [4b] Found {len(all_btns)} button(s):")
    for b in all_btns:
        print(f"       '{b['label']}'  ({b['x']},{b['y']})")

    # 4c: Find the topic "Options" button (exact label match first, then fallbacks)
    print("  [4c] Looking for Options / More Actions button...")
    def find_btn(btns, exact=None, contains=None, exclude=None):
        for b in btns:
            lbl = b["label"]
            if exact and lbl == exact:
                if not exclude or exclude not in lbl.lower():
                    return b
            if contains and contains in lbl.lower():
                if not exclude or exclude not in lbl.lower():
                    return b
        return None

    dots = (
        find_btn(all_btns, exact="Options")
        or find_btn(all_btns, contains="more options")
        or find_btn(all_btns, contains="more actions")
        or find_btn(all_btns, contains="options", exclude="course")
    )
    if not dots:
        raise RuntimeError(
            f"Could not find Options/More Actions button.\n"
            f"  Page: {page.url}\n"
            f"  Buttons: {[b['label'] for b in all_btns]}"
        )
    print(f"  [4c] ✓ '{dots['label']}' at ({dots['x']},{dots['y']}) — clicking...")
    await page.mouse.click(dots["x"], dots["y"])
    await page.wait_for_timeout(600)

    # 4e: Find Edit menu item — re-scan after menu opens, exact label match
    print("  [4e] Looking for Edit in dropdown...")
    menu_items = await page.evaluate(_WALK_JS, {"hints": None, "editMode": True})
    print(f"  [4e] Menu items visible: {[b['label'] for b in menu_items if b['label'].strip()]}")
    edit = next((b for b in menu_items if b["label"].strip().lower() == "edit"), None)
    if not edit:
        raise RuntimeError("Could not find Edit option in the dropdown.")
    print(f"  [4e] ✓ '{edit['label']}' at ({edit['x']},{edit['y']}) — clicking...")

    # 4f: Click Edit — may open in same tab or new tab
    edit_page = None
    try:
        async with page.context.expect_page(timeout=5000) as new_page_info:
            await page.mouse.click(edit["x"], edit["y"])
        edit_page = await new_page_info.value
        print(f"  [4f] Opened in new tab: {edit_page.url}")
    except Exception:
        # Opened in same tab
        edit_page = page
        print("  [4f] Opened in same tab — waiting for page to load...")
    await edit_page.wait_for_load_state("domcontentloaded")
    await edit_page.wait_for_timeout(3000)
    print(f"  [4f] ✓ Edit page ready: {edit_page.url}")

    # 4g: Set TinyMCE content directly via JS — skips Source Code dialog entirely.
    #     TinyMCE exposes tinymce.activeEditor.setContent() in the page context.
    print("  [4g] Setting editor content via TinyMCE API...")
    result = await edit_page.evaluate("""
        (html) => {
            try {
                if (typeof tinymce === 'undefined') return 'tinymce not found';
                const ed = tinymce.activeEditor;
                if (!ed) return 'no active editor';
                ed.setContent(html);
                return 'ok';
            } catch(e) {
                return 'error: ' + e.message;
            }
        }
    """, html)
    print(f"  [4g] TinyMCE result: {result}")
    if result != "ok":
        raise RuntimeError(f"Could not set TinyMCE content: {result}")
    await edit_page.wait_for_timeout(500)
    print("  [4g] ✓ Content set")

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
        print(f"  [4j] ✓ Found Save at ({save['x']:.0f},{save['y']:.0f}) — clicking (closes dialog)...")
        await edit_page.mouse.click(save["x"], save["y"])
    else:
        print("  [4j] Falling back to locator...")
        await edit_page.locator("button:has-text('Save')").last.click()

    # Wait for dialog to close, then click the topic page Save
    await edit_page.wait_for_timeout(2000)
    print("  [4k] Dialog closed — looking for topic page Save button...")
    save2 = await edit_page.evaluate("""
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
    if save2:
        print(f"  [4k] ✓ Found page Save at ({save2['x']:.0f},{save2['y']:.0f}) — clicking...")
        await edit_page.mouse.click(save2["x"], save2["y"])
        await edit_page.wait_for_load_state("domcontentloaded", timeout=15000)
        print("  ✓ Course Syllabus saved successfully!")
    else:
        print("  [4k] No second Save found — dialog Save may have saved directly")
    await edit_page.close()


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


# ── Downloads cleanup ────────────────────────────────────────────────────────
def _maybe_clear_downloads(prompt_fn=input):
    download_dir = _HERE / "downloads"
    files = list(download_dir.iterdir()) if download_dir.exists() else []
    if not files:
        return
    answer = prompt_fn(
        f"Clear the downloads folder? ({len(files)} file(s) inside)\n\n"
        "Click Yes to delete them, No to keep them. (y/n)"
    ).strip().lower()
    if answer == "y":
        for f in files:
            try:
                f.unlink()
            except Exception:
                pass
        print(f"  ✓ Downloads cleared ({len(files)} file(s) deleted)")
    else:
        print("  Downloads kept")


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
        browser = await p.chromium.launch(
            headless=False, slow_mo=80,
            args=["--start-maximized"],
        )
        context = await browser.new_context(
            storage_state=BS_SESSION_FILE if os.path.exists(BS_SESSION_FILE) else None,
            no_viewport=True,
        )
        page = await context.new_page()

        print("Opening Brightspace...")
        await page.goto(BRIGHTSPACE_BASE)
        print("─" * 50)
        print("  Log in with your Okanagan College account.")
        print("  Complete any MFA steps (email code, authenticator, etc.).")
        print("  The script will continue automatically once it detects")
        print("  that you are on the Brightspace home page.")
        print("─" * 50)

        # Poll until fully on Brightspace — never navigate, just watch the URL
        for i in range(180):   # up to 9 minutes
            await page.wait_for_timeout(3000)
            url = page.url
            on_bs = "learn.okanagancollege.ca" in url
            on_ms = "microsoftonline.com" in url or "login.microsoft" in url
            on_login = "/d2l/lp/auth" in url or "/login" in url
            if on_bs and not on_ms and not on_login:
                break
            if i % 10 == 0 and i > 0:
                print(f"  Still waiting for login... ({i * 3}s elapsed)  |  current: {url[:80]}")
        else:
            raise RuntimeError("Login timed out after 9 minutes — please try again")

        print(f"✓ Logged in and on Brightspace home — saving session...")
        await page.wait_for_load_state("networkidle", timeout=20000)
        await context.storage_state(path=BS_SESSION_FILE)
        print("✓ Session saved")

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
        try:
            await page.goto(content_url, wait_until="commit")
        except Exception:
            pass
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

        try:
            await page.goto(content_url, wait_until="commit")
        except Exception:
            pass
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)
        await paste_html_to_syllabus(page, html, course_id=course_id)

        print("\n✓ All done!")
        _maybe_clear_downloads(prompt_fn)
        await browser.close()


# ── Step 4 standalone test ────────────────────────────────────────────────────
async def test_step4(course_url: str = ""):
    """Test only Step 4: read existing coursebridge_preview.html and paste into Brightspace."""
    preview_path = _HERE / "coursebridge_preview.html"
    if not preview_path.exists():
        raise RuntimeError(
            "coursebridge_preview.html not found. Run Steps 1-3 first to generate it."
        )

    html = preview_path.read_text(encoding="utf-8")
    print(f"Loaded HTML from {preview_path.name} ({len(html):,} chars)")

    _course_url = course_url or COURSE_URL
    if not _course_url:
        raise RuntimeError("Course CRN or URL is required.")

    match = re.search(r'/(?:le|content|lessons|quizzing|home)/(\d+)', _course_url)
    if match:
        course_id = match.group(1)
    elif re.fullmatch(r'\d{4,6}', _course_url.strip()):
        course_id = None  # resolved after login
    else:
        raise RuntimeError(f"Could not extract course ID from: {_course_url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80)
        context = await browser.new_context(
            storage_state=BS_SESSION_FILE if os.path.exists(BS_SESSION_FILE) else None
        )
        page = await context.new_page()

        print("Opening Brightspace...")
        await page.goto(BRIGHTSPACE_BASE)
        print("Waiting for login (log in if prompted)...")
        for i in range(180):
            await page.wait_for_timeout(3000)
            url = page.url
            if "learn.okanagancollege.ca" in url and "microsoftonline.com" not in url:
                try:
                    await page.goto(f"{BRIGHTSPACE_BASE}/d2l/home", timeout=15000)
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    await page.wait_for_timeout(2000)
                except Exception:
                    pass
                if "learn.okanagancollege.ca" in page.url and "microsoftonline.com" not in page.url:
                    break
            if i % 10 == 0 and i > 0:
                print(f"  Still waiting... ({i * 3}s)")
        else:
            raise RuntimeError("Login timed out")

        await page.wait_for_load_state("networkidle", timeout=20000)
        await context.storage_state(path=BS_SESSION_FILE)
        print("✓ Logged in")

        if course_id is None:
            course_id = await find_course_id_by_crn(page, _course_url.strip())

        await paste_html_to_syllabus(page, html, course_id=course_id)

        print("\n✓ Step 4 test complete!")
        await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert and paste course outline into Brightspace")
    parser.add_argument("--dry-run", action="store_true", help="Download + convert only, no paste")
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))
