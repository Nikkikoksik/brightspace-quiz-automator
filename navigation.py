from playwright.async_api import Page


async def get_assignment_names(page: Page) -> list[str]:
    """Read all assignment names from the assignments list page."""
    buttons = await page.locator(
        "button[aria-haspopup='true'][aria-label*='Actions for']"
    ).all()
    names = []
    for btn in buttons:
        label = await btn.get_attribute("aria-label")
        if label:
            names.append(label.replace("Actions for ", "").strip())
    return names


async def open_assignment_edit(page: Page, name: str):
    """Open the Actions dropdown for an assignment and click Edit."""
    buttons = await page.locator(
        "button[aria-haspopup='true'][aria-label*='Actions for']"
    ).all()
    btn = None
    for b in buttons:
        label = await b.get_attribute("aria-label")
        if label and name in label:
            btn = b
            break
    if btn is None:
        raise Exception(f"Actions button for '{name}' not found")
    await btn.click()
    await page.wait_for_timeout(400)
    edit = page.locator(
        "d2l-menu-item[text='Edit Folder'], d2l-menu-item[text='Edit Assignment'], "
        "li:has-text('Edit Folder'), li:has-text('Edit Assignment')"
    ).first
    await edit.click()
    await page.wait_for_load_state("networkidle")


async def get_quiz_names(page: Page) -> list[str]:
    """Read all quiz names from the quiz list page."""
    buttons = await page.locator(
        "button[aria-haspopup='true'][aria-label*='Actions for']"
    ).all()
    names = []
    for btn in buttons:
        label = await btn.get_attribute("aria-label")
        if label:
            names.append(label.replace("Actions for ", "").strip())
    return names


async def open_quiz_edit(page: Page, name: str):
    """Open the Actions dropdown for a quiz and click Edit."""
    buttons = await page.locator(
        "button[aria-haspopup='true'][aria-label*='Actions for']"
    ).all()
    btn = None
    for b in buttons:
        label = await b.get_attribute("aria-label")
        if label and name in label:
            btn = b
            break
    if btn is None:
        raise Exception(f"Actions button for '{name}' not found")
    await btn.click()
    await page.wait_for_timeout(400)
    await page.locator("d2l-menu-item[text='Edit']").first.click()
    await page.wait_for_load_state("networkidle")
