#!/usr/bin/env python3
"""
Course Outline Automator

Usage:
  python course_outline_automator.py              # full run
  python course_outline_automator.py --dry-run   # download + convert only, no paste
"""

import asyncio
import argparse
import os
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from playwright.async_api import async_playwright, Page

# ── Config defaults (overridable via run() parameters or GUI) ─────────────────
BRIGHTSPACE_BASE      = "https://learn.okanagancollege.ca"
COURSEBRIDGE_URL      = "https://coursebridge.okanagancollege.app/content-converter"
COURSEBRIDGE_EMAIL    = ""
COURSEBRIDGE_PASSWORD = ""
OUTLINE_SEARCH_TERMS  = ["outline"]
SYLLABUS_TOPIC_NAME   = "Course Syllabus"
COURSE_URL            = ""

_HERE           = Path(__file__).parent.parent
BS_SESSION_FILE = str(_HERE / "session.json")
CB_SESSION_FILE = str(_HERE / "cb_session.json")

# JS that walks shadow DOM + same-origin iframes and returns visible buttons.
# Pass {hints: ["word"]} to return first match, or {} to return all.
_WALK_JS = """
    (opts) => {
        const hints    = opts && opts.hints    ? opts.hints    : null;
        const editMode = opts && opts.editMode ? true : false;
        const found = [];
        function walkRoot(root, ox, oy) {
            const sel = editMode
                ? 'd2l-menu-item, [role="menuitem"], button, a, li'
                : 'button, [role="button"]';
            for (const el of root.querySelectorAll(sel)) {
                const r = el.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) continue;
                const label = editMode
                    ? (el.getAttribute('text') || el.getAttribute('aria-label') || (el.textContent||'').trim().slice(0,50))
                    : (el.getAttribute('aria-label') || el.getAttribute('title') || (el.textContent||'').trim().slice(0,50));
                const x = Math.round(ox + r.left + r.width/2);
                const y = Math.round(oy + r.top  + r.height/2);
                if (hints) {
                    if (hints.some(h => label.toLowerCase().includes(h))) return { label, x, y };
                } else { found.push({ label, x, y }); }
            }
            for (const el of root.querySelectorAll('*')) {
                if (el.shadowRoot) { const c = walkRoot(el.shadowRoot, ox, oy); if (hints && c) return c; }
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


def _find_btn(btns, exact=None, contains=None, exclude=None):
    """Return first button dict matching exact label or containing a substring."""
    for b in btns:
        lbl = b["label"]
        if exact and lbl == exact:
            if not exclude or exclude not in lbl.lower(): return b
        if contains and contains in lbl.lower():
            if not exclude or exclude not in lbl.lower(): return b
    return None


# ── Login helper ───────────────────────────────────────────────────────────────

async def _wait_for_bs_login(page, context):
    """Navigate to Brightspace, auto-login if credentials saved, then save session."""
    import json as _json
    print("Opening Brightspace...")
    await page.goto(BRIGHTSPACE_BASE)
    await page.wait_for_load_state("domcontentloaded", timeout=15000)
    try:
        _cfg_path = Path(os.environ.get("APPDATA", Path.home())) / "BrightspaceAutomator" / "outline_config.json"
        with open(str(_cfg_path)) as _f:
            _cfg = _json.load(_f)
        bs_user, bs_pass = _cfg.get("bs_username", ""), _cfg.get("bs_password", "")
    except Exception:
        bs_user, bs_pass = "", ""
    has_login_form = bool(await page.locator("input[name='userName']").count() or await page.locator("text=Manual Login").count())
    if bs_user and bs_pass and has_login_form:
        try:
            print("  Auto-login: expanding Manual Login form...")
            await page.locator("text=Manual Login").click()
            await page.wait_for_timeout(800)
            await page.locator("input[name='userName']").fill(bs_user)
            await page.locator("input[name='password']").fill(bs_pass)
            await page.locator("button:has-text('Log In')").click()
            print("  Credentials submitted — waiting for redirect...")
        except Exception as e:
            print(f"  Auto-login failed ({e}) — please log in manually in the browser")
    else:
        if not bs_user:
            print("─" * 50)
            print("  No credentials saved. Log in manually in the browser.")
            print("  Save credentials in Settings to enable auto-login.")
            print("─" * 50)
    for i in range(180):
        await page.wait_for_timeout(3000)
        url = page.url
        if "learn.okanagancollege.ca" in url and "microsoftonline.com" not in url:
            has_login_form = await page.evaluate("() => !!document.querySelector('#userName')")
            if has_login_form:
                continue
            try:
                await page.goto(f"{BRIGHTSPACE_BASE}/d2l/home", timeout=15000)
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                await page.wait_for_timeout(2000)
            except Exception:
                pass
            if "/d2l/home" in page.url:
                break
        if i % 10 == 0 and i > 0:
            print(f"  Still waiting... ({i * 3}s)  |  {page.url[:80]}")
    else:
        raise RuntimeError("Login timed out after 9 minutes")
    print("✓ Logged in — saving session...")
    await page.wait_for_load_state("networkidle", timeout=20000)
    await context.storage_state(path=BS_SESSION_FILE)
    print("✓ Session saved")


# ── Step 1 helpers ─────────────────────────────────────────────────────────────

async def _fetch_matching_topics(page: Page, course_id: str) -> list[tuple[str, str]]:
    """Fetch TOC from Brightspace API, return (title, url) pairs matching search terms."""
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
            print(f"  ✓ API v{api_ver}")
            break
    if not toc:
        print("  ✗ API unavailable")
        return []

    def flatten(node):
        items = []
        for topic in node.get("Topics", []):
            items.append((topic.get("Title", ""), topic.get("Url", "")))
        for mod in node.get("Modules", []):
            items.extend(flatten(mod))
        return items

    all_topics = flatten(toc)
    print(f"  {len(all_topics)} topic(s) — scanning for matches...")
    matches = []
    for title, url in all_topics:
        for term in OUTLINE_SEARCH_TERMS:
            if term.lower() in title.lower():
                full_url = url if url.startswith("http") else BRIGHTSPACE_BASE + url
                matches.append((title, full_url))
                print(f"    Candidate: {title}")
                break
    if not matches:
        print("  No topics matched search terms")
    return matches


async def _try_download_candidate(page: Page, title: str, url: str, download_dir: Path, prompt_fn) -> "Path | None":
    """Confirm by title, then download. Returns path or None if skipped."""
    answer = prompt_fn(f'Found: "{title}"\n\nIs this the correct course outline? (y/n)').strip().lower()
    if answer != "y":
        print(f"  Skipping '{title}'...")
        return None

    print(f"  Downloading: {title}...")
    direct_download = False
    try:
        await page.goto(url)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)
    except Exception as e:
        if "download is starting" in str(e).lower():
            direct_download = True
        else:
            raise

    if direct_download:
        async with page.expect_download(timeout=30000) as dl_info:
            try:
                await page.goto(url)
            except Exception as e:
                if "download is starting" not in str(e).lower():
                    raise
        download = await dl_info.value
        raw_dest = download_dir / download.suggested_filename
        await download.save_as(raw_dest)
        dest = ensure_extension(raw_dest)
        print(f"  ✓ Downloaded: {dest.name}")
        return dest

    dl_coords = await page.evaluate("""
        () => {
            function walk(root) {
                for (const el of root.querySelectorAll('button, a, [role="button"]')) {
                    const label = (el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || '').toLowerCase().trim();
                    if (label.includes('download')) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) return { x: r.left + r.width/2, y: r.top + r.height/2, label };
                    }
                }
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) { const c = walk(el.shadowRoot); if (c) return c; }
                    if (el.tagName === 'IFRAME') {
                        try { const ir = el.getBoundingClientRect(); const c = walk(el.contentDocument); if (c) return { x: c.x + ir.left, y: c.y + ir.top, label: c.label }; } catch(e) {}
                    }
                }
                return null;
            }
            return walk(document);
        }
    """)
    if not dl_coords:
        print(f"  ⚠ No download button found for '{title}' — falling back to manual download")
        return await _manual_download_fallback(page, download_dir, prompt_fn)

    print(f"  ✓ Found '{dl_coords['label']}' — clicking...")
    async with page.expect_download(timeout=30000) as dl_info:
        await page.mouse.click(dl_coords["x"], dl_coords["y"])
    download = await dl_info.value
    raw_dest = download_dir / download.suggested_filename
    await download.save_as(raw_dest)
    dest = ensure_extension(raw_dest)
    print(f"  ✓ Saved: {dest.name}")
    return dest


async def _manual_download_fallback(page: Page, download_dir: Path, prompt_fn) -> Path | None:
    """Wait for user to manually trigger a download, or return None if no outline exists."""
    print("  No matching file confirmed — waiting for manual download...")
    answer = prompt_fn(
        "Is there a course outline in this course?\n"
        "If YES — find it in the browser, click Download, then click Yes.\n"
        "If NO — click No to skip the course outline step. (y/n)"
    )
    if answer.strip().lower() not in ("y", "yes"):
        print("  Skipping course outline — no outline present.")
        return None
    try:
        dl = await page.context.wait_for_event("download", timeout=30000)
        raw_dest = download_dir / dl.suggested_filename
        await dl.save_as(raw_dest)
        dest = ensure_extension(raw_dest)
        print(f"  ✓ Downloaded: {dest.name}")
        return dest
    except Exception:
        raise RuntimeError("No download detected. Click Download in the browser before clicking Yes.")


async def find_and_download_outline(page: Page, course_id: str = "", prompt_fn=input) -> Path:
    """Find course outline via API, confirm with user, download it."""
    print("\nStep 1 — Finding course outline...")
    await page.wait_for_timeout(2000)
    download_dir = _HERE / "downloads"
    download_dir.mkdir(exist_ok=True)
    matches = await _fetch_matching_topics(page, course_id)
    for i, (title, url) in enumerate(matches):
        print(f"  Candidate {i+1}/{len(matches)}: {title}...")
        result = await _try_download_candidate(page, title, url, download_dir, prompt_fn)
        if result:
            return result
    return await _manual_download_fallback(page, download_dir, prompt_fn)


# ── File utilities ─────────────────────────────────────────────────────────────

def ensure_extension(path: Path) -> Path:
    """Detect file type from magic bytes and add .pdf / .docx / .rtf if missing."""
    if path.suffix.lower() in (".pdf", ".docx", ".doc", ".rtf"):
        return path
    with open(path, "rb") as f:
        header = f.read(8)
    if header.startswith(b"%PDF"):
        new_path = path.with_suffix(".pdf")
    elif header.startswith(b"PK"):
        new_path = path.with_suffix(".docx")
    elif header.startswith(b"{\\rt"):
        new_path = path.with_suffix(".rtf")
    else:
        print(f"  ⚠ Unknown file type ({header[:4].hex()}) — keeping as-is")
        return path
    path.rename(new_path)
    print(f"  Detected → {new_path.suffix}")
    return new_path


def convert_pdf_to_docx(pdf_path: Path) -> Path:
    """Convert PDF to docx using pdf2docx."""
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


# ── Step 3: CourseBridge ───────────────────────────────────────────────────────

async def _cb_login(page, email: str, password: str):
    """Log into CourseBridge if the login form is visible."""
    if not await page.locator("input[type='email'], input[name='email']").count():
        return
    print("  Logging into CourseBridge...")
    await page.locator("input[type='email'], input[name='email']").first.fill(email)
    await page.locator("input[type='password']").first.fill(password)
    await page.locator("button:has-text('Sign in'), button[type='submit']").first.click()
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(2000)


async def _cb_upload_and_convert(page, file_path: Path):
    """Upload file, set template to Course Syllabus, click Convert, wait for Copy HTML."""
    print(f"  Uploading {file_path.name}...")
    # Try specific accept selector first; fall back to any file input if the
    # attribute value has changed on CourseBridge's side.
    selectors = [
        "input[accept='.pdf,.docx,.pptx,.txt,.md,.markdown,.text,.html,.htm,.csv,.tsv,.rtf,.json']",
        "input[accept='.pdf,.doc,.docx']",
        "input[type='file']",
    ]
    uploaded = False
    for selector in selectors:
        try:
            await page.wait_for_selector(selector, state="attached", timeout=30000)
            print(f"  Found upload input: {selector}")
            await page.locator(selector).first.set_input_files(str(file_path))
            uploaded = True
            break
        except Exception as e:
            print(f"  Selector {selector!r} failed: {e}")
            continue
    if not uploaded:
        raise RuntimeError("Could not find the file upload input on CourseBridge — the page may have changed.")
    await page.wait_for_timeout(500)
    trigger = page.locator("button[data-slot='select-trigger']").first
    template_text = await trigger.inner_text()
    if "Course Syllabus" not in template_text:
        print(f"  ⚠ Template '{template_text.strip()}' — setting Course Syllabus...")
        await trigger.click()
        await page.locator("text=Course Syllabus").first.click()
        await page.wait_for_timeout(300)
    print("  Converting...")
    await page.locator("button:has-text('Convert Document')").first.click()
    print("  Waiting for conversion...")
    copy_btn = page.locator("button:has-text('Copy HTML')").first
    for elapsed in range(0, 120, 3):
        await page.wait_for_timeout(3000)
        if await copy_btn.count() and await copy_btn.is_visible():
            print("  ✓ Conversion complete")
            return
        if elapsed % 15 == 0 and elapsed > 0:
            print(f"  Still waiting... ({elapsed}s)")
    raise RuntimeError("CourseBridge: 'Copy HTML' never appeared after 2 minutes")


async def _cb_get_html(page) -> str:
    """Click Copy HTML, read from clipboard or fall back to <pre> element."""
    await page.locator("button:has-text('Copy HTML')").first.click()
    await page.wait_for_timeout(500)
    html = ""
    try:
        html = await page.evaluate("() => navigator.clipboard.readText()")
    except Exception:
        pass
    if not html.strip():
        html = await page.locator("pre.font-mono").first.inner_text()
    return html


async def convert_with_coursebridge(file_path: Path, email: str, password: str, context=None, pause_fn=None) -> str:
    """Upload docx to CourseBridge, return HTML string.

    If context is provided, opens CourseBridge as a new tab in the existing browser.
    pause_fn: optional callable called after conversion so user can review the tab.
    """
    print("\nStep 3 — CourseBridge conversion...")

    if context is not None:
        page = await context.new_page()
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        await page.goto(COURSEBRIDGE_URL)
        await page.wait_for_load_state("domcontentloaded")
        await _cb_login(page, email, password)
        await page.wait_for_timeout(2000)
        if page.url != COURSEBRIDGE_URL:
            await page.goto(COURSEBRIDGE_URL)
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(1000)
        await _cb_upload_and_convert(page, file_path)
        if pause_fn:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, pause_fn, "CourseBridge conversion complete.\n\nReview the CourseBridge tab in the browser, then click OK to continue.")
        html = await _cb_get_html(page)
        print(f"  ✓ HTML captured ({len(html)} chars)")
        return html

    # Standalone: create own browser, close when done
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=60, args=["--start-maximized"])
        own_ctx = await browser.new_context(
            storage_state=CB_SESSION_FILE if os.path.exists(CB_SESSION_FILE) else None,
            no_viewport=True,
        )
        await own_ctx.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await own_ctx.new_page()
        await page.goto(COURSEBRIDGE_URL)
        await page.wait_for_load_state("domcontentloaded")
        await _cb_login(page, email, password)
        await page.wait_for_timeout(2000)
        if page.url != COURSEBRIDGE_URL:
            await page.goto(COURSEBRIDGE_URL)
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(1000)
        await _cb_upload_and_convert(page, file_path)
        html = await _cb_get_html(page)
        await own_ctx.storage_state(path=CB_SESSION_FILE)
        await browser.close()
    print(f"  ✓ HTML captured ({len(html)} chars)")
    return html


# ── Step 4 helpers ─────────────────────────────────────────────────────────────

async def _click_save_and_close(page) -> bool:
    """Find and click the 'Save and Close' d2l-button."""
    coords = await page.evaluate("""
        () => {
            for (const el of document.querySelectorAll('d2l-button')) {
                if ((el.textContent || '').trim() === 'Save and Close') {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0) return { x: r.left + r.width/2, y: r.top + r.height/2 };
                }
            }
            return null;
        }
    """)
    if coords:
        await page.mouse.click(coords["x"], coords["y"])
        return True
    return False


async def _get_topic_id(page: Page, course_id: str) -> tuple[str, str]:
    """Look up Course Syllabus TopicId via API. Returns (topic_id, viewer_url)."""
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
            if t.get("Title", "").strip().lower() == target.lower(): return t
        for m in node.get("Modules", []):
            r = find_topic(m, target)
            if r: return r
        return None

    topic_data = find_topic(toc, SYLLABUS_TOPIC_NAME) if toc else None
    if not topic_data:
        raise RuntimeError(f"Could not find '{SYLLABUS_TOPIC_NAME}' topic via API.")
    topic_id = str(topic_data.get("TopicId"))
    print(f"  [4a] ✓ Found '{SYLLABUS_TOPIC_NAME}' — TopicId: {topic_id}")
    viewer_url = f"{BRIGHTSPACE_BASE}/d2l/le/content/{course_id}/viewContent/{topic_id}/View"
    return topic_id, viewer_url


async def _open_topic_edit_page(page: Page, topic_id: str, course_id: str):
    """Navigate to topic viewer, click Options → Edit. Returns the edit page."""
    viewer_url = f"{BRIGHTSPACE_BASE}/d2l/le/content/{course_id}/viewContent/{topic_id}/View"
    await page.goto(viewer_url)
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(4000)

    all_btns = await page.evaluate(_WALK_JS, {"hints": None})
    print(f"  [4b] {len(all_btns)} button(s): {[b['label'] for b in all_btns]}")
    dots = (
        _find_btn(all_btns, exact="Options")
        or _find_btn(all_btns, contains="more options")
        or _find_btn(all_btns, contains="more actions")
        or _find_btn(all_btns, contains="options", exclude="course")
    )
    if not dots:
        raise RuntimeError(f"Could not find Options button. Buttons: {[b['label'] for b in all_btns]}")
    print(f"  [4c] ✓ '{dots['label']}' — clicking...")
    await page.mouse.click(dots["x"], dots["y"])
    await page.wait_for_timeout(600)

    menu_items = await page.evaluate(_WALK_JS, {"hints": None, "editMode": True})
    print(f"  [4e] Menu: {[b['label'] for b in menu_items if b['label'].strip()]}")
    edit = next((b for b in menu_items if b["label"].strip().lower() == "edit"), None)
    if not edit:
        raise RuntimeError("Could not find Edit option in dropdown.")
    print(f"  [4e] ✓ '{edit['label']}' — clicking...")
    try:
        async with page.context.expect_page(timeout=5000) as new_page_info:
            await page.mouse.click(edit["x"], edit["y"])
        edit_page = await new_page_info.value
        print(f"  [4f] Opened in new tab: {edit_page.url}")
    except Exception:
        edit_page = page
        print("  [4f] Opened in same tab")
    await edit_page.wait_for_load_state("domcontentloaded")
    await edit_page.wait_for_timeout(3000)
    return edit_page


async def _set_tinymce_content(edit_page, html: str) -> str:
    """Set TinyMCE editor content via JS API. Returns 'ok' or an error string."""
    return await edit_page.evaluate("""
        (html) => {
            try {
                if (typeof tinymce === 'undefined') return 'tinymce not found';
                const ed = tinymce.activeEditor;
                if (!ed) return 'no active editor';
                ed.setContent(html);
                return 'ok';
            } catch(e) { return 'error: ' + e.message; }
        }
    """, html)



async def paste_html_to_syllabus(page: Page, html: str, course_id: str):
    """Find Course Syllabus topic, open editor, replace HTML via TinyMCE, save."""
    print("\nStep 4 — Pasting HTML into Brightspace...")
    topic_id, viewer_url = await _get_topic_id(page, course_id)
    print(f"  [4a] Navigating to: {viewer_url}")
    edit_page = await _open_topic_edit_page(page, topic_id, course_id)
    print(f"  [4f] ✓ Edit page ready: {edit_page.url}")
    result = await _set_tinymce_content(edit_page, html)
    print(f"  [4g] TinyMCE result: {result}")
    if result != "ok":
        raise RuntimeError(f"Could not set TinyMCE content: {result}")
    await edit_page.wait_for_timeout(500)
    print("  [4g] ✓ Content set")
    print("  Clicking Save and Close...")
    saved = await _click_save_and_close(edit_page)
    if saved:
        await edit_page.wait_for_load_state("domcontentloaded", timeout=15000)
        print("  ✓ Course Syllabus saved successfully!")
    else:
        print("  ⚠ Save and Close not found — save manually in the browser")


# ── CRN → course ID lookup ────────────────────────────────────────────────────

async def find_course_id_by_crn(page, crn: str) -> str:
    """Find the Brightspace course ID for a given CRN."""
    print(f"  Looking up CRN {crn}...")
    _js = """
        (crn) => {
            const results = [];
            function walk(root) {
                for (const el of root.querySelectorAll('a')) {
                    const href = el.getAttribute('href') || '';
                    if (href.includes('/d2l/home/') && el.textContent.includes(crn))
                        results.push({ href: el.href || href, text: (el.textContent || '').trim().slice(0, 100) });
                }
                for (const el of root.querySelectorAll('*')) { if (el.shadowRoot) walk(el.shadowRoot); }
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
        print(f"  [{nav_url.split('/')[-1]}] {len(links)} link(s) containing '{crn}'")
        for lnk in links:
            print(f"    {lnk['text'][:80]}  →  {lnk['href']}")
        if links:
            m = re.search(r'/d2l/home/(\d+)', links[0]["href"])
            if m:
                course_id = m.group(1)
                print(f"  ✓ Brightspace ID: {course_id}")
                return course_id
    raise RuntimeError(f"Could not find a course with CRN {crn} on Brightspace.")


# ── Main helpers ───────────────────────────────────────────────────────────────

async def _resolve_course_id(page, course_url: str) -> str:
    """Extract or look up the Brightspace course ID from a URL or CRN."""
    if re.fullmatch(r'\d{4,6}', course_url.strip()):
        print(f"CRN entered: {course_url.strip()} — looking up course...")
        return await find_course_id_by_crn(page, course_url.strip())
    match = re.search(r'/(?:le|content|lessons|quizzing|home)/(\d+)', course_url)
    if not match:
        print(f"✗ Could not extract course ID from: {course_url}")
        sys.exit(1)
    course_id = match.group(1)
    print(f"Course ID from URL: {course_id}")
    return course_id


def _convert_rtf_to_docx(rtf_path: Path) -> Path:
    """Convert RTF to DOCX using pypandoc (auto-installs pypandoc and Pandoc if missing)."""
    try:
        import pypandoc
    except ImportError:
        print("  Installing pypandoc...")
        os.system(f"{sys.executable} -m pip install pypandoc")
        import pypandoc

    try:
        pypandoc.get_pandoc_version()
    except OSError:
        print("  Pandoc not found — downloading and installing Pandoc (one-time, ~30 MB)...")
        pypandoc.download_pandoc()
        print("  ✓ Pandoc installed")

    docx_path = rtf_path.with_suffix(".docx")
    print("  Converting RTF → docx...")
    pypandoc.convert_file(str(rtf_path), "docx", outputfile=str(docx_path))
    print(f"  ✓ Converted: {docx_path.name}")
    return docx_path


async def _convert_outline(page, course_id: str, prompt_fn, email: str, password: str, context=None, pause_fn=None) -> str | None:
    """Steps 1-3: download outline, convert if needed, run CourseBridge. Returns HTML or None if skipped."""
    file_path = await find_and_download_outline(page, course_id=course_id, prompt_fn=prompt_fn)
    if file_path is None:
        return None
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        print("\nStep 2 — PDF detected, converting...")
        file_path = convert_pdf_to_docx(file_path)
    elif suffix == ".rtf":
        print("\nStep 2 — RTF detected, converting...")
        file_path = _convert_rtf_to_docx(file_path)
    else:
        print(f"\nStep 2 — {file_path.suffix} file, no conversion needed")
    return await convert_with_coursebridge(file_path, email=email, password=password, context=context, pause_fn=pause_fn)


# ── Main orchestrator ──────────────────────────────────────────────────────────

async def _run_outline_steps(page, context, course_url, email, password, dry_run, prompt_fn, rename_fn, pause_fn):
    """Inner logic for run() — shared between standalone and staged invocations."""
    course_id = await _resolve_course_id(page, course_url)
    content_url = f"{BRIGHTSPACE_BASE}/d2l/le/lessons/{course_id}"
    print("Navigating to Content tab...")
    await page.goto(content_url)
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(5000)

    if dry_run:
        print("⚠  DRY RUN MODE — HTML will not be pasted into Brightspace")

    html = await _convert_outline(page, course_id, prompt_fn, email, password, context=context, pause_fn=pause_fn)
    if html is None:
        print("\n✓ Course outline step skipped — no outline present.")
        return

    if dry_run:
        print(f"\n✓ Dry run complete — HTML captured ({len(html):,} chars)")
        return

    await page.bring_to_front()
    await page.goto(content_url)
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(2000)
    await paste_html_to_syllabus(page, html, course_id=course_id)
    print("\n✓ All done!")
    if rename_fn:
        from staging_automator import maybe_rename_staged
        await maybe_rename_staged(page, rename_fn)


async def run(dry_run: bool = False, course_url: str = "", email: str = "", password: str = "", prompt_fn=input, rename_fn=None, context=None, page=None):
    _course_url = course_url or COURSE_URL
    _email      = email or COURSEBRIDGE_EMAIL
    _password   = password or COURSEBRIDGE_PASSWORD
    if not _course_url:
        print("✗ Course CRN or URL is not set.")
        sys.exit(1)

    if context is not None:
        # Called from staging — reuse the shared browser context, leave browser open
        await _run_outline_steps(page, context, _course_url, _email, _password, dry_run, prompt_fn, rename_fn, pause_fn=prompt_fn)
        return

    # Standalone — create own browser, close when done
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80, args=["--start-maximized"])
        own_ctx = await browser.new_context(
            storage_state=BS_SESSION_FILE if os.path.exists(BS_SESSION_FILE) else None,
            no_viewport=True,
        )
        own_page = await own_ctx.new_page()
        await _wait_for_bs_login(own_page, own_ctx)
        await _run_outline_steps(own_page, own_ctx, _course_url, _email, _password, dry_run, prompt_fn, rename_fn, pause_fn=prompt_fn)
        # Stay alive until user closes the browser manually
        try:
            await own_page.wait_for_event("close", timeout=0)
        except Exception:
            pass



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert and paste course outline into Brightspace")
    parser.add_argument("--dry-run", action="store_true", help="Download + convert only, no paste")
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))
