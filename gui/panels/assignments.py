import asyncio
import sys
import threading

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QMessageBox, QPushButton, QWidget

from gui.telemetry import _sentry_capture, _sentry_context
from gui.theme import T, _btn, _entry_style


class AssignmentPanelMixin:

    def _build_assignment_panel(self, parent: QWidget):
        layout = self._panel_scroll(parent)
        self._panel_header(layout, "Assignment Automator", "Bulk-update assignment settings across courses")

        self._section_label(layout, "ASSIGNMENT PAGE URLS")
        self._assign_url_container, _ = self._make_url_rows_container()
        layout.addWidget(self._assign_url_container)
        layout.addSpacing(6)

        add_btn = QPushButton("＋  Add assignment page URL")
        add_btn.setFixedHeight(32)
        add_btn.setStyleSheet(
            _btn("transparent", T["btn_muted"], T["text_muted"])
            + "QPushButton { border: 1px solid " + T["card_border"] + "; }"
        )
        add_btn.clicked.connect(
            lambda: self._add_url_row(self._assign_url_container, self._assign_url_rows)
        )
        layout.addWidget(add_btn)
        layout.addSpacing(16)

        gear_btn, gear = self._gear_button([("Add to Grade Book", True)])
        self._assign_gradebook_var = gear["Add to Grade Book"]

        self._assign_run_btn = QPushButton("▶  Run Assignments")
        self._assign_run_btn.setFixedHeight(52)
        self._assign_run_btn.setStyleSheet(
            _btn(T["btn_primary"], T["btn_primary_h"]) + "QPushButton { font-size: 16px; }"
        )
        self._assign_run_btn.clicked.connect(self._start_assignment_run)
        run_row = QHBoxLayout()
        run_row.setSpacing(8)
        run_row.addWidget(self._assign_run_btn, stretch=1)
        run_row.addWidget(gear_btn)
        layout.addLayout(run_row)
        layout.addSpacing(12)

        self._section_label(layout, "LOG")
        self._assign_log = self._make_log(layout, min_height=220)
        layout.addStretch()

    def _start_assignment_run(self):
        urls = [e.text().strip() for _, e in self._assign_url_rows if e.text().strip()]
        if not urls:
            self._log_append(self._assign_log, "⚠  No URLs entered.")
            return
        self._sync_current_course(urls[0])
        self._last_assign_urls = urls
        self._assign_run_btn.setEnabled(False)
        self._assign_run_btn.setText("Running…")
        self._resume_event.set()
        self._assign_log.clear()
        settings = {"set_in_gradebook": self._assign_gradebook_var.isChecked()}
        ask_fn   = self._make_ask_fn()
        q        = self._log_queue
        bridge   = self._bridge

        def review_fn():
            bridge.review(
                "Assignments Complete",
                "All assignments processed.\n\nClick OK to close the browser.",
            )

        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("assign", t.rstrip()))
                def flush(self): pass

            old, sys.stdout = sys.stdout, W()
            success = False
            try:
                _sentry_context("assignments", urls[0] if urls else "")
                from browser import run_assignments
                asyncio.run(run_assignments(
                    urls=urls, dry_run=False,
                    settings=settings, ask_fn=ask_fn, review_fn=review_fn,
                    history_fn=lambda name, url: self._append_history([(name, url)], "assignment"),
                ))
                success = True
            except Exception as e:
                _sentry_capture(e)
                q.put(("assign", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("assign", "__ASSIGN_DONE__" if success else "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    def _run_assignments_for(self, urls: list):
        if not urls:
            return
        self._sync_current_course(urls[0])
        self._show_panel("Assignment Automator")
        self._last_assign_urls = urls
        self._assign_run_btn.setEnabled(False)
        self._assign_run_btn.setText("Running…")
        self._resume_event.set()
        self._assign_log.clear()
        settings = {"set_in_gradebook": self._assign_gradebook_var.isChecked()}
        ask_fn   = self._make_ask_fn()
        q        = self._log_queue
        bridge   = self._bridge

        def review_fn():
            bridge.review(
                "All Done!",
                "Quizzes and assignments are both complete.\n\nClick OK to close the browser.",
            )

        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("assign", t.rstrip()))
                def flush(self): pass

            old, sys.stdout = sys.stdout, W()
            try:
                from browser import run_assignments
                asyncio.run(run_assignments(
                    urls=urls, dry_run=False,
                    settings=settings, ask_fn=ask_fn, review_fn=review_fn,
                    history_fn=lambda name, url: self._append_history([(name, url)], "assignment"),
                ))
            except Exception as e:
                _sentry_capture(e)
                q.put(("assign", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("assign", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    def _post_assign_review(self):
        r = QMessageBox.question(
            self,
            "Run Quizzes?",
            "Would you also like to run the Quiz Automator\nfor the same course(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if r == QMessageBox.StandardButton.Yes:
            self._run_quizzes_for(self._last_assign_urls)
