import asyncio
import sys
import threading

from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget,
)

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

    # Worker methods land in Task 8/9 — temporary placeholders so the app runs:
    def _start_gb_fetch(self):
        self._log_append(self._gradebook_log, "Fetch flow arrives in Task 8.")

    def _gb_pick_file(self):
        self._log_append(self._gradebook_log, "Local-file flow arrives in Task 8.")

    def _gb_term_work(self):
        pass

    def _gb_skip_nonstandard(self):
        pass

    def _start_gb_apply(self):
        self._log_append(self._gradebook_log, "Apply flow arrives in Task 9.")
