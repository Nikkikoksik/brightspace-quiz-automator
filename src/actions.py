import re

from playwright.async_api import Page


async def apply_rename_title(page: Page, current_name: str, dry_run: bool) -> None:
    """Rename quiz title if it contains 'Moodle', replacing with 'Brightspace' (case-preserving)."""
    def _replace(m):
        w = m.group(0)
        if w == w.upper(): return "BRIGHTSPACE"
        if w[0].isupper(): return "Brightspace"
        return "brightspace"

    new_name = re.sub(r"\bmoodle\b", _replace, current_name, flags=re.IGNORECASE)
    if new_name == current_name:
        return

    if dry_run:
        print(f"    Rename    : [DRY RUN] '{current_name}' → '{new_name}'")
        return

    ok = await page.evaluate("""
        (newTitle) => {
            try {
                const editor = document.querySelector('d2l-activity-quiz-editor');
                const detail = editor?.shadowRoot?.querySelector('d2l-activity-quiz-editor-detail');
                const inputText = detail?.shadowRoot?.querySelector('d2l-input-text');
                const input = inputText?.shadowRoot?.querySelector('input');
                if (!input) return false;
                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                setter.call(input, newTitle);
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.dispatchEvent(new Event('change', {bubbles: true}));
                return true;
            } catch(e) { return false; }
        }
    """, new_name)

    if ok:
        print(f"    Rename    : ✓ '{current_name}' → '{new_name}'")
    else:
        print(f"    Rename    : ✗ title input not found")


