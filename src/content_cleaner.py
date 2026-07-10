import asyncio
import contextlib
import io
import os
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright, Page

from course_outline_automator import (
    BRIGHTSPACE_BASE,
    _WALK_JS,
    _resolve_course_id,
    _open_topic_edit_page,
    _set_tinymce_content,
    _click_save_and_close,
)

if os.name == "nt":
    _USERDATA_DIR = Path(os.environ["APPDATA"]) / "BrightspaceAutomator"
else:
    _USERDATA_DIR = Path.home() / ".local" / "share" / "BrightspaceAutomator"

from browser import _BS_PROFILE, _load_bs_credentials, _wait_for_login
from navigation import (
    get_course_name,
    set_per_page_200,
    _find_menu_item,
    _find_action_button,
    open_quiz_edit,
)

SKIP_MODULES = {
    "How to Use This Blueprint",
    "Welcome Module",
    "Module [#]: [Module Title]",
    "Conclusion",
}


async def _collect_topic_ids(page: Page, course_id: str, api_ver: str, module_id: int, out: set):
    """Recursively collect all topic IDs under a module."""
    result = await page.evaluate(f"""
        async () => {{
            try {{
                const r = await fetch('{BRIGHTSPACE_BASE}/d2l/api/le/{api_ver}/{course_id}/content/modules/{module_id}/structure/');
                if (!r.ok) return null;
                return await r.json();
            }} catch(e) {{ return null; }}
        }}
    """)
    for item in (result or []):
        if item.get("Type") == 1:
            out.add(str(item.get("Id", "")))
        elif item.get("Type") == 0:
            sub = item.get("Id")
            if sub:
                await _collect_topic_ids(page, course_id, api_ver, sub, out)


async def get_skip_topic_ids(page: Page, course_id: str) -> set:
    """Return topic IDs that belong to SKIP_MODULES using the content modules API."""
    skip_ids: set = set()
    for api_ver in ["1.70", "1.67", "1.68", "1.69", "1.60"]:
        root = await page.evaluate(f"""
            async () => {{
                try {{
                    const r = await fetch('{BRIGHTSPACE_BASE}/d2l/api/le/{api_ver}/{course_id}/content/root/');
                    if (!r.ok) return null;
                    return await r.json();
                }} catch(e) {{ return null; }}
            }}
        """)
        if not root:
            continue
        # root/ returns either a list of top-level items OR a single module object
        if isinstance(root, list):
            children = root
        else:
            root_id = root.get("Id")
            if not root_id:
                continue
            children = await page.evaluate(f"""
                async () => {{
                    try {{
                        const r = await fetch('{BRIGHTSPACE_BASE}/d2l/api/le/{api_ver}/{course_id}/content/modules/{root_id}/structure/');
                        if (!r.ok) return null;
                        return await r.json();
                    }} catch(e) {{ return null; }}
                }}
            """)
        for item in (children or []):
            if item.get("Type") == 0 and item.get("Title", "") in SKIP_MODULES:
                mid = item.get("Id")
                print(f"  Skipping module: {item['Title']}")
                if mid:
                    await _collect_topic_ids(page, course_id, api_ver, mid, skip_ids)
        return skip_ids
    print("  Could not get module structure — no topics will be skipped")
    return skip_ids


