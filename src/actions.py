from playwright.async_api import Page


async def _set_points_if_zero(page: Page):
    """After Add to Grade Book, set points to 10 if the field shows 0 or is empty."""
    fixed = await page.evaluate("""
        () => {
            function fix(root) {
                for (const inp of root.querySelectorAll('input[type="number"]')) {
                    const r = inp.getBoundingClientRect();
                    if (r.width > 0 && (inp.value === '0' || inp.value === '')) {
                        inp.value = '10';
                        inp.dispatchEvent(new Event('input',  { bubbles: true }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                }
                // also handle d2l-input-number web component
                for (const el of root.querySelectorAll('d2l-input-number')) {
                    const r = el.getBoundingClientRect();
                    const val = parseFloat(el.getAttribute('value') || el.value || '0');
                    if (r.width > 0 && (isNaN(val) || val === 0)) {
                        el.setAttribute('value', '10');
                        if (el.shadowRoot) {
                            const inner = el.shadowRoot.querySelector('input');
                            if (inner) {
                                inner.value = '10';
                                inner.dispatchEvent(new Event('input',  { bubbles: true }));
                                inner.dispatchEvent(new Event('change', { bubbles: true }));
                            }
                        }
                        return true;
                    }
                }
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) { if (fix(el.shadowRoot)) return true; }
                }
                return false;
            }
            return fix(document);
        }
    """)
    if fixed:
        print("    Gradebook : set points to 10 (was 0)")


async def apply_gradebook(page: Page, dry_run: bool):
    """Switch quiz from Not in Grade Book → In Grade Book."""
    try:
        try:
            await page.wait_for_function("""
                () => {
                    function find(root) {
                        for (const el of root.querySelectorAll('button.d2l-grade-info, [class*="grade-info"]')) {
                            if (el.getBoundingClientRect().width > 0) return true;
                        }
                        for (const el of root.querySelectorAll('*')) {
                            if (el.shadowRoot && find(el.shadowRoot)) return true;
                        }
                        return false;
                    }
                    return find(document);
                }
            """, timeout=30000)
        except Exception:
            pass

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
            await page.wait_for_timeout(800)
            await _set_points_if_zero(page)
            print("    Gradebook : ✓ Added to Grade Book")
        else:
            print("    Gradebook : already In Grade Book — skipping")

    except Exception as e:
        print(f"    Gradebook : ✗ {e}")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)


async def _read_timing_summary(page: Page) -> str | None:
    """Read the timing enforcement text from the quiz edit page summary.
    Looks for div.margin-top-8 whose text is timing-related (submit/enforced/minutes).
    Walks all shadow roots since the div lives inside the timing panel's shadow DOM.
    """
    return await page.evaluate("""
        () => {
            function find(root) {
                for (const div of root.querySelectorAll('div.margin-top-8')) {
                    const t = div.textContent.trim();
                    if (t && (t.includes('submit') || t.includes('enforced') || t.includes('minutes')))
                        return t;
                }
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) { const r = find(el.shadowRoot); if (r) return r; }
                }
                return null;
            }
            return find(document);
        }
    """)


