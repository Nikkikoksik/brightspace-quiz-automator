import asyncio
import json
import sys
import threading

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from gui.constants import STAGING_DONE_FILE, STAGING_QUEUE_FILE
from gui.theme import T, _btn, _entry_style, _scroll_style, _tab_style


class QueuePanelMixin:

    def _build_queue_panel(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(0)
        self._panel_header(layout, "Staging Queue", "Track which courses have been staged")

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self._staging_refresh_btn = QPushButton("⟳  Refresh Queue")
        self._staging_refresh_btn.setFixedHeight(36)
        self._staging_refresh_btn.setStyleSheet(_btn(T["btn_muted"], T["btn_muted_h"]))
        self._staging_refresh_btn.clicked.connect(self._start_staging_refresh)
        top_row.addWidget(self._staging_refresh_btn)
        top_row.addStretch()
        layout.addLayout(top_row)
        layout.addSpacing(6)

        self._queue_status_label = QLabel("")
        self._queue_status_label.setStyleSheet(
            f"color: {T['text_muted']}; font-size: 12px; background: transparent;"
        )
        layout.addWidget(self._queue_status_label)
        layout.addSpacing(10)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self._queue_add_entry = QLineEdit()
        self._queue_add_entry.setPlaceholderText(
            "Add a course (e.g. MATH-100-001-31899.202530)…"
        )
        self._queue_add_entry.setFixedHeight(34)
        self._queue_add_entry.setStyleSheet(_entry_style())
        self._queue_add_entry.returnPressed.connect(self._queue_add_course)
        add_btn = QPushButton("+ Add")
        add_btn.setFixedHeight(34)
        add_btn.setFixedWidth(70)
        add_btn.setStyleSheet(_btn(T["btn_add"], T["btn_add_h"]))
        add_btn.clicked.connect(self._queue_add_course)
        add_row.addWidget(self._queue_add_entry, stretch=1)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)
        layout.addSpacing(14)

        self._queue_tabs = QTabWidget()
        self._queue_tabs.setStyleSheet(_tab_style())
        layout.addWidget(self._queue_tabs, stretch=1)

        self._queue_todo_scroll = QScrollArea()
        self._queue_todo_scroll.setWidgetResizable(True)
        self._queue_todo_scroll.setStyleSheet(_scroll_style())
        self._queue_todo_inner  = QWidget()
        self._queue_todo_layout = QVBoxLayout(self._queue_todo_inner)
        self._queue_todo_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._queue_todo_scroll.setWidget(self._queue_todo_inner)
        self._queue_tabs.addTab(self._queue_todo_scroll, "To Do")

        self._queue_done_scroll = QScrollArea()
        self._queue_done_scroll.setWidgetResizable(True)
        self._queue_done_scroll.setStyleSheet(_scroll_style())
        self._queue_done_inner  = QWidget()
        self._queue_done_layout = QVBoxLayout(self._queue_done_inner)
        self._queue_done_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._queue_done_scroll.setWidget(self._queue_done_inner)
        self._queue_tabs.addTab(self._queue_done_scroll, "Done")

        self._load_staging_queue_list()

    def _queue_add_course(self):
        course = self._queue_add_entry.text().strip()
        if not course:
            return
        try:
            with open(STAGING_QUEUE_FILE, encoding="utf-8") as f:
                existing = [l.strip() for l in f if l.strip()]
        except FileNotFoundError:
            existing = []
        if course not in existing:
            existing.append(course)
            with open(STAGING_QUEUE_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(existing) + "\n")
        self._queue_add_entry.clear()
        self._load_staging_queue_list()

    def _done_set(self) -> set:
        try:
            with open(STAGING_DONE_FILE, encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()

    def _save_done_set(self, done: set):
        with open(STAGING_DONE_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(done), f, indent=2)

    def _toggle_course_done(self, course: str):
        done = self._done_set()
        done.discard(course) if course in done else done.add(course)
        self._save_done_set(done)
        self._load_staging_queue_list()

    def _queue_delete_course(self, course: str):
        try:
            with open(STAGING_QUEUE_FILE, encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip() and l.strip() != course]
        except FileNotFoundError:
            lines = []
        with open(STAGING_QUEUE_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        done = self._done_set()
        done.discard(course)
        self._save_done_set(done)
        self._load_staging_queue_list()

    def _load_staging_queue_list(self):
        if not hasattr(self, "_queue_todo_layout"):
            return
        for layout in [self._queue_todo_layout, self._queue_done_layout]:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        try:
            with open(STAGING_QUEUE_FILE, encoding="utf-8") as f:
                courses = [l.strip() for l in f if l.strip()]
        except FileNotFoundError:
            courses = []
        done      = self._done_set()
        pending   = [c for c in courses if c not in done]
        completed = [c for c in courses if c in done]
        total     = len(courses)
        if hasattr(self, "_queue_status_label"):
            self._queue_status_label.setText(
                f"{len(completed)} of {total} done  ·  {total - len(completed)} remaining"
                if total else "No courses yet — click Refresh or add one above"
            )

        def make_row(parent_layout, course, is_done):
            row   = QWidget()
            row.setStyleSheet("background: transparent;")
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(4)
            bg  = "#141a14" if is_done else "#1c1c2e"
            hov = "#1a2a1a" if is_done else "#22334a"
            col = "#4a7a4a" if is_done else "#b0b8cc"
            btn = QPushButton(f"  {course}")
            btn.setFixedHeight(30)
            btn.setStyleSheet(
                f"QPushButton {{ background: {bg}; color: {col}; border: none; "
                f"border-radius: 6px; text-align: left; padding-left: 8px; "
                f"font-family: 'Consolas', monospace; font-size: 12px; }} "
                f"QPushButton:hover {{ background: {hov}; }}"
            )
            btn.clicked.connect(lambda _, c=course: self._toggle_course_done(c))
            row_l.addWidget(btn, stretch=1)
            del_btn = QPushButton("×")
            del_btn.setFixedSize(28, 30)
            del_btn.setStyleSheet(_btn("transparent", "#3a1a1a", "#554444"))
            del_btn.clicked.connect(lambda _, c=course: self._queue_delete_course(c))
            row_l.addWidget(del_btn)
            parent_layout.addWidget(row)

        if pending:
            for c in pending:
                make_row(self._queue_todo_layout, c, False)
        else:
            lbl = QLabel(
                "Nothing left to do!" if courses
                else "No courses yet — click Refresh or add one above"
            )
            lbl.setStyleSheet(f"color: {T['text_dim']}; font-size: 12px; padding: 10px;")
            self._queue_todo_layout.addWidget(lbl)

        if completed:
            for c in completed:
                make_row(self._queue_done_layout, c, True)
        else:
            lbl = QLabel("No completed courses yet.")
            lbl.setStyleSheet(f"color: {T['text_dim']}; font-size: 12px; padding: 10px;")
            self._queue_done_layout.addWidget(lbl)

    def _start_staging_refresh(self):
        self._staging_refresh_btn.setEnabled(False)
        self._staging_refresh_btn.setText("Refreshing…")
        q = self._log_queue

        def worker():
            from staging_scraper import scrape, should_process

            class W:
                def write(self, t):
                    if t.strip(): q.put(("staging", t.rstrip()))
                def flush(self): pass

            old, sys.stdout = sys.stdout, W()
            try:
                courses  = asyncio.run(scrape())
                filtered = [c for c in sorted(courses) if should_process(c)]
                skipped  = len(courses) - len(filtered)
                with open(STAGING_QUEUE_FILE, "w", encoding="utf-8") as f:
                    for c in filtered:
                        f.write(c + "\n")
                print(f"\n✓ Queue updated — {len(filtered)} course(s) to stage  ({skipped} skipped)")
                for c in filtered:
                    print(f"   {c}")
            except Exception as e:
                from gui.telemetry import _sentry_capture
                _sentry_capture(e)
                q.put(("staging", f"✗  {e}"))
            finally:
                sys.stdout = old
                QTimer.singleShot(0, lambda: (
                    self._staging_refresh_btn.setEnabled(True),
                    self._staging_refresh_btn.setText("⟳  Refresh Queue"),
                    self._load_staging_queue_list(),
                ))

        threading.Thread(target=worker, daemon=True).start()
