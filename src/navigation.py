import re
from urllib.parse import urlparse, parse_qs

from playwright.async_api import Page

BS_BASE = "https://learn.okanagancollege.ca"


def _extract_course_id(url: str) -> str:
    """Extract Brightspace org-unit ID from any course URL."""
    # ?ou=XXXXX or &ou=XXXXX
    qs = parse_qs(urlparse(url).query)
    if "ou" in qs:
        return qs["ou"][0]
    # /d2l/home/XXXXX
    m = re.search(r"/d2l/home/(\d+)", url)
    if m:
        return m.group(1)
    raise ValueError(f"Cannot extract course ID from URL: {url}")


def resolve_quiz_url(url: str) -> str:
    """Return the quiz list URL for any Brightspace course URL."""
    if "quizzes_list" in url:
        return url
    ou = _extract_course_id(url)
    return f"{BS_BASE}/d2l/lms/quizzing/user/quizzes_list.d2l?ou={ou}"


def resolve_assignment_url(url: str) -> str:
    """Return the assignment list URL for any Brightspace course URL."""
    if "folders_list" in url:
        return url
    ou = _extract_course_id(url)
    return f"{BS_BASE}/d2l/lms/dropbox/user/folders_list.d2l?ou={ou}"


async def discover_course_urls(page: Page, course_url: str) -> dict:
    """Navigate to a course page and extract quiz/assignment URLs from the nav shadow DOM."""
    try:
        await page.goto(course_url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)

    found = await page.evaluate("""
        () => {
            function walk(root) {
                const result = {};
                for (const el of root.querySelectorAll('d2l-menu-item')) {
                    const text = (el.getAttribute('text') || '').toLowerCase().trim();
                    const href = el.getAttribute('href') || '';
                    if (href) {
                        const abs = new URL(href, location.origin).href;
                        if (text === 'quizzes')     result.quizzes     = abs;
                        if (text === 'assignments') result.assignments = abs;
                    }
                }
                for (const a of root.querySelectorAll('a[href]')) {
                    const text = a.textContent.trim().toLowerCase();
                    if (text === 'quizzes'     && !result.quizzes)     result.quizzes     = a.href;
                    if (text === 'assignments' && !result.assignments) result.assignments = a.href;
                }
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) {
                        const sub = walk(el.shadowRoot);
                        if (!result.quizzes     && sub.quizzes)     result.quizzes     = sub.quizzes;
                        if (!result.assignments && sub.assignments) result.assignments = sub.assignments;
                    }
                }
                return result;
            }
            return walk(document);
        }
    """)

    if not found.get("quizzes"):
        try:
            found["quizzes"] = resolve_quiz_url(course_url)
        except ValueError:
            pass
    if not found.get("assignments"):
        try:
            found["assignments"] = resolve_assignment_url(course_url)
        except ValueError:
            pass

    return found


async def _find_menu_item(page: Page, text: str) -> dict | None:
    """Find a d2l-menu-item by its text attribute, walking shadow DOM. Returns {x, y}."""
    for _ in range(8):
        coords = await page.evaluate(
            """(text) => {
                function find(root) {
                    for (const el of root.querySelectorAll('d2l-menu-item')) {
                        const t = (el.getAttribute('text') || el.textContent || '').trim();
                        if (t === text) {
                            const r = el.getBoundingClientRect();
                            if (r.width > 0) return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                        }
                    }
                    for (const el of root.querySelectorAll('*')) {
                        if (el.shadowRoot) { const c = find(el.shadowRoot); if (c) return c; }
                    }
                    return null;
                }
                return find(document);
            }""",
            text,
        )
        if coords:
            return coords
        await page.wait_for_timeout(200)
    return None


