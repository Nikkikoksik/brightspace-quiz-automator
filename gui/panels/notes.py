from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QTextEdit, QWidget,
)

from gui.constants import NOTES_FILE
from gui.theme import T, _btn


class NotesPanelMixin:

    def _build_notes_panel(self, parent: QWidget):
        from PyQt6.QtWidgets import QVBoxLayout
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(0)
        self._panel_header(layout, "Course Notes", "Auto-populated from staging run. Editable.")

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        copy_btn = QPushButton("Copy All")
        copy_btn.setFixedHeight(32)
        copy_btn.setFixedWidth(100)
        copy_btn.setStyleSheet(_btn(T["btn_muted"], T["btn_muted_h"]))
        copy_btn.clicked.connect(self._notes_copy)
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(32)
        clear_btn.setFixedWidth(80)
        clear_btn.setStyleSheet(_btn(T["btn_danger"], T["btn_danger_h"]))
        clear_btn.clicked.connect(self._notes_clear)
        btn_row.addWidget(copy_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addSpacing(12)

        self._notes_box = QTextEdit()
        self._notes_box.setStyleSheet(
            f"QTextEdit {{ background: {T['card_bg']}; color: {T['text']}; "
            f"border: 1px solid {T['card_border']}; border-radius: 8px; "
            f"font-family: 'Cascadia Code', 'Consolas', monospace; "
            f"font-size: 12px; padding: 12px; }}"
        )
        self._notes_box.textChanged.connect(self._save_notes)
        layout.addWidget(self._notes_box, stretch=1)

    def _notes_copy(self):
        text = self._notes_box.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)

    def _notes_clear(self):
        self._notes_box.clear()
        self._save_notes()

    def _save_notes(self):
        try:
            with open(NOTES_FILE, "w", encoding="utf-8") as f:
                f.write(self._notes_box.toPlainText())
        except Exception:
            pass

    def _load_notes(self):
        try:
            with open(NOTES_FILE, encoding="utf-8") as f:
                content = f.read()
            if content.strip():
                self._notes_box.blockSignals(True)
                self._notes_box.setPlainText(content)
                self._notes_box.blockSignals(False)
        except FileNotFoundError:
            pass
