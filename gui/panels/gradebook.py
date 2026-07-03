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
from gui.gradebook_board import GradebookBoard
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

        self._section_label(layout, "REVIEW BOARD")
        self._gb_board = GradebookBoard()
        layout.addWidget(self._gb_board)
        layout.addSpacing(12)

        self._gb_apply_btn = QPushButton("▶   Apply to Brightspace (step-by-step)")
        self._gb_apply_btn.setFixedHeight(44)
        self._gb_apply_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"]))
        self._gb_apply_btn.clicked.connect(self._start_gb_apply)
        self._gb_apply_btn.setEnabled(False)
        layout.addWidget(self._gb_apply_btn)
        layout.addSpacing(16)

        self._section_label(layout, "LOG")
        self._gradebook_log = self._make_log(layout, min_height=200)
        layout.addStretch()

    TERM_WORK_COMMENT = ("Grade items present in gradebook so made one category "
                         "weighted 100% and all items have been placed in this category.")
    SKIP_COMMENT = ("Material and resources have been successfully migrated. The course "
                    "syllabus included supplementary materials so we did not apply this "
                    "to the course syllabus template. Grade Book also not configured, "
                    "please reach out for support, if desired.")

    def _start_gb_fetch(self):
        course_input = self._gb_course.text().strip()
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
                from gradebook_automator import fetch_gradebook_items, fetch_outline_text

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
                            return None, None

                        items = await fetch_gradebook_items(page, ou)
                        text  = await fetch_outline_text(page, ou)
                        return items, text
                    finally:
                        await browser.close()

            old, sys.stdout = sys.stdout, _QueueWriter(q, "gradebook")
            try:
                _sentry_context("gradebook", course_input)
                items, text = asyncio.run(run())
                if items is not None:
                    QTimer.singleShot(0, lambda: self._gb_on_fetched(items, text))
            except Exception as e:
                _sentry_capture(e)
                q.put(("gradebook", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("gradebook", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    def _gb_on_fetched(self, items, text):
        import gradebook_automator as ga
        self._gb_items, self._gb_outline_text = items, text
        self._gb_skip_btn.show()
        if ga.is_placeholder(text):
            self._gb_banner.setText(
                "No syllabus content found — create a single Term Work category?")
            self._gb_banner.show()
            self._gb_termwork_btn.show()
            return
        self._gb_run_extraction(text)

    def _gb_run_extraction(self, text):
        q = self._log_queue

        def worker():
            import gradebook_automator as ga
            provider, key = self._load_gradebook_creds()
            if not key:
                q.put(("gradebook", f"⚠ No API key for {provider} — set it in Settings."))
                q.put(("gradebook", "__DONE__"))
                return
            try:
                s = ga.extract_categories(text, self._gb_items, provider, key)
                QTimer.singleShot(0, lambda: (
                    self._gb_board.load_structure(s),
                    self._gb_apply_btn.setEnabled(True),
                ))
                q.put(("gradebook", "✓  Categories extracted."))
            except ValueError:
                QTimer.singleShot(0, self._gb_show_selection_fallback)
                q.put(("gradebook", "⚠  AI could not find the weighting table."))
            except Exception as e:
                _sentry_capture(e)
                q.put(("gradebook", f"✗  {e}"))
            finally:
                q.put(("gradebook", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

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
            lay = self._gb_board.parentWidget().layout()   # insert above board
            idx = lay.indexOf(self._gb_board)
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
        self._gb_run_extraction(sel)

    def _gb_term_work(self):
        s = {"categories": [{"name": "Term Work", "weight": 100.0,
                             "items": list(self._gb_items)}], "uncategorized": []}
        self._gb_board.load_structure(s)
        self._gb_apply_btn.setEnabled(True)
        QApplication.clipboard().setText(self.TERM_WORK_COMMENT)
        self._log_append(self._gradebook_log, f"Comment (copied to clipboard): {self.TERM_WORK_COMMENT}")

    def _gb_skip_nonstandard(self):
        QApplication.clipboard().setText(self.SKIP_COMMENT)
        self._log_append(self._gradebook_log, f"Comment (copied to clipboard): {self.SKIP_COMMENT}")
        self._gb_apply_btn.setEnabled(False)

    def _gb_pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            None, "Choose outline file", "", "Documents (*.pdf *.docx)")
        if not path:
            return
        has_items = bool(getattr(self, "_gb_items", None))
        q = self._log_queue
        self._log_append(self._gradebook_log, "Reading file…")

        def worker():
            import gradebook_automator as ga
            try:
                text = ga.extract_text_from_file(path)
            except Exception as e:
                q.put(("gradebook", f"✗  Could not read file: {e}"))
                return

            def on_done():
                self._gb_outline_text = text
                if not has_items:
                    self._log_append(
                        self._gradebook_log,
                        "⚠  No gradebook items fetched yet — run Fetch first (items come from Brightspace).")
                    return
                self._gb_run_extraction(text)

            QTimer.singleShot(0, on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _start_gb_apply(self):
        self._log_append(self._gradebook_log, "Apply flow arrives in Task 9.")


class _QueueWriter:
    def __init__(self, q, tag):
        self._q, self._tag = q, tag

    def write(self, t):
        if t.strip():
            self._q.put((self._tag, t.rstrip()))

    def flush(self):
        pass
