import asyncio
import sys
import threading

from PyQt6.QtWidgets import QLineEdit, QPushButton, QWidget

from gui.telemetry import _sentry_capture
from gui.theme import T, _btn, _entry_style


class ContentCleanerPanelMixin:

    def _build_content_cleaner_panel(self, parent: QWidget):
        layout = self._panel_scroll(parent)
        self._panel_header(
            layout,
            "Content Cleaner",
            "Replace Moodle references with Brightspace across content topics",
        )

        self._section_label(layout, "COURSE  (CRN NUMBER OR BRIGHTSPACE URL)")
        self._cleaner_url = QLineEdit()
        self._cleaner_url.setPlaceholderText(
            "e.g. 80147 or https://learn.okanagancollege.ca/..."
        )
        self._cleaner_url.setFixedHeight(38)
        self._cleaner_url.setStyleSheet(_entry_style())
        layout.addWidget(self._cleaner_url)
        layout.addSpacing(20)

        self._cleaner_run_btn = QPushButton("▶  Run Content Cleaner")
        self._cleaner_run_btn.setFixedHeight(52)
        self._cleaner_run_btn.setStyleSheet(
            _btn(T["btn_primary"], T["btn_primary_h"]) + "QPushButton { font-size: 16px; }"
        )
        self._cleaner_run_btn.clicked.connect(self._start_content_cleaner_run)
        layout.addWidget(self._cleaner_run_btn)
        layout.addSpacing(20)

        self._section_label(layout, "LOG")
        self._cleaner_log = self._make_log(layout, min_height=300)
        layout.addStretch()

    def _start_content_cleaner_run(self):
        course_url = self._cleaner_url.text().strip()
        if not course_url:
            self._log_append(self._cleaner_log, "⚠  Course URL or CRN is required.")
            return

        self._cleaner_run_btn.setEnabled(False)
        self._cleaner_run_btn.setText("Running…")
        self._cleaner_log.clear()
        q = self._log_queue

        def worker():
            from content_cleaner import scan_course

            class W:
                def write(self, t):
                    if t.strip():
                        q.put(("cleaner", t.rstrip()))
                def flush(self):
                    pass

            old, sys.stdout = sys.stdout, W()
            try:
                asyncio.run(scan_course(course_url=course_url))
            except Exception as e:
                _sentry_capture(e)
                q.put(("cleaner", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("cleaner", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()
