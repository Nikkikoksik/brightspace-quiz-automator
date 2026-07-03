"""Drag-and-drop review board: columns = categories, cards = gradebook items.
No auto-rebalancing — weights only change when the user types them."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QPushButton, QScrollArea, QVBoxLayout, QWidget, QFrame,
)

from gui.theme import T, _btn, _card, _entry_style

UNCATEGORIZED = "Uncategorized"


class _Column(QFrame):
    def __init__(self, name: str, weight: float | None, on_remove=None):
        super().__init__()
        self.setStyleSheet(_card())
        self.setFixedWidth(210)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        self.name_edit = QLineEdit(name)
        self.name_edit.setStyleSheet(_entry_style())
        self.name_edit.setFixedHeight(30)
        lay.addWidget(self.name_edit)

        self.weight_edit = None
        if weight is not None:                      # Uncategorized has no weight
            row = QHBoxLayout()
            self.weight_edit = QLineEdit(f"{weight:g}")
            self.weight_edit.setStyleSheet(_entry_style())
            self.weight_edit.setFixedHeight(28)
            self.weight_edit.setFixedWidth(60)
            row.addWidget(self.weight_edit)
            row.addWidget(QLabel("%"))
            row.addStretch()
            lay.addLayout(row)

        self.items = QListWidget()
        self.items.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.items.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.items.setMinimumHeight(160)
        lay.addWidget(self.items)

    def weight(self) -> float:
        if self.weight_edit is None:
            return 0.0
        try:
            return float(self.weight_edit.text())
        except ValueError:
            return 0.0

    def item_names(self) -> list[str]:
        return [self.items.item(i).text() for i in range(self.items.count())]


class GradebookBoard(QWidget):
    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._add_btn = QPushButton("+  Add Category")
        self._add_btn.setFixedHeight(32)
        self._add_btn.setStyleSheet(_btn(T["btn_muted"], T["btn_muted_h"]))
        self._add_btn.clicked.connect(lambda: self.add_category())
        outer.addWidget(self._add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(280)
        inner = QWidget()
        self._cols_layout = QHBoxLayout(inner)
        self._cols_layout.setSpacing(10)
        self._cols_layout.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        self._columns: list[_Column] = []

    def _clear(self):
        for col in self._columns:
            col.setParent(None)
        self._columns = []

    def add_category(self, name: str = "New Category", weight: float = 0.0,
                     items: list[str] | None = None, uncategorized: bool = False):
        col = _Column(name, None if uncategorized else weight)
        for it in items or []:
            col.items.addItem(it)
        self._cols_layout.insertWidget(self._cols_layout.count() - 1, col)
        self._columns.append(col)
        return col

    def load_structure(self, structure: dict):
        self._clear()
        for cat in structure.get("categories", []):
            self.add_category(cat["name"], cat["weight"], cat["items"])
        unc = structure.get("uncategorized", [])
        if unc:
            self.add_category(UNCATEGORIZED, items=unc, uncategorized=True)

    def to_structure(self) -> dict:
        categories, uncategorized = [], []
        for col in self._columns:
            if col.name_edit.text().strip() == UNCATEGORIZED:
                uncategorized.extend(col.item_names())
            else:
                categories.append({
                    "name":   col.name_edit.text().strip(),
                    "weight": col.weight(),
                    "items":  col.item_names(),
                })
        return {"categories": categories, "uncategorized": uncategorized}