async def _find_action_button(page: Page, name: str) -> dict | None:
    """Find the Actions button for an item, scrolling down if needed. Returns {x, y}."""
    for _ in range(5):
        # Scroll the button into center of viewport first
        found = await page.evaluate(
            """(name) => {
                function find(root) {
                    for (const btn of root.querySelectorAll('button[aria-haspopup="true"]')) {
                        const label = btn.getAttribute('aria-label') || '';
                        if (label.includes('Actions for') && label.includes(name)) {
                            btn.scrollIntoView({ block: 'center', behavior: 'instant' });
                            return true;
                        }
                    }
                    for (const el of root.querySelectorAll('*')) {
                        if (el.shadowRoot) { const c = find(el.shadowRoot); if (c) return c; }
                    }
                    return false;
                }
                return find(document);
            }""",
            name,
        )
        if found:
            await page.wait_for_timeout(200)
            coords = await page.evaluate(
                """(name) => {
                    function find(root) {
                        for (const btn of root.querySelectorAll('button[aria-haspopup="true"]')) {
                            const label = btn.getAttribute('aria-label') || '';
                            if (label.includes('Actions for') && label.includes(name)) {
                                const r = btn.getBoundingClientRect();
                                if (r.width > 0) return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
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
                return coords
        await page.evaluate("window.scrollBy(0, 800)")
        await page.wait_for_timeout(400)
    return None


async def set_per_page_200(page: Page):
    """Select 200-per-page in the list page dropdown so all items load at once."""
    selected = await page.evaluate("""
        () => {
            for (const sel of document.querySelectorAll('select')) {
                for (const opt of sel.options) {
                    if (opt.value === '200') {
                        sel.value = '200';
                        sel.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                }
            }
            return false;
        }
    """)
    if selected:
        await page.wait_for_timeout(1500)


async def get_assignment_names(page: Page) -> list[str]:
    """Read all assignment names from the assignments list page."""
    await page.evaluate("window.scrollTo(0, 0)")
    names = []
    seen = set()
    prev_count = -1
    while True:
        buttons = await page.locator(
            "button[aria-haspopup='true'][aria-label*='Actions for']"
        ).all()
        for btn in buttons:
            label = await btn.get_attribute("aria-label")
            if label and label not in seen:
                seen.add(label)
                names.append(label.replace("Actions for ", "").strip())
        if len(names) == prev_count:
            break
        prev_count = len(names)
        await page.evaluate("window.scrollBy(0, 800)")
        await page.wait_for_timeout(300)
    await page.evaluate("window.scrollTo(0, 0)")
    return names


async def open_assignment_edit(page: Page, name: str):
    """Open the Actions dropdown for an assignment and click Edit."""
    coords = await _find_action_button(page, name)
    if coords is None:
        raise Exception(f"Actions button for '{name}' not found")
    await page.mouse.click(coords["x"], coords["y"])
    edit_coords = await _find_menu_item(page, "Edit Folder") or await _find_menu_item(page, "Edit Assignment")
    if edit_coords is None:
        raise Exception(f"Edit menu item for '{name}' not found")
    await page.mouse.click(edit_coords["x"], edit_coords["y"])
    await page.wait_for_load_state("domcontentloaded")
    try:
        await page.wait_for_selector(
            "button.d2l-grade-info, button[class*='grade-info'], button.d2l-collapsible-panel-opener",
            timeout=15000,
        )
    except Exception:
        pass


async def get_quiz_names(page: Page) -> list[str]:
    """Read all quiz names from the quiz list page."""
    await page.evaluate("window.scrollTo(0, 0)")
    names = []
    seen = set()
    prev_count = -1
    while True:
        buttons = await page.locator(
            "button[aria-haspopup='true'][aria-label*='Actions for']"
        ).all()
        for btn in buttons:
            label = await btn.get_attribute("aria-label")
            if label and label not in seen:
                seen.add(label)
                names.append(label.replace("Actions for ", "").strip())
        if len(names) == prev_count:
            break
        prev_count = len(names)
        await page.evaluate("window.scrollBy(0, 800)")
        await page.wait_for_timeout(300)
    await page.evaluate("window.scrollTo(0, 0)")
    return names


async def _dump_menu_items(page: Page) -> list[str]:
    """Return all d2l-menu-item text values found in the DOM (for diagnostics)."""
    return await page.evaluate("""() => {
        const results = [];
        function find(root) {
            for (const el of root.querySelectorAll('d2l-menu-item')) {
                const t = (el.getAttribute('text') || el.textContent || '').trim();
                const r = el.getBoundingClientRect();
                results.push(`"${t}" (visible=${r.width > 0})`);
            }
            for (const el of root.querySelectorAll('*')) {
                if (el.shadowRoot) find(el.shadowRoot);
            }
        }
        find(document);
        return results;
    }""")


async def open_quiz_edit(page: Page, name: str):
    """Open the Actions dropdown for a quiz and click Edit."""
    coords = await _find_action_button(page, name)
    if coords is None:
        raise Exception(f"Actions button for '{name}' not found")
    await page.mouse.click(coords["x"], coords["y"])
    edit_coords = await _find_menu_item(page, "Edit")
    if edit_coords is None:
        items = await _dump_menu_items(page)
        print(f"  DEBUG menu items found: {items}")
        raise Exception(f"Edit menu item for '{name}' not found")
    await page.mouse.click(edit_coords["x"], edit_coords["y"])
    await page.wait_for_load_state("domcontentloaded")
    try:
        await page.wait_for_selector(
            "button.d2l-grade-info, button.d2l-collapsible-panel-opener",
            timeout=15000,
        )
    except Exception:
        pass


async def harvest_quiz_edit_urls(page: Page, quiz_url: str) -> list[tuple[str, str]]:
    """Walk shadow DOM on quiz list to extract (name, edit_url) pairs without clicking Actions menus.
    Returns empty list if hrefs are null (lazy-rendered) — caller falls back to sequential."""
    try:
        await page.goto(quiz_url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    try:
        await page.wait_for_selector(
            "button[aria-haspopup='true'][aria-label*='Actions for']", timeout=30000
        )
    except Exception:
        return []

    await set_per_page_200(page)

    # Scroll to load all items (same pattern as get_quiz_names)
    prev_count = -1
    while True:
        count = await page.locator(
            "button[aria-haspopup='true'][aria-label*='Actions for']"
        ).count()
        if count == prev_count:
            break
        prev_count = count
        await page.evaluate("window.scrollBy(0, 2000)")
        await page.wait_for_timeout(300)
    await page.evaluate("window.scrollTo(0, 0)")

    result = await page.evaluate("""
        () => {
            const names = [];
            const hrefs = [];
            function walkNames(root) {
                for (const btn of root.querySelectorAll('button[aria-haspopup="true"]')) {
                    const label = btn.getAttribute('aria-label') || '';
                    if (label.startsWith('Actions for '))
                        names.push(label.replace('Actions for ', '').trim());
                }
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) walkNames(el.shadowRoot);
                }
            }
            function walkHrefs(root) {
                for (const el of root.querySelectorAll('d2l-menu-item')) {
                    if ((el.getAttribute('text') || '').trim() === 'Edit') {
                        const href = el.getAttribute('href') || '';
                        if (href) hrefs.push(new URL(href, location.origin).href);
                    }
                }
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) walkHrefs(el.shadowRoot);
                }
            }
            walkNames(document);
            walkHrefs(document);
            return { names, hrefs };
        }
    """)

    names = result.get("names", [])
    hrefs = result.get("hrefs", [])
    if hrefs and len(names) == len(hrefs):
        return list(zip(names, hrefs))
    return []
