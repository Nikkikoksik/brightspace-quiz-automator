import asyncio
import json
import os
import queue
import sys
import threading
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame, QLineEdit,
    QCheckBox, QTextEdit, QScrollArea, QSizePolicy, QTabWidget,
    QMessageBox, QDialog, QDialogButtonBox, QSpinBox,
)
from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal
from PyQt6.QtGui import QPalette, QColor, QFont, QIcon

sys.path.insert(0, str(Path(__file__).parent / "src"))

VERSION      = "v0.8.0"
_HERE        = Path(__file__).parent
ICON_PATH    = str(_HERE / "installer" / "assets" / "icon.ico")
USERDATA_DIR = Path(os.environ["APPDATA"]) / "BrightspaceAutomator"
USERDATA_DIR.mkdir(parents=True, exist_ok=True)

_CHECK_SVG = USERDATA_DIR / "check.svg"
_CHECK_SVG.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12"><polyline points="1.5,6 4.5,9.5 10.5,2.5" stroke="white" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>')
_CHECK_SVG_PATH = str(_CHECK_SVG).replace("\\", "/")

COURSES_FILE        = str(USERDATA_DIR / "courses.txt")
OUTLINE_CFG         = str(USERDATA_DIR / "outline_config.json")
NOTES_FILE          = str(USERDATA_DIR / "notes.txt")
STAGING_DONE_FILE   = str(USERDATA_DIR / "staging_done.json")
STAGING_QUEUE_FILE  = str(USERDATA_DIR / "staging_queue.txt")
SESSION_FILE_GUI    = str(USERDATA_DIR / "session.json")
COURSE_HISTORY_FILE = str(USERDATA_DIR / "course_history.json")

# ── Slate theme ───────────────────────────────────────────────────────────────
T = {
    "bg":           "#0d1117",
    "sidebar_bg":   "#010409",
    "card_bg":      "#161b22",
    "card_border":  "#21262d",
    "accent":       "#0ea5e9",
    "accent_dim":   "#0c4a6e",
    "accent_hover": "#38bdf8",
    "nav_hover":    "#161b22",
    "nav_active":   "#0c4a6e",
    "text":         "#e6edf3",
    "text_muted":   "#8b949e",
    "text_dim":     "#484f58",
    "btn_primary":  "#0ea5e9",
    "btn_primary_h":"#38bdf8",
    "btn_muted":    "#21262d",
    "btn_muted_h":  "#30363d",
    "btn_danger":   "#6e1a1a",
    "btn_danger_h": "#922222",
    "btn_add":      "#14532d",
    "btn_add_h":    "#166534",
    "warn":         "#f59e0b",
    "success":      "#22c55e",
    "terminal_bg":  "#010409",
}


def _dark_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window,          QColor(T["bg"]))
    p.setColor(QPalette.ColorRole.WindowText,      QColor(T["text"]))
    p.setColor(QPalette.ColorRole.Base,            QColor(T["card_bg"]))
    p.setColor(QPalette.ColorRole.AlternateBase,   QColor(T["sidebar_bg"]))
    p.setColor(QPalette.ColorRole.Text,            QColor(T["text"]))
    p.setColor(QPalette.ColorRole.Button,          QColor(T["btn_muted"]))
    p.setColor(QPalette.ColorRole.ButtonText,      QColor(T["text"]))
    p.setColor(QPalette.ColorRole.Highlight,       QColor(T["accent"]))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(T["text_dim"]))
    p.setColor(QPalette.ColorRole.Mid,             QColor(T["card_border"]))
    return p


# ── Style helpers ─────────────────────────────────────────────────────────────

def _btn(bg: str, hover: str, text: str = "#ffffff", radius: int = 8) -> str:
    return f"""
        QPushButton {{
            background: {bg}; color: {text}; border: none;
            border-radius: {radius}px; font-size: 13px;
            padding: 0 16px; font-weight: 600;
        }}
        QPushButton:hover {{ background: {hover}; }}
        QPushButton:disabled {{ background: {T["btn_muted"]}; color: {T["text_dim"]}; }}
    """

def _card() -> str:
    return f"QFrame {{ background: {T['card_bg']}; border: 1px solid {T['card_border']}; border-radius: 10px; }}"

def _entry_style() -> str:
    return f"""
        QLineEdit {{
            background: {T["bg"]}; color: {T["text"]};
            border: 1px solid {T["card_border"]}; border-radius: 6px;
            padding: 0 12px; font-size: 13px;
        }}
        QLineEdit:focus {{ border: 1px solid {T["accent"]}; }}
    """

def _checkbox_style(warn: bool = False) -> str:
    color = T["warn"] if warn else T["text"]
    return f"""
        QCheckBox {{ color: {color}; font-size: 13px; spacing: 8px; padding: 5px 0px; }}
        QCheckBox::indicator {{
            width: 16px; height: 16px;
            border: 1px solid {T["card_border"]}; border-radius: 4px; background: {T["bg"]};
        }}
        QCheckBox::indicator:checked {{
            background: {T["accent"]}; border: 1px solid {T["accent"]};
            image: url({_CHECK_SVG_PATH});
        }}
    """

def _log_style() -> str:
    return f"""
        QTextEdit {{
            background: {T["terminal_bg"]}; color: {T["text_muted"]};
            border: none; border-left: 2px solid {T["accent_dim"]}; border-radius: 0px;
            font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
            font-size: 12px; padding: 10px 14px;
        }}
    """

def _tab_style() -> str:
    return f"""
        QTabWidget::pane {{ border: 1px solid {T["card_border"]}; border-radius: 8px; background: {T["card_bg"]}; }}
        QTabBar::tab {{
            background: {T["btn_muted"]}; color: {T["text_muted"]};
            padding: 8px 20px; border-radius: 6px; margin-right: 4px; font-size: 12px;
        }}
        QTabBar::tab:selected {{ background: {T["nav_active"]}; color: {T["accent"]}; font-weight: 600; }}
        QTabBar::tab:hover {{ background: {T["btn_muted_h"]}; color: {T["text"]}; }}
    """

def _scroll_style() -> str:
    return f"""
        QScrollArea {{ background: transparent; border: none; }}
        QWidget {{ background: transparent; }}
        QScrollBar:vertical {{
            background: {T["bg"]}; width: 6px; border-radius: 3px;
        }}
        QScrollBar::handle:vertical {{ background: {T["card_border"]}; border-radius: 3px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    """


# ── Sentry ────────────────────────────────────────────────────────────────────

_DEFAULT_SENTRY_DSN = "https://b178c330abfc081169e6395ae85da7db@o4511530722459648.ingest.de.sentry.io/4511530734780496"

def _init_sentry(dsn: str = ""):
    try:
        import sentry_sdk
        resolved = dsn or _DEFAULT_SENTRY_DSN
        if resolved:
            sentry_sdk.init(dsn=resolved, traces_sample_rate=0, release=VERSION)
    except Exception:
        pass

def _sentry_capture(e: Exception):
    try:
        import sentry_sdk; sentry_sdk.capture_exception(e)
    except Exception:
        pass

def _sentry_context(step: str, course: str = ""):
    try:
        import sentry_sdk
        sentry_sdk.set_tag("step", step)
        if course: sentry_sdk.set_tag("course", course)
    except Exception:
        pass


