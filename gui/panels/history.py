import json
import webbrowser
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from gui.constants import COURSE_HISTORY_FILE
from gui.theme import T, _btn, _entry_style, _scroll_style


class HistoryPanelMixin:

    def _build_history_panel(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(0)
        self._panel_header(layout, "History", "Courses you've worked on")

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self._history_search = QLineEdit()
        self._history_search.setPlaceholderText("Search by course name, CRN, or code…")
        self._history_search.setFixedHeight(32)
        self._history_search.setStyleSheet(_entry_style())
        self._history_search.textChanged.connect(lambda: self._load_history_tab())
        top_row.addWidget(self._history_search, stretch=1)

        clear_btn = QPushButton("Clear History")
        clear_btn.setFixedHeight(32)
        clear_btn.setStyleSheet(_btn(T["btn_danger"], T["btn_danger_h"]))
        clear_btn.clicked.connect(self._clear_history)
        top_row.addWidget(clear_btn)
        layout.addLayout(top_row)
        layout.addSpacing(10)

        self._history_scroll = QScrollArea()
        self._history_scroll.setWidgetResizable(True)
        self._history_scroll.setStyleSheet(_scroll_style())
        self._history_inner  = QWidget()
        self._history_layout = QVBoxLayout(self._history_inner)
        self._history_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._history_scroll.setWidget(self._history_inner)
        layout.addWidget(self._history_scroll, stretch=1)

    def _load_history_tab(self):
        if not hasattr(self, "_history_layout"):
            return
        while self._history_layout.count():
            item = self._history_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        term = (
            self._history_search.text().strip().lower()
            if hasattr(self, "_history_search") else ""
        )
        try:
            with open(COURSE_HISTORY_FILE, encoding="utf-8") as f:
                entries = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            entries = []
        filtered = [
            e for e in entries
            if not term or term in e.get("name", "").lower()
        ]
        if not filtered:
            lbl = QLabel("No history yet." if not term else "No matches.")
            lbl.setStyleSheet(f"color: {T['text_muted']}; font-size: 12px; padding: 10px;")
            self._history_layout.addWidget(lbl)
            return
        kind_labels = {
            "staging":    "Staged",
            "quiz":       "Quizzes",
            "assignment": "Assignments",
            "outline":    "Course Outline",
            "cleaner":    "Content Cleaned",
        }

        groups: dict[str, list] = {}
        for e in filtered:
            groups.setdefault(e.get("name", ""), []).append(e)
        ordered_names = sorted(
            groups.keys(),
            key=lambda n: max(e.get("timestamp", "") for e in groups[n]),
            reverse=True,
        )

        for name in ordered_names:
            acts = sorted(groups[name], key=lambda e: e.get("timestamp", ""), reverse=True)
            url  = next((e.get("url") for e in acts if e.get("url")), None)
            card = QFrame()
            card.setStyleSheet(
                f"QFrame {{ background: {T['card_bg']}; "
                f"border: 1px solid {T['card_border']}; border-radius: 6px; }}"
            )
            card_l = QVBoxLayout(card)
            card_l.setContentsMargins(10, 8, 10, 8)
            card_l.setSpacing(4)

            if url:
                title = QPushButton(f"🔗  {name}")
                title.setCursor(Qt.CursorShape.PointingHandCursor)
                title.setToolTip("Click to open this course in your browser")
                title.setStyleSheet(
                    "QPushButton { background: transparent; color: #ffffff; "
                    "font-family: 'Consolas', monospace; font-size: 14px; font-weight: 600; "
                    "border: none; text-align: left; padding: 0; }"
                    f"QPushButton:hover {{ color: {T['accent']}; }}"
                )
                title.clicked.connect(lambda _, u=url: webbrowser.open(u))
            else:
                title = QLabel(name)
                title.setStyleSheet(
                    "color: #ffffff; font-family: 'Consolas', monospace; "
                    "font-size: 14px; font-weight: 600; border: none;"
                )
            card_l.addWidget(title)

            for e in acts:
                kind  = e.get("type", "quiz")
                label = kind_labels.get(kind, kind)
                ts    = e.get("timestamp", "")[:16].replace("T", " ")
                act_row = QHBoxLayout()
                act_row.setContentsMargins(0, 0, 0, 0)
                act_lbl = QLabel(label)
                act_lbl.setStyleSheet(f"color: {T['text_muted']}; font-size: 12px; border: none;")
                act_row.addWidget(act_lbl, stretch=1)
                ts_lbl = QLabel(ts)
                ts_lbl.setStyleSheet(f"color: {T['text_muted']}; font-size: 11px; border: none;")
                act_row.addWidget(ts_lbl)
                card_l.addLayout(act_row)

            self._history_layout.addWidget(card)

    def _clear_history(self):
        r = QMessageBox.question(
            self,
            "Clear History?",
            "This will permanently delete all history entries. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return
        try:
            with open(COURSE_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump([], f)
        except Exception:
            pass
        self._load_history_tab()

    def _append_history(self, items: list, kind: str):
        """items: list of (name, url) tuples."""
        try:
            try:
                with open(COURSE_HISTORY_FILE, encoding="utf-8") as f:
                    entries = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                entries = []
            ts = datetime.now().isoformat(timespec="seconds")
            for name, url in items:
                entries = [
                    e for e in entries
                    if not (e.get("name") == name and e.get("type") == kind)
                ]
                entries.append({"name": name, "url": url, "type": kind, "timestamp": ts})
            with open(COURSE_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2)
        except Exception:
            pass
