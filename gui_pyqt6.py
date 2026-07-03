import json
import os
import queue
import sys
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QTextEdit, QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

sys.path.insert(0, str(Path(__file__).parent / "src"))

from gui.constants import (
    COURSES_FILE, ICON_PATH, OUTLINE_CFG, SESSION_FILE_GUI, VERSION,
)
from gui.dialogs import _ThreadBridge
from gui.panels import (
    AssignmentPanelMixin, ContentCleanerPanelMixin, GradebookPanelMixin,
    HistoryPanelMixin, OutlinePanelMixin, QuizPanelMixin,
    SettingsPanelMixin, StagingPanelMixin, TimerFixPanelMixin,
)
from gui.telemetry import _init_sentry, _sentry_capture
from gui.theme import T, _btn, _dark_palette, _entry_style, _log_style, _scroll_style


# ── Main window ───────────────────────────────────────────────────────────────

class App(
    StagingPanelMixin,
    QuizPanelMixin,
    AssignmentPanelMixin,
    OutlinePanelMixin,
    GradebookPanelMixin,
    ContentCleanerPanelMixin,
    TimerFixPanelMixin,
    HistoryPanelMixin,
    SettingsPanelMixin,
    QMainWindow,
):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Brightspace Automator")
        self.resize(960, 820)
        self.setMinimumSize(800, 600)
        self.setStyleSheet(f"background: {T['bg']}; color: {T['text']};")
        if Path(ICON_PATH).exists():
            self.setWindowIcon(QIcon(ICON_PATH))

        self._log_queue        = queue.Queue()
        self._resume_event     = threading.Event()
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
            ("Gradebook",            self._build_gradebook_panel),
            ("Timer Fix",            self._build_timerfix_panel),
            ("Content Cleaner",      self._build_content_cleaner_panel),
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
        brand.setStyleSheet(
            f"color: {T['text']}; font-size: 14px; font-weight: 700; "
            f"padding: 28px 20px 20px 20px; background: transparent;"
        )
        layout.addWidget(brand)

        self._nav_btns: dict[str, QPushButton] = {}
        for key, label in [
            ("Staging", "Staging"),
            ("Quiz Automator", "Quizzes"),
            ("Assignment Automator", "Assignments"),
            ("Course Outline", "Course Outline"),
            ("Gradebook", "Gradebook"),
        ]:
            layout.addWidget(self._make_nav_btn(key, label))

        layout.addWidget(self._sidebar_divider())
        opt = QLabel("OPTIONAL")
        opt.setStyleSheet(
            f"color: {T['text_muted']}; font-size: 10px; font-weight: 600; "
            f"letter-spacing: 1px; padding: 6px 20px 2px 20px; background: transparent;"
        )
        layout.addWidget(opt)
        for key, label in [
            ("Timer Fix", "Timer Fix"),
            ("Content Cleaner", "Content Cleaner"),
            ("History", "History"),
        ]:
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
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {T['card_border']}; margin: 6px 16px;")
        return line

    def _apply_nav_style(self, btn: QPushButton, active: bool):
        if active:
            btn.setStyleSheet(
                f"QPushButton {{ background: {T['nav_active']}; color: {T['accent']}; "
                f"font-size: 13px; font-weight: 600; text-align: left; padding-left: 20px; "
                f"border: none; border-radius: 6px; margin: 1px 8px; }}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {T['text_muted']}; "
                f"font-size: 13px; text-align: left; padding-left: 20px; border: none; "
                f"border-radius: 6px; margin: 1px 8px; }} "
                f"QPushButton:hover {{ background: {T['nav_hover']}; color: {T['text']}; }}"
            )

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
        inner = QWidget()
        inner.setStyleSheet(f"background: {T['bg']};")
        scroll.setWidget(inner)
        outer = QVBoxLayout(parent)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(0)
        return layout

    def _panel_header(self, layout: QVBoxLayout, title: str, subtitle: str = ""):
        lbl = QLabel(title)
        lbl.setStyleSheet(
            f"color: {T['text']}; font-size: 22px; font-weight: 700; background: transparent;"
        )
        layout.addWidget(lbl)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setStyleSheet(
                f"color: {T['text_muted']}; font-size: 12px; background: transparent;"
            )
            layout.addWidget(sub)
        layout.addSpacing(16)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {T['card_border']};")
        layout.addWidget(line)
        layout.addSpacing(20)

    def _gear_button(
        self, options: list[tuple[str, bool]],
        extra_widget: QWidget | None = None,
    ) -> tuple[QToolButton, dict]:
        """Gear icon with a checkable dropdown menu. Caller places the returned button.
        Returns (button, {label: QAction})."""
        gear = QToolButton()
        gear.setText("⚙")
        gear.setToolTip("Settings")
        gear.setCursor(Qt.CursorShape.PointingHandCursor)
        gear.setFixedSize(32, 32)
        gear.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        gear.setStyleSheet(f"""
            QToolButton {{
                background: transparent; color: {T["text_muted"]};
                border: 1px solid {T["card_border"]}; border-radius: 16px; font-size: 15px;
            }}
            QToolButton:hover {{ background: {T["btn_muted"]}; color: {T["text"]}; }}
            QToolButton::menu-indicator {{ image: none; width: 0; }}
        """)
        menu = QMenu(gear)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {T["card_bg"]}; color: {T["text"]};
                border: 1px solid {T["card_border"]}; border-radius: 6px; padding: 4px;
            }}
            QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 4px; }}
            QMenu::item:selected {{ background: {T["nav_hover"]}; }}
        """)
        actions: dict = {}
        for label, checked in options:
            act = QAction(label, menu)
            act.setCheckable(True)
            act.setChecked(checked)
            menu.addAction(act)
            actions[label] = act
        if extra_widget is not None:
            if options:
                menu.addSeparator()
            widget_action = QWidgetAction(menu)
            widget_action.setDefaultWidget(extra_widget)
            menu.addAction(widget_action)
        gear.setMenu(menu)
        return gear, actions

    def _section_label(self, layout: QVBoxLayout, text: str):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {T['text_muted']}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(lbl)
        layout.addSpacing(6)

    def _make_log(self, layout: QVBoxLayout, min_height: int = 200) -> QTextEdit:
        box = QTextEdit()
        box.setReadOnly(True)
        box.setMinimumHeight(min_height)
        box.setStyleSheet(_log_style())
        layout.addWidget(box)
        return box

    def _log_append(self, box: QTextEdit, text: str):
        box.append(text)
        box.verticalScrollBar().setValue(box.verticalScrollBar().maximum())

    def _make_url_rows_container(self) -> tuple[QWidget, QVBoxLayout]:
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        return container, layout

    def _add_url_row(
        self, container: QWidget, rows: list,
        url: str = "", placeholder: str = "Paste course page URL here…",
    ):
        row_widget = QWidget()
        row_widget.setStyleSheet("background: transparent;")
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        entry = QLineEdit()
        entry.setPlaceholderText(placeholder)
        entry.setFixedHeight(36)
        entry.setStyleSheet(_entry_style())
        if url:
            entry.setText(url)
        row_layout.addWidget(entry, stretch=1)
        container.layout().addWidget(row_widget)
        rows.append((row_widget, entry))

    # ── Log polling ───────────────────────────────────────────────────────────

    def _poll_log(self):
        try:
            while True:
                tag, msg = self._log_queue.get_nowait()
                if tag == "phase":
                    panel = {
                        "quiz":    "Quiz Automator",
                        "assign":  "Assignment Automator",
                        "outline": "Course Outline",
                    }.get(msg)
                    if panel:
                        self._show_panel(panel)
                    continue
                box = {
                    "quiz":    getattr(self, "_quiz_log",    None),
                    "assign":  getattr(self, "_assign_log",  None),
                    "tfix":    getattr(self, "_tfix_log",    None),
                    "cleaner": getattr(self, "_cleaner_log", None),
                    "staging": getattr(self, "_staging_log", None),
                    "outline": getattr(self, "_outline_log", None),
                    "gradebook": getattr(self, "_gradebook_log", None),
                }.get(tag, getattr(self, "_outline_log", None))

                if msg == "__QUIZ_DONE__":
                    self._quiz_run_btn.setEnabled(True)
                    self._quiz_run_btn.setText("▶  Run Quizzes")
                    self._resume_event.set()
                    QTimer.singleShot(0, self._post_quiz_review)
                elif msg == "__ASSIGN_DONE__":
                    self._assign_run_btn.setEnabled(True)
                    self._assign_run_btn.setText("▶  Run Assignments")
                    self._resume_event.set()
                    QTimer.singleShot(0, self._post_assign_review)
                elif msg == "__DONE__":
                    if tag == "quiz":
                        self._quiz_run_btn.setEnabled(True)
                        self._quiz_run_btn.setText("▶  Run Quizzes")
                        self._resume_event.set()
                    elif tag == "assign":
                        self._assign_run_btn.setEnabled(True)
                        self._assign_run_btn.setText("▶  Run Assignments")
                        self._resume_event.set()
                    elif tag == "tfix":
                        self._tfix_run_btn.setEnabled(True)
                        self._tfix_run_btn.setText("▶  Run Timer Fix")
                    elif tag == "cleaner":
                        self._cleaner_run_btn.setEnabled(True)
                        self._cleaner_run_btn.setText("▶  Run Content Cleaner")
                    elif tag == "staging":
                        self._staging_steps12_btn.setEnabled(True)
                        self._staging_steps12_btn.setText("▶   Stage Course")
                    elif tag == "outline":
                        self._outline_run_btn.setEnabled(True)
                        self._outline_run_btn.setText("▶  Run Course Outline")
                    elif tag == "gradebook":
                        self._gb_fetch_btn.setEnabled(True)
                        self._gb_fetch_btn.setText("▶   Fetch Outline + Gradebook")
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
        self._add_url_row(
            self._tfix_url_container, self._tfix_url_rows,
            placeholder="Paste quiz page URL here…",
        )

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
            if cfg.get("sentry_dsn"):
                self._sentry_dsn.setText(cfg["sentry_dsn"])
                _init_sentry(cfg["sentry_dsn"])
            else:
                _init_sentry()
            if cfg.get("ai_provider"):
                idx = {"claude": 0, "gpt": 1, "gemini": 2}.get(cfg["ai_provider"], 0)
                self._ai_provider_combo.setCurrentIndex(idx)
            for k in ("claude", "gpt", "gemini"):
                if cfg.get(f"{k}_api_key"):
                    self._ai_key_fields[k].setText(cfg[f"{k}_api_key"])
        except (FileNotFoundError, json.JSONDecodeError):
            _init_sentry()

    def _save_config(
        self, course_url=None, email=None, password=None,
        sentry_dsn=None, bs_username=None, bs_password=None,
        ai_provider=None, claude_api_key=None, gpt_api_key=None, gemini_api_key=None,
    ):
        try:
            with open(OUTLINE_CFG) as f:
                cfg = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            cfg = {}
        if course_url  is not None: cfg["course_url"]  = course_url
        if email       is not None: cfg["cb_email"]     = email
        if password    is not None: cfg["cb_password"]  = password
        if sentry_dsn  is not None: cfg["sentry_dsn"]  = sentry_dsn
        if bs_username is not None: cfg["bs_username"]  = bs_username
        if bs_password is not None: cfg["bs_password"]  = bs_password
        if ai_provider    is not None: cfg["ai_provider"]     = ai_provider
        if claude_api_key is not None: cfg["claude_api_key"]  = claude_api_key
        if gpt_api_key    is not None: cfg["gpt_api_key"]     = gpt_api_key
        if gemini_api_key is not None: cfg["gemini_api_key"]  = gemini_api_key
        with open(OUTLINE_CFG, "w") as f:
            json.dump(cfg, f)

    def _load_gradebook_creds(self) -> tuple[str, str]:
        """Return (provider, api_key) from saved config."""
        try:
            with open(OUTLINE_CFG) as f:
                cfg = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            cfg = {}
        provider = cfg.get("ai_provider", "claude")
        return provider, cfg.get(f"{provider}_api_key", "")

    # ── Ask-range helper ──────────────────────────────────────────────────────

    def _make_ask_fn(self):
        bridge = self._bridge
        def ask(total, label):
            return bridge.ask_range(total, label)
        return ask


# ── Entry point ───────────────────────────────────────────────────────────────

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