async def apply_auto_submit(page: Page, dry_run: bool):
    """Set timer expiry action to 'Automatically submit the quiz attempt'."""
    try:
        # Wait for the editor to render the Timing section
        try:
            await page.wait_for_selector(
                "button.d2l-collapsible-panel-opener", timeout=15000
            )
        except Exception:
            pass

        # Wait for Timer Settings link — if absent, quiz has no timer
        try:
            await page.wait_for_selector("text=Timer Settings", timeout=5000)
        except Exception:
            print("    Timer     : no timer configured — skipping")
            return

        timer_link = page.locator("text=Timer Settings").first
        if not await timer_link.count():
            print("    Timer     : no timer configured — skipping")
            return

        print("    Timer     : opening Timer Settings...")
        await timer_link.click()
        await page.wait_for_selector(
            "input[type='radio'][name='timeLimitOption'][value='autosubmit']",
            timeout=30000,
        )

        radio = page.locator("input[type='radio'][name='timeLimitOption'][value='autosubmit']")
        if await radio.is_checked():
            print("    Timer     : already auto-submit — skipping")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
            return True

        if dry_run:
            print("    Timer     : [DRY RUN] Would select auto-submit")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
            return

        # Find radio coordinates for a real pointer-event click
        print("    Timer     : finding radio button coords...")
        radio_coords = await page.evaluate("""
            () => {
                function labelOf(el, root) {
                    const p = el.closest('label');
                    if (p) return p.textContent.trim();
                    if (el.id) {
                        const lbl = root.querySelector(`label[for="${el.id}"]`);
                        if (lbl) return lbl.textContent.trim();
                    }
                    return el.nextElementSibling?.textContent?.trim() || '';
                }
                function find(root) {
                    for (const el of root.querySelectorAll('input[type="radio"]')) {
                        const lbl = labelOf(el, root);
                        if (lbl.toLowerCase().includes('automatically submit') || el.value === 'autosubmit') {
                            const r = el.getBoundingClientRect();
                            if (r.width > 0) return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: lbl };
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
        if not radio_coords:
            print("    Timer     : ⚠ autosubmit radio not found — skipping")
            return
        print(f"    Timer     : clicking radio '{radio_coords.get('label', 'autosubmit')}'...")
        await _flash_click(page, radio_coords["x"], radio_coords["y"])
        await page.wait_for_timeout(600)
        radio_state = await radio.is_checked()
        print(f"    Timer     : radio checked = {radio_state}")

        if not radio_state:
            # Coordinate click missed — fall back to Playwright locator click
            print("    Timer     : coord click missed — trying locator click...")
            try:
                await radio.scroll_into_view_if_needed()
                await radio.click()
                await page.wait_for_timeout(400)
                radio_state = await radio.is_checked()
                print(f"    Timer     : radio checked (locator) = {radio_state}")
            except Exception as e:
                print(f"    Timer     : locator click failed: {e}")

        if not radio_state:
            print("    Timer     : ⚠ could not check radio — escaping dialog")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
            return False

        # Click the OK button directly by coordinates (more reliable than Enter key)
        ok_coords = await _find_button_coords(page, "OK")
        if ok_coords:
            print(f"    Timer     : clicking OK at ({ok_coords['x']:.0f}, {ok_coords['y']:.0f})...")
            await _flash_click(page, ok_coords["x"], ok_coords["y"])
        else:
            print("    Timer     : OK button not found — pressing Enter as fallback")
            await page.keyboard.press("Enter")
        print("    Timer     : waiting for dialog to close...")

        try:
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
            """, timeout=10000)
            print("    Timer     : dialog closed ✓")
        except Exception:
            print("    Timer     : ⚠ dialog did not close after 10s — OK click may have missed")

        print("    Timer     : waiting for API to settle...")
        await page.wait_for_timeout(1000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await page.wait_for_timeout(800)
        print("    Timer     : network idle ✓")
        summary_after = await _read_timing_summary(page)
        print(f"    Timer     : summary after OK = '{summary_after}'")

        if summary_after == "Auto-submit when time is up":
            return True

        if summary_after != "Auto-submit when time is up":
            print("    Timer     : ⚠ summary did not update — retrying once...")
            await timer_link.click()
            await page.wait_for_selector(
                "input[type='radio'][name='timeLimitOption'][value='autosubmit']",
                timeout=15000,
            )
            retry_radio_coords = await page.evaluate("""
                () => {
                    function find(root) {
                        for (const el of root.querySelectorAll('input[type="radio"]')) {
                            if (el.value === 'autosubmit' ||
                                (el.closest('label') || {}).textContent?.toLowerCase().includes('automatically submit')) {
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
            if retry_radio_coords:
                await _flash_click(page, retry_radio_coords["x"], retry_radio_coords["y"])
            await page.wait_for_timeout(600)
            retry_radio_state = await radio.is_checked()
            if not retry_radio_state:
                print("    Timer     : retry coord click missed — trying locator click...")
                try:
                    await radio.scroll_into_view_if_needed()
                    await radio.click()
                    await page.wait_for_timeout(400)
                    retry_radio_state = await radio.is_checked()
                    print(f"    Timer     : retry radio checked (locator) = {retry_radio_state}")
                except Exception as e:
                    print(f"    Timer     : retry locator click failed: {e}")
            if not retry_radio_state:
                print("    Timer     : ⚠ retry could not check radio — escaping")
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(400)
                return False
            retry_ok_coords = await _find_button_coords(page, "OK")
            if retry_ok_coords:
                print(f"    Timer     : retry — clicking OK at ({retry_ok_coords['x']:.0f}, {retry_ok_coords['y']:.0f})...")
                await _flash_click(page, retry_ok_coords["x"], retry_ok_coords["y"])
            else:
                await page.keyboard.press("Enter")
            await page.wait_for_timeout(1500)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            summary_retry = await _read_timing_summary(page)
            if summary_retry == "Auto-submit when time is up":
                print("    Timer     : ✓ retry succeeded")
                return True
            else:
                print(f"    Timer     : ✗ FAILED — still '{summary_retry}' after retry")
                return False

    except Exception as e:
        print(f"    Timer     : ✗ {e}")
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass


async def _find_button_coords(page: Page, exact_text: str):
    """Find a d2l-button or button by exact text, piercing shadow roots for real coords."""
    return await page.evaluate("""
        (text) => {
            function find(root) {
                for (const el of root.querySelectorAll('d2l-button, button')) {
                    if (el.textContent.trim() === text) {
                        const target = el.shadowRoot ? el.shadowRoot.querySelector('button') : el;
                        if (target) {
                            const r = target.getBoundingClientRect();
                            if (r.width > 0) return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
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
    """, exact_text)


async def _flash_click(page: Page, x: float, y: float):
    """Highlight the element at (x, y) green, pause briefly, then click."""
    await page.evaluate("""
        ([x, y]) => {
            const el = document.elementFromPoint(x, y);
            if (!el) return;
            const orig = el.style.cssText;
            el.style.outline = '3px solid #00cc88';
            el.style.outlineOffset = '2px';
            el.style.boxShadow = '0 0 10px rgba(0,204,136,0.6)';
            setTimeout(() => { el.style.cssText = orig; }, 600);
        }
    """, [x, y])
    await page.wait_for_timeout(200)
    await page.mouse.click(x, y)


async def save_quiz(page: Page, dry_run: bool):
    """Click Save (commits changes), then Save and Close (exits editor)."""
    if dry_run:
        print("    Save      : [DRY RUN] Would click Save then Save and Close")
        return
    try:
        save_coords = await _find_button_coords(page, "Save")
        if save_coords:
            print(f"    Save      : clicking Save at ({save_coords['x']}, {save_coords['y']})...")
            await _flash_click(page, save_coords["x"], save_coords["y"])
            await page.wait_for_timeout(1500)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            await page.wait_for_timeout(800)
            print("    Save      : Save clicked ✓")
        else:
            print("    Save      : ⚠ Save button not found — skipping intermediate save")

        sac_coords = await _find_button_coords(page, "Save and Close")
        if not sac_coords:
            raise Exception("Save and Close button not found")
        print(f"    Save      : clicking Save and Close at ({sac_coords['x']}, {sac_coords['y']})...")
        await _flash_click(page, sac_coords["x"], sac_coords["y"])
        print("    Save      : clicked — waiting for navigation...")
        await page.wait_for_load_state("domcontentloaded", timeout=12000)
        print(f"    Save      : ✓  (landed on {page.url[-60:]})")
    except Exception as e:
        print(f"    Save      : ✗ {e}")


async def apply_assignment_gradebook(page: Page, dry_run: bool):
    """Switch assignment from Not in Grade Book → In Grade Book (shadow DOM aware)."""
    try:
        try:
            await page.wait_for_function("""
                () => {
                    function find(root) {
                        for (const el of root.querySelectorAll('button.d2l-grade-info, button[class*="grade-info"], [class*="grade-info"], button, a')) {
                            const t = el.innerText || el.textContent || '';
                            if (t.includes('Grade Book') || el.classList.toString().includes('grade')) {
                                if (el.getBoundingClientRect().width > 0) return true;
                            }
                        }
                        for (const el of root.querySelectorAll('*')) {
                            if (el.shadowRoot) { const r = find(el.shadowRoot); if (r) return r; }
                        }
                        return false;
                    }
                    return find(document);
                }
            """, timeout=20000)
        except Exception:
            await page.wait_for_timeout(1500)

        info = await page.evaluate("""
            () => {
                function find(root) {
                    // Search by class first
                    for (const el of root.querySelectorAll('button.d2l-grade-info, button[class*="grade-info"], [class*="grade-info"]')) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0)
                            return { x: r.left + r.width / 2, y: r.top + r.height / 2,
                                     text: el.innerText || el.textContent || '' };
                    }
                    // Fall back: any visible element whose text contains "Not in Grade Book"
                    for (const el of root.querySelectorAll('button, a, [role="button"], d2l-button, select')) {
                        const t = el.innerText || el.textContent || '';
                        if (t.includes('Not in Grade Book')) {
                            const r = el.getBoundingClientRect();
                            if (r.width > 0)
                                return { x: r.left + r.width / 2, y: r.top + r.height / 2, text: t };
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
        await _flash_click(page, info["x"], info["y"])
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

        await _flash_click(page, option["x"], option["y"])
        await page.wait_for_timeout(800)
        await _set_points_if_zero(page)
        print("    Gradebook : ✓ Added to Grade Book")

    except Exception as e:
        print(f"    Gradebook : ✗ {e}")
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        await page.wait_for_timeout(300)


async def verify_quiz_settings(page: Page) -> dict:
    """
    Read current quiz settings without changing anything.
    Returns {"gradebook": True/False/None, "auto_submit": True/False/None}
    None means the element wasn't found (no timer configured, etc.)
    """
    result = {"gradebook": None, "auto_submit": None}

    # Gradebook status
    try:
        grade_btn = page.locator("button.d2l-grade-info").first
        if await grade_btn.count():
            div_text = await grade_btn.locator("div").first.inner_text()
            result["gradebook"] = "Not in Grade Book" not in div_text
    except Exception:
        pass

    # Auto-submit timer status
    try:
        timing_btn = page.locator("button.d2l-collapsible-panel-opener").filter(has_text="Timing")
        if await timing_btn.count():
            if await timing_btn.get_attribute("aria-expanded") == "false":
                await timing_btn.click()
                await page.wait_for_timeout(600)

        timer_link = page.locator("text=Timer Settings").first
        if await timer_link.count():
            await timer_link.click()
            await page.wait_for_selector(
                "input[type='radio'][name='timeLimitOption']", timeout=10000
            )
            radio = page.locator("input[type='radio'][name='timeLimitOption'][value='autosubmit']")
            result["auto_submit"] = await radio.is_checked()
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
        else:
            result["auto_submit"] = None  # no timer on this quiz
    except Exception:
        pass

    return result


async def save_assignment(page: Page, dry_run: bool):
    """Save the assignment edit page."""
    if dry_run:
        print("    Save      : [DRY RUN] Would click Save and Close")
        return
    try:
        save_coords = await _find_button_coords(page, "Save")
        if save_coords:
            print(f"    Save      : clicking Save at ({save_coords['x']}, {save_coords['y']})...")
            await _flash_click(page, save_coords["x"], save_coords["y"])
            await page.wait_for_timeout(1500)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            await page.wait_for_timeout(800)
            print("    Save      : Save clicked ✓")
        else:
            print("    Save      : ⚠ Save button not found — skipping intermediate save")

        sac_coords = await _find_button_coords(page, "Save and Close")
        if not sac_coords:
            raise Exception("Save and Close button not found")
        print(f"    Save      : clicking Save and Close at ({sac_coords['x']}, {sac_coords['y']})...")
        await _flash_click(page, sac_coords["x"], sac_coords["y"])
        print("    Save      : clicked — waiting for navigation...")
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        print(f"    Save      : ✓  (landed on {page.url[-60:]})")
    except Exception as e:
        print(f"    Save      : ✗ {e}")