async def get_all_topics(page: Page, course_id: str) -> list[dict]:
    """Fetch all content topics — tries TOC API first, falls back to DOM scraping."""
    toc = None
    for api_ver in ["1.70", "1.67", "1.68", "1.69", "1.60", "1.50"]:
        result = await page.evaluate(f"""
            async () => {{
                try {{
                    const r = await fetch('{BRIGHTSPACE_BASE}/d2l/api/le/{api_ver}/{course_id}/content/toc');
                    if (!r.ok) return {{ status: r.status }};
                    return {{ toc: await r.json() }};
                }} catch(e) {{ return {{ error: e.message }}; }}
            }}
        """)
        if result and result.get("toc"):
            toc = result["toc"]
            print(f"  ✓ TOC API v{api_ver}")
            break
        else:
            detail = result.get("status") or result.get("error") or "no response"
            print(f"  API v{api_ver}: {detail}")

    if toc:
        def flatten(node):
            items = []
            for topic in node.get("Topics", []):
                items.append({
                    "Title":   topic.get("Title", ""),
                    "TopicId": str(topic.get("TopicId", "")),
                    "Url":     topic.get("Url", ""),
                })
            for mod in node.get("Modules", []):
                items.extend(flatten(mod))
            return items
        return flatten(toc)

    print("  API unavailable — falling back to DOM scraping...")
    topics = await page.evaluate(f"""
        () => {{
            const seen = new Set();
            const results = [];
            function walk(root) {{
                for (const a of root.querySelectorAll('a[href*="viewContent"]')) {{
                    const href = a.getAttribute('href') || '';
                    const m = href.match(/viewContent\\/(\d+)/);
                    if (m && !seen.has(m[1])) {{
                        seen.add(m[1]);
                        results.push({{
                            Title:   (a.textContent || '').trim() || href,
                            TopicId: m[1],
                            Url:     href,
                        }});
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
    if topics:
        print(f"  ✓ DOM scrape found {len(topics)} topic(s)")
    else:
        print("  ✗ No topics found via DOM either — check that you're on the course content page")
    return topics or []


_FIND_DOTS_JS = """
    () => {
        function find(root) {
            for (const icon of root.querySelectorAll('d2l-icon-custom')) {
                for (const path of icon.querySelectorAll('path')) {
                    const d = path.getAttribute('d') || '';
                    if (d.includes('M2,7') && d.includes('M9,7') && d.includes('M16,7')) {
                        let n = icon;
                        while (n) {
                            const tag = (n.tagName || '').toLowerCase();
                            if (tag === 'button' ||
                                (n.getAttribute && n.getAttribute('role') === 'button')) {
                                const r = n.getBoundingClientRect();
                                if (r.width > 0) return {x: r.left + r.width/2, y: r.top + r.height/2};
                            }
                            n = n.parentElement;
                        }
                    }
                }
            }
            for (const el of root.querySelectorAll('*')) {
                if (el.shadowRoot) { const c = find(el.shadowRoot); if (c) return c; }
            }
            return null;
        }
        return find(document);
    }
"""

_FIND_TEXTAREA_JS = """
    () => {
        function search(root) {
            for (const ta of root.querySelectorAll('textarea')) {
                if (ta.offsetHeight > 50) return ta;
            }
            for (const el of root.querySelectorAll('*')) {
                if (el.shadowRoot) {
                    const ta = search(el.shadowRoot);
                    if (ta) return ta;
                }
            }
            return null;
        }
        const ta = search(document);
        return ta ? ta.value : null;
    }
"""


async def _set_dialog_textarea(edit_page, html: str) -> bool:
    return await edit_page.evaluate("""
        (html) => {
            function search(root) {
                for (const ta of root.querySelectorAll('textarea')) {
                    if (ta.offsetHeight > 50) return ta;
                }
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) {
                        const ta = search(el.shadowRoot);
                        if (ta) return ta;
                    }
                }
                return null;
            }
            const ta = search(document);
            if (!ta) return false;
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, 'value'
            ).set;
            setter.call(ta, html);
            ta.dispatchEvent(new Event('input', {bubbles: true}));
            ta.dispatchEvent(new Event('change', {bubbles: true}));
            return true;
        }
    """, html)


async def _click_dialog_button(edit_page, label: str) -> None:
    await edit_page.evaluate("""
        (label) => {
            function search(root) {
                for (const btn of root.querySelectorAll('button')) {
                    const t = (btn.textContent || btn.innerText || '').trim().toLowerCase();
                    if (t === label.toLowerCase()) { btn.click(); return true; }
                }
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot && search(el.shadowRoot)) return true;
                }
                return false;
            }
            search(document);
        }
    """, label)


def _case_replace(word: str) -> str:
    if word == word.upper():
        return "BRIGHTSPACE"
    if word[0].isupper():
        return "Brightspace"
    return "brightspace"


def replace_moodle(html: str, topic_name: str) -> tuple[str, list[str], list[str]]:
    """
    Replace 'moodle' text in HTML. Returns (new_html, changes, warnings).
    - Links with 'moodle' in href: replace link text only, keep href, add warning.
    - All other text nodes: case-preserving replacement.
    """
    changes: list[str] = []
    warnings: list[str] = []

    # Step 1: handle <a href="...moodle..."> links
    def _replace_link(m: re.Match) -> str:
        attrs   = m.group(1)
        content = m.group(2)
        href_m  = re.search(r'href=["\']([^"\']*)["\']', attrs, re.IGNORECASE)
        if href_m and "moodle" in href_m.group(1).lower():
            new_content = re.sub(
                r"\bmoodle\b",
                lambda wm: _case_replace(wm.group(0)),
                content,
                flags=re.IGNORECASE,
            )
            warnings.append(
                f"  ⚠  [{topic_name}] Moodle link — href may be dead: {href_m.group(1)}"
            )
            if new_content != content:
                changes.append(f"  [link text] '{content.strip()}' → '{new_content.strip()}'")
            return f"<a{attrs}>{new_content}</a>"
        return m.group(0)

    html = re.sub(r"<a([^>]*)>(.*?)</a>", _replace_link, html, flags=re.IGNORECASE | re.DOTALL)

    # Step 2: replace in text nodes only (segments between tags)
    def _replace_segment(m: re.Match) -> str:
        segment = m.group(0)
        if segment.startswith("<"):
            return segment  # leave tags untouched
        def _replace_word(wm: re.Match) -> str:
            rep = _case_replace(wm.group(0))
            changes.append(f"  [text] '{wm.group(0)}' → '{rep}'")
            return rep
        return re.sub(r"\bmoodle\b", _replace_word, segment, flags=re.IGNORECASE)

    html = re.sub(r"<[^>]*>|[^<]+", _replace_segment, html)

    return html, changes, warnings


def replace_moodle_in_title(title: str) -> tuple[str, bool]:
    new = re.sub(r"\bmoodle\b", lambda m: _case_replace(m.group(0)), title, flags=re.IGNORECASE)
    return new, new != title


_FIND_AND_SET_TITLE_JS = """
    ([currentTitle, newTitle]) => {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
        function fire(el) {
            el.dispatchEvent(new Event('input',  {bubbles: true, composed: true}));
            el.dispatchEvent(new Event('change', {bubbles: true, composed: true}));
        }
        function findAndSet(root) {
            // Lit-based activity editors (assignments/quizzes/discussions): the
            // title lives in a d2l-input-text — set the HOST value property and
            // fire composed events, or the editor state never sees the change.
            for (const host of root.querySelectorAll('d2l-input-text')) {
                const inner = host.shadowRoot && host.shadowRoot.querySelector('input');
                const val = (inner && inner.value) || host.value || '';
                if (val === currentTitle) {
                    host.value = newTitle;
                    if (inner) { setter.call(inner, newTitle); fire(inner); }
                    fire(host);
                    return true;
                }
            }
            for (const el of root.querySelectorAll('input')) {
                if (el.value === currentTitle) {
                    setter.call(el, newTitle);
                    fire(el);
                    return true;
                }
            }
            for (const el of root.querySelectorAll('*')) {
                if (el.shadowRoot) {
                    const r = findAndSet(el.shadowRoot);
                    if (r) return r;
                }
            }
            return false;
        }
        return findAndSet(document);
    }
