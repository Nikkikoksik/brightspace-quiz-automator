import asyncio
import json as _json
import os
import re as _re
import sys
import threading
from urllib.parse import urlparse

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLineEdit, QPushButton, QWidget

from gui.constants import SESSION_FILE_GUI
from gui.telemetry import _sentry_capture, _sentry_context
from gui.theme import T, _btn, _entry_style


class StagingPanelMixin:

    def _build_staging_panel(self, parent: QWidget):
        layout = self._panel_scroll(parent)
        self._panel_header(layout, "Staging", "Automate the Brightspace staging process one step at a time")

        self._section_label(layout, "COURSE  —  CRN OR BRIGHTSPACE URL")
        self._staging_crn = QLineEdit()
        self._staging_crn.setPlaceholderText(
            "e.g. 31899  or  https://learn.okanagancollege.ca/d2l/home/…"
        )
        self._staging_crn.setFixedHeight(40)
        self._staging_crn.setStyleSheet(_entry_style())
        self._staging_crn.textChanged.connect(self._sync_current_course)
        self._staging_crn.editingFinished.connect(self._auto_extract_crn)
        layout.addWidget(self._staging_crn)
        layout.addSpacing(16)

        self._staging_steps12_btn = QPushButton("▶   Stage Course")
        self._staging_steps12_btn.setFixedHeight(52)
        self._staging_steps12_btn.setStyleSheet(
            _btn(T["btn_primary"], T["btn_primary_h"]) + "QPushButton { font-size: 16px; }"
        )
        self._staging_steps12_btn.clicked.connect(self._start_staging_steps_1_2)
        layout.addWidget(self._staging_steps12_btn)
        layout.addSpacing(20)

        self._section_label(layout, "LOG")
        self._staging_log = self._make_log(layout, min_height=300)
        layout.addStretch()

    def _auto_extract_crn(self):
        val = self._staging_crn.text().strip()
        if not val.startswith("http") or getattr(self, "_crn_extracting", False):
            return
        self._crn_extracting = True
        q = self._log_queue

        def worker():
            async def run():
                from playwright.async_api import async_playwright
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    ctx = await browser.new_context(
                        storage_state=SESSION_FILE_GUI if os.path.exists(SESSION_FILE_GUI) else None
                    )
                    page = await ctx.new_page()
                    await page.goto(val)
                    await page.wait_for_load_state("domcontentloaded")
                    await page.wait_for_timeout(1500)
                    home_m = _re.search(r'/d2l/(?:home|le/[^/]+)/(\d+)', val)
                    if home_m:
                        parsed = urlparse(val)
                        base   = f"{parsed.scheme}://{parsed.netloc}"
                        org_id = home_m.group(1)
                        api_url = f"{base}/d2l/api/lp/1.9/courses/{org_id}"
                        try:
                            resp = await page.evaluate(f"""
                                async () => {{
                                    const r = await fetch('{api_url}');
                                    if (r.ok) return await r.text();
                                    return null;
                                }}
                            """)
                            if resp:
                                data = _json.loads(resp)
                                code = data.get("Code", "")
                                if code:
                                    await browser.close()
                                    return code
                        except Exception:
                            pass
                    text = await page.title() + " " + await page.evaluate("document.body.innerText")
                    await browser.close()
                    return text

            try:
                text = asyncio.run(run())
                m = _re.search(r'[A-Z][A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+-(\d+)\.\d+', text)
                if m:
                    crn = m.group(1)
                    QTimer.singleShot(0, lambda: self._staging_crn.setText(crn))
                    q.put(("staging", f"✓  Extracted CRN: {crn}"))
                else:
                    if _re.search(r'/d2l/(?:home|le/[^/]+)/\d+', val):
                        q.put(("staging", "ℹ  No CRN on this page — URL will be used directly."))
                    else:
                        q.put(("staging", "⚠  Could not find a course code on that page."))
            except Exception as e:
                q.put(("staging", f"✗  {e}"))
            finally:
                self._crn_extracting = False

        threading.Thread(target=worker, daemon=True).start()

    def _start_staging_steps_1_2(self):
        crn = self._staging_crn.text().strip()
        self._sync_current_course(crn)
        if not crn:
            self._log_append(self._staging_log, "⚠  Enter a CRN or URL.")
            return
        self._staging_steps12_btn.setEnabled(False)
        self._staging_steps12_btn.setText("Running…")
        self._staging_log.clear()
        q       = self._log_queue
        bridge  = self._bridge
        coursebridge_email    = self._cb_email.text().strip()
        coursebridge_password = self._cb_password.text().strip()

        def worker():
            from staging_automator import run_steps_1_2

            # Mutable so phase_fn can reroute log output to the matching tab mid-run.
            current_tag = ["staging"]

            class W:
                def write(self, t):
                    if t.strip(): q.put((current_tag[0], t.rstrip()))
                def flush(self): pass

            def phase_fn(phase):
                tag = {
                    "quiz": "quiz",
                    "assignment": "assign",
                    "outline": "outline",
                    "gradebook": "gradebook",
                }.get(phase, "staging")
                current_tag[0] = tag
                q.put(("phase", tag))

            old, sys.stdout = sys.stdout, W()
            try:
                _sentry_context("staging", crn)
                asyncio.run(run_steps_1_2(
                    crn, dry_run=False,
                    prompt_fn=bridge.prompt,
                    history_fn=lambda name, url, kind: self._append_history([(name, url)], kind),
                    phase_fn=phase_fn,
                    no_outline_fn=lambda course_url: q.put(("term_work", course_url)),
                    coursebridge_email=coursebridge_email,
                    coursebridge_password=coursebridge_password,
                ))
            except Exception as e:
                _sentry_capture(e)
                q.put(("staging", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("staging", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()
