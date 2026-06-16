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
    _save_two_pass,
)

_HERE = Path(__file__).parent.parent
if os.name == "nt":
    _USERDATA_DIR = Path(os.environ["APPDATA"]) / "BrightspaceAutomator"
else:
    _USERDATA_DIR = Path.home() / ".local" / "share" / "BrightspaceAutomator"
SESSION_FILE = str(_USERDATA_DIR / "session.json")

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
    (newTitle) => {
        try {
            const input = document
                .querySelector('d2l-activity-content-editor').shadowRoot
                .querySelector('d2l-activity-editor').shadowRoot
                .querySelector('d2l-activity-content-editor-detail').shadowRoot
                .querySelector('d2l-activity-content-file-detail').shadowRoot
                .querySelector('d2l-activity-content-editor-title').shadowRoot
                .querySelector('d2l-input-text').shadowRoot
                .querySelector('input');
            if (!input) return false;
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            setter.call(input, newTitle);
            input.dispatchEvent(new Event('input', {bubbles: true}));
            input.dispatchEvent(new Event('change', {bubbles: true}));
            return true;
        } catch(e) { return false; }
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
        ok = await edit_page.evaluate(_FIND_AND_SET_TITLE_JS, new_title)
        if ok:
            print("    ✓ Title updated")
        else:
            print("    ✗ Title input not found — rename manually")

    await edit_page.wait_for_timeout(500)
    await _save_two_pass(edit_page)
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


async def scan_course(course_url: str, dry_run: bool = False) -> None:
    """Main entry point: scan all HTML topics in a course and replace Moodle references."""
    if dry_run:
        print("⚠  DRY RUN — no changes will be saved\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=60, args=["--start-maximized"])
        context = await browser.new_context(
            storage_state=SESSION_FILE if os.path.exists(SESSION_FILE) else None,
            no_viewport=True,
        )
        page = await context.new_page()

        course_id = await _resolve_course_id(page, course_url)

        print(f"Loading course home...")
        await page.goto(f"{BRIGHTSPACE_BASE}/d2l/home/{course_id}")
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)

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
        await page.goto(content_url)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(3000)

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

        await browser.close()
