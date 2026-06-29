import asyncio
import sys
import threading

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QCheckBox, QLineEdit, QPushButton, QWidget

from gui.telemetry import _sentry_capture
from gui.theme import T, _btn, _checkbox_style, _entry_style


class OutlinePanelMixin:

    def _build_outline_panel(self, parent: QWidget):
        layout = self._panel_scroll(parent)
        self._panel_header(
            layout, "Course Outline",
            "Download, convert and paste the course outline into Brightspace",
        )

        self._section_label(layout, "COURSE  (CRN number  or  full Brightspace URL)")
        self._outline_url = QLineEdit()
        self._outline_url.setPlaceholderText(
            "e.g.  80147  or  https://learn.okanagancollege.ca/…"
        )
        self._outline_url.setFixedHeight(38)
        self._outline_url.setStyleSheet(_entry_style())
        layout.addWidget(self._outline_url)
        layout.addSpacing(16)

        self._outline_dryrun = QCheckBox(
            "Dry run  (download + convert only — nothing pasted into Brightspace)"
        )
        self._outline_dryrun.setStyleSheet(_checkbox_style(warn=True))
        layout.addWidget(self._outline_dryrun)
        layout.addSpacing(20)

        self._outline_run_btn = QPushButton("▶  Run Course Outline")
        self._outline_run_btn.setFixedHeight(52)
        self._outline_run_btn.setStyleSheet(
            _btn(T["btn_primary"], T["btn_primary_h"]) + "QPushButton { font-size: 16px; }"
        )
        self._outline_run_btn.clicked.connect(self._start_outline_run)
        layout.addWidget(self._outline_run_btn)
        layout.addSpacing(8)

        self._section_label(layout, "TEST INDIVIDUAL STEPS")
        self._test_step4_btn = QPushButton(
            "▶   TEST STEP 4 ONLY  (paste existing HTML into Brightspace)"
        )
        self._test_step4_btn.setFixedHeight(38)
        self._test_step4_btn.setStyleSheet(_btn("#1a2e1a", "#2a4a2a"))
        self._test_step4_btn.clicked.connect(self._start_test_step4)
        layout.addWidget(self._test_step4_btn)
        layout.addSpacing(12)

        self._section_label(layout, "LOG")
        self._outline_log = self._make_log(layout, min_height=220)
        layout.addStretch()

    def _start_outline_run(self):
        course_url = self._outline_url.text().strip()
        email      = self._cb_email.text().strip()
        password   = self._cb_password.text().strip()
        if not course_url:
            self._log_append(self._outline_log, "⚠  Course URL is required.")
            return
        if not email or not password:
            self._log_append(
                self._outline_log,
                "⚠  CourseBridge credentials required — go to Settings.",
            )
            return
        self._outline_run_btn.setEnabled(False)
        self._outline_run_btn.setText("Running…")
        self._outline_log.clear()
        self._save_config(course_url=course_url, email=email, password=password)
        dry_run = self._outline_dryrun.isChecked()
        q       = self._log_queue
        bridge  = self._bridge

        def worker():
            from course_outline_automator import run as outline_run

            class W:
                def write(self, t):
                    if t.strip(): q.put(("outline", t.rstrip()))
                def flush(self): pass

            old, sys.stdout = sys.stdout, W()
            try:
                asyncio.run(outline_run(
                    dry_run=dry_run, course_url=course_url,
                    email=email, password=password,
                    prompt_fn=bridge.prompt,
                ))
            except Exception as e:
                _sentry_capture(e)
                q.put(("outline", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("outline", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    def _start_test_step4(self):
        course_url = self._outline_url.text().strip()
        if not course_url:
            self._log_append(self._outline_log, "⚠  Course URL or CRN is required.")
            return
        self._test_step4_btn.setEnabled(False)
        self._test_step4_btn.setText("Running…")
        self._outline_log.clear()
        q = self._log_queue

        def worker():
            from course_outline_automator import test_step4

            class W:
                def write(self, t):
                    if t.strip(): q.put(("outline", t.rstrip()))
                def flush(self): pass

            old, sys.stdout = sys.stdout, W()
            try:
                asyncio.run(test_step4(course_url=course_url))
            except Exception as e:
                _sentry_capture(e)
                q.put(("outline", f"✗  {e}"))
            finally:
                sys.stdout = old
                QTimer.singleShot(0, lambda: (
                    self._test_step4_btn.setEnabled(True),
                    self._test_step4_btn.setText(
                        "▶   TEST STEP 4 ONLY  (paste existing HTML into Brightspace)"
                    ),
                ))

        threading.Thread(target=worker, daemon=True).start()
