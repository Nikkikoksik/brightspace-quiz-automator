import json
from datetime import datetime

from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit,
    QScrollArea, QVBoxLayout, QWidget,
)

from gui.constants import COURSE_HISTORY_FILE
from gui.theme import T, _entry_style, _scroll_style


class HistoryPanelMixin:

    def _build_history_panel(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(0)
        self._panel_header(layout, "History", "Completed quiz and assignment runs")

        self._history_search = QLineEdit()
        self._history_search.setPlaceholderText("Search by URL…")
        self._history_search.setFixedHeight(32)
        self._history_search.setStyleSheet(_entry_style())
        self._history_search.textChanged.connect(lambda: self._load_history_tab())
        layout.addWidget(self._history_search)
        layout.addSpacing(10)

        self._history_scroll = QScrollArea()
        self._history_scroll.setWidgetResizable(True)
        self._history_scroll.setStyleSheet(_scroll_style())
        self._history_inner  = QWidget()
        self._history_layout = QVBoxLayout(self._history_inner)
        from PyQt6.QtCore import Qt
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
            e for e in reversed(entries)
            if not term or term in e.get("url", "").lower()
        ]
        if not filtered:
            lbl = QLabel("No history yet." if not term else "No matches.")
            lbl.setStyleSheet(f"color: {T['text_dim']}; font-size: 12px; padding: 10px;")
            self._history_layout.addWidget(lbl)
            return
        for entry in filtered:
            url   = entry.get("url", "")
            kind  = entry.get("type", "quiz")
            ts    = entry.get("timestamp", "")[:16].replace("T", " ")
            icon  = "[Q]" if kind == "quiz" else "[A]"
            short = url[-72:] if len(url) > 72 else url
            row   = QFrame()
            row.setStyleSheet(
                f"QFrame {{ background: {T['card_bg']}; "
                f"border: 1px solid {T['card_border']}; border-radius: 6px; }}"
            )
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(8, 5, 8, 5)
            txt = QLabel(f"{icon}  {short}")
            txt.setStyleSheet(
                f"color: {T['text_muted']}; font-family: 'Consolas', monospace; "
                f"font-size: 11px; border: none;"
            )
            row_l.addWidget(txt, stretch=1)
            ts_lbl = QLabel(ts)
            ts_lbl.setStyleSheet(f"color: {T['text_dim']}; font-size: 10px; border: none;")
            row_l.addWidget(ts_lbl)
            self._history_layout.addWidget(row)

    def _append_history(self, urls: list, kind: str):
        try:
            try:
                with open(COURSE_HISTORY_FILE, encoding="utf-8") as f:
                    entries = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                entries = []
            ts = datetime.now().isoformat(timespec="seconds")
            for url in urls:
                entries.append({"url": url, "type": kind, "timestamp": ts})
            with open(COURSE_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2)
        except Exception:
            pass
