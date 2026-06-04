from playwright.async_api import Page


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
    await page.wait_for_timeout(400)
    edit_coords = await _find_menu_item(page, "Edit Folder") or await _find_menu_item(page, "Edit Assignment")
    if edit_coords is None:
        raise Exception(f"Edit menu item for '{name}' not found")
    await page.mouse.click(edit_coords["x"], edit_coords["y"])
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(800)


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


async def open_quiz_edit(page: Page, name: str):
    """Open the Actions dropdown for a quiz and click Edit."""
    coords = await _find_action_button(page, name)
    if coords is None:
        raise Exception(f"Actions button for '{name}' not found")
    await page.mouse.click(coords["x"], coords["y"])
    await page.wait_for_timeout(400)
    edit_coords = await _find_menu_item(page, "Edit")
    if edit_coords is None:
        raise Exception(f"Edit menu item for '{name}' not found")
    await page.mouse.click(edit_coords["x"], edit_coords["y"])
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(800)
