from playwright.async_api import Page


async def apply_gradebook(page: Page, dry_run: bool):
    """Switch quiz from Not in Grade Book → In Grade Book."""
    try:
        grade_btn = page.locator("button.d2l-grade-info").first

        if not await grade_btn.count():
            print("    Gradebook : not found — skipping")
            return

        div_text = await grade_btn.locator("div").first.inner_text()

        if "Not in Grade Book" in div_text:
            if dry_run:
                print("    Gradebook : [DRY RUN] Would switch to In Grade Book")
                return
            print("    Gradebook : Not in Grade Book → switching...")
            await grade_btn.click()
            await page.wait_for_selector(
                "d2l-menu-item[text='Add to Grade Book'], li:has-text('Add to Grade Book')",
                timeout=5000,
            )
            option = page.locator(
                "d2l-menu-item[text='Add to Grade Book'], li:has-text('Add to Grade Book')"
            ).first
            await option.click()
            print("    Gradebook : ✓ Added to Grade Book")
        else:
            print("    Gradebook : already In Grade Book — skipping")

    except Exception as e:
        print(f"    Gradebook : ✗ {e}")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)


async def apply_auto_submit(page: Page, dry_run: bool):
    """Set timer expiry action to 'Automatically submit the quiz attempt'."""
    try:
        timing_btn = page.locator("button.d2l-collapsible-panel-opener").filter(has_text="Timing")
        if await timing_btn.count():
            if await timing_btn.get_attribute("aria-expanded") == "false":
                await timing_btn.click()

        # Wait for Timer Settings to actually appear instead of a fixed delay
        try:
            await page.wait_for_selector("text=Timer Settings", timeout=15000)
        except Exception:
            print("    Timer     : Timer Settings link not found after 15s — skipping")
            return

        timer_link = page.locator("text=Timer Settings").first
        if not await timer_link.count():
            print("    Timer     : Timer Settings link not found — skipping")
            return

        if dry_run:
            print("    Timer     : [DRY RUN] Would open Timer Settings and select auto-submit")
            return

        print("    Timer     : opening Timer Settings...")
        await timer_link.click()
        await page.wait_for_selector(
            "input[type='radio'][name='timeLimitOption'][value='autosubmit']",
            timeout=15000,
        )
        await page.locator(
            "input[type='radio'][name='timeLimitOption'][value='autosubmit']"
        ).click()

        await page.wait_for_timeout(400)
        coords = await page.evaluate("""
            () => {
                function find(root) {
                    for (const el of root.querySelectorAll('d2l-button[slot="footer"]')) {
                        if (el.textContent.trim() === 'OK') {
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
            }
        """)
        if not coords:
            raise Exception("OK button not found in shadow DOM")
        await page.mouse.click(coords["x"], coords["y"])
        await page.wait_for_function("""
            () => {
                function hasOk(root) {
                    for (const el of root.querySelectorAll('d2l-button[slot="footer"]')) {
                        if (el.textContent.trim() === 'OK' && el.getBoundingClientRect().width > 0)
                            return true;
                    }
                    for (const el of root.querySelectorAll('*')) {
                        if (el.shadowRoot && hasOk(el.shadowRoot)) return true;
                    }
                    return false;
                }
                return !hasOk(document);
            }
        """, timeout=8000)
        print("    Timer     : ✓ auto-submit selected")

    except Exception as e:
        print(f"    Timer     : ✗ {e}")
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass


async def save_quiz(page: Page, dry_run: bool):
    """Click Save and Close, wait for the page to settle."""
    if dry_run:
        print("    Save      : [DRY RUN] Would click Save and Close")
        return
    try:
        coords = await page.evaluate("""
            () => {
                function find(root) {
                    for (const el of root.querySelectorAll('button, d2l-button')) {
                        const t = el.textContent.trim();
                        if (t === 'Save and Close' || t === 'Save') {
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
            }
        """)
        if not coords:
            raise Exception("Save button not found in shadow DOM")
        await page.mouse.click(coords["x"], coords["y"])
        await page.wait_for_load_state("networkidle", timeout=12000)
        print("    Save      : ✓")
    except Exception as e:
        print(f"    Save      : ✗ {e}")


async def apply_assignment_gradebook(page: Page, dry_run: bool):
    """Switch assignment from Not in Grade Book → In Grade Book (shadow DOM aware)."""
    try:
        await page.wait_for_timeout(800)

        info = await page.evaluate("""
            () => {
                function find(root) {
                    for (const el of root.querySelectorAll('button.d2l-grade-info, button[class*="grade-info"]')) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0)
                            return { x: r.left + r.width / 2, y: r.top + r.height / 2,
                                     text: el.innerText || el.textContent || '' };
                    }
                    for (const el of root.querySelectorAll('*')) {
                        if (el.shadowRoot) { const c = find(el.shadowRoot); if (c) return c; }
                    }
                    return null;
                }
                return find(document);
            }
        """)

        if not info:
            print("    Gradebook : grade info button not found in DOM/shadow DOM — skipping")
            return

        print(f"    Gradebook : found button text = {repr(info.get('text','').strip()[:80])}")
        if "Not in Grade Book" not in info.get("text", ""):
            print("    Gradebook : already In Grade Book — skipping")
            return

        if dry_run:
            print("    Gradebook : [DRY RUN] Would switch to In Grade Book")
            return

        print("    Gradebook : Not in Grade Book → switching...")
        await page.mouse.click(info["x"], info["y"])
        await page.wait_for_timeout(600)

        option = await page.evaluate("""
            () => {
                function find(root) {
                    for (const el of root.querySelectorAll('d2l-menu-item, li, a, button')) {
                        const t = (el.getAttribute('text') || el.textContent || '').trim();
                        if (t === 'Add to Grade Book' || t.startsWith('Add to Grade Book')) {
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
            }
        """)

        if not option:
            raise Exception("'Add to Grade Book' menu item not found after clicking grade button")

        await page.mouse.click(option["x"], option["y"])
        await page.wait_for_timeout(400)
        print("    Gradebook : ✓ Added to Grade Book")

    except Exception as e:
        print(f"    Gradebook : ✗ {e}")
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        await page.wait_for_timeout(300)


async def save_assignment(page: Page, dry_run: bool):
    """Save the assignment edit page."""
    if dry_run:
        print("    Save      : [DRY RUN] Would click Save and Close")
        return
    try:
        coords = await page.evaluate("""
            () => {
                function find(root) {
                    for (const el of root.querySelectorAll('button, d2l-button')) {
                        const t = el.textContent.trim();
                        if (t === 'Save and Close' || t === 'Save') {
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
            }
        """)
        if not coords:
            raise Exception("Save button not found in shadow DOM")
        await page.mouse.click(coords["x"], coords["y"])
        await page.wait_for_load_state("networkidle", timeout=12000)
        print("    Save      : ✓")
    except Exception as e:
        print(f"    Save      : ✗ {e}")