# ── Cross-thread UI bridge ────────────────────────────────────────────────────

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
        self._start = QSpinBox(); self._start.setRange(1, total); self._start.setValue(1)
        self._start.setStyleSheet(f"background: {T['bg']}; color: {T['text']}; border: 1px solid {T['card_border']}; border-radius: 4px; padding: 2px 6px;")
        row.addWidget(self._start)
        row.addWidget(QLabel("To:"))
        self._end = QSpinBox(); self._end.setRange(1, total); self._end.setValue(total)
        self._end.setStyleSheet(f"background: {T['bg']}; color: {T['text']}; border: 1px solid {T['card_border']}; border-radius: 4px; padding: 2px 6px;")
        row.addWidget(self._end)
        layout.addLayout(row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.setStyleSheet(_btn(T["btn_muted"], T["btn_muted_h"]))
        btns.accepted.connect(self._ok)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _ok(self):
        self.start_val = self._start.value()
        self.end_val   = self._end.value()
        self.accept()


# ── Main window ───────────────────────────────────────────────────────────────

class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Brightspace Automator")
        self.resize(960, 820)
        self.setMinimumSize(800, 600)
        self.setStyleSheet(f"background: {T['bg']}; color: {T['text']};")
        if Path(ICON_PATH).exists():
            self.setWindowIcon(QIcon(ICON_PATH))

        self._log_queue    = queue.Queue()
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._last_quiz_urls   = []
        self._last_assign_urls = []
        self._url_rows         = []
        self._assign_url_rows  = []
        self._tfix_url_rows    = []
        self._bridge           = _ThreadBridge(self)

        self._build_ui()
        self._load_courses()
        self._load_config()
        self._load_notes()

        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_log)
        self._poll_timer.start(100)

    # ── Root layout ───────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())

        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background: {T['bg']};")
        layout.addWidget(self._stack, stretch=1)

        self._panels: dict[str, QWidget] = {}
        for key, builder in [
            ("Staging",              self._build_staging_panel),
            ("Quiz Automator",       self._build_quiz_panel),
            ("Assignment Automator", self._build_assignment_panel),
            ("Course Outline",       self._build_outline_panel),
            ("Notes",                self._build_notes_panel),
            ("Timer Fix",            self._build_timerfix_panel),
            ("Queue",                self._build_queue_panel),
            ("History",              self._build_history_panel),
            ("Settings",             self._build_settings_panel),
        ]:
            panel = QWidget()
            panel.setStyleSheet(f"background: {T['bg']};")
            builder(panel)
            self._stack.addWidget(panel)
            self._panels[key] = panel

        self._show_panel("Staging")

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setFixedWidth(210)
        sidebar.setStyleSheet(f"background: {T['sidebar_bg']};")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 16)
        layout.setSpacing(0)

        brand = QLabel("Brightspace\nAutomator")
        brand.setStyleSheet(f"color: {T['text']}; font-size: 14px; font-weight: 700; padding: 28px 20px 20px 20px; background: transparent;")
        layout.addWidget(brand)

        self._nav_btns: dict[str, QPushButton] = {}
        for key, label in [
            ("Staging", "Staging"), ("Quiz Automator", "Quizzes"),
            ("Assignment Automator", "Assignments"), ("Course Outline", "Course Outline"),
            ("Notes", "Notes"),
        ]:
            layout.addWidget(self._make_nav_btn(key, label))

        layout.addWidget(self._sidebar_divider())
        opt = QLabel("OPTIONAL")
        opt.setStyleSheet(f"color: {T['text_dim']}; font-size: 10px; font-weight: 600; letter-spacing: 1px; padding: 6px 20px 2px 20px; background: transparent;")
        layout.addWidget(opt)
        for key, label in [("Timer Fix", "Timer Fix"), ("Queue", "Queue"), ("History", "History")]:
            layout.addWidget(self._make_nav_btn(key, label))

        layout.addStretch()
        layout.addWidget(self._sidebar_divider())
        layout.addWidget(self._make_nav_btn("Settings", f"Settings  {VERSION}"))
        return sidebar

    def _make_nav_btn(self, key: str, label: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setFixedHeight(38)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _, k=key: self._show_panel(k))
        self._nav_btns[key] = btn
        self._apply_nav_style(btn, False)
        return btn

    def _sidebar_divider(self) -> QFrame:
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); line.setFixedHeight(1)
        line.setStyleSheet(f"background: {T['card_border']}; margin: 6px 16px;")
        return line

    def _apply_nav_style(self, btn: QPushButton, active: bool):
        if active:
            btn.setStyleSheet(f"""QPushButton {{ background: {T['nav_active']}; color: {T['accent']}; font-size: 13px; font-weight: 600; text-align: left; padding-left: 20px; border: none; border-radius: 6px; margin: 1px 8px; }}""")
        else:
            btn.setStyleSheet(f"""QPushButton {{ background: transparent; color: {T['text_muted']}; font-size: 13px; text-align: left; padding-left: 20px; border: none; border-radius: 6px; margin: 1px 8px; }} QPushButton:hover {{ background: {T['nav_hover']}; color: {T['text']}; }}""")

    def _show_panel(self, name: str):
        if name in self._panels:
            self._stack.setCurrentWidget(self._panels[name])
        for key, btn in self._nav_btns.items():
            self._apply_nav_style(btn, key == name)
        if name == "History":
            QTimer.singleShot(10, self._load_history_tab)

    # ── Panel helpers ─────────────────────────────────────────────────────────

    def _panel_scroll(self, parent: QWidget) -> QVBoxLayout:
        scroll = QScrollArea(parent)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(_scroll_style() + f"QScrollArea {{ background: {T['bg']}; }}")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget(); inner.setStyleSheet(f"background: {T['bg']};")
        scroll.setWidget(inner)
        outer = QVBoxLayout(parent); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        outer.addWidget(scroll)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(0)
        return layout

    def _panel_header(self, layout: QVBoxLayout, title: str, subtitle: str = ""):
        lbl = QLabel(title)
        lbl.setStyleSheet(f"color: {T['text']}; font-size: 22px; font-weight: 700; background: transparent;")
        layout.addWidget(lbl)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setStyleSheet(f"color: {T['text_muted']}; font-size: 12px; background: transparent;")
            layout.addWidget(sub)
        layout.addSpacing(16)
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); line.setFixedHeight(1)
        line.setStyleSheet(f"background: {T['card_border']};")
        layout.addWidget(line)
        layout.addSpacing(20)

    def _section_label(self, layout: QVBoxLayout, text: str):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {T['text_dim']}; font-size: 10px; font-weight: 700; letter-spacing: 1px; background: transparent;")
        layout.addWidget(lbl)
        layout.addSpacing(6)

    def _make_log(self, layout: QVBoxLayout, min_height: int = 200) -> QTextEdit:
        box = QTextEdit(); box.setReadOnly(True)
        box.setMinimumHeight(min_height); box.setStyleSheet(_log_style())
        layout.addWidget(box)
        return box

    def _log_append(self, box: QTextEdit, text: str):
        box.append(text)
        box.verticalScrollBar().setValue(box.verticalScrollBar().maximum())

    def _make_url_rows_container(self) -> tuple[QWidget, QVBoxLayout]:
        container = QWidget(); container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(4)
        return container, layout

    def _add_url_row(self, container: QWidget, rows: list, url: str = "", placeholder: str = "Paste course page URL here…"):
        row_widget = QWidget(); row_widget.setStyleSheet("background: transparent;")
        row_layout = QHBoxLayout(row_widget); row_layout.setContentsMargins(0, 0, 0, 0); row_layout.setSpacing(6)
        entry = QLineEdit(); entry.setPlaceholderText(placeholder)
        entry.setFixedHeight(36); entry.setStyleSheet(_entry_style())
        if url: entry.setText(url)
        row_layout.addWidget(entry, stretch=1)
        remove_btn = QPushButton("✕"); remove_btn.setFixedSize(36, 36)
        remove_btn.setStyleSheet(_btn("transparent", T["btn_danger_h"], T["text_dim"]))
        remove_btn.clicked.connect(lambda: self._remove_url_row(rows, row_widget))
        row_layout.addWidget(remove_btn)
        container.layout().addWidget(row_widget)
        rows.append((row_widget, entry))

    def _remove_url_row(self, rows: list, row_widget: QWidget):
        rows[:] = [(w, e) for w, e in rows if w is not row_widget]
        row_widget.deleteLater()

    # ── Staging panel ─────────────────────────────────────────────────────────

    def _build_staging_panel(self, parent: QWidget):
        layout = self._panel_scroll(parent)
        self._panel_header(layout, "Staging", "Automate the Brightspace staging process one step at a time")

        self._section_label(layout, "COURSE  —  CRN OR BRIGHTSPACE URL")
        self._staging_crn = QLineEdit()
        self._staging_crn.setPlaceholderText("e.g. 31899  or  https://learn.okanagancollege.ca/d2l/home/…")
        self._staging_crn.setFixedHeight(40); self._staging_crn.setStyleSheet(_entry_style())
        self._staging_crn.editingFinished.connect(self._auto_extract_crn)
        layout.addWidget(self._staging_crn)
        layout.addSpacing(16)

        self._staging_dryrun = QCheckBox("Dry run  (navigate only, no changes)")
        self._staging_dryrun.setStyleSheet(_checkbox_style(warn=True))
        layout.addWidget(self._staging_dryrun)
        layout.addSpacing(20)

        self._staging_steps12_btn = QPushButton("▶   Stage Course")
        self._staging_steps12_btn.setFixedHeight(52)
        self._staging_steps12_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"]) + "QPushButton { font-size: 16px; }")
        self._staging_steps12_btn.clicked.connect(self._start_staging_steps_1_2)
        layout.addWidget(self._staging_steps12_btn)
        layout.addSpacing(20)

        self._section_label(layout, "LOG")
        self._staging_log = self._make_log(layout, min_height=300)
        layout.addStretch()

    # ── Quiz panel ────────────────────────────────────────────────────────────

    def _build_quiz_panel(self, parent: QWidget):
        layout = self._panel_scroll(parent)
        self._panel_header(layout, "Quiz Automator", "Bulk-update quiz settings across courses")

        self._section_label(layout, "COURSE URLS")
        self._quiz_url_container, _ = self._make_url_rows_container()
        layout.addWidget(self._quiz_url_container)
        layout.addSpacing(6)

        add_btn = QPushButton("＋  Add course URL")
        add_btn.setFixedHeight(32)
        add_btn.setStyleSheet(_btn("transparent", T["btn_muted"], T["text_muted"]) + "QPushButton { border: 1px solid " + T["card_border"] + "; }")
        add_btn.clicked.connect(lambda: self._add_url_row(self._quiz_url_container, self._url_rows))
        layout.addWidget(add_btn)
        layout.addSpacing(16)

        self._section_label(layout, "SETTINGS")
        self._gradebook_var  = QCheckBox("Add to Grade Book");   self._gradebook_var.setChecked(True);  self._gradebook_var.setStyleSheet(_checkbox_style())
        self._autosubmit_var = QCheckBox("Auto-submit on timer expiry"); self._autosubmit_var.setChecked(True); self._autosubmit_var.setStyleSheet(_checkbox_style())
        self._quiz_dryrun    = QCheckBox("Dry run  (preview only — nothing will be saved)"); self._quiz_dryrun.setStyleSheet(_checkbox_style(warn=True))
        for cb in [self._gradebook_var, self._autosubmit_var, self._quiz_dryrun]:
            layout.addWidget(cb)
        layout.addSpacing(20)

        self._quiz_run_btn = QPushButton("▶  Run Quizzes")
        self._quiz_run_btn.setFixedHeight(52)
        self._quiz_run_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"]) + "QPushButton { font-size: 16px; }")
        self._quiz_run_btn.clicked.connect(self._start_quiz_run)
        layout.addWidget(self._quiz_run_btn)
        layout.addSpacing(6)

        self._quiz_pause_btn = QPushButton("⏸   PAUSE")
        self._quiz_pause_btn.setFixedHeight(36)
        self._quiz_pause_btn.setStyleSheet(_btn(T["btn_muted"], T["btn_muted_h"]))
        self._quiz_pause_btn.setEnabled(False)
        self._quiz_pause_btn.clicked.connect(self._toggle_quiz_pause)
        layout.addWidget(self._quiz_pause_btn)
        layout.addSpacing(6)

        self._quiz_verify_btn = QPushButton("🔍   VERIFY SETTINGS  (read-only check, no changes)")
        self._quiz_verify_btn.setFixedHeight(38)
        self._quiz_verify_btn.setStyleSheet(_btn("#1a2e1a", "#2a4a2a"))
        self._quiz_verify_btn.clicked.connect(self._start_quiz_verify)
        layout.addWidget(self._quiz_verify_btn)
        layout.addSpacing(12)

        self._section_label(layout, "LOG")
        self._quiz_log = self._make_log(layout, min_height=220)
        layout.addStretch()

    # ── Assignment panel ──────────────────────────────────────────────────────

    def _build_assignment_panel(self, parent: QWidget):
        layout = self._panel_scroll(parent)
        self._panel_header(layout, "Assignment Automator", "Bulk-update assignment settings across courses")

        self._section_label(layout, "ASSIGNMENT PAGE URLS")
        self._assign_url_container, _ = self._make_url_rows_container()
        layout.addWidget(self._assign_url_container)
        layout.addSpacing(6)

        add_btn = QPushButton("＋  Add assignment page URL")
        add_btn.setFixedHeight(32)
        add_btn.setStyleSheet(_btn("transparent", T["btn_muted"], T["text_muted"]) + "QPushButton { border: 1px solid " + T["card_border"] + "; }")
        add_btn.clicked.connect(lambda: self._add_url_row(self._assign_url_container, self._assign_url_rows))
        layout.addWidget(add_btn)
        layout.addSpacing(16)

        self._section_label(layout, "SETTINGS")
        self._assign_gradebook_var = QCheckBox("Add to Grade Book"); self._assign_gradebook_var.setChecked(True); self._assign_gradebook_var.setStyleSheet(_checkbox_style())
        self._assign_dryrun        = QCheckBox("Dry run  (preview only — nothing will be saved)"); self._assign_dryrun.setStyleSheet(_checkbox_style(warn=True))
        for cb in [self._assign_gradebook_var, self._assign_dryrun]:
            layout.addWidget(cb)
        layout.addSpacing(20)

        self._assign_run_btn = QPushButton("▶  Run Assignments")
        self._assign_run_btn.setFixedHeight(52)
        self._assign_run_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"]) + "QPushButton { font-size: 16px; }")
        self._assign_run_btn.clicked.connect(self._start_assignment_run)
        layout.addWidget(self._assign_run_btn)
        layout.addSpacing(6)

        self._assign_pause_btn = QPushButton("⏸   PAUSE")
        self._assign_pause_btn.setFixedHeight(36)
        self._assign_pause_btn.setStyleSheet(_btn(T["btn_muted"], T["btn_muted_h"]))
        self._assign_pause_btn.setEnabled(False)
        self._assign_pause_btn.clicked.connect(self._toggle_assign_pause)
        layout.addWidget(self._assign_pause_btn)
        layout.addSpacing(12)

        self._section_label(layout, "LOG")
        self._assign_log = self._make_log(layout, min_height=220)
        layout.addStretch()

    # ── Timer Fix panel ───────────────────────────────────────────────────────

    def _build_timerfix_panel(self, parent: QWidget):
        layout = self._panel_scroll(parent)
        self._panel_header(layout, "Timer Fix", "Re-run only the auto-submit timer fix — skips grade book entirely")

        self._section_label(layout, "QUIZ PAGE URLS")
        self._tfix_url_container, _ = self._make_url_rows_container()
        layout.addWidget(self._tfix_url_container)
        layout.addSpacing(6)

        add_btn = QPushButton("＋  Add quiz page URL")
        add_btn.setFixedHeight(32)
        add_btn.setStyleSheet(_btn("transparent", T["btn_muted"], T["text_muted"]) + "QPushButton { border: 1px solid " + T["card_border"] + "; }")
        add_btn.clicked.connect(lambda: self._add_url_row(self._tfix_url_rows, self._tfix_url_rows, placeholder="Paste quiz page URL here…"))
        layout.addWidget(add_btn)
        layout.addSpacing(16)

        self._tfix_dryrun   = QCheckBox("Dry run  (preview only — nothing will be saved)"); self._tfix_dryrun.setStyleSheet(_checkbox_style(warn=True))
        self._tfix_testmode = QCheckBox("Test mode  (first quiz only)"); self._tfix_testmode.setStyleSheet(_checkbox_style(warn=True))
        for cb in [self._tfix_dryrun, self._tfix_testmode]:
            layout.addWidget(cb)
        layout.addSpacing(20)

        self._tfix_run_btn = QPushButton("▶  Run Timer Fix")
        self._tfix_run_btn.setFixedHeight(52)
        self._tfix_run_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"]) + "QPushButton { font-size: 16px; }")
        self._tfix_run_btn.clicked.connect(self._start_timer_fix)
        layout.addWidget(self._tfix_run_btn)
        layout.addSpacing(20)

        self._section_label(layout, "LOG")
        self._tfix_log = self._make_log(layout, min_height=280)
        layout.addStretch()

    # ── Course Outline panel ──────────────────────────────────────────────────

    def _build_outline_panel(self, parent: QWidget):
        layout = self._panel_scroll(parent)
        self._panel_header(layout, "Course Outline", "Download, convert and paste the course outline into Brightspace")

        self._section_label(layout, "COURSE  (CRN number  or  full Brightspace URL)")
        self._outline_url = QLineEdit()
        self._outline_url.setPlaceholderText("e.g.  80147  or  https://learn.okanagancollege.ca/…")
        self._outline_url.setFixedHeight(38); self._outline_url.setStyleSheet(_entry_style())
        layout.addWidget(self._outline_url)
        layout.addSpacing(16)

        self._outline_dryrun = QCheckBox("Dry run  (download + convert only — nothing pasted into Brightspace)")
        self._outline_dryrun.setStyleSheet(_checkbox_style(warn=True))
        layout.addWidget(self._outline_dryrun)
        layout.addSpacing(20)

        self._outline_run_btn = QPushButton("▶  Run Course Outline")
        self._outline_run_btn.setFixedHeight(52)
        self._outline_run_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"]) + "QPushButton { font-size: 16px; }")
        self._outline_run_btn.clicked.connect(self._start_outline_run)
        layout.addWidget(self._outline_run_btn)
        layout.addSpacing(8)

        self._section_label(layout, "TEST INDIVIDUAL STEPS")
        self._test_step4_btn = QPushButton("▶   TEST STEP 4 ONLY  (paste existing HTML into Brightspace)")
        self._test_step4_btn.setFixedHeight(38)
        self._test_step4_btn.setStyleSheet(_btn("#1a2e1a", "#2a4a2a"))
        self._test_step4_btn.clicked.connect(self._start_test_step4)
        layout.addWidget(self._test_step4_btn)
        layout.addSpacing(12)

        self._section_label(layout, "LOG")
        self._outline_log = self._make_log(layout, min_height=220)
        layout.addStretch()

    # ── Notes panel ───────────────────────────────────────────────────────────

    def _build_notes_panel(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(0)
        self._panel_header(layout, "Course Notes", "Auto-populated from staging run. Editable.")

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        copy_btn = QPushButton("Copy All"); copy_btn.setFixedHeight(32); copy_btn.setFixedWidth(100)
        copy_btn.setStyleSheet(_btn(T["btn_muted"], T["btn_muted_h"])); copy_btn.clicked.connect(self._notes_copy)
        clear_btn = QPushButton("Clear"); clear_btn.setFixedHeight(32); clear_btn.setFixedWidth(80)
        clear_btn.setStyleSheet(_btn(T["btn_danger"], T["btn_danger_h"])); clear_btn.clicked.connect(self._notes_clear)
        btn_row.addWidget(copy_btn); btn_row.addWidget(clear_btn); btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addSpacing(12)

        self._notes_box = QTextEdit()
        self._notes_box.setStyleSheet(f"QTextEdit {{ background: {T['card_bg']}; color: {T['text']}; border: 1px solid {T['card_border']}; border-radius: 8px; font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px; padding: 12px; }}")
        self._notes_box.textChanged.connect(self._save_notes)
        layout.addWidget(self._notes_box, stretch=1)

    # ── Queue panel ───────────────────────────────────────────────────────────

    def _build_queue_panel(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(0)
        self._panel_header(layout, "Staging Queue", "Track which courses have been staged")

        top_row = QHBoxLayout(); top_row.setSpacing(8)
        self._staging_refresh_btn = QPushButton("⟳  Refresh Queue"); self._staging_refresh_btn.setFixedHeight(36)
        self._staging_refresh_btn.setStyleSheet(_btn(T["btn_muted"], T["btn_muted_h"]))
        self._staging_refresh_btn.clicked.connect(self._start_staging_refresh)
        top_row.addWidget(self._staging_refresh_btn); top_row.addStretch()
        layout.addLayout(top_row)
        layout.addSpacing(6)

        self._queue_status_label = QLabel("")
        self._queue_status_label.setStyleSheet(f"color: {T['text_muted']}; font-size: 12px; background: transparent;")
        layout.addWidget(self._queue_status_label)
        layout.addSpacing(10)

        add_row = QHBoxLayout(); add_row.setSpacing(6)
        self._queue_add_entry = QLineEdit()
        self._queue_add_entry.setPlaceholderText("Add a course (e.g. MATH-100-001-31899.202530)…")
        self._queue_add_entry.setFixedHeight(34); self._queue_add_entry.setStyleSheet(_entry_style())
        self._queue_add_entry.returnPressed.connect(self._queue_add_course)
        add_btn = QPushButton("+ Add"); add_btn.setFixedHeight(34); add_btn.setFixedWidth(70)
        add_btn.setStyleSheet(_btn(T["btn_add"], T["btn_add_h"])); add_btn.clicked.connect(self._queue_add_course)
        add_row.addWidget(self._queue_add_entry, stretch=1); add_row.addWidget(add_btn)
        layout.addLayout(add_row)
        layout.addSpacing(14)

        self._queue_tabs = QTabWidget()
        self._queue_tabs.setStyleSheet(_tab_style())
        layout.addWidget(self._queue_tabs, stretch=1)

        self._queue_todo_scroll = QScrollArea(); self._queue_todo_scroll.setWidgetResizable(True); self._queue_todo_scroll.setStyleSheet(_scroll_style())
        self._queue_todo_inner = QWidget(); self._queue_todo_layout = QVBoxLayout(self._queue_todo_inner); self._queue_todo_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._queue_todo_scroll.setWidget(self._queue_todo_inner)
        self._queue_tabs.addTab(self._queue_todo_scroll, "To Do")

        self._queue_done_scroll = QScrollArea(); self._queue_done_scroll.setWidgetResizable(True); self._queue_done_scroll.setStyleSheet(_scroll_style())
        self._queue_done_inner = QWidget(); self._queue_done_layout = QVBoxLayout(self._queue_done_inner); self._queue_done_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._queue_done_scroll.setWidget(self._queue_done_inner)
        self._queue_tabs.addTab(self._queue_done_scroll, "Done")

        self._load_staging_queue_list()

    # ── History panel ─────────────────────────────────────────────────────────

    def _build_history_panel(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(0)
        self._panel_header(layout, "History", "Completed quiz and assignment runs")

        self._history_search = QLineEdit(); self._history_search.setPlaceholderText("Search by URL…")
        self._history_search.setFixedHeight(32); self._history_search.setStyleSheet(_entry_style())
        self._history_search.textChanged.connect(lambda: self._load_history_tab())
        layout.addWidget(self._history_search)
        layout.addSpacing(10)

        self._history_scroll = QScrollArea(); self._history_scroll.setWidgetResizable(True); self._history_scroll.setStyleSheet(_scroll_style())
        self._history_inner = QWidget(); self._history_layout = QVBoxLayout(self._history_inner); self._history_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._history_scroll.setWidget(self._history_inner)
        layout.addWidget(self._history_scroll, stretch=1)

    # ── Settings panel ────────────────────────────────────────────────────────

    def _build_settings_panel(self, parent: QWidget):
        layout = self._panel_scroll(parent)
        self._panel_header(layout, "Settings", "Credentials and global configuration")

        self._section_label(layout, "COURSEBRIDGE")
        cb_frame = QFrame(); cb_frame.setStyleSheet(_card())
        cb_layout = QVBoxLayout(cb_frame); cb_layout.setContentsMargins(16, 16, 16, 16); cb_layout.setSpacing(8)
        cb_layout.addWidget(QLabel("Email"))
        self._cb_email = QLineEdit(); self._cb_email.setFixedHeight(36); self._cb_email.setStyleSheet(_entry_style())
        cb_layout.addWidget(self._cb_email)
        cb_layout.addWidget(QLabel("Password"))
        self._cb_password = QLineEdit(); self._cb_password.setFixedHeight(36); self._cb_password.setEchoMode(QLineEdit.EchoMode.Password); self._cb_password.setStyleSheet(_entry_style())
        cb_layout.addWidget(self._cb_password)
        layout.addWidget(cb_frame)
        layout.addSpacing(16)

        self._section_label(layout, "BRIGHTSPACE SESSION")
        bs_frame = QFrame(); bs_frame.setStyleSheet(_card())
        bs_layout = QVBoxLayout(bs_frame); bs_layout.setContentsMargins(16, 16, 16, 16); bs_layout.setSpacing(8)
        bs_layout.addWidget(QLabel("Username"))
        self._bs_username = QLineEdit(); self._bs_username.setFixedHeight(36); self._bs_username.setStyleSheet(_entry_style())
        bs_layout.addWidget(self._bs_username)
        bs_layout.addWidget(QLabel("Password"))
        self._bs_password = QLineEdit(); self._bs_password.setFixedHeight(36); self._bs_password.setEchoMode(QLineEdit.EchoMode.Password); self._bs_password.setStyleSheet(_entry_style())
        bs_layout.addWidget(self._bs_password)
        session_exists = os.path.exists(SESSION_FILE_GUI)
        self._bs_status = QLabel("✓  Session saved" if session_exists else "✗  No session — log in first")
        self._bs_status.setStyleSheet(f"color: {T['success'] if session_exists else T['warn']}; font-size: 12px;")
        bs_layout.addWidget(self._bs_status)
        btn_row2 = QHBoxLayout(); btn_row2.setSpacing(8)
        self._bs_login_btn = QPushButton("Login to Brightspace"); self._bs_login_btn.setFixedHeight(36)
        self._bs_login_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"])); self._bs_login_btn.clicked.connect(self._start_bs_login)
        clear_sess_btn = QPushButton("Clear Session"); clear_sess_btn.setFixedHeight(36)
        clear_sess_btn.setStyleSheet(_btn(T["btn_danger"], T["btn_danger_h"])); clear_sess_btn.clicked.connect(self._clear_bs_session)
        btn_row2.addWidget(self._bs_login_btn); btn_row2.addWidget(clear_sess_btn); btn_row2.addStretch()
        bs_layout.addLayout(btn_row2)
        layout.addWidget(bs_frame)
        layout.addSpacing(16)

        self._section_label(layout, "ERROR REPORTING (SENTRY)")
        sentry_frame = QFrame(); sentry_frame.setStyleSheet(_card())
        sentry_layout = QVBoxLayout(sentry_frame); sentry_layout.setContentsMargins(16, 16, 16, 16); sentry_layout.setSpacing(8)
        sentry_layout.addWidget(QLabel("Sentry DSN  (leave blank to disable)"))
        self._sentry_dsn = QLineEdit(); self._sentry_dsn.setPlaceholderText("https://...@sentry.io/...")
        self._sentry_dsn.setFixedHeight(36); self._sentry_dsn.setStyleSheet(_entry_style())
        sentry_layout.addWidget(self._sentry_dsn)
        layout.addWidget(sentry_frame)
        layout.addSpacing(20)

        self._save_settings_btn = QPushButton("Save Settings"); self._save_settings_btn.setFixedHeight(42); self._save_settings_btn.setFixedWidth(160)
        self._save_settings_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"])); self._save_settings_btn.clicked.connect(self._save_settings)
        layout.addWidget(self._save_settings_btn)
        layout.addStretch()

    # ── Log polling ───────────────────────────────────────────────────────────

    def _poll_log(self):
        try:
            while True:
                tag, msg = self._log_queue.get_nowait()
                box = {"quiz": getattr(self, "_quiz_log", None), "assign": getattr(self, "_assign_log", None),
                       "tfix": getattr(self, "_tfix_log", None), "staging": getattr(self, "_staging_log", None),
                       "outline": getattr(self, "_outline_log", None)}.get(tag, getattr(self, "_outline_log", None))

                if tag == "note":
                    if hasattr(self, "_notes_box"):
                        self._notes_box.append(msg); self._save_notes()
                    if hasattr(self, "_staging_log"):
                        self._log_append(self._staging_log, "📝  Note added — review in the Notes tab")
                    continue

                if msg == "__QUIZ_DONE__":
                    self._quiz_run_btn.setEnabled(True); self._quiz_run_btn.setText("▶  Run Quizzes")
                    self._quiz_pause_btn.setEnabled(False); self._quiz_pause_btn.setText("⏸   PAUSE")
                    self._quiz_verify_btn.setEnabled(True)
                    self._resume_event.set()
                    QTimer.singleShot(0, self._post_quiz_review)
                elif msg == "__ASSIGN_DONE__":
                    self._assign_run_btn.setEnabled(True); self._assign_run_btn.setText("▶  Run Assignments")
                    self._assign_pause_btn.setEnabled(False); self._assign_pause_btn.setText("⏸   PAUSE")
                    self._resume_event.set()
                    QTimer.singleShot(0, self._post_assign_review)
                elif msg == "__DONE__":
                    if tag == "quiz":
                        self._quiz_run_btn.setEnabled(True); self._quiz_run_btn.setText("▶  Run Quizzes")
                        self._quiz_pause_btn.setEnabled(False); self._quiz_verify_btn.setEnabled(True)
                        self._resume_event.set()
                    elif tag == "assign":
                        self._assign_run_btn.setEnabled(True); self._assign_run_btn.setText("▶  Run Assignments")
                        self._assign_pause_btn.setEnabled(False); self._resume_event.set()
                    elif tag == "tfix":
                        self._tfix_run_btn.setEnabled(True); self._tfix_run_btn.setText("▶  Run Timer Fix")
                    elif tag == "staging":
                        self._staging_steps12_btn.setEnabled(True); self._staging_steps12_btn.setText("▶   Stage Course")
                    elif tag == "outline":
                        self._outline_run_btn.setEnabled(True); self._outline_run_btn.setText("▶  Run Course Outline")
                elif box:
                    self._log_append(box, msg)
        except queue.Empty:
            pass

    # ── Config persistence ────────────────────────────────────────────────────

    def _load_courses(self):
        try:
            with open(COURSES_FILE) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        self._add_url_row(self._quiz_url_container, self._url_rows, url=line)
        except FileNotFoundError:
            pass
        if not self._url_rows:
            self._add_url_row(self._quiz_url_container, self._url_rows)
        self._add_url_row(self._assign_url_container, self._assign_url_rows)
        self._add_url_row(self._tfix_url_container, self._tfix_url_rows, placeholder="Paste quiz page URL here…")

    def _save_courses(self, urls: list):
        with open(COURSES_FILE, "w") as f:
            for url in urls:
                f.write(url + "\n")

    def _load_config(self):
        try:
            with open(OUTLINE_CFG) as f:
                cfg = json.load(f)
            if cfg.get("course_url"):  self._outline_url.setText(cfg["course_url"])
            if cfg.get("cb_email"):    self._cb_email.setText(cfg["cb_email"])
            if cfg.get("cb_password"): self._cb_password.setText(cfg["cb_password"])
            if cfg.get("bs_username"): self._bs_username.setText(cfg["bs_username"])
            if cfg.get("bs_password"): self._bs_password.setText(cfg["bs_password"])
            if cfg.get("sentry_dsn"):  self._sentry_dsn.setText(cfg["sentry_dsn"]); _init_sentry(cfg["sentry_dsn"])
            else: _init_sentry()
        except (FileNotFoundError, json.JSONDecodeError):
            _init_sentry()

    def _save_config(self, course_url=None, email=None, password=None, sentry_dsn=None, bs_username=None, bs_password=None):
        try:
            with open(OUTLINE_CFG) as f: cfg = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            cfg = {}
        if course_url  is not None: cfg["course_url"]   = course_url
        if email       is not None: cfg["cb_email"]      = email
        if password    is not None: cfg["cb_password"]   = password
        if sentry_dsn  is not None: cfg["sentry_dsn"]   = sentry_dsn
        if bs_username is not None: cfg["bs_username"]   = bs_username
        if bs_password is not None: cfg["bs_password"]   = bs_password
        with open(OUTLINE_CFG, "w") as f: json.dump(cfg, f)

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

    def _save_notes(self):
        try:
            with open(NOTES_FILE, "w", encoding="utf-8") as f:
                f.write(self._notes_box.toPlainText())
        except Exception:
            pass

    def _notes_copy(self):
        text = self._notes_box.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)

    def _notes_clear(self):
        self._notes_box.clear(); self._save_notes()

    # ── Settings actions ──────────────────────────────────────────────────────

    def _save_settings(self):
        dsn = self._sentry_dsn.text().strip()
        self._save_config(
            email=self._cb_email.text().strip(),
            password=self._cb_password.text().strip(),
            sentry_dsn=dsn,
            bs_username=self._bs_username.text().strip(),
            bs_password=self._bs_password.text().strip(),
        )
        _init_sentry(dsn)
        self._save_settings_btn.setText("✓  Saved")
        QTimer.singleShot(1500, lambda: self._save_settings_btn.setText("Save Settings"))

    def _start_bs_login(self):
        self._bs_login_btn.setEnabled(False); self._bs_login_btn.setText("Opening browser…")
        q = self._log_queue
        def worker():
            from browser import run_bs_login
            class W:
                def write(self, t):
                    if t.strip(): q.put(("outline", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try:
                asyncio.run(run_bs_login())
                QTimer.singleShot(0, lambda: self._bs_status.setText("✓  Session saved") or self._bs_status.setStyleSheet(f"color: {T['success']}; font-size: 12px;"))
            except Exception as e:
                _sentry_capture(e); q.put(("outline", f"✗  Login failed: {e}"))
            finally:
                sys.stdout = old
                QTimer.singleShot(0, lambda: (self._bs_login_btn.setEnabled(True), self._bs_login_btn.setText("Login to Brightspace")))
        threading.Thread(target=worker, daemon=True).start()

    def _clear_bs_session(self):
        if os.path.exists(SESSION_FILE_GUI): os.remove(SESSION_FILE_GUI)
        self._bs_status.setText("✗  No session — log in first")
        self._bs_status.setStyleSheet(f"color: {T['warn']}; font-size: 12px;")

    # ── Queue helpers ─────────────────────────────────────────────────────────

    def _queue_add_course(self):
        course = self._queue_add_entry.text().strip()
        if not course: return
        try:
            with open(STAGING_QUEUE_FILE, encoding="utf-8") as f: existing = [l.strip() for l in f if l.strip()]
        except FileNotFoundError:
            existing = []
        if course not in existing:
            existing.append(course)
            with open(STAGING_QUEUE_FILE, "w", encoding="utf-8") as f: f.write("\n".join(existing) + "\n")
        self._queue_add_entry.clear(); self._load_staging_queue_list()

    def _done_set(self) -> set:
        try:
            with open(STAGING_DONE_FILE, encoding="utf-8") as f: return set(json.load(f))
        except Exception: return set()

    def _save_done_set(self, done: set):
        with open(STAGING_DONE_FILE, "w", encoding="utf-8") as f: json.dump(sorted(done), f, indent=2)

    def _toggle_course_done(self, course: str):
        done = self._done_set()
        done.discard(course) if course in done else done.add(course)
        self._save_done_set(done); self._load_staging_queue_list()

    def _queue_delete_course(self, course: str):
        try:
            with open(STAGING_QUEUE_FILE, encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip() and l.strip() != course]
        except FileNotFoundError: lines = []
        with open(STAGING_QUEUE_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        done = self._done_set(); done.discard(course); self._save_done_set(done)
        self._load_staging_queue_list()

    def _load_staging_queue_list(self):
        if not hasattr(self, "_queue_todo_layout"): return
        for layout in [self._queue_todo_layout, self._queue_done_layout]:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget(): item.widget().deleteLater()
        try:
            with open(STAGING_QUEUE_FILE, encoding="utf-8") as f: courses = [l.strip() for l in f if l.strip()]
        except FileNotFoundError: courses = []
        done = self._done_set()
        pending = [c for c in courses if c not in done]
        completed = [c for c in courses if c in done]
        total = len(courses)
        if hasattr(self, "_queue_status_label"):
            self._queue_status_label.setText(
                f"{len(completed)} of {total} done  ·  {total - len(completed)} remaining" if total
                else "No courses yet — click Refresh or add one above"
            )

        def make_row(parent_layout, course, is_done):
            row = QWidget(); row.setStyleSheet("background: transparent;")
            row_l = QHBoxLayout(row); row_l.setContentsMargins(0, 0, 0, 0); row_l.setSpacing(4)
            bg  = "#141a14" if is_done else "#1c1c2e"
            hov = "#1a2a1a" if is_done else "#22334a"
            col = "#4a7a4a" if is_done else "#b0b8cc"
            btn = QPushButton(f"  {course}"); btn.setFixedHeight(30)
            btn.setStyleSheet(f"QPushButton {{ background: {bg}; color: {col}; border: none; border-radius: 6px; text-align: left; padding-left: 8px; font-family: 'Consolas', monospace; font-size: 12px; }} QPushButton:hover {{ background: {hov}; }}")
            btn.clicked.connect(lambda _, c=course: self._toggle_course_done(c))
            row_l.addWidget(btn, stretch=1)
            del_btn = QPushButton("×"); del_btn.setFixedSize(28, 30)
            del_btn.setStyleSheet(_btn("transparent", "#3a1a1a", "#554444"))
            del_btn.clicked.connect(lambda _, c=course: self._queue_delete_course(c))
            row_l.addWidget(del_btn)
            parent_layout.addWidget(row)

        if pending:
            for c in pending: make_row(self._queue_todo_layout, c, False)
        else:
            lbl = QLabel("Nothing left to do!" if courses else "No courses yet — click Refresh or add one above")
            lbl.setStyleSheet(f"color: {T['text_dim']}; font-size: 12px; padding: 10px;"); self._queue_todo_layout.addWidget(lbl)
        if completed:
            for c in completed: make_row(self._queue_done_layout, c, True)
        else:
            lbl = QLabel("No completed courses yet."); lbl.setStyleSheet(f"color: {T['text_dim']}; font-size: 12px; padding: 10px;"); self._queue_done_layout.addWidget(lbl)

    # ── History ───────────────────────────────────────────────────────────────

    def _load_history_tab(self):
        if not hasattr(self, "_history_layout"): return
        while self._history_layout.count():
            item = self._history_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        term = self._history_search.text().strip().lower() if hasattr(self, "_history_search") else ""
        try:
            with open(COURSE_HISTORY_FILE, encoding="utf-8") as f: entries = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): entries = []
        filtered = [e for e in reversed(entries) if not term or term in e.get("url", "").lower()]
        if not filtered:
            lbl = QLabel("No history yet." if not term else "No matches.")
            lbl.setStyleSheet(f"color: {T['text_dim']}; font-size: 12px; padding: 10px;"); self._history_layout.addWidget(lbl); return
        for entry in filtered:
            url   = entry.get("url", ""); kind = entry.get("type", "quiz")
            ts    = entry.get("timestamp", "")[:16].replace("T", " ")
            icon  = "[Q]" if kind == "quiz" else "[A]"
            short = url[-72:] if len(url) > 72 else url
            row = QFrame(); row.setStyleSheet(f"QFrame {{ background: {T['card_bg']}; border: 1px solid {T['card_border']}; border-radius: 6px; }}")
            row_l = QHBoxLayout(row); row_l.setContentsMargins(8, 5, 8, 5)
            txt = QLabel(f"{icon}  {short}"); txt.setStyleSheet(f"color: {T['text_muted']}; font-family: 'Consolas', monospace; font-size: 11px; border: none;"); row_l.addWidget(txt, stretch=1)
            ts_lbl = QLabel(ts); ts_lbl.setStyleSheet(f"color: {T['text_dim']}; font-size: 10px; border: none;"); row_l.addWidget(ts_lbl)
            self._history_layout.addWidget(row)

    def _append_history(self, urls: list, kind: str):
        try:
            try:
                with open(COURSE_HISTORY_FILE, encoding="utf-8") as f: entries = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError): entries = []
            ts = datetime.now().isoformat(timespec="seconds")
            for url in urls: entries.append({"url": url, "type": kind, "timestamp": ts})
            with open(COURSE_HISTORY_FILE, "w", encoding="utf-8") as f: json.dump(entries, f, indent=2)
        except Exception: pass

    # ── Ask-range helper ──────────────────────────────────────────────────────

    def _make_ask_fn(self):
        bridge = self._bridge
        def ask(total, label):
            return bridge.ask_range(total, label)
        return ask

    # ── Post-run review prompts ───────────────────────────────────────────────

    def _post_quiz_review(self):
        r = QMessageBox.question(self, "Run Assignments?",
            "Would you also like to run the Assignment Automator\nfor the same course(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            self._run_assignments_for(self._last_quiz_urls)

    def _post_assign_review(self):
        r = QMessageBox.question(self, "Run Quizzes?",
            "Would you also like to run the Quiz Automator\nfor the same course(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            self._run_quizzes_for(self._last_assign_urls)

    # ── Staging run ───────────────────────────────────────────────────────────

    def _auto_extract_crn(self):
        val = self._staging_crn.text().strip()
        if not val.startswith("http") or getattr(self, "_crn_extracting", False): return
        self._crn_extracting = True; q = self._log_queue
        def worker():
            from playwright.async_api import async_playwright
            import re as _re
            import json as _json
            from urllib.parse import urlparse
            async def run():
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    ctx = await browser.new_context(storage_state=SESSION_FILE_GUI if os.path.exists(SESSION_FILE_GUI) else None)
                    page = await ctx.new_page()
                    await page.goto(val)
                    await page.wait_for_load_state("domcontentloaded")
                    await page.wait_for_timeout(1500)
                    # For /d2l/home/{id} URLs, try LP API first — returns full course code as JSON
                    home_m = _re.search(r'/d2l/(?:home|le/[^/]+)/(\d+)', val)
                    if home_m:
                        parsed = urlparse(val)
                        base = f"{parsed.scheme}://{parsed.netloc}"
                        org_id = home_m.group(1)
                        api_url = f"{base}/d2l/api/lp/1.9/courses/{org_id}"
                        try:
                            resp = await page.evaluate(f"""
                                async () => {{
                                    const r = await fetch('{api_url}');
                                    if (r.ok) return await r.text();
                                    return null;
                                }}
                            """)
                            if resp:
                                data = _json.loads(resp)
                                code = data.get("Code", "")
                                if code:
                                    await browser.close()
                                    return code
                        except Exception:
                            pass
                    text = await page.title() + " " + await page.evaluate("document.body.innerText")
                    await browser.close()
                    return text
            try:
                text = asyncio.run(run())
                m = _re.search(r'[A-Z][A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+-(\d+)\.\d+', text)
                if m:
                    crn = m.group(1)
                    QTimer.singleShot(0, lambda: self._staging_crn.setText(crn))
                    q.put(("staging", f"✓  Extracted CRN: {crn}"))
                else:
                    import re as _re2
                    if _re2.search(r'/d2l/(?:home|le/[^/]+)/\d+', val):
                        q.put(("staging", "ℹ  No CRN on this page — URL will be used directly."))
                    else:
                        q.put(("staging", "⚠  Could not find a course code on that page."))
            except Exception as e: q.put(("staging", f"✗  {e}"))
            finally: self._crn_extracting = False
        threading.Thread(target=worker, daemon=True).start()

    def _start_staging_steps_1_2(self):
        crn = self._staging_crn.text().strip()
        if not crn: self._log_append(self._staging_log, "⚠  Enter a CRN or URL."); return
        self._staging_steps12_btn.setEnabled(False); self._staging_steps12_btn.setText("Running…")
        self._staging_log.clear(); dry_run = self._staging_dryrun.isChecked(); q = self._log_queue
        bridge = self._bridge
        def worker():
            from staging_automator import run_steps_1_2
            class W:
                def write(self, t):
                    if t.strip(): q.put(("staging", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try:
                _sentry_context("staging", crn)
                asyncio.run(run_steps_1_2(crn, dry_run=dry_run, prompt_fn=bridge.prompt, note_fn=lambda t: q.put(("note", t))))
            except Exception as e: _sentry_capture(e); q.put(("staging", f"✗  {e}"))
            finally: sys.stdout = old; q.put(("staging", "__DONE__"))
        threading.Thread(target=worker, daemon=True).start()

    def _start_staging_refresh(self):
        self._staging_refresh_btn.setEnabled(False); self._staging_refresh_btn.setText("Refreshing…")
        q = self._log_queue
        def worker():
            from staging_scraper import scrape, should_process
            class W:
                def write(self, t):
                    if t.strip(): q.put(("staging", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try:
                courses = asyncio.run(scrape()); filtered = [c for c in sorted(courses) if should_process(c)]
                skipped = len(courses) - len(filtered)
                with open(STAGING_QUEUE_FILE, "w", encoding="utf-8") as f:
                    for c in filtered: f.write(c + "\n")
                print(f"\n✓ Queue updated — {len(filtered)} course(s) to stage  ({skipped} skipped)")
                for c in filtered: print(f"   {c}")
            except Exception as e: _sentry_capture(e); q.put(("staging", f"✗  {e}"))
            finally:
                sys.stdout = old
                QTimer.singleShot(0, lambda: (self._staging_refresh_btn.setEnabled(True), self._staging_refresh_btn.setText("⟳  Refresh Queue"), self._load_staging_queue_list()))
        threading.Thread(target=worker, daemon=True).start()

    # ── Quiz run ──────────────────────────────────────────────────────────────

    def _start_quiz_run(self):
        urls = [e.text().strip() for _, e in self._url_rows if e.text().strip()]
        if not urls: self._log_append(self._quiz_log, "⚠  No URLs entered."); return
        self._save_courses(urls); self._last_quiz_urls = urls
        self._quiz_run_btn.setEnabled(False); self._quiz_run_btn.setText("Running…")
        self._quiz_pause_btn.setEnabled(True); self._quiz_verify_btn.setEnabled(False)
        self._resume_event.set(); self._quiz_log.clear()
        settings = {"set_in_gradebook": self._gradebook_var.isChecked(), "set_auto_submit": self._autosubmit_var.isChecked()}
        dry_run = self._quiz_dryrun.isChecked(); ask_fn = self._make_ask_fn(); q = self._log_queue; resume = self._resume_event
        bridge = self._bridge
        def pause_fn():
            if not resume.is_set():
                q.put(("quiz", "⏸  Paused — click Resume to continue...")); resume.wait(); q.put(("quiz", "▶  Resuming..."))
        def review_fn(): bridge.review("Quizzes Complete", "All quizzes processed.\n\nReview the browser for any errors, then click OK to close it.")
        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("quiz", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W(); success = False
            try:
                _sentry_context("quizzes", urls[0] if urls else "")
                from browser import run as browser_run
                asyncio.run(browser_run(urls=urls, dry_run=dry_run, settings=settings, pause_fn=pause_fn, ask_fn=ask_fn, review_fn=review_fn))
                success = True; self._append_history(urls, "quiz")
            except Exception as e: _sentry_capture(e); q.put(("quiz", f"✗  {e}"))
            finally: sys.stdout = old; q.put(("quiz", "__QUIZ_DONE__" if success else "__DONE__"))
        threading.Thread(target=worker, daemon=True).start()

    def _toggle_quiz_pause(self):
        if self._resume_event.is_set():
            self._resume_event.clear(); self._quiz_pause_btn.setText("▶   RESUME")
            self._quiz_pause_btn.setStyleSheet(_btn("#1a3a1a", "#2a5a2a"))
        else:
            self._resume_event.set(); self._quiz_pause_btn.setText("⏸   PAUSE")
            self._quiz_pause_btn.setStyleSheet(_btn(T["btn_muted"], T["btn_muted_h"]))

    def _start_quiz_verify(self):
        urls = [e.text().strip() for _, e in self._url_rows if e.text().strip()]
        if not urls: self._log_append(self._quiz_log, "⚠  No course URLs entered."); return
        self._quiz_verify_btn.setEnabled(False); self._quiz_verify_btn.setText("Verifying…")
        self._quiz_log.clear(); q = self._log_queue
        def worker():
            from browser import run_verify
            class W:
                def write(self, t):
                    if t.strip(): q.put(("quiz", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try: asyncio.run(run_verify(urls))
            except Exception as e: _sentry_capture(e); q.put(("quiz", f"✗  {e}"))
            finally: sys.stdout = old; q.put(("quiz", "__DONE__"))
        threading.Thread(target=worker, daemon=True).start()

    def _run_quizzes_for(self, urls: list):
        if not urls: return
        self._show_panel("Quiz Automator"); self._last_quiz_urls = urls
        self._quiz_run_btn.setEnabled(False); self._quiz_run_btn.setText("Running…")
        self._quiz_pause_btn.setEnabled(True); self._quiz_verify_btn.setEnabled(False)
        self._resume_event.set(); self._quiz_log.clear()
        settings = {"set_in_gradebook": self._gradebook_var.isChecked(), "set_auto_submit": self._autosubmit_var.isChecked()}
        dry_run = self._quiz_dryrun.isChecked(); ask_fn = self._make_ask_fn(); q = self._log_queue; resume = self._resume_event
        bridge = self._bridge
        def pause_fn():
            if not resume.is_set():
                q.put(("quiz", "⏸  Paused...")); resume.wait(); q.put(("quiz", "▶  Resuming..."))
        def review_fn(): bridge.review("All Done!", "Assignments and quizzes are both complete.\n\nClick OK to close the browser.")
        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("quiz", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try:
                _sentry_context("quizzes", urls[0] if urls else "")
                from browser import run as browser_run
                asyncio.run(browser_run(urls=urls, dry_run=dry_run, settings=settings, pause_fn=pause_fn, ask_fn=ask_fn, review_fn=review_fn))
            except Exception as e: _sentry_capture(e); q.put(("quiz", f"✗  {e}"))
            finally: sys.stdout = old; q.put(("quiz", "__DONE__"))
        threading.Thread(target=worker, daemon=True).start()

    # ── Assignment run ────────────────────────────────────────────────────────

    def _start_assignment_run(self):
        urls = [e.text().strip() for _, e in self._assign_url_rows if e.text().strip()]
        if not urls: self._log_append(self._assign_log, "⚠  No URLs entered."); return
        self._last_assign_urls = urls
        self._assign_run_btn.setEnabled(False); self._assign_run_btn.setText("Running…")
        self._assign_pause_btn.setEnabled(True); self._resume_event.set(); self._assign_log.clear()
        settings = {"set_in_gradebook": self._assign_gradebook_var.isChecked()}
        dry_run = self._assign_dryrun.isChecked(); ask_fn = self._make_ask_fn(); q = self._log_queue; resume = self._resume_event
        bridge = self._bridge
        def pause_fn():
            if not resume.is_set():
                q.put(("assign", "⏸  Paused...")); resume.wait(); q.put(("assign", "▶  Resuming..."))
        def review_fn(): bridge.review("Assignments Complete", "All assignments processed.\n\nClick OK to close the browser.")
        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("assign", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W(); success = False
            try:
                _sentry_context("assignments", urls[0] if urls else "")
                from browser import run_assignments
                asyncio.run(run_assignments(urls=urls, dry_run=dry_run, settings=settings, pause_fn=pause_fn, ask_fn=ask_fn, review_fn=review_fn))
                success = True; self._append_history(urls, "assignment")
            except Exception as e: _sentry_capture(e); q.put(("assign", f"✗  {e}"))
            finally: sys.stdout = old; q.put(("assign", "__ASSIGN_DONE__" if success else "__DONE__"))
        threading.Thread(target=worker, daemon=True).start()

    def _toggle_assign_pause(self):
        if self._resume_event.is_set():
            self._resume_event.clear(); self._assign_pause_btn.setText("▶   RESUME")
            self._assign_pause_btn.setStyleSheet(_btn("#1a3a1a", "#2a5a2a"))
        else:
            self._resume_event.set(); self._assign_pause_btn.setText("⏸   PAUSE")
            self._assign_pause_btn.setStyleSheet(_btn(T["btn_muted"], T["btn_muted_h"]))

    def _run_assignments_for(self, urls: list):
        if not urls: return
        self._show_panel("Assignment Automator"); self._last_assign_urls = urls
        self._assign_run_btn.setEnabled(False); self._assign_run_btn.setText("Running…")
        self._assign_pause_btn.setEnabled(True); self._resume_event.set(); self._assign_log.clear()
        settings = {"set_in_gradebook": self._assign_gradebook_var.isChecked()}
        dry_run = self._assign_dryrun.isChecked(); ask_fn = self._make_ask_fn(); q = self._log_queue; resume = self._resume_event
        bridge = self._bridge
        def pause_fn():
            if not resume.is_set():
                q.put(("assign", "⏸  Paused...")); resume.wait(); q.put(("assign", "▶  Resuming..."))
        def review_fn(): bridge.review("All Done!", "Quizzes and assignments are both complete.\n\nClick OK to close the browser.")
        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("assign", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try:
                from browser import run_assignments
                asyncio.run(run_assignments(urls=urls, dry_run=dry_run, settings=settings, pause_fn=pause_fn, ask_fn=ask_fn, review_fn=review_fn))
            except Exception as e: _sentry_capture(e); q.put(("assign", f"✗  {e}"))
            finally: sys.stdout = old; q.put(("assign", "__DONE__"))
        threading.Thread(target=worker, daemon=True).start()

    # ── Timer Fix run ─────────────────────────────────────────────────────────

    def _start_timer_fix(self):
        urls = [e.text().strip() for _, e in self._tfix_url_rows if e.text().strip()]
        if not urls: self._log_append(self._tfix_log, "⚠  No URLs entered."); return
        self._tfix_run_btn.setEnabled(False); self._tfix_run_btn.setText("Running…"); self._tfix_log.clear()
        dry_run = self._tfix_dryrun.isChecked(); test_mode = self._tfix_testmode.isChecked()
        ask_fn = self._make_ask_fn(); q = self._log_queue
        def worker():
            from browser import run_timer_fix
            class W:
                def write(self, t):
                    if t.strip(): q.put(("tfix", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try:
                _sentry_context("timer_fix", urls[0] if urls else "")
                asyncio.run(run_timer_fix(urls=urls, dry_run=dry_run, ask_fn=ask_fn, limit=1 if test_mode else None))
            except Exception as e: _sentry_capture(e); q.put(("tfix", f"✗  {e}"))
            finally: sys.stdout = old; q.put(("tfix", "__DONE__"))
        threading.Thread(target=worker, daemon=True).start()

    # ── Course Outline run ────────────────────────────────────────────────────

    def _start_outline_run(self):
        course_url = self._outline_url.text().strip()
        email = self._cb_email.text().strip(); password = self._cb_password.text().strip()
        if not course_url: self._log_append(self._outline_log, "⚠  Course URL is required."); return
        if not email or not password: self._log_append(self._outline_log, "⚠  CourseBridge credentials required — go to Settings."); return
        self._outline_run_btn.setEnabled(False); self._outline_run_btn.setText("Running…"); self._outline_log.clear()
        self._save_config(course_url=course_url, email=email, password=password)
        dry_run = self._outline_dryrun.isChecked(); q = self._log_queue; bridge = self._bridge
        def worker():
            from course_outline_automator import run as outline_run
            class W:
                def write(self, t):
                    if t.strip(): q.put(("outline", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try:
                asyncio.run(outline_run(dry_run=dry_run, course_url=course_url, email=email, password=password, prompt_fn=bridge.prompt))
            except Exception as e: _sentry_capture(e); q.put(("outline", f"✗  {e}"))
            finally: sys.stdout = old; q.put(("outline", "__DONE__"))
        threading.Thread(target=worker, daemon=True).start()

    def _start_test_step4(self):
        course_url = self._outline_url.text().strip()
        if not course_url: self._log_append(self._outline_log, "⚠  Course URL or CRN is required."); return
        self._test_step4_btn.setEnabled(False); self._test_step4_btn.setText("Running…"); self._outline_log.clear()
        q = self._log_queue
        def worker():
            from course_outline_automator import test_step4
            class W:
                def write(self, t):
                    if t.strip(): q.put(("outline", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try: asyncio.run(test_step4(course_url=course_url))
            except Exception as e: _sentry_capture(e); q.put(("outline", f"✗  {e}"))
            finally:
                sys.stdout = old
                QTimer.singleShot(0, lambda: (self._test_step4_btn.setEnabled(True), self._test_step4_btn.setText("▶   TEST STEP 4 ONLY  (paste existing HTML into Brightspace)")))
        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BrightspaceAutomator")
        sys.stdout.reconfigure(encoding="utf-8")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    app.setFont(QFont("Segoe UI", 10))
    if Path(ICON_PATH).exists():
        app.setWindowIcon(QIcon(ICON_PATH))

    window = App()
    window.show()
    sys.exit(app.exec())
