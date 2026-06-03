from playwright.async_api import Page


async def _find_action_button(page: Page, name: str):
    """Find the Actions button for an item, scrolling down if needed."""
    for _ in range(5):
        buttons = await page.locator(
            "button[aria-haspopup='true'][aria-label*='Actions for']"
        ).all()
        for b in buttons:
            label = await b.get_attribute("aria-label")
            if label and name in label:
                return b
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
    btn = await _find_action_button(page, name)
    if btn is None:
        raise Exception(f"Actions button for '{name}' not found")
    await btn.click()
    await page.wait_for_timeout(400)
    edit = page.locator(
        "d2l-menu-item[text='Edit Folder'], d2l-menu-item[text='Edit Assignment'], "
        "li:has-text('Edit Folder'), li:has-text('Edit Assignment')"
    ).first
    await edit.click()
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
    btn = await _find_action_button(page, name)
    if btn is None:
        raise Exception(f"Actions button for '{name}' not found")
    await btn.click()
    await page.wait_for_timeout(400)
    await page.locator("d2l-menu-item[text='Edit']").first.click()
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(800)