"""


async def process_topic(
    page: Page, course_id: str, topic: dict, dry_run: bool
) -> tuple[list[str], list[str]]:
    """Open a topic editor, read HTML via Source Code dialog, optionally replace and save."""
    title    = topic["Title"]
    topic_id = topic["TopicId"]

    new_title, title_changed = replace_moodle_in_title(title)

    async def _close(ep):
        if ep is not page:
            try:
                await ep.close()
            except Exception:
                pass

    print(f"\n  {title[:80]}")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            edit_page = await _open_topic_edit_page(page, topic_id, course_id)
    except Exception as e:
        print(f"    Skipped: {e}")
        return [], []

    html = None
    via_dialog = False

    def _find_source_code(btns):
        return next(
            (b for b in (btns or []) if b.get("label", "").strip().lower() == "source code"),
            None,
        )

    # ── step 1: check if Source Code is already visible ──────────────────
    try:
        btns = await edit_page.evaluate(_WALK_JS)
        src_btn = _find_source_code(btns)
    except Exception:
        btns = []
        src_btn = None

    # ── step 2: if not visible, click three-dots and try again ───────────
    if not src_btn:
        try:
            dots = await edit_page.evaluate(_FIND_DOTS_JS)
        except Exception:
            dots = None

        if dots:
            await edit_page.mouse.click(dots["x"], dots["y"])
            await edit_page.wait_for_timeout(800)
            try:
                btns = await edit_page.evaluate(_WALK_JS)
                src_btn = _find_source_code(btns)
            except Exception:
                src_btn = None

    # ── step 3: click Source Code → dialog opens → read textarea ─────────
    if src_btn:
        await edit_page.mouse.click(src_btn["x"], src_btn["y"])
        await edit_page.wait_for_timeout(1200)
        try:
            html = await edit_page.evaluate(_FIND_TEXTAREA_JS)
            if html is not None:
                via_dialog = True
        except Exception:
            pass

    # ── fallback: TinyMCE JS API ──────────────────────────────────────────
    if html is None:
        try:
            html = await edit_page.evaluate("""
                () => {
                    if (typeof tinymce === 'undefined' || !tinymce.activeEditor) return null;
                    return tinymce.activeEditor.getContent() || null;
                }
            """)
        except Exception:
            html = None

    if html is None and not title_changed:
        print("    Not an HTML topic — skipped")
        await _close(edit_page)
        return [], []

    if html is not None:
        new_html, changes, warnings = replace_moodle(html, title)
    else:
        new_html, changes, warnings = "", [], []

    if not changes and not warnings and not title_changed:
        print("    No Moodle references found")
        if via_dialog:
            await _click_dialog_button(edit_page, "Cancel")
            await edit_page.wait_for_timeout(400)
        await _close(edit_page)
        return [], []

    for line in changes:
        print(line)
    for line in warnings:
        print(line)

    if title_changed:
        print(f"  [title] '{title}' → '{new_title}'")
        changes.append(f"  [title] '{title}' → '{new_title}'")

    if dry_run:
        if title_changed:
            print("    (dry run — title not renamed)")
        print("    (dry run — not saved)")
        if via_dialog:
            await _click_dialog_button(edit_page, "Cancel")
            await edit_page.wait_for_timeout(400)
        await _close(edit_page)
        return changes, warnings

    # ── live run: write HTML changes ──────────────────────────────────────
    if html is not None:
        if via_dialog:
            ok = await _set_dialog_textarea(edit_page, new_html)
            if not ok:
                print("    ✗ Could not write to dialog textarea")
                await _click_dialog_button(edit_page, "Cancel")
                await edit_page.wait_for_timeout(400)
                await _close(edit_page)
                return [], []
            await edit_page.wait_for_timeout(400)
            await _click_dialog_button(edit_page, "Save")
            await edit_page.wait_for_timeout(800)
        else:
            result = await _set_tinymce_content(edit_page, new_html)
            if result != "ok":
                print(f"    ✗ Could not set content: {result}")
                await _close(edit_page)
                return [], []

    # ── live run: write title ─────────────────────────────────────────────
    if title_changed:
        ok = await edit_page.evaluate(_FIND_AND_SET_TITLE_JS, [title, new_title])
        if ok:
            print("    ✓ Title updated")
        else:
            print("    ✗ Title input not found — rename manually")

    await edit_page.wait_for_timeout(500)
    saved = await edit_page.evaluate("""
        () => {
            function walk(root) {
                for (const el of root.querySelectorAll('button, d2l-button')) {
                    const text = (el.textContent || '').trim();
                    if (text === 'Save and Close') {
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
    if saved:
        await edit_page.mouse.click(saved["x"], saved["y"])
        await edit_page.wait_for_load_state("domcontentloaded", timeout=15000)
        print("    ✓ Saved")
    else:
        if await _click_save_and_close(edit_page):
            await edit_page.wait_for_load_state("domcontentloaded", timeout=15000)
            print("    ✓ Saved")
    return changes, warnings


async def get_all_assignments(page: Page, course_id: str) -> list[dict]:
    """Fetch all assignment (dropbox) folders with their instructions HTML via API."""
    for api_ver in ["1.70", "1.67", "1.68", "1.69", "1.60", "1.50"]:
        result = await page.evaluate(f"""
            async () => {{
                try {{
                    const r = await fetch('{BRIGHTSPACE_BASE}/d2l/api/le/{api_ver}/{course_id}/dropbox/folders/');
                    if (!r.ok) return {{ status: r.status }};
                    return {{ folders: await r.json() }};
                }} catch(e) {{ return {{ error: e.message }}; }}
            }}
        """)
        folders = (result or {}).get("folders")
        if folders is not None:
            print(f"  ✓ Dropbox API v{api_ver}")
            return [
                {
                    "Id":   str(f.get("Id", "")),
                    "Name": f.get("Name", ""),
                    "Html": (f.get("CustomInstructions") or {}).get("Html")
                            or (f.get("CustomInstructions") or {}).get("Text", ""),
                }
                for f in folders
            ]
        detail = result.get("status") or result.get("error") or "no response"
        print(f"  Dropbox API v{api_ver}: {detail}")
    print("  ✗ Could not fetch assignments — skipping assignment scan")
    return []


_FIND_SAVE_AND_CLOSE_JS = """
    () => {
        function walk(root) {
            for (const el of root.querySelectorAll('button, d2l-button')) {
                const text = (el.textContent || '').trim();
                if (text === 'Save and Close') {
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
"""


_SET_TINYMCE_JS = """
    (html) => {
        try {
            if (typeof tinymce === 'undefined') return 'tinymce not found';
            const editors = tinymce.editors || tinymce.get() || [];
            for (const ed of editors) {
                const content = ed.getContent() || '';
                if (/moodle/i.test(content)) {
                    ed.setContent(html);
                    ed.fire('change');
                    return 'ok';
                }
            }
            return 'no editor with moodle content';
        } catch(e) { return 'error: ' + e.message; }
    }
"""


_FIND_HTMLEDITOR_JS = """
    () => {
        function find(root) {
            for (const sel of ['d2l-htmleditor', '.tox-edit-area__iframe', '.d2l-htmleditor-container']) {
                for (const el of root.querySelectorAll(sel)) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0) return { x: r.left + r.width/2, y: r.top + Math.min(r.height/2, 100) };
                }
            }
            for (const el of root.querySelectorAll('*')) {
                if (el.shadowRoot) { const c = find(el.shadowRoot); if (c) return c; }
            }
            return null;
        }
        return find(document);
    }
"""

_EDITOR_DIAG_JS = """
    () => {
        const found = [];
        function walk(root) {
            for (const sel of ['d2l-htmleditor', 'd2l-activity-assignment-editor',
                               '.tox-edit-area__iframe', 'iframe', 'textarea']) {
                for (const el of root.querySelectorAll(sel)) {
                    const r = el.getBoundingClientRect();
                    found.push(sel + (r.width > 0 ? '' : ' (hidden)'));
                }
            }
            for (const el of root.querySelectorAll('*')) {
                if (el.shadowRoot) walk(el.shadowRoot);
            }
        }
        walk(document);
        return [...new Set(found)].join(', ') || 'no editor elements found';
    }
"""


async def _try_set_all_frames(edit_page, new_html: str) -> str:
    results = []
    for frame in edit_page.frames:
        try:
            result = await frame.evaluate(_SET_TINYMCE_JS, new_html)
        except Exception as e:
            result = f"frame error: {e}"
        if result == "ok":
            return "ok"
        results.append(result)
    found = [r for r in results if r != "tinymce not found"]
    return found[0] if found else "tinymce not found"


async def _set_editor_html(edit_page, new_html: str) -> str:
    """Set instructions HTML on the TinyMCE editor containing 'moodle'.
    The activity editor lazy-loads TinyMCE, so click the instructions
    area first to force initialization, then poll all frames."""
    result = await _try_set_all_frames(edit_page, new_html)
    if result == "ok":
        return "ok"

    try:
        coords = await edit_page.evaluate(_FIND_HTMLEDITOR_JS)
    except Exception:
        coords = None
    if coords:
        await edit_page.mouse.click(coords["x"], coords["y"])

    for _ in range(10):
        await edit_page.wait_for_timeout(1000)
        result = await _try_set_all_frames(edit_page, new_html)
        if result == "ok":
            return "ok"

    try:
        diag = await edit_page.evaluate(_EDITOR_DIAG_JS)
    except Exception as e:
        diag = f"diag failed: {e}"
    return f"{result} — page has: {diag}"


async def _open_assignment_edit_admin(page: Page, name: str) -> None:
    """Open an assignment editor from the ADMIN list page (folders_manage.d2l).
    Rows there use d2l-dropdown-context-menu, not button[aria-haspopup]."""
    coords = None
    for _ in range(5):
        coords = await page.evaluate(
            """(name) => {
                function find(root) {
                    for (const el of root.querySelectorAll('d2l-dropdown-context-menu')) {
                        const label = el.getAttribute('aria-label') || el.getAttribute('text') || '';
                        if (label.includes('Actions for') && label.includes(name)) {
                            el.scrollIntoView({block: 'center', behavior: 'instant'});
                            const r = el.getBoundingClientRect();
                            if (r.width > 0) return { x: r.left + r.width/2, y: r.top + r.height/2 };
                        }
                    }
                    for (const el of root.querySelectorAll('*')) {
                        if (el.shadowRoot) { const c = find(el.shadowRoot); if (c) return c; }
                    }
                    return null;
                }
                return find(document);
            }""",
            name,
        )
        if coords:
            break
        await page.evaluate("window.scrollBy(0, 800)")
        await page.wait_for_timeout(400)
    if coords is None:
        raise Exception(f"Actions menu for '{name}' not found on admin list")
    await page.wait_for_timeout(300)
    await page.mouse.click(coords["x"], coords["y"])
    await page.wait_for_timeout(500)
    edit_coords = await _find_menu_item(page, "Edit Assignment") or await _find_menu_item(page, "Edit Folder")
    if edit_coords is None:
        raise Exception(f"Edit menu item for '{name}' not found")
    await page.mouse.click(edit_coords["x"], edit_coords["y"])
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(800)


async def process_assignment(page: Page, course_id: str, folder: dict, dry_run: bool) -> tuple[list[str], list[str]]:
    """Replace Moodle references in one assignment's name and instructions."""
    name = folder["Name"]
    html = folder["Html"] or ""

    new_name, name_changed = replace_moodle_in_title(name)
    new_html, changes, warnings = replace_moodle(html, name)

    if not changes and not warnings and not name_changed:
        return [], []

    print(f"\n  [Assignment] {name[:70]}")
    for line in changes:
        print(line)
    for line in warnings:
        print(line)
    if name_changed:
        print(f"  [title] '{name}' → '{new_name}'")
        changes.append(f"  [title] '{name}' → '{new_name}'")

    if dry_run:
        print("    (dry run — not saved)")
        return changes, warnings

    list_url = f"{BRIGHTSPACE_BASE}/d2l/lms/dropbox/admin/folders_manage.d2l?ou={course_id}"
    # Retry once: right after Save and Close, D2L's redirect back to the list can
    # still be in flight, which aborts the first goto (net::ERR_ABORTED).
    for attempt in range(2):
        try:
            await page.goto(list_url, wait_until="domcontentloaded")
            break
        except Exception:
            if attempt == 1:
                print("    ✗ Could not load assignments list — edit manually")
                return [], warnings
            await page.wait_for_timeout(2500)
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    await page.wait_for_timeout(1000)
    await set_per_page_200(page)
    try:
        await _open_assignment_edit_admin(page, name)
    except Exception as e:
        print(f"    ✗ Could not open editor: {e} — edit manually")
        return [], warnings
    await page.wait_for_timeout(2000)

    if changes and html:
        result = await _set_editor_html(page, new_html)
        if result.startswith("no editor with moodle content"):
            print("    ~ Instructions already clean in editor — continuing")
            changes = [c for c in changes if c.startswith("  [title]")]
        elif result != "ok":
            print(f"    ✗ Could not set instructions: {result} — edit manually")
            return [], warnings

    if name_changed:
        ok = await page.evaluate(_FIND_AND_SET_TITLE_JS, [name, new_name])
        if ok:
            print("    ✓ Title updated")
        else:
            print("    ✗ Title input not found — rename manually")

    await page.wait_for_timeout(500)
    saved = await page.evaluate(_FIND_SAVE_AND_CLOSE_JS)
    if not saved:
        print("    ✗ Save and Close not found — save manually")
        return [], warnings
    await page.mouse.click(saved["x"], saved["y"])
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    await page.wait_for_timeout(1000)
    print("    ✓ Saved")
    return changes, warnings


async def get_all_quizzes(page: Page, course_id: str) -> list[dict]:
    """Fetch all quizzes (paged API) with description/header/footer HTML."""
    for api_ver in ["1.70", "1.67", "1.68", "1.69", "1.60", "1.50"]:
        quizzes: list[dict] = []
        url = f"{BRIGHTSPACE_BASE}/d2l/api/le/{api_ver}/{course_id}/quizzes/"
        ok = True
        while url:
            result = await page.evaluate("""
                async (url) => {
                    try {
                        const r = await fetch(url);
                        if (!r.ok) return { status: r.status };
                        return { page: await r.json() };
                    } catch(e) { return { error: e.message }; }
                }
            """, url)
            data = (result or {}).get("page")
            if data is None:
                ok = False
                detail = result.get("status") or result.get("error") or "no response"
                print(f"  Quizzes API v{api_ver}: {detail}")
                break
            quizzes.extend(data.get("Objects") or [])
            url = data.get("Next")
        if ok:
            print(f"  ✓ Quizzes API v{api_ver}")
            return [
                {
                    "Id":     str(q.get("QuizId", "")),
                    "Name":   q.get("Name", ""),
                    "Html":   ((q.get("Description") or {}).get("Text") or {}).get("Html", "") or "",
                    "Header": ((q.get("Header") or {}).get("Text") or {}).get("Html", "") or "",
                    "Footer": ((q.get("Footer") or {}).get("Text") or {}).get("Html", "") or "",
                }
                for q in quizzes
            ]
    print("  ✗ Could not fetch quizzes — skipping quiz scan")
    return []


async def process_quiz(page: Page, course_id: str, quiz: dict, dry_run: bool) -> tuple[list[str], list[str]]:
    """Replace Moodle references in one quiz's name and description."""
    name = quiz["Name"]
    html = quiz["Html"] or ""

    new_name, name_changed = replace_moodle_in_title(name)
    new_html, changes, warnings = replace_moodle(html, name)

    for field in ("Header", "Footer"):
        if re.search(r"moodle", quiz.get(field) or "", re.IGNORECASE):
            warnings.append(f"  ⚠  [{name}] Moodle in quiz {field.lower()} — fix manually in the editor")

    if not changes and not warnings and not name_changed:
        return [], []

    print(f"\n  [Quiz] {name[:70]}")
    for line in changes:
        print(line)
    for line in warnings:
        print(line)
    if name_changed:
        print(f"  [title] '{name}' → '{new_name}'")
        changes.append(f"  [title] '{name}' → '{new_name}'")

    if dry_run:
        print("    (dry run — not saved)")
        return changes, warnings

    if not changes and not name_changed:
        return [], warnings  # header/footer warnings only — nothing to save

    list_url = f"{BRIGHTSPACE_BASE}/d2l/lms/quizzing/user/quizzes_list.d2l?ou={course_id}"
    for attempt in range(2):
        try:
            await page.goto(list_url, wait_until="domcontentloaded")
            break
        except Exception:
            if attempt == 1:
                print("    ✗ Could not load quiz list — edit manually")
                return [], warnings
            await page.wait_for_timeout(2500)
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    await page.wait_for_timeout(1000)
    await set_per_page_200(page)
    try:
        await open_quiz_edit(page, name)
    except Exception as e:
        print(f"    ✗ Could not open editor: {e} — edit manually")
        return [], warnings
    await page.wait_for_timeout(2000)

    if changes and html:
        result = await _set_editor_html(page, new_html)
        if result.startswith("no editor with moodle content"):
            print("    ~ Description already clean in editor — continuing")
            changes = [c for c in changes if c.startswith("  [title]")]
        elif result != "ok":
            print(f"    ✗ Could not set description: {result} — edit manually")
            return [], warnings

    if name_changed:
        ok = await page.evaluate(_FIND_AND_SET_TITLE_JS, [name, new_name])
        print("    ✓ Title updated" if ok else "    ✗ Title input not found — rename manually")

    await page.wait_for_timeout(500)
    saved = await page.evaluate(_FIND_SAVE_AND_CLOSE_JS)
    if not saved:
        print("    ✗ Save and Close not found — save manually")
        return [], warnings
    await page.mouse.click(saved["x"], saved["y"])
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    await page.wait_for_timeout(1000)
    print("    ✓ Saved")
    return changes, warnings


async def get_all_discussions(page: Page, course_id: str) -> list[dict]:
    """Fetch all discussion forums and topics with their description HTML."""
    for api_ver in ["1.70", "1.67", "1.68", "1.69", "1.60", "1.50"]:
        forums = await page.evaluate(f"""
            async () => {{
                try {{
                    const r = await fetch('{BRIGHTSPACE_BASE}/d2l/api/le/{api_ver}/{course_id}/discussions/forums/');
                    if (!r.ok) return null;
                    return await r.json();
                }} catch(e) {{ return null; }}
            }}
        """)
        if forums is None:
            print(f"  Discussions API v{api_ver}: no response")
            continue
        print(f"  ✓ Discussions API v{api_ver}")
        items: list[dict] = []
        for f in forums:
            desc = f.get("Description") or {}
            items.append({
                "Kind": "Forum",
                "Name": f.get("Name", ""),
                "Html": desc.get("Html") or desc.get("Text", "") or "",
            })
            topics = await page.evaluate(f"""
                async () => {{
                    try {{
                        const r = await fetch('{BRIGHTSPACE_BASE}/d2l/api/le/{api_ver}/{course_id}/discussions/forums/{f.get("ForumId")}/topics/');
                        if (!r.ok) return null;
                        return await r.json();
                    }} catch(e) {{ return null; }}
                }}
            """)
            for t in (topics or []):
                tdesc = t.get("Description") or {}
                items.append({
                    "Kind": "Topic",
                    "Name": t.get("Name", ""),
                    "Html": tdesc.get("Html") or tdesc.get("Text", "") or "",
                })
        return items
    print("  ✗ Could not fetch discussions — skipping discussion scan")
    return []


async def _open_discussion_edit(page: Page, name: str, kind: str) -> None:
    """From the discussions list, open Edit Forum / Edit Topic for the named item.
    A forum and its topic can share a name, so try each matching Actions button
    until the right Edit menu item shows up."""
    target = f"Edit {kind}"
    for _ in range(3):
        coords = await _find_action_button(page, name)
        if coords is None:
            raise Exception(f"Actions button for '{name}' not found")
        await page.mouse.click(coords["x"], coords["y"])
        await page.wait_for_timeout(500)
        edit_coords = await _find_menu_item(page, target)
        if edit_coords:
            await page.mouse.click(edit_coords["x"], edit_coords["y"])
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(800)
            return
        # wrong menu (forum vs topic) — close it and scroll past this button
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
        await page.evaluate("window.scrollBy(0, 200)")
    raise Exception(f"'{target}' menu item for '{name}' not found")


async def process_discussion(page: Page, course_id: str, item: dict, dry_run: bool) -> tuple[list[str], list[str]]:
    """Replace Moodle references in one discussion forum/topic name and description."""
    name = item["Name"]
    kind = item["Kind"]
    html = item["Html"] or ""

    new_name, name_changed = replace_moodle_in_title(name)
    new_html, changes, warnings = replace_moodle(html, name)

    if not changes and not warnings and not name_changed:
        return [], []

    print(f"\n  [{kind}] {name[:70]}")
    for line in changes:
        print(line)
    for line in warnings:
        print(line)
    if name_changed:
        print(f"  [title] '{name}' → '{new_name}'")
        changes.append(f"  [title] '{name}' → '{new_name}'")

    if dry_run:
        print("    (dry run — not saved)")
        return changes, warnings

    list_url = f"{BRIGHTSPACE_BASE}/d2l/le/{course_id}/discussions/List"
    for attempt in range(2):
        try:
            await page.goto(list_url, wait_until="domcontentloaded")
            break
        except Exception:
            if attempt == 1:
                print("    ✗ Could not load discussions list — edit manually")
                return [], warnings
            await page.wait_for_timeout(2500)
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    await page.wait_for_timeout(1000)
    try:
        await _open_discussion_edit(page, name, kind)
    except Exception as e:
        print(f"    ✗ Could not open editor: {e} — edit manually")
        return [], warnings
    await page.wait_for_timeout(2000)

    if changes and html:
        result = await _set_editor_html(page, new_html)
        if result.startswith("no editor with moodle content"):
            print("    ~ Description already clean in editor — continuing")
            changes = [c for c in changes if c.startswith("  [title]")]
        elif result != "ok":
            print(f"    ✗ Could not set description: {result} — edit manually")
            return [], warnings

    if name_changed:
        ok = await page.evaluate(_FIND_AND_SET_TITLE_JS, [name, new_name])
        print("    ✓ Title updated" if ok else "    ✗ Title input not found — rename manually")

    await page.wait_for_timeout(500)
    saved = await page.evaluate(_FIND_SAVE_AND_CLOSE_JS)
    if not saved:
        print("    ✗ Save and Close not found — save manually")
        return [], warnings
    await page.mouse.click(saved["x"], saved["y"])
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    await page.wait_for_timeout(1000)
    print("    ✓ Saved")
    return changes, warnings


async def pre_scan_topics(page: Page, topics: list[dict]) -> list[dict]:
    """Batch-fetch topic content URLs and return only those containing 'moodle'."""
    to_scan = [(t["TopicId"], t.get("Url", "")) for t in topics if t.get("Url")]
    no_url  = [t for t in topics if not t.get("Url")]

    if not to_scan:
        print("  No content URLs available — will open all topics in editor")
        return topics

    print(f"  Pre-scanning {len(to_scan)} topic(s) in batches of 10...")
    BATCH = 10
    moodle_ids: set[str] = set()
    uncertain_ids: set[str] = set()
    external_count = 0

    for i in range(0, len(to_scan), BATCH):
        batch = to_scan[i : i + BATCH]
        results = await page.evaluate("""
            async (items) => {
                const base = location.origin;
                return await Promise.all(items.map(async ([id, url]) => {
                    // External links (YouTube, PDFs, websites) are never HTML editor topics
                    if (url.startsWith('http') && !url.startsWith(base))
                        return [id, 'external'];
                    try {
                        const full = url.startsWith('http') ? url : base + url;
                        const r = await fetch(full, {credentials: 'include'});
                        if (!r.ok) return [id, null];
                        const text = await r.text();
                        return [id, /moodle/i.test(text)];
                    } catch(e) {
                        return [id, null];
                    }
                }));
            }
        """, batch)
        for topic_id, has_moodle in results:
            if has_moodle is True:
                moodle_ids.add(str(topic_id))
            elif has_moodle is None:
                uncertain_ids.add(str(topic_id))
            elif has_moodle == "external":
                external_count += 1
            # False (clean) → skip

    clean = len(to_scan) - len(moodle_ids) - len(uncertain_ids) - external_count
    print(f"  Pre-scan: {len(moodle_ids)} with Moodle, {len(uncertain_ids)} uncertain, {external_count} external links, {clean} clean")

    # keep moodle hits + uncertain (don't risk skipping) + any topics with no URL
    keep_ids = moodle_ids | uncertain_ids | {t["TopicId"] for t in no_url}
    return [t for t in topics if t["TopicId"] in keep_ids]


class _TaskLogRouter(io.TextIOBase):
    """stdout proxy that buffers writes per asyncio task so parallel tabs
    don't interleave their log lines. Unregistered tasks write through."""

    def __init__(self, real):
        self.real = real
        self.buffers: dict = {}

    def write(self, s):
        buf = self.buffers.get(asyncio.current_task())
        if buf is not None:
            buf.append(s)
        else:
            self.real.write(s)
        return len(s)

    def flush(self):
        try:
            self.real.flush()
        except Exception:
            pass


async def _process_parallel(context, course_id, items, worker_fn, dry_run, max_tabs=3):
    """Run worker_fn(page, course_id, item, dry_run) over items using up to
    max_tabs concurrent pages. Returns [(item, changes, warnings), ...]."""
    results: list = []
    if not items:
        return results

    queue: asyncio.Queue = asyncio.Queue()
    for it in items:
        queue.put_nowait(it)

    router = _TaskLogRouter(sys.stdout)
    real_stdout, sys.stdout = sys.stdout, router

    async def worker():
        page = await context.new_page()
        task = asyncio.current_task()
        try:
            while True:
                try:
                    it = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                router.buffers[task] = []
                try:
                    changes, warnings = await worker_fn(page, course_id, it, dry_run)
                    results.append((it, changes, warnings))
                except Exception as e:
                    print(f"\n  ✗ Skipped '{it['Name'][:50]}': {e}")
                finally:
                    chunk = "".join(router.buffers.pop(task, []))
                    if chunk.strip():
                        real_stdout.write(chunk if chunk.endswith("\n") else chunk + "\n")
                        router.flush()
        finally:
            try:
                await page.close()
            except Exception:
                pass

    try:
        await asyncio.gather(*[worker() for _ in range(min(max_tabs, len(items)))])
    finally:
        sys.stdout = real_stdout
    return results


def _has_moodle(item: dict) -> bool:
    hay = " ".join(str(item.get(k) or "") for k in ("Name", "Html", "Header", "Footer"))
    return bool(re.search(r"moodle", hay, re.IGNORECASE))


async def scan_course(course_url: str, dry_run: bool = False, history_fn=None) -> None:
    """Main entry point: scan all HTML topics in a course and replace Moodle references."""
    if dry_run:
        print("⚠  DRY RUN — no changes will be saved\n")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            _BS_PROFILE,
            headless=False,
            slow_mo=60,
            args=["--start-maximized"],
            no_viewport=True,
        )
        page = await context.new_page()

        await _wait_for_login(page, context)

        course_id = await _resolve_course_id(page, course_url)

        print(f"Loading course home...")
        await page.goto(f"{BRIGHTSPACE_BASE}/d2l/home/{course_id}")
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)

        if history_fn:
            try:
                history_fn(
                    await get_course_name(page) or await page.title(),
                    f"{BRIGHTSPACE_BASE}/d2l/home/{course_id}",
                )
            except Exception:
                pass

        nav_href = await page.evaluate("""
            () => {
                function walk(root) {
                    for (const el of root.querySelectorAll('d2l-menu-item')) {
                        const text = (el.getAttribute('text') || el.textContent || '').trim().toLowerCase();
                        const href = el.getAttribute('href') || '';
                        if (text === 'content' && href)
                            return new URL(href, location.origin).href;
                    }
                    for (const el of root.querySelectorAll('*')) {
                        if (el.shadowRoot) { const r = walk(el.shadowRoot); if (r) return r; }
                    }
                    return null;
                }
                return walk(document);
            }
        """)
        content_url = nav_href or f"{BRIGHTSPACE_BASE}/d2l/le/lessons/{course_id}"
        print(f"Navigating to content tab{' (from nav)' if nav_href else ' (direct URL)'}...")
        await page.goto(content_url, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=20000)
        print(f"  ✓ Settled at: {page.url}")

        print("Fetching topic list...")
        topics = await get_all_topics(page, course_id)
        print(f"{len(topics)} topic(s) found")

        print("Identifying modules to skip...")
        skip_ids = await get_skip_topic_ids(page, course_id)
        if skip_ids:
            before = len(topics)
            topics = [t for t in topics if t["TopicId"] not in skip_ids]
            print(f"  {before - len(topics)} topic(s) excluded, {len(topics)} remaining")

        all_filtered = topics[:]
        title_hit_ids = {
            t["TopicId"] for t in all_filtered
            if re.search(r"\bmoodle\b", t["Title"], re.IGNORECASE)
        }
        if title_hit_ids:
            print(f"  {len(title_hit_ids)} topic(s) with Moodle in title")

        print("Pre-scanning for Moodle references...")
        topics = await pre_scan_topics(page, all_filtered)

        prescan_ids = {t["TopicId"] for t in topics}
        title_only = [t for t in all_filtered if t["TopicId"] in title_hit_ids - prescan_ids]
        if title_only:
            print(f"  + {len(title_only)} title-only topic(s) added")
            topics += title_only

        print(f"  {len(topics)} topic(s) to open in editor")
        print(f"{'─' * 50}")

        all_changes:   list[str] = []
        all_warnings:  list[str] = []
        modified_topics: list[tuple[str, list[str]]] = []

        for topic in topics:
            if page.is_closed():
                print("\n  [RECOVERY] Page closed — opening new page...")
                try:
                    page = await context.new_page()
                    await page.goto(f"{BRIGHTSPACE_BASE}/d2l/home/{course_id}")
                    await page.wait_for_load_state("domcontentloaded")
                    await page.wait_for_timeout(2000)
                except Exception as re_err:
                    print(f"  [RECOVERY] Failed: {re_err}")
                    break

            changes, warnings = await process_topic(page, course_id, topic, dry_run)
            if changes or warnings:
                modified_topics.append((topic["Title"], changes))
            all_changes.extend(changes)
            all_warnings.extend(warnings)

        print(f"\n{'─' * 50}")
        print("Scanning assignment descriptions...")
        assignments = await get_all_assignments(page, course_id)
        flagged = [f for f in assignments if _has_moodle(f)]
        print(f"{len(assignments)} assignment(s) found, {len(flagged)} with Moodle")
        for folder, changes, warnings in await _process_parallel(
            context, course_id, flagged, process_assignment, dry_run
        ):
            if changes or warnings:
                modified_topics.append((f"[Assignment] {folder['Name']}", changes))
            all_changes.extend(changes)
            all_warnings.extend(warnings)

        print(f"\n{'─' * 50}")
        print("Scanning quiz descriptions...")
        quizzes = await get_all_quizzes(page, course_id)
        flagged = [q for q in quizzes if _has_moodle(q)]
        print(f"{len(quizzes)} quiz(zes) found, {len(flagged)} with Moodle")
        for quiz, changes, warnings in await _process_parallel(
            context, course_id, flagged, process_quiz, dry_run
        ):
            if changes or warnings:
                modified_topics.append((f"[Quiz] {quiz['Name']}", changes))
            all_changes.extend(changes)
            all_warnings.extend(warnings)

        print(f"\n{'─' * 50}")
        print("Scanning discussion descriptions...")
        discussions = await get_all_discussions(page, course_id)
        flagged = [d for d in discussions if _has_moodle(d)]
        print(f"{len(discussions)} forum(s)/topic(s) found, {len(flagged)} with Moodle")
        for item, changes, warnings in await _process_parallel(
            context, course_id, flagged, process_discussion, dry_run
        ):
            if changes or warnings:
                modified_topics.append((f"[{item['Kind']}] {item['Name']}", changes))
            all_changes.extend(changes)
            all_warnings.extend(warnings)

        verb = "would be modified" if dry_run else "modified"
        print(f"\n{'─' * 50}")
        print(f"✓  Done — {len(modified_topics)} topic(s) {verb}")

        if modified_topics:
            print(f"\nChanged topics:")
            for i, (title, changes) in enumerate(modified_topics, 1):
                print(f"  {i}. {title[:80]}")
                for c in changes:
                    print(f"    {c.strip()}")

        if all_warnings:
            print(f"\n⚠  Moodle links flagged for manual review:")
            for w in all_warnings:
                print(f"  {w.strip()}")

        # Let the last save request settle before tearing the browser down —
        # closing immediately can abort the final Save and Close mid-flight.
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)
        await context.close()