async def _set_points_if_zero(page: Page):
    """After Add to Grade Book, set points to 10 if the field shows 0 or is empty."""
    await page.evaluate("""
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


async def apply_gradebook(page: Page, dry_run: bool) -> bool | None:
    """Switch quiz from Not in Grade Book → In Grade Book. Returns True if changed, False if already set, None if not found."""
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
            return None

        div_text = await grade_btn.locator("div").first.inner_text()

        if "Not in Grade Book" in div_text:
            if dry_run:
                print("    Gradebook : [DRY RUN] Would switch to In Grade Book")
                return False
            await grade_btn.click()
            await page.wait_for_selector(
                "d2l-menu-item[text='Add to Grade Book'], li:has-text('Add to Grade Book')",
                timeout=5000,
            )
            option = page.locator(
                "d2l-menu-item[text='Add to Grade Book'], li:has-text('Add to Grade Book')"
            ).first
            await option.click()
            try:
                # Confirm the change landed. The grade button lives in shadow DOM,
                # so this MUST walk shadow roots — a flat document.querySelector
                # returns null and silently times out (~5s of dead wait per quiz).
                await page.wait_for_function("""
                    () => {
                        function find(root) {
                            for (const btn of root.querySelectorAll('button.d2l-grade-info')) {
                                const div = btn.querySelector('div');
                                if (div) return !div.textContent.includes('Not in Grade Book');
                            }
                            for (const el of root.querySelectorAll('*'))
                                if (el.shadowRoot) { const r = find(el.shadowRoot); if (r !== null) return r; }
                            return null;
                        }
                        return find(document) === true;
                    }
                """, timeout=5000)
            except Exception:
                pass
            await _set_points_if_zero(page)
            return True
        else:
            return False

    except Exception as e:
        print(f"    Gradebook : ✗ {e}")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
        return None


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


async def apply_auto_submit(page: Page, dry_run: bool, out: dict | None = None):
    """Set timer expiry action to 'Automatically submit the quiz attempt'.

    Rewritten for D2L's new quiz editor (/d2l/le/activities/edit/...), whose
    controls live in nested shadow DOMs with no stable CSS classes. Every step
    finds its target by visible text via a recursive shadow-DOM walk, then
    clicks real viewport coords — the only approach that survives this UI.

    If `out` is provided, the original (pre-change) timer radio value is stored
    in out["timer_value"] once the dialog opens — this lets the caller capture
    the undo value without a second dialog-open in read_quiz_before_state.
    """

    async def _coords_by_text(selector, text):
        """Center coords of the first visible `selector` whose text contains `text`."""
        return await page.evaluate(
            """
            ([selector, text]) => {
                const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const want = norm(text);
                function find(root) {
                    for (const el of root.querySelectorAll(selector)) {
                        if (norm(el.textContent).includes(want)) {
                            const r = el.getBoundingClientRect();
                            if (r.width > 0 && r.height > 0)
                                return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                        }
                    }
                    for (const el of root.querySelectorAll('*'))
                        if (el.shadowRoot) { const c = find(el.shadowRoot); if (c) return c; }
                    return null;
                }
                return find(document);
            }
            """,
            [selector, text],
        )

    async def _wait_coords(selector, text, timeout=10000, interval=100):
        """Poll for an element by text; return coords as soon as it's visible, else None.

        Fast on quick loads (returns the moment it appears) and patient on slow
        Brightspace loads (keeps checking up to `timeout`). No fixed sleeps.
        """
        waited = 0
        while True:
            c = await _coords_by_text(selector, text)
            if c:
                return c
            if waited >= timeout:
                return None
            await page.wait_for_timeout(interval)
            waited += interval

    async def _summary():
        """Read the Timing panel summary line (visible even while collapsed)."""
        return await page.evaluate(
            """
            () => {
                const phrases = ['submit', 'Flag attempts', 'not enforced', 'time is up'];
                function find(root) {
                    for (const el of root.querySelectorAll('div, span')) {
                        const t = (el.textContent || '').trim();
                        if (t && t.length < 60 && phrases.some(p => t.includes(p))
                            && el.getBoundingClientRect().width > 0)
                            return t;
                    }
                    for (const el of root.querySelectorAll('*')) {
                        if (el.shadowRoot) { const r = find(el.shadowRoot); if (r) return r; }
                    }
                    return null;
                }
                return find(document);
            }
            """
        )

    async def _autosubmit_checked():
        """True if the auto-submit radio is selected. Matched by value, not label
        text — radio `value` is stable across wording/locale changes."""
        return await page.evaluate(
            """
            () => {
                function find(root) {
                    for (const inp of root.querySelectorAll('input[type="radio"]'))
                        if (inp.value === 'autosubmit') return inp.checked;
                    for (const el of root.querySelectorAll('*'))
                        if (el.shadowRoot) { const r = find(el.shadowRoot); if (r !== null) return r; }
                    return null;
                }
                return find(document);
            }
            """
        )

    async def _dialog_open():
        """True while the Timer Settings dialog (heading exactly 'Timing') is visible."""
        return await page.evaluate(
            """
            () => {
                function f(r) {
                    for (const h of r.querySelectorAll('h2'))
                        if (h.textContent.trim() === 'Timing'
                            && h.getBoundingClientRect().width > 0) return true;
                    for (const el of r.querySelectorAll('*'))
                        if (el.shadowRoot && f(el.shadowRoot)) return true;
                    return false;
                }
                return f(document);
            }
            """
        )

    try:
        # 0) Already set? The panel summary is readable without opening anything.
        summary_before = await _summary()
        if summary_before and "submit" in summary_before.lower():
            return False

        # 1) Reach the Timer Settings button. Expand the panel only if it isn't
        #    already open — clicking an open panel would collapse it. Check the
        #    panel's aria-expanded state directly (instant) instead of blindly
        #    polling 1.5s for the Timer Settings button, which used to stall every
        #    quiz because the panel is normally collapsed.
        expanded = await page.evaluate("""
            () => {
                function find(root) {
                    for (const el of root.querySelectorAll('button.d2l-collapsible-panel-opener')) {
                        const t = (el.innerText || el.textContent || '');
                        if (t.includes('Timing'))
                            return el.getAttribute('aria-expanded') === 'true';
                    }
                    for (const el of root.querySelectorAll('*'))
                        if (el.shadowRoot) { const r = find(el.shadowRoot); if (r !== null) return r; }
                    return null;
                }
                return find(document);
            }
        """)
        timer = await _coords_by_text("button", "Timer Settings") if expanded else None
        if not timer:
            header = await _coords_by_text("button", "Timing & Display")
            if header:
                await page.mouse.click(header["x"], header["y"])
            timer = await _wait_coords("button", "Timer Settings", timeout=12000)
        if not timer:
            print("    Timer     : no timer configured — skipping")
            return

        # 2) Open the Timer dialog reliably. A click fired immediately after the
        #    panel expands can be swallowed mid-relayout, so confirm the dialog
        #    opened and re-click only if it's still closed (re-clicking while it's
        #    open would hit the backdrop and close it).
        opened = False
        for _ in range(3):
            if await _dialog_open():
                opened = True
                break
            await page.mouse.click(timer["x"], timer["y"])
            waited = 0
            while waited < 3000:
                if await _dialog_open():
                    opened = True
                    break
                await page.wait_for_timeout(100)
                waited += 100
            if opened:
                break
            timer = await _coords_by_text("button", "Timer Settings") or timer
        if not opened:
            print("    Timer     : ⚠ Timing dialog did not open — escaping")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
            return False

        # Wait for the OPTIONS to render — the radios appear a beat after the modal.
        opt = await _wait_coords("label", "Automatically submit", timeout=8000)
        if not opt:
            print("    Timer     : ⚠ auto-submit option didn't render — escaping")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
            return False

        # Capture the ORIGINAL radio value for undo before we change anything.
        # The dialog is open and the radios are rendered, so this is free — it
        # replaces the separate dialog-open that read_quiz_before_state used to do.
        if out is not None:
            out["timer_value"] = await page.evaluate("""
                () => {
                    function find(root) {
                        for (const el of root.querySelectorAll('input[type="radio"][name="timeLimitOption"]'))
                            if (el.checked) return el.value;
                        for (const el of root.querySelectorAll('*'))
                            if (el.shadowRoot) { const r = find(el.shadowRoot); if (r) return r; }
                        return null;
                    }
                    return find(document);
                }
            """)

        if dry_run:
            print("    Timer     : [DRY RUN] Would select auto-submit")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
            return

        # 3) Select auto-submit and CONFIRM the radio actually took before
        #    committing — otherwise OK closes the dialog on the old value.
        selected = False
        for _ in range(4):
            await _flash_click(page, opt["x"], opt["y"])
            waited = 0
            while waited < 1500:
                if await _autosubmit_checked():
                    selected = True
                    break
                await page.wait_for_timeout(75)
                waited += 75
            if selected:
                break
            opt = await _coords_by_text("label", "Automatically submit") or opt
        if not selected:
            print("    Timer     : ⚠ could not select auto-submit radio — escaping")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
            return False

        # 4) Commit by clicking OK. Enter does NOT close this dialog in the new
        #    editor (verified live) — the OK button must be clicked by coords.
        for _ in range(4):
            ok = await _find_timer_dialog_ok_coords(page) or await _find_button_coords(page, "OK")
            if ok:
                await _flash_click(page, ok["x"], ok["y"])
            else:
                await page.keyboard.press("Enter")
            await page.wait_for_timeout(500)
            if not await _dialog_open():
                break

        # 5) Wait for the dialog to close.
        try:
            await page.wait_for_function(
                "() => { const f = r => { for (const h of r.querySelectorAll('h2'))"
                " if (h.textContent.trim() === 'Timing' && h.getBoundingClientRect().width > 0) return true;"
                " for (const el of r.querySelectorAll('*')) if (el.shadowRoot && f(el.shadowRoot)) return true;"
                " return false; }; return !f(document); }",
                timeout=10000,
            )
        except Exception:
            print("    Timer     : ⚠ dialog did not close after 10s")

        # 6) Verify via the panel summary — poll, since it refreshes a beat after close.
        summary_after = None
        waited = 0
        while waited < 4000:
            summary_after = await _summary()
            if summary_after and "submit" in summary_after.lower():
                print("    Timer     : ✓ auto-submit set")
                return True
            await page.wait_for_timeout(100)
            waited += 100
        print(f"    Timer     : ✗ FAILED — summary still '{summary_after}'")
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
            const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
            const getText = el => norm([
                el.getAttribute?.('aria-label'),
                el.getAttribute?.('text'),
                el.innerText,
                el.textContent,
                el.shadowRoot?.innerText,
                el.shadowRoot?.textContent
            ].filter(Boolean).join(' '));
            const getCoords = el => {
                const target = el.shadowRoot?.querySelector('button, [role="button"]') || el;
                const r = target.getBoundingClientRect();
                if (r.width > 0 && r.height > 0)
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                return null;
            };
            function find(root) {
                for (const el of root.querySelectorAll('d2l-button, button, [role="button"]')) {
                    if (getText(el) === text) {
                        const coords = getCoords(el);
                        if (coords) return coords;
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


async def _find_timer_dialog_ok_coords(page: Page):
    """Find the OK button inside the quiz timer settings dialog."""
    return await page.evaluate("""
        () => {
            const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
            const getText = el => norm([
                el.getAttribute?.('aria-label'),
                el.getAttribute?.('text'),
                el.innerText,
                el.textContent,
                el.shadowRoot?.innerText,
                el.shadowRoot?.textContent
            ].filter(Boolean).join(' '));
            const getCoords = el => {
                const target = el.shadowRoot?.querySelector('button, [role="button"]') || el;
                const r = target.getBoundingClientRect();
                if (r.width > 0 && r.height > 0)
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2, text: getText(el) };
                return null;
            };

            function findDialog(root) {
                const dialog = root.querySelector?.('#quiz-timer-settings-dialog');
                if (dialog) return dialog;
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) {
                        const found = findDialog(el.shadowRoot);
                        if (found) return found;
                    }
                }
                return null;
            }

            const dialog = findDialog(document);
            if (!dialog) return null;

            const buttons = [...dialog.querySelectorAll('d2l-button, button, [role="button"]')]
                .map(el => ({ el, coords: getCoords(el) }))
                .filter(item => item.coords);
            const ok = buttons.find(item => item.coords.text === 'OK');
            if (ok) return ok.coords;

            const directOk = dialog.querySelector('d2l-button:nth-child(3)');
            const directCoords = directOk ? getCoords(directOk) : null;
            if (directCoords) return directCoords;

            return buttons.length ? buttons[buttons.length - 1].coords : null;
        }
    """)


async def _find_editor_footer_button_coords(
    page: Page,
    exact_text: str | None = None,
    index: int | None = None,
):
    """Find a quiz editor footer button by label, or by footer order as a fallback."""
    return await page.evaluate("""
        ([text, index]) => {
            const want = text ? text.replace(/\\s+/g, ' ').trim() : null;
            const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
            const seen = new Set();

            const getText = el => norm([
                el.getAttribute?.('aria-label'),
                el.getAttribute?.('text'),
                el.innerText,
                el.textContent,
                el.shadowRoot?.innerText,
                el.shadowRoot?.textContent
            ].filter(Boolean).join(' '));

            const getCoords = el => {
                const target = el.shadowRoot?.querySelector('button, [role="button"]') || el;
                const r = target.getBoundingClientRect();
                if (r.width > 0 && r.height > 0)
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2, text: getText(el) };
                return null;
            };

            function collectButtons(root, out) {
                for (const el of root.querySelectorAll('d2l-button, button, [role="button"]')) {
                    if (seen.has(el)) continue;
                    seen.add(el);
                    const coords = getCoords(el);
                    if (coords) out.push({ el, coords });
                }
            }

            function footerButtons(footer) {
                const out = [];
                const roots = [];
                if (footer.shadowRoot) {
                    const buttons = footer.shadowRoot.querySelector('d2l-activity-editor-buttons');
                    if (buttons?.shadowRoot) roots.push(buttons.shadowRoot);
                    roots.push(footer.shadowRoot);
                }
                roots.push(footer);
                for (const root of roots) collectButtons(root, out);
                return out;
            }

            function findFooter(root) {
                for (const footer of root.querySelectorAll('d2l-activity-editor-footer')) {
                    const buttons = footerButtons(footer);
                    if (buttons.length) return buttons;
                }
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) {
                        const buttons = findFooter(el.shadowRoot);
                        if (buttons?.length) return buttons;
                    }
                }
                return [];
            }

            const buttons = findFooter(document);
            if (want) {
                const match = buttons.find(b => b.coords.text === want);
                if (match) return match.coords;
            }
            if (Number.isInteger(index) && index >= 0 && index < buttons.length)
                return buttons[index].coords;
            return null;
        }
    """, [exact_text, index])


async def _wait_for_quiz_editor_exit(page: Page, timeout: int = 10000) -> bool:
    """Return true once Save and Close has landed back on a quiz list or editor is gone."""
    try:
        await page.wait_for_function("""
            () => {
                const url = location.href;
                if (/\\/d2l\\/lms\\/quizzing\\/(quizzing|user\\/quizzes_list|admin\\/quizzes_manage)\\.d2l/i.test(url))
                    return true;

                function hasVisibleEditor(root) {
                    for (const el of root.querySelectorAll('d2l-activity-editor, d2l-activity-quiz-editor')) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) return true;
                    }
                    for (const el of root.querySelectorAll('*')) {
                        if (el.shadowRoot && hasVisibleEditor(el.shadowRoot)) return true;
                    }
                    return false;
                }

                return !hasVisibleEditor(document);
            }
        """, timeout=timeout)
        return True
    except Exception:
        return False


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
    """Click footer Save first, then Save and Close to leave the editor."""
    if dry_run:
        print("    Save      : [DRY RUN] Would click Save, then Save and Close")
        return
    try:
        save_coords = (
            await _find_editor_footer_button_coords(page, exact_text="Save")
            or await _find_button_coords(page, "Save")
            or await _find_editor_footer_button_coords(page, index=1)
        )
        if save_coords:
            await _flash_click(page, save_coords["x"], save_coords["y"])
            await page.wait_for_timeout(1000)
        else:
            print("    Save      : Save button not found - continuing to Save and Close")

        for attempt in range(4):
            sac_coords = (
                await _find_editor_footer_button_coords(page, exact_text="Save and Close")
                or await _find_button_coords(page, "Save and Close")
                or await _find_editor_footer_button_coords(page, index=0)
            )
            if not sac_coords:
                raise Exception("Save and Close button not found")
            await _flash_click(page, sac_coords["x"], sac_coords["y"])
            if await _wait_for_quiz_editor_exit(page, timeout=8000):
                print("    Save      : saved & closed")
                return
            try:
                await page.wait_for_url(
                    lambda url: any(path in str(url) for path in (
                        "/d2l/lms/quizzing/quizzing.d2l",
                        "/d2l/lms/quizzing/user/quizzes_list.d2l",
                        "/d2l/lms/quizzing/admin/quizzes_manage.d2l",
                    )),
                    timeout=6000,
                )
                print("    Save      : ✓ saved & closed")
                return
            except Exception:
                if attempt < 3:
                    print(f"    Save      : retry {attempt + 1} - still waiting for editor to close")
        print("    Save      : did not leave quiz editor after 4 attempts")
    except Exception as e:
        print(f"    Save      : ✗ {e}")


async def apply_assignment_gradebook(page: Page, dry_run: bool) -> bool | None:
    """Switch assignment from Not in Grade Book → In Grade Book (shadow DOM aware). Returns True if changed, False if already set, None if not found."""
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
            pass

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
            return None

        print(f"    Gradebook : found button text = {repr(info.get('text','').strip()[:80])}")
        if "Not in Grade Book" not in info.get("text", ""):
            print("    Gradebook : already In Grade Book — skipping")
            return False

        if dry_run:
            print("    Gradebook : [DRY RUN] Would switch to In Grade Book")
            return False

        print("    Gradebook : Not in Grade Book → switching...")
        await _flash_click(page, info["x"], info["y"])
        await page.wait_for_selector(
            "d2l-menu-item[text='Add to Grade Book'], li:has-text('Add to Grade Book')",
            timeout=5000,
        )

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
        try:
            await page.wait_for_function("""
                () => {
                    function find(root) {
                        for (const el of root.querySelectorAll('button.d2l-grade-info, [class*="grade-info"]')) {
                            if (el.getBoundingClientRect().width > 0)
                                return !(el.innerText || el.textContent || '').includes('Not in Grade Book');
                        }
                        for (const el of root.querySelectorAll('*')) {
                            if (el.shadowRoot) { const r = find(el.shadowRoot); if (r !== undefined) return r; }
                        }
                        return false;
                    }
                    return find(document);
                }
            """, timeout=5000)
        except Exception:
            pass
        await _set_points_if_zero(page)
        print("    Gradebook : ✓ Added to Grade Book")
        return True

    except Exception as e:
        print(f"    Gradebook : ✗ {e}")
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        await page.wait_for_timeout(300)
        return None


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
                try:
                    await page.wait_for_selector("text=Timer Settings", timeout=5000)
                except Exception:
                    pass

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


async def apply_pdf_only_file_type(page: Page, dry_run: bool):
    """
    If the Allowable File Extensions dropdown is set to 'Custom File Types' (value=5),
    change it to 'PDF Only' (value=1). All other values are left alone.
    select#assignment-allowable-filetypes may live inside a shadow root.
    """
    try:
        # Expand Submission & Completion if collapsed
        sub_btn = page.locator("button.d2l-collapsible-panel-opener").filter(has_text="Submission")
        if await sub_btn.count() and await sub_btn.get_attribute("aria-expanded") == "false":
            print("    FileType  : expanding Submission & Completion...")
            await sub_btn.click()
            try:
                await page.wait_for_selector("#assignment-allowable-filetypes", timeout=5000)
            except Exception:
                pass

        result = await page.evaluate("""
            () => {
                function walk(root) {
                    const sel = root.querySelector('#assignment-allowable-filetypes');
                    if (sel) return { value: sel.value, text: sel.options[sel.selectedIndex]?.text || '' };
                    for (const el of root.querySelectorAll('*')) {
                        if (el.shadowRoot) { const r = walk(el.shadowRoot); if (r) return r; }
                    }
                    return null;
                }
                return walk(document);
            }
        """)

        if not result:
            print("    FileType  : #assignment-allowable-filetypes not found — skipping")
            return

        print(f"    FileType  : current = '{result['text']}' (value={result['value']})")

        if result["value"] != "5":
            print("    FileType  : not Custom File Types — skipping")
            return

        if dry_run:
            print("    FileType  : [DRY RUN] Would change to PDF Only")
            return

        print("    FileType  : Custom File Types → changing to PDF Only...")
        changed = await page.evaluate("""
            () => {
                function walk(root) {
                    const sel = root.querySelector('#assignment-allowable-filetypes');
                    if (sel) {
                        sel.value = '1';
                        sel.dispatchEvent(new Event('input',  { bubbles: true }));
                        sel.dispatchEvent(new Event('change', { bubbles: true }));
                        return sel.value;
                    }
                    for (const el of root.querySelectorAll('*')) {
                        if (el.shadowRoot) { const r = walk(el.shadowRoot); if (r) return r; }
                    }
                    return null;
                }
                return walk(document);
            }
        """)
        if changed == "1":
            print("    FileType  : ✓ Changed to PDF Only")
        else:
            print(f"    FileType  : ⚠ set value returned {changed!r}")

    except Exception as e:
        print(f"    FileType  : ✗ {e}")


async def read_quiz_before_state(page: Page) -> dict:
    """Read current gradebook state before making changes.

    The original timer radio value (for undo) is NOT read here anymore — it is
    captured by apply_auto_submit via its `out` dict during the dialog-open it
    already performs, which avoids opening the timer dialog twice per quiz.
    """
    result = {"gradebook": None, "timer_value": None}
    try:
        grade_btn = page.locator("button.d2l-grade-info").first
        if await grade_btn.count():
            div_text = await grade_btn.locator("div").first.inner_text()
            result["gradebook"] = "Not in Grade Book" not in div_text
    except Exception:
        pass
    return result


async def revert_gradebook(page: Page) -> bool:
    """Switch quiz from In Grade Book back to Not in Grade Book."""
    try:
        grade_btn = page.locator("button.d2l-grade-info").first
        if not await grade_btn.count():
            print("    Revert GB : grade button not found — skipping")
            return False
        div_text = await grade_btn.locator("div").first.inner_text()
        if "Not in Grade Book" in div_text:
            print("    Revert GB : already Not in Grade Book — skipping")
            return False
        await grade_btn.click()
        await page.wait_for_selector(
            "d2l-menu-item[text='Remove from Grade Book'], li:has-text('Remove from Grade Book')",
            timeout=5000,
        )
        option = page.locator(
            "d2l-menu-item[text='Remove from Grade Book'], li:has-text('Remove from Grade Book')"
        ).first
        await option.click()
        print("    Revert GB : ✓ Removed from Grade Book")
        return True
    except Exception as e:
        print(f"    Revert GB : ✗ {e}")
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        return False


async def revert_auto_submit(page: Page, original_value: str) -> bool:
    """Restore timer expiry radio to original_value."""
    try:
        timing_btn = page.locator("button.d2l-collapsible-panel-opener").filter(has_text="Timing")
        if await timing_btn.count() and await timing_btn.get_attribute("aria-expanded") == "false":
            await timing_btn.click()
        try:
            await page.wait_for_selector("text=Timer Settings", timeout=5000)
        except Exception:
            print("    Revert Timer: Timer Settings not found — skipping")
            return False
        timer_link = page.locator("text=Timer Settings").first
        if not await timer_link.count():
            return False
        await timer_link.click()
        await page.wait_for_selector("input[type='radio'][name='timeLimitOption']", timeout=15000)
        radio = page.locator(f"input[type='radio'][name='timeLimitOption'][value='{original_value}']")
        if await radio.is_checked():
            print(f"    Revert Timer: already '{original_value}' — skipping")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
            return False
        coords = await page.evaluate("""
            (val) => {
                function find(root) {
                    for (const el of root.querySelectorAll('input[type="radio"]')) {
                        if (el.value === val) {
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
        """, original_value)
        if not coords:
            print(f"    Revert Timer: ⚠ radio '{original_value}' not found")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
            return False
        await _flash_click(page, coords["x"], coords["y"])
        ok_coords = await _find_button_coords(page, "OK")
        if ok_coords:
            await _flash_click(page, ok_coords["x"], ok_coords["y"])
        else:
            await page.keyboard.press("Enter")
        await page.wait_for_timeout(500)
        print(f"    Revert Timer: ✓ restored to '{original_value}'")
        return True
    except Exception as e:
        print(f"    Revert Timer: ✗ {e}")
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        return False


async def save_assignment(page: Page, dry_run: bool):
    """Save the assignment edit page."""
    if dry_run:
        print("    Save      : [DRY RUN] Would click Save and Close")
        return
    try:
        save_coords = (
            await _find_editor_footer_button_coords(page, exact_text="Save")
            or await _find_button_coords(page, "Save")
            or await _find_editor_footer_button_coords(page, index=1)
        )
        if save_coords:
            print(f"    Save      : clicking Save at ({save_coords['x']}, {save_coords['y']})...")
            await _flash_click(page, save_coords["x"], save_coords["y"])
            print("    Save      : Save clicked ✓")
            await page.wait_for_timeout(1000)
        else:
            print("    Save      : ⚠ Save button not found — skipping intermediate save")

        for attempt in range(4):
            sac_coords = (
                await _find_editor_footer_button_coords(page, exact_text="Save and Close")
                or await _find_button_coords(page, "Save and Close")
                or await _find_editor_footer_button_coords(page, index=0)
            )
            if not sac_coords:
                raise Exception("Save and Close button not found")
            print(f"    Save      : clicking Save and Close at ({sac_coords['x']}, {sac_coords['y']})...")
            await _flash_click(page, sac_coords["x"], sac_coords["y"])
            print("    Save      : clicked — waiting for editor to close...")
            if await _wait_for_quiz_editor_exit(page, timeout=8000):
                print(f"    Save      : ✓  (landed on {page.url[-60:]})")
                return
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=6000)
                print(f"    Save      : ✓  (landed on {page.url[-60:]})")
                return
            except Exception:
                if attempt < 3:
                    print(f"    Save      : retry {attempt + 1} - still waiting for editor to close")
        print("    Save      : did not leave assignment editor after 4 attempts")
    except Exception as e:
        print(f"    Save      : ✗ {e}")
