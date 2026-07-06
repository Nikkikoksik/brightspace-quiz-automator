import asyncio
import sys
import threading

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QWidget,
)

from gui.telemetry import _sentry_capture, _sentry_context
from gui.theme import T, _btn, _entry_style


class QuizPanelMixin:

    def _build_quiz_panel(self, parent: QWidget):
        layout = self._panel_scroll(parent)
        self._panel_header(layout, "Quiz Automator", "Bulk-update quiz settings across courses")

        self._section_label(layout, "COURSE URLS")
        self._quiz_url_container, _ = self._make_url_rows_container()
        layout.addWidget(self._quiz_url_container)
        layout.addSpacing(6)

        add_btn = QPushButton("＋  Add course URL")
        add_btn.setFixedHeight(32)
        add_btn.setStyleSheet(
            _btn("transparent", T["btn_muted"], T["text_muted"])
            + "QPushButton { border: 1px solid " + T["card_border"] + "; }"
        )
        add_btn.clicked.connect(lambda: self._add_url_row(self._quiz_url_container, self._url_rows))
        layout.addWidget(add_btn)
        layout.addSpacing(16)

        worker_widget = QWidget()
        worker_row = QHBoxLayout(worker_widget)
        worker_row.setContentsMargins(12, 6, 12, 6)
        worker_lbl = QLabel("Parallel browser tabs")
        worker_lbl.setStyleSheet(f"color: {T['text']};")
        worker_row.addWidget(worker_lbl)
        self._worker_spin = QSpinBox()
        self._worker_spin.setRange(1, 3)
        self._worker_spin.setValue(1)
        self._worker_spin.setFixedWidth(60)
        self._worker_spin.setToolTip("1 is most reliable; higher is faster but flakier")
        self._worker_spin.setStyleSheet(
            f"background: {T['bg']}; color: {T['text']}; "
            f"border: 1px solid {T['card_border']}; border-radius: 4px; padding: 2px 6px;"
        )
        worker_row.addWidget(self._worker_spin)

        gear_btn, gear = self._gear_button([
            ("Add to Grade Book", True),
            ("Auto-submit on timer expiry", True),
        ], extra_widget=worker_widget)
        self._gradebook_var  = gear["Add to Grade Book"]
        self._autosubmit_var = gear["Auto-submit on timer expiry"]

        self._quiz_run_btn = QPushButton("▶  Run Quizzes")
        self._quiz_run_btn.setFixedHeight(52)
        self._quiz_run_btn.setStyleSheet(
            _btn(T["btn_primary"], T["btn_primary_h"]) + "QPushButton { font-size: 16px; }"
        )
        self._quiz_run_btn.clicked.connect(self._start_quiz_run)
        run_row = QHBoxLayout()
        run_row.setSpacing(8)
        run_row.addWidget(self._quiz_run_btn, stretch=1)
        run_row.addWidget(gear_btn)
        layout.addLayout(run_row)
        layout.addSpacing(12)

        self._section_label(layout, "LOG")
        self._quiz_log = self._make_log(layout, min_height=220)
        layout.addStretch()

    def _start_quiz_run(self):
        urls = [e.text().strip() for _, e in self._url_rows if e.text().strip()]
        if not urls:
            self._log_append(self._quiz_log, "⚠  No URLs entered.")
            return
        self._sync_current_course(urls[0])
        self._save_courses(urls)
        self._last_quiz_urls = urls
        self._quiz_run_btn.setEnabled(False)
        self._quiz_run_btn.setText("Running…")
        self._resume_event.set()
        self._quiz_log.clear()
        settings = {
            "set_in_gradebook": self._gradebook_var.isChecked(),
            "set_auto_submit":  self._autosubmit_var.isChecked(),
            "worker_count":     self._worker_spin.value(),
        }
        ask_fn  = self._make_ask_fn()
        q       = self._log_queue
        bridge  = self._bridge

        def review_fn():
            bridge.review(
                "Quizzes Complete",
                "All quizzes processed.\n\nReview the browser for any errors, then click OK to close it.",
            )

        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("quiz", t.rstrip()))
                def flush(self): pass

            old, sys.stdout = sys.stdout, W()
            success = False
            try:
                _sentry_context("quizzes", urls[0] if urls else "")
                from browser import run as browser_run
                asyncio.run(browser_run(
                    urls=urls, dry_run=False,
                    settings=settings, ask_fn=ask_fn, review_fn=review_fn,
                    history_fn=lambda name, url: self._append_history([(name, url)], "quiz"),
                ))
                success = True
            except Exception as e:
                _sentry_capture(e)
                q.put(("quiz", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("quiz", "__QUIZ_DONE__" if success else "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    def _run_quizzes_for(self, urls: list):
        if not urls:
            return
        self._sync_current_course(urls[0])
        self._show_panel("Quiz Automator")
        self._last_quiz_urls = urls
        self._quiz_run_btn.setEnabled(False)
        self._quiz_run_btn.setText("Running…")
        self._resume_event.set()
        self._quiz_log.clear()
        settings = {
            "set_in_gradebook": self._gradebook_var.isChecked(),
            "set_auto_submit":  self._autosubmit_var.isChecked(),
            "worker_count":     self._worker_spin.value(),
        }
        ask_fn  = self._make_ask_fn()
        q       = self._log_queue
        bridge  = self._bridge

        def review_fn():
            bridge.review(
                "All Done!",
                "Assignments and quizzes are both complete.\n\nClick OK to close the browser.",
            )

        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("quiz", t.rstrip()))
                def flush(self): pass

            old, sys.stdout = sys.stdout, W()
            try:
                _sentry_context("quizzes", urls[0] if urls else "")
                from browser import run as browser_run
                asyncio.run(browser_run(
                    urls=urls, dry_run=False,
                    settings=settings, ask_fn=ask_fn, review_fn=review_fn,
                    history_fn=lambda name, url: self._append_history([(name, url)], "quiz"),
                ))
            except Exception as e:
                _sentry_capture(e)
                q.put(("quiz", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("quiz", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    def _post_quiz_review(self):
        r = QMessageBox.question(
            self,
            "Run Assignments?",
            "Would you also like to run the Assignment Automator\nfor the same course(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if r == QMessageBox.StandardButton.Yes:
            self._run_assignments_for(self._last_quiz_urls)
