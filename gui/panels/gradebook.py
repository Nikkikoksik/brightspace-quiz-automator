import asyncio
import os
import sys
import threading

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QWidget,
)

from gui.constants import SESSION_FILE_GUI
from gui.gradebook_review_window import GradebookReviewWindow
from gui.telemetry import _sentry_capture, _sentry_context
from gui.theme import T, _btn, _entry_style


class GradebookPanelMixin:

    def _build_gradebook_panel(self, parent: QWidget):
        layout = self._panel_scroll(parent)
        self._panel_header(layout, "Gradebook",
                           "AI-assisted gradebook categories from the course outline")

        self._section_label(layout, "COURSE  —  CRN OR BRIGHTSPACE URL")
        self._gb_course = QLineEdit()
        self._gb_course.setPlaceholderText(
            "e.g. 31899  or  https://learn.okanagancollege.ca/d2l/home/…")
        self._gb_course.setFixedHeight(40)
        self._gb_course.setStyleSheet(_entry_style())
        self._gb_course.textChanged.connect(self._sync_current_course)
        layout.addWidget(self._gb_course)
        layout.addSpacing(10)

        btn_row = QHBoxLayout()
        self._gb_fetch_btn = QPushButton("▶   Fetch Outline + Gradebook")
        self._gb_fetch_btn.setFixedHeight(44)
        self._gb_fetch_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"]))
        self._gb_fetch_btn.clicked.connect(self._start_gb_fetch)
        btn_row.addWidget(self._gb_fetch_btn)

        self._gb_file_btn = QPushButton("Use Local File…")
        self._gb_file_btn.setFixedHeight(44)
        self._gb_file_btn.setStyleSheet(_btn(T["btn_muted"], T["btn_muted_h"]))
        self._gb_file_btn.clicked.connect(self._gb_pick_file)
        btn_row.addWidget(self._gb_file_btn)

        self._gb_direct_termwork_btn = QPushButton("No Outline → Term Work")
        self._gb_direct_termwork_btn.setFixedHeight(44)
        self._gb_direct_termwork_btn.setStyleSheet(_btn(T["btn_muted"], T["btn_muted_h"]))
        self._gb_direct_termwork_btn.clicked.connect(self._start_gb_term_work_fetch)
        btn_row.addWidget(self._gb_direct_termwork_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addSpacing(12)

        # Scenario banner (hidden until fetch decides which scenario applies)
        self._gb_banner = QLabel("")
        self._gb_banner.setWordWrap(True)
        self._gb_banner.setStyleSheet(f"color: {T['warn']}; font-size: 12px;")
        self._gb_banner.hide()
        layout.addWidget(self._gb_banner)

        banner_row = QHBoxLayout()
        self._gb_termwork_btn = QPushButton("Create Term Work category (100%)")
        self._gb_termwork_btn.setFixedHeight(36)
        self._gb_termwork_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"]))
        self._gb_termwork_btn.clicked.connect(self._gb_term_work)
        self._gb_termwork_btn.hide()
        banner_row.addWidget(self._gb_termwork_btn)

        self._gb_skip_btn = QPushButton("Not a standard outline — skip gradebook")
        self._gb_skip_btn.setFixedHeight(36)
        self._gb_skip_btn.setStyleSheet(_btn(T["btn_danger"], T["btn_danger_h"]))
        self._gb_skip_btn.clicked.connect(self._gb_skip_nonstandard)
        self._gb_skip_btn.hide()
        banner_row.addWidget(self._gb_skip_btn)
        banner_row.addStretch()
        layout.addLayout(banner_row)
        layout.addSpacing(12)

        self._section_label(layout, "REVIEW")
        self._gb_summary = QLabel("Run Fetch to load the gradebook for review.")
        self._gb_summary.setWordWrap(True)
        self._gb_summary.setStyleSheet(f"color: {T['text_muted']}; font-size: 12px;")
        layout.addWidget(self._gb_summary)
        layout.addSpacing(6)

        self._gb_open_btn = QPushButton("Open Review Board")
        self._gb_open_btn.setFixedHeight(40)
        self._gb_open_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"]))
        self._gb_open_btn.clicked.connect(self._gb_open_review)
        self._gb_open_btn.setEnabled(False)
        layout.addWidget(self._gb_open_btn)
        layout.addSpacing(16)

        # Anchor + layout ref so the AI-failed selection box can be inserted here.
        self._gb_panel_layout = layout
        self._gb_open_anchor = self._gb_open_btn

        self._section_label(layout, "LOG")
        self._gradebook_log = self._make_log(layout, min_height=200)
        layout.addStretch()

        self._gb_window: GradebookReviewWindow | None = None

    TERM_WORK_COMMENT = ("Grade items present in gradebook so made one category "
                         "weighted 100% and all items have been placed in this category.")
    SKIP_COMMENT = ("Material and resources have been successfully migrated. The course "
                    "syllabus included supplementary materials so we did not apply this "
                    "to the course syllabus template. Grade Book also not configured, "
                    "please reach out for support, if desired.")

    def _gb_ensure_window(self) -> GradebookReviewWindow:
        if self._gb_window is None:
            self._gb_window = GradebookReviewWindow(self)
            self._gb_window.apply_requested.connect(self._start_gb_apply)
        return self._gb_window

    def _gb_show_window(self, structure: dict):
        """Load the structure into the pop-out window and bring it forward."""
        win = self._gb_ensure_window()
        win.load_structure(structure)
        n_cats = len(structure.get("categories", []))
        n_items = sum(len(c.get("items", [])) for c in structure.get("categories", []))
        n_items += len(structure.get("uncategorized", []))
        self._gb_summary.setText(f"{n_cats} categories, {n_items} items loaded.")
        self._gb_open_btn.setEnabled(True)
        win.show()
        win.raise_()
        win.activateWindow()

    def _gb_open_review(self):
        if self._gb_window is None:
            self._log_append(self._gradebook_log, "⚠  Nothing to review yet — run Fetch first.")
            return
        self._gb_window.show()
        self._gb_window.raise_()
        self._gb_window.activateWindow()

    def _start_gb_fetch(self):
        course_input = self._gb_course.text().strip()
        self._sync_current_course(course_input)
        if not course_input:
            self._log_append(self._gradebook_log, "⚠  Enter a CRN or URL.")
            return
        self._gb_fetch_btn.setEnabled(False)
        self._gb_fetch_btn.setText("Running…")
        q = self._log_queue

        def worker():
            async def run():
                from playwright.async_api import async_playwright
                from browser import _wait_for_login
                from staging_automator import _resolve_ou
                import gradebook_automator as ga
                from gradebook_automator import fetch_gradebook_items
                from course_outline_automator import (
                    convert_evaluation_schema_with_coursebridge,
                    find_and_download_outline,
                )

                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
                    try:
                        context = await browser.new_context(
                            storage_state=SESSION_FILE_GUI if os.path.exists(SESSION_FILE_GUI) else None,
                            no_viewport=True,
                        )
                        page = await context.new_page()
                        await _wait_for_login(page, context)

                        _, ou = await _resolve_ou(page, course_input)
                        if not ou:
                            return None, None, None

                        outline_path = await find_and_download_outline(
                            page, course_id=ou, prompt_fn=self._bridge.prompt
                        )
                        text = ga.extract_text_from_file(outline_path) if outline_path else ""
                        data = await fetch_gradebook_items(page, ou)
                        structure = None
                        if outline_path:
                            html = await convert_evaluation_schema_with_coursebridge(
                                outline_path,
                                self._cb_email.text().strip(),
                                self._cb_password.text().strip(),
                                context=context,
                            )
                            structure = ga.structure_from_evaluation_html(html, data["items"])
                        return data, text, structure
                    finally:
                        await browser.close()

            old, sys.stdout = sys.stdout, _QueueWriter(q, "gradebook")
            try:
                _sentry_context("gradebook", course_input)
                data, text, structure = asyncio.run(run())
                if data is not None:
                    # QTimer.singleShot from a worker thread never fires (no Qt
                    # event loop here) — route through the poll queue instead.
                    q.put(("gb_fetched", (data, text, structure)))
            except Exception as e:
                _sentry_capture(e)
                q.put(("gradebook", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("gradebook", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    def _start_gb_term_work_fetch(self):
        """Fetch gradebook items only and prepare one Term Work category."""
        course_input = self._gb_course.text().strip()
        self._sync_current_course(course_input)
        if not course_input:
            self._log_append(self._gradebook_log, "⚠  Enter a CRN or URL.")
            return
        self._gb_fetch_btn.setEnabled(False)
        self._gb_direct_termwork_btn.setEnabled(False)
        self._gb_direct_termwork_btn.setText("Loading…")
        q = self._log_queue

        def worker():
            async def run():
                from playwright.async_api import async_playwright
                from browser import _wait_for_login
                from staging_automator import _resolve_ou
                from gradebook_automator import fetch_gradebook_items

                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
                    try:
                        context = await browser.new_context(
                            storage_state=SESSION_FILE_GUI if os.path.exists(SESSION_FILE_GUI) else None,
                            no_viewport=True,
                        )
                        page = await context.new_page()
                        await _wait_for_login(page, context)
                        _, ou = await _resolve_ou(page, course_input)
                        if not ou:
                            return None
                        return await fetch_gradebook_items(page, ou)
                    finally:
                        await browser.close()

            old, sys.stdout = sys.stdout, _QueueWriter(q, "gradebook")
            try:
                _sentry_context("gradebook", course_input)
                data = asyncio.run(run())
                if data is not None:
                    q.put(("gb_term_work_data", data))
            except Exception as e:
                _sentry_capture(e)
                q.put(("gradebook", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("gradebook", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    def _gb_on_fetched(self, data, text, structure=None):
        import gradebook_automator as ga
        self._gb_items, self._gb_outline_text = data["items"], text
        if text and not ga.is_placeholder(text):
            self._log_append(
                self._gradebook_log,
                f"✓  Course outline fetched ({len(text.strip())} chars).",
            )
        else:
            self._log_append(
                self._gradebook_log,
                "⚠  Course outline was not found or was empty.",
            )
        self._gb_skip_btn.show()
        if structure and structure.get("categories"):
            self._gb_show_window(structure)
            placed = sum(len(c.get("items", [])) for c in structure["categories"])
            remaining = len(structure.get("uncategorized", []))
            self._log_append(
                self._gradebook_log,
                f"✓  CourseBridge extracted {len(structure['categories'])} evaluation categor(ies); "
                f"locally placed {placed} item(s), {remaining} need review.",
            )
            return
        if structure is not None:
            self._log_append(
                self._gradebook_log,
                "⚠  CourseBridge did not return an evaluation schema; falling back to existing flow.",
            )
        if getattr(self, "_gb_force_term_work", False):
            self._gb_force_term_work = False
            if data["categories"]:
                self._gb_show_window({
                    "categories": data["categories"],
                    "uncategorized": data["uncategorized"],
                })
                self._log_append(self._gradebook_log, "Existing gradebook categories already exist; review them manually instead of Term Work.")
                return
            self._gb_banner.setText("No course outline selected; prepared a single Term Work category.")
            self._gb_banner.show()
            self._gb_termwork_btn.hide()
            self._gb_term_work()
            return
        if data["categories"]:
            # Gradebook already has categories. If some items are unassigned,
            # ask the AI to sort those loose items into the existing categories
            # (no new categories, weights untouched). Otherwise show as-is.
            if data["uncategorized"]:
                self._log_append(self._gradebook_log,
                                 f"Existing categories found; sorting "
                                 f"{len(data['uncategorized'])} unassigned item(s) with AI…")
                self._gb_run_mapping(data["categories"], data["uncategorized"], text)
            else:
                self._gb_show_window({
                    "categories":    data["categories"],
                    "uncategorized": data["uncategorized"],
                })
                self._log_append(self._gradebook_log,
                                 f"✓  Loaded existing gradebook structure: "
                                 f"{len(data['categories'])} categories, {len(data['items'])} items.")
            return
        if ga.is_placeholder(text):
            self._gb_banner.setText(
                "No syllabus content found — create a single Term Work category?")
            self._gb_banner.show()
            self._gb_termwork_btn.show()
            return
        self._gb_run_extraction(text)

    def _gb_run_extraction(self, text, from_selection=False):
        q = self._log_queue

        def worker():
            import gradebook_automator as ga
            provider, key = self._load_gradebook_creds()
            if not key:
                q.put(("gradebook", f"⚠ No API key for {provider} — set it in Settings."))
                q.put(("gradebook", "__DONE__"))
                return
            try:
                if from_selection:
                    # User highlighted the weighting text themselves — it may be
                    # tiny, so skip resolve_categories' placeholder length check.
                    try:
                        s = ga.extract_categories(text, self._gb_items, provider, key)
                        s["source"] = "outline"
                    except ValueError:
                        s = {"source": "term_work"}
                else:
                    s = ga.resolve_categories(text, self._gb_items, provider, key)

                if s.get("source") == "term_work":
                    # AI couldn't extract — offer both recovery paths, never
                    # auto-apply Term Work without the user choosing it.
                    q.put(("gb_offer_fallbacks", None))
                    q.put(("gradebook", "⚠  AI could not find the weighting table."))
                else:
                    q.put(("gb_load_board", s))
                    q.put(("gradebook", "✓  Categories extracted."))
            except Exception as e:
                _sentry_capture(e)
                q.put(("gradebook", f"✗  {e}"))
            finally:
                q.put(("gradebook", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    def _gb_run_mapping(self, existing_categories, loose_items, outline_text=""):
        """Worker: AI-sort loose items into existing categories. Falls back to
        showing the structure unchanged (items left uncategorized) if there's
        no API key or the call fails — user can still sort by hand."""
        q = self._log_queue
        as_is = {"categories": existing_categories, "uncategorized": loose_items}

        def worker():
            import gradebook_automator as ga
            provider, key = self._load_gradebook_creds()
            if not key:
                q.put(("gradebook", f"⚠ No API key for {provider} — sort items manually."))
                q.put(("gb_load_board", as_is))
                q.put(("gradebook", "__DONE__"))
                return
            try:
                outline_status = (
                    f"{len(outline_text.strip())} chars"
                    if outline_text and not ga.is_placeholder(outline_text)
                    else "not available"
                )
                q.put((
                    "gradebook",
                    f"AI sort context: provider={provider}, "
                    f"{len(existing_categories)} existing categor(ies), "
                    f"{len(loose_items)} unassigned item(s), outline={outline_status}.",
                ))
                s = ga.map_items_to_existing(
                    existing_categories, loose_items, provider, key, outline_text
                )
                placed = len(loose_items) - len(s.get("uncategorized", []))
                q.put(("gb_load_board", s))
                if placed:
                    q.put((
                        "gradebook",
                        f"✓  AI placed {placed} of {len(loose_items)} unassigned item(s); "
                        f"{len(s.get('uncategorized', []))} still need manual sorting.",
                    ))
                else:
                    q.put((
                        "gradebook",
                        "⚠  AI did not place any unassigned items; sort them manually.",
                    ))
            except ga.AIRateLimitError as e:
                _sentry_capture(e)
                q.put(("gradebook", f"⚠  {e}"))
                q.put(("gb_load_board", as_is))
            except Exception as e:
                _sentry_capture(e)
                q.put(("gradebook", f"⚠  AI sort failed ({e}); sort items manually."))
                q.put(("gb_load_board", as_is))
            finally:
                q.put(("gradebook", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    def _gb_offer_fallbacks(self):
        """Extraction failed: show the highlight-it-yourself box AND the
        Term Work button so the user picks the recovery path."""
        self._gb_show_selection_fallback()
        self._gb_banner.setText(
            "AI couldn't find the weighting table — highlight it below, "
            "or create a single Term Work category instead.")
        self._gb_banner.show()
        self._gb_termwork_btn.show()

    def _gb_show_selection_fallback(self):
        if getattr(self, "_gb_fallback_box", None) is None:
            self._gb_fallback_label = QLabel(
                "AI couldn't find the weighting table — highlight it below.")
            self._gb_fallback_box = QTextEdit()
            self._gb_fallback_box.setReadOnly(True)      # selection still works
            self._gb_fallback_box.setMinimumHeight(200)
            self._gb_extract_sel_btn = QPushButton("Extract from Selection")
            self._gb_extract_sel_btn.setFixedHeight(36)
            self._gb_extract_sel_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"]))
            self._gb_extract_sel_btn.clicked.connect(self._gb_extract_from_selection)
            lay = self._gb_panel_layout           # insert above the Open button
            idx = lay.indexOf(self._gb_open_anchor)
            lay.insertWidget(idx, self._gb_fallback_label)
            lay.insertWidget(idx + 1, self._gb_fallback_box)
            lay.insertWidget(idx + 2, self._gb_extract_sel_btn)
        self._gb_fallback_box.setPlainText(self._gb_outline_text)
        self._gb_fallback_label.show(); self._gb_fallback_box.show(); self._gb_extract_sel_btn.show()

    def _gb_extract_from_selection(self):
        sel = self._gb_fallback_box.textCursor().selectedText()
        if not sel.strip():
            self._log_append(self._gradebook_log, "⚠  Select the weighting text first.")
            return
        self._gb_run_extraction(sel, from_selection=True)

    def _gb_term_work(self):
        s = {"categories": [{"name": "Term Work", "weight": 100.0,
                             "items": list(self._gb_items)}], "uncategorized": []}
        self._gb_show_window(s)
        QApplication.clipboard().setText(self.TERM_WORK_COMMENT)
        self._log_append(self._gradebook_log, f"Comment (copied to clipboard): {self.TERM_WORK_COMMENT}")

    def _gb_load_term_work_data(self, data: dict):
        self._gb_items = list(data.get("items", []))
        self._gb_outline_text = ""
        self._gb_banner.setText("No course outline selected; prepared a single Term Work category.")
        self._gb_banner.show()
        self._gb_termwork_btn.hide()
        self._gb_term_work()

    def _gb_skip_nonstandard(self):
        QApplication.clipboard().setText(self.SKIP_COMMENT)
        self._log_append(self._gradebook_log, f"Comment (copied to clipboard): {self.SKIP_COMMENT}")
        self._gb_open_btn.setEnabled(False)

    def _prepare_term_work_for_course(self, course_input: str):
        self._sync_current_course(course_input)
        self._show_panel("Gradebook")
        self._gb_course.setText(course_input)
        self._start_gb_term_work_fetch()

    def _gb_pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            None, "Choose outline file", "", "Documents (*.pdf *.docx)")
        if not path:
            return
        q = self._log_queue
        self._log_append(self._gradebook_log, "Reading file…")

        def worker():
            import gradebook_automator as ga
            try:
                text = ga.extract_text_from_file(path)
            except Exception as e:
                q.put(("gradebook", f"✗  Could not read file: {e}"))
                return
            q.put(("gb_file_text", text))

        threading.Thread(target=worker, daemon=True).start()

    def _gb_file_loaded(self, text):
        """GUI-thread continuation of _gb_pick_file."""
        self._gb_outline_text = text
        if not getattr(self, "_gb_items", None):
            self._log_append(
                self._gradebook_log,
                "⚠  No gradebook items fetched yet — run Fetch first (items come from Brightspace).")
            return
        self._gb_run_extraction(text)

    def _start_gb_apply(self, structure: dict):
        # structure comes from the review window's apply_requested signal
        # (the window already ran the invalid-weight guard before emitting).
        if not structure.get("categories"):
            self._log_append(self._gradebook_log, "⚠  Nothing to apply — no categories.")
            return
        course_input = self._gb_course.text().strip()
        self._sync_current_course(course_input)
        self._log_append(self._gradebook_log, "Applying to Brightspace…")
        q = self._log_queue
        bridge = self._bridge

        def worker():
            async def run():
                from playwright.async_api import async_playwright
                from browser import _wait_for_login
                from staging_automator import _resolve_ou
                from gradebook_automator import apply_categories

                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
                    try:
                        context = await browser.new_context(
                            storage_state=SESSION_FILE_GUI if os.path.exists(SESSION_FILE_GUI) else None,
                            no_viewport=True,
                        )
                        page = await context.new_page()
                        await _wait_for_login(page, context)

                        _, ou = await _resolve_ou(page, course_input)
                        if not ou:
                            return

                        def step_fn(label):
                            bridge.prompt(f"Next: {label}. OK to continue…")
                        await apply_categories(page, ou, structure, step_fn)
                    finally:
                        await browser.close()

            old, sys.stdout = sys.stdout, _QueueWriter(q, "gradebook")
            try:
                _sentry_context("gradebook", course_input)
                asyncio.run(run())
            except Exception as e:
                _sentry_capture(e)
                q.put(("gradebook", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("gradebook", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()


class _QueueWriter:
    def __init__(self, q, tag):
        self._q, self._tag = q, tag

    def write(self, t):
        if t.strip():
            self._q.put((self._tag, t.rstrip()))

    def flush(self):
        pass
