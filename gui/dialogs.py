import threading

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QMessageBox, QSpinBox, QVBoxLayout,
)

from gui.theme import T, _btn


class _ThreadBridge(QObject):
    _prompt_sig    = pyqtSignal(str)
    _ask_range_sig = pyqtSignal(int, str)
    _review_sig    = pyqtSignal(str, str)

    def __init__(self, parent):
        super().__init__(parent)
        self._result = [None]
        self._event  = threading.Event()
        self._prompt_sig.connect(self._on_prompt)
        self._ask_range_sig.connect(self._on_ask_range)
        self._review_sig.connect(self._on_review)

    def prompt(self, text: str) -> str:
        self._event.clear()
        self._prompt_sig.emit(text)
        self._event.wait()
        return self._result[0]

    def ask_range(self, total: int, label: str) -> tuple:
        self._event.clear()
        self._ask_range_sig.emit(total, label)
        self._event.wait()
        return self._result[0]

    def review(self, title: str, msg: str):
        self._event.clear()
        self._review_sig.emit(title, msg)
        self._event.wait()

    def confirm(self, title: str, msg: str) -> bool:
        answer = self.prompt(f"{title}\n\n{msg}\n\n(y/n)")
        return answer == "y"

    def _on_prompt(self, text: str):
        is_yn = "(y/n)" in text
        msg   = text.replace("(y/n)", "").strip()
        box   = QMessageBox(self.parent())
        box.setWindowTitle("Confirmation" if is_yn else "Action Required")
        box.setText(msg)
        box.setStyleSheet(f"QMessageBox {{ background: {T['card_bg']}; }} QLabel {{ color: {T['text']}; }}")
        if is_yn:
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            r = box.exec()
            self._result[0] = "y" if r == QMessageBox.StandardButton.Yes else "n"
        else:
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.exec()
            self._result[0] = ""
        self._event.set()

    def _on_ask_range(self, total: int, label: str):
        dlg = _RangeDialog(total, label, self.parent())
        if dlg.exec():
            self._result[0] = (dlg.start_val, dlg.end_val)
        else:
            self._result[0] = (1, total)
        self._event.set()

    def _on_review(self, title: str, msg: str):
        QMessageBox.information(self.parent(), title, msg)
        self._event.set()


class _RangeDialog(QDialog):
    def __init__(self, total: int, label: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select range")
        self.setFixedSize(300, 160)
        self.setStyleSheet(f"background: {T['card_bg']}; color: {T['text']};")
        self.start_val = 1
        self.end_val   = total

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        layout.addWidget(QLabel(f"Found {total} {label}(s). Process which range?"))

        row = QHBoxLayout()
        row.addWidget(QLabel("From:"))
        self._start = QSpinBox()
        self._start.setRange(1, total)
        self._start.setValue(1)
        self._start.setStyleSheet(
            f"background: {T['bg']}; color: {T['text']}; "
            f"border: 1px solid {T['card_border']}; border-radius: 4px; padding: 2px 6px;"
        )
        row.addWidget(self._start)
        row.addWidget(QLabel("To:"))
        self._end = QSpinBox()
        self._end.setRange(1, total)
        self._end.setValue(total)
        self._end.setStyleSheet(
            f"background: {T['bg']}; color: {T['text']}; "
            f"border: 1px solid {T['card_border']}; border-radius: 4px; padding: 2px 6px;"
        )
        row.addWidget(self._end)
        layout.addLayout(row)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.setStyleSheet(_btn(T["btn_muted"], T["btn_muted_h"]))
        btns.accepted.connect(self._ok)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _ok(self):
        self.start_val = self._start.value()
        self.end_val   = self._end.value()
        self.accept()
