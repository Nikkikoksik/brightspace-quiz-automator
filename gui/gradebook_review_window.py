"""Pop-out gradebook review window.

Non-modal top-level window: vertical scrolling sections (one per category),
inline name+weight edit, remove category/item, a permanent Uncategorized
section, and a footer Apply. Keeps the same data interface the old embedded
board had — load_structure / to_structure / invalid_weight_columns — so the
apply pipeline is untouched. Emits `apply_requested(structure)` on Apply.

v1: no free drag-drop. Items move via each row's "Move ▾" menu; the ✕ on an
item is a shortcut for "move to Uncategorized". Uncategorized items are left
unchanged during assort.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from gui.theme import T, _btn, _entry_style, _scroll_style

UNCATEGORIZED = "Uncategorized"


class _ItemRow(QFrame):
    """One grade item inside a section: name, Move ▾ menu, ✕ (→ Uncategorized)."""

    def __init__(self, name: str, window: "GradebookReviewWindow"):
        super().__init__()
        self.name = name
        self._window = window
        self.setObjectName("itemRow")
        self.setStyleSheet(
            f"QFrame#itemRow {{ background: {T['bg']}; border: 1px solid {T['card_border']};"
            f" border-left: 3px solid {T['accent_dim']}; border-radius: 6px; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 5, 6, 5)
        row.setSpacing(8)

        lbl = QLabel(name)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {T['text']}; font-size: 12px; border: none;")
        row.addWidget(lbl, stretch=1)

        move = QPushButton("Move ▾")
        move.setCursorShape = None
        move.setFixedHeight(24)
        move.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {T['text_muted']};"
            f" border: 1px solid {T['card_border']}; border-radius: 5px;"
            f" font-size: 11px; padding: 0 8px; }}"
            f"QPushButton:hover {{ color: {T['text']}; border-color: {T['btn_muted_h']}; }}")
        move.clicked.connect(self._show_move_menu)
        row.addWidget(move)

        rm = QPushButton("✕")
        rm.setFixedSize(24, 24)
        rm.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {T['text_dim']};"
            f" border: none; font-size: 13px; }}"
            f"QPushButton:hover {{ color: {T['danger_text']}; }}")
        rm.clicked.connect(lambda: self._window.move_item(self, UNCATEGORIZED))
        row.addWidget(rm)

    def _show_move_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {T['card_bg']}; color: {T['text']};"
            f" border: 1px solid {T['card_border']}; }}"
            f"QMenu::item:selected {{ background: {T['nav_active']}; color: {T['accent']}; }}")
        for target in self._window.section_names():
            if target == self._current_section_name():
                continue
            act = QAction(target, menu)
            act.triggered.connect(lambda _=False, t=target: self._window.move_item(self, t))
            menu.addAction(act)
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _current_section_name(self) -> str:
        sec = self.parent()
        while sec is not None and not isinstance(sec, _Section):
            sec = sec.parent()
        return sec.name() if sec else ""


class _Section(QFrame):
    """A category (editable name+weight, removable) or the Uncategorized bin."""

    def __init__(self, name: str, weight: float | None,
                 window: "GradebookReviewWindow", removable: bool = True):
        super().__init__()
        self._window = window
        self._removable = removable
        is_uncat = weight is None
        border = "1px dashed" if is_uncat else "1px solid"
        bg = "#12171e" if is_uncat else T["card_bg"]
        self.setStyleSheet(
            f"QFrame#sec {{ background: {bg}; border: {border} {T['card_border']};"
            f" border-radius: 10px; }}")
        self.setObjectName("sec")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        if is_uncat:
            cap = QLabel("Uncategorized — items here are left unchanged")
            cap.setStyleSheet(f"color: {T['text_muted']}; font-size: 12px; border: none;")
            head.addWidget(cap, stretch=1)
            self.name_edit = None
            self.weight_edit = None
        else:
            self.name_edit = QLineEdit(name)
            self.name_edit.setStyleSheet(_entry_style())
            self.name_edit.setFixedHeight(30)
            head.addWidget(self.name_edit, stretch=1)

            self.weight_edit = QLineEdit(f"{weight:g}")
            self.weight_edit.setStyleSheet(_entry_style())
            self.weight_edit.setFixedHeight(30)
            self.weight_edit.setFixedWidth(52)
            self.weight_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.weight_edit.textChanged.connect(self._window.recalc_total)
            head.addWidget(self.weight_edit)
            pct = QLabel("%")
            pct.setStyleSheet(f"color: {T['text_muted']}; font-size: 12px; border: none;")
            head.addWidget(pct)

            rm = QPushButton("✕")
            rm.setFixedSize(26, 26)
            rm.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {T['danger_text']};"
                f" border: none; font-size: 14px; }}"
                f"QPushButton:hover {{ color: #ff7b72; }}")
            rm.clicked.connect(lambda: self._window.remove_section(self))
            head.addWidget(rm)
        lay.addLayout(head)

        self._items_box = QVBoxLayout()
        self._items_box.setSpacing(4)

        items_wrap = QWidget()
        items_wrap.setStyleSheet("background: transparent; border: none;")
        items_lay = QHBoxLayout(items_wrap)
        items_lay.setContentsMargins(8, 2, 0, 0)
        items_lay.setSpacing(10)

        rail = QFrame()
        rail.setFixedWidth(2)
        rail.setStyleSheet(
            f"background: {T['accent_dim'] if not is_uncat else T['card_border']}; "
            "border: none; border-radius: 1px;"
        )
        items_lay.addWidget(rail)
        items_lay.addLayout(self._items_box, stretch=1)
        lay.addWidget(items_wrap)

    def name(self) -> str:
        return UNCATEGORIZED if self.name_edit is None else self.name_edit.text().strip()

    def weight(self) -> float:
        if self.weight_edit is None:
            return 0.0
        try:
            return float(self.weight_edit.text())
        except ValueError:
            return 0.0

    def weight_valid(self) -> bool:
        if self.weight_edit is None:
            return True
        try:
            float(self.weight_edit.text())
            return True
        except ValueError:
            return False

    def mark_weight_validity(self):
        if self.weight_edit is None:
            return
        style = _entry_style()
        if not self.weight_valid():
            style += f' QLineEdit {{ border: 1px solid {T["danger_text"]}; }}'
        self.weight_edit.setStyleSheet(style)

    def add_item_row(self, row: _ItemRow):
        self._items_box.addWidget(row)

    def take_item_rows(self) -> list[_ItemRow]:
        rows = []
        while self._items_box.count():
            w = self._items_box.takeAt(0).widget()
            if isinstance(w, _ItemRow):
                rows.append(w)
        return rows

    def item_names(self) -> list[str]:
        return [self._items_box.itemAt(i).widget().name
                for i in range(self._items_box.count())
                if isinstance(self._items_box.itemAt(i).widget(), _ItemRow)]


class GradebookReviewWindow(QDialog):
    apply_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review Gradebook")
        self.setModal(False)
        self.resize(660, 620)
        self.setStyleSheet(f"QDialog {{ background: {T['bg']}; }}")
        self._sections: list[_Section] = []
        self._uncat: _Section | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        head = QHBoxLayout()
        add = QPushButton("+  Add Category")
        add.setFixedHeight(32)
        add.setStyleSheet(_btn(T["btn_muted"], T["btn_muted_h"]))
        add.clicked.connect(lambda: self._add_category("New Category", 0.0, []))
        head.addWidget(add, alignment=Qt.AlignmentFlag.AlignLeft)
        head.addStretch()
        head.addWidget(self._muted_label("Total"))
        self._total_lbl = QLabel("0%")
        self._total_lbl.setFixedHeight(26)
        self._total_lbl.setStyleSheet(self._total_style(False))
        head.addWidget(self._total_lbl)
        outer.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(_scroll_style())
        inner = QWidget()
        self._sec_layout = QVBoxLayout(inner)
        self._sec_layout.setContentsMargins(0, 0, 0, 0)
        self._sec_layout.setSpacing(10)
        self._sec_layout.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll, stretch=1)

        foot = QHBoxLayout()
        self._hint = QLabel("Weights are advisory — the final check runs after Apply.")
        self._hint.setStyleSheet(f"color: {T['text_muted']}; font-size: 11px;")
        foot.addWidget(self._hint)
        foot.addStretch()
        self._apply_btn = QPushButton("▶  Apply to Brightspace")
        self._apply_btn.setFixedHeight(38)
        self._apply_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"]))
        self._apply_btn.clicked.connect(self._on_apply)
        foot.addWidget(self._apply_btn)
        outer.addLayout(foot)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _muted_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {T['text_muted']}; font-size: 12px;")
        return lbl

    def _total_style(self, ok: bool) -> str:
        bg, fg = ("#0f3d2e", T["success"]) if ok else ("#3d2f0a", T["warn"])
        return (f"background: {bg}; color: {fg}; font-size: 13px; font-weight: 600;"
                f" border-radius: 12px; padding: 3px 12px;")

    def _insert_before_uncat(self, sec: _Section):
        # keep Uncategorized last, stretch after it
        idx = self._sec_layout.count() - 1  # before the trailing stretch
        if self._uncat is not None:
            idx = self._sec_layout.indexOf(self._uncat)
        self._sec_layout.insertWidget(idx, sec)

    # ── public interface (matches old board) ─────────────────────────────────
    def load_structure(self, structure: dict):
        for sec in self._sections:
            sec.setParent(None)
        if self._uncat is not None:
            self._uncat.setParent(None)
        self._sections = []
        self._uncat = None

        for cat in structure.get("categories", []):
            self._add_category(cat["name"], cat.get("weight", 0.0),
                               cat.get("items", []))
        # Uncategorized always present, always last.
        self._uncat = _Section(UNCATEGORIZED, None, self, removable=False)
        for name in structure.get("uncategorized", []):
            self._uncat.add_item_row(_ItemRow(name, self))
        self._sec_layout.insertWidget(self._sec_layout.count() - 1, self._uncat)
        self.recalc_total()

    def to_structure(self) -> dict:
        categories, uncategorized = [], []
        for sec in self._sections:
            categories.append({"name": sec.name(), "weight": sec.weight(),
                               "items": sec.item_names()})
        if self._uncat is not None:
            uncategorized = self._uncat.item_names()
        return {"categories": categories, "uncategorized": uncategorized}

    def invalid_weight_columns(self) -> list[str]:
        return [s.name() for s in self._sections if not s.weight_valid()]

    def section_names(self) -> list[str]:
        return [s.name() for s in self._sections] + [UNCATEGORIZED]

    # ── mutations ────────────────────────────────────────────────────────────
    def _add_category(self, name: str, weight: float, items: list[str]):
        sec = _Section(name, weight, self, removable=True)
        for it in items:
            sec.add_item_row(_ItemRow(it, self))
        self._sections.append(sec)
        self._insert_before_uncat(sec)
        self.recalc_total()
        return sec

    def remove_section(self, sec: _Section):
        if sec not in self._sections:
            return
        for row in sec.take_item_rows():          # items → Uncategorized
            self._uncat.add_item_row(row)
        self._sections.remove(sec)
        sec.setParent(None)
        self.recalc_total()

    def move_item(self, row: _ItemRow, target_name: str):
        row.setParent(None)
        target = self._uncat
        if target_name != UNCATEGORIZED:
            target = next((s for s in self._sections if s.name() == target_name),
                          self._uncat)
        target.add_item_row(row)

    def recalc_total(self):
        total = sum(s.weight() for s in self._sections if s.weight_valid())
        ok = round(total) == 100
        self._total_lbl.setText(f"{round(total)}%")
        self._total_lbl.setStyleSheet(self._total_style(ok))
        for s in self._sections:
            s.mark_weight_validity()

    # ── apply ────────────────────────────────────────────────────────────────
    def _on_apply(self):
        bad = self.invalid_weight_columns()
        if bad:
            self._hint.setText(f"⚠ Invalid weight for: {', '.join(bad)} — enter a number.")
            self._hint.setStyleSheet(f"color: {T['danger_text']}; font-size: 11px;")
            return
        structure = self.to_structure()
        if not structure["categories"]:
            self._hint.setText("⚠ Nothing to apply — add at least one category.")
            self._hint.setStyleSheet(f"color: {T['danger_text']}; font-size: 11px;")
            return
        self.apply_requested.emit(structure)
        self.hide()

    def closeEvent(self, event):
        # Hide instead of destroy so state survives; tab can re-open it.
        event.ignore()
        self.hide()
