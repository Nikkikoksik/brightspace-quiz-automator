from playwright.async_api import Page


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
    btn = page.locator(
        f"button[aria-haspopup='true'][aria-label*='Actions for {name}']"
    ).first
    await btn.click()
    await page.wait_for_timeout(400)
    await page.locator("d2l-menu-item[text='Edit']").first.click()
    await page.wait_for_load_state("networkidle")
