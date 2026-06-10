import asyncio
import json
import os
import queue
import sys
import threading
from pathlib import Path
from tkinter import messagebox

sys.path.insert(0, str(Path(__file__).parent / "src"))

import customtkinter as ctk

try:
    from CTkMessagebox import CTkMessagebox
except ImportError:
    CTkMessagebox = None  # fall back to native messagebox until setup.bat is re-run

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

VERSION = "v0.8.0"

_HERE        = Path(__file__).parent
if os.name == "nt":
    USERDATA_DIR = Path(os.environ["APPDATA"]) / "BrightspaceAutomator"
else:
    USERDATA_DIR = Path.home() / ".local" / "share" / "BrightspaceAutomator"
USERDATA_DIR.mkdir(parents=True, exist_ok=True)

COURSES_FILE        = str(USERDATA_DIR / "courses.txt")
OUTLINE_CFG         = str(USERDATA_DIR / "outline_config.json")
NOTES_FILE          = str(USERDATA_DIR / "notes.txt")
STAGING_DONE_FILE   = str(USERDATA_DIR / "staging_done.json")
STAGING_QUEUE_FILE  = str(USERDATA_DIR / "staging_queue.txt")
SESSION_FILE_GUI    = str(USERDATA_DIR / "session.json")
COURSE_HISTORY_FILE = str(USERDATA_DIR / "course_history.json")


def _migrate_userdata():
    import shutil
    legacy = {
        "courses.txt":         COURSES_FILE,
        "outline_config.json": OUTLINE_CFG,
        "notes.txt":           NOTES_FILE,
        "staging_done.json":   STAGING_DONE_FILE,
        "staging_queue.txt":   STAGING_QUEUE_FILE,
        "session.json":        SESSION_FILE_GUI,
    }
    for name, dst in legacy.items():
        src = _HERE / name
        if src.exists() and not Path(dst).exists():
            shutil.copy2(src, dst)

_migrate_userdata()

_BG            = "#0f0f14"   # main window background
_SIDEBAR_BG    = "#0a0a0f"
_CARD          = "#17171f"   # settings / input card background
_NAV_HOVER     = "#16161e"
_NAV_ACTIVE    = "#1c2735"
_ACCENT        = "#0d9488"   # single teal accent used app-wide
_ACCENT_H      = "#14b8a6"
_BTN_PRIMARY   = _ACCENT
_BTN_PRIMARY_H = _ACCENT_H
_BTN_MUTED     = "#1e1e28"
_BTN_MUTED_H   = "#2a2a38"
_BTN_DANGER    = "#3f1717"
_BTN_DANGER_H  = "#5a2020"
_BTN_ADD       = "#16382a"
_BTN_ADD_H     = "#1e5038"
_DIVIDER       = "#222230"
_TEXT_DIM      = "#9aa0b8"   # nav idle, subtitles
_TEXT_FAINT    = "#5d6378"   # section labels, hints
_LOG_BG        = "#0b0b10"
_LOG_BORDER    = "#1c1c26"

# Apply the palette to CustomTkinter's defaults so every default-styled
# widget (buttons, checkboxes, entries, tabs, dialogs) matches the accent.
ctk.ThemeManager.theme["CTk"]["fg_color"]        = ["#f3f3f6", _BG]
ctk.ThemeManager.theme["CTkToplevel"]["fg_color"] = ["#f3f3f6", _BG]
ctk.ThemeManager.theme["CTkFrame"]["fg_color"]    = ["#ebebec", _CARD]
ctk.ThemeManager.theme["CTkFrame"]["top_fg_color"] = ["#dbdbdc", "#1e1e28"]
ctk.ThemeManager.theme["CTkButton"]["fg_color"]      = [_ACCENT, _ACCENT]
ctk.ThemeManager.theme["CTkButton"]["hover_color"]   = [_ACCENT_H, _ACCENT_H]
ctk.ThemeManager.theme["CTkButton"]["corner_radius"] = 8
ctk.ThemeManager.theme["CTkCheckBox"]["fg_color"]    = [_ACCENT, _ACCENT]
ctk.ThemeManager.theme["CTkCheckBox"]["hover_color"] = [_ACCENT_H, _ACCENT_H]
ctk.ThemeManager.theme["CTkEntry"]["fg_color"]       = ["#f9f9fa", "#101016"]
ctk.ThemeManager.theme["CTkEntry"]["border_color"]   = ["#979da2", "#2a2a38"]
ctk.ThemeManager.theme["CTkTextbox"]["fg_color"]     = ["#f9f9fa", "#101016"]
ctk.ThemeManager.theme["CTkSegmentedButton"]["selected_color"]       = [_ACCENT, _ACCENT]
ctk.ThemeManager.theme["CTkSegmentedButton"]["selected_hover_color"] = [_ACCENT_H, _ACCENT_H]


_DEFAULT_SENTRY_DSN = "https://b178c330abfc081169e6395ae85da7db@o4511530722459648.ingest.de.sentry.io/4511530734780496"


def _init_sentry(dsn: str = ""):
    try:
        import sentry_sdk
        resolved = dsn or _DEFAULT_SENTRY_DSN
        if resolved:
            sentry_sdk.init(dsn=resolved, traces_sample_rate=0, release=VERSION)
    except Exception:
        pass


def _sentry_context(step: str, course: str = ""):
    try:
        import sentry_sdk
        sentry_sdk.set_tag("step", step)
        if course:
            sentry_sdk.set_tag("course", course)
    except Exception:
        pass


def _sentry_capture(e: Exception):
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(e)
    except Exception:
        pass


class _GUIPrompter:
    """Bridges worker-thread input() calls to main-thread dialogs."""

    def __init__(self, root):
        self._root = root

    def __call__(self, prompt: str) -> str:
        result = [""]
        event  = threading.Event()

        def show():
            is_yn = "(y/n)" in prompt
            msg   = prompt.replace("(y/n)", "").strip()

            dlg = ctk.CTkToplevel(self._root)
            dlg.title("Confirmation" if is_yn else "Action Required")
            dlg.resizable(False, False)
            dlg.attributes("-topmost", True)
            # No grab_set() — keeps dialog non-modal so Chromium stays clickable

            ctk.CTkLabel(dlg, text=msg, wraplength=420, justify="left").pack(padx=24, pady=(20, 12))

            def _respond(val):
                result[0] = val
                dlg.destroy()
                event.set()

            if is_yn:
                row = ctk.CTkFrame(dlg, fg_color="transparent")
                row.pack(pady=(0, 20))
                ctk.CTkButton(row, text="Yes", width=100,
                              command=lambda: _respond("y")).pack(side="left", padx=8)
                ctk.CTkButton(row, text="No", width=100,
                              fg_color=_BTN_DANGER, hover_color=_BTN_DANGER_H,
                              command=lambda: _respond("n")).pack(side="left", padx=8)
            else:
                ctk.CTkButton(dlg, text="OK", width=100,
                              command=lambda: _respond("")).pack(pady=(0, 20))

        self._root.after(0, show)
        event.wait()
        return result[0]


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Brightspace Automator")
        self.geometry("960x820")
        self.minsize(800, 600)

        self._log_queue    = queue.Queue()
        self._url_rows     = []
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._last_quiz_urls   = []
        self._last_assign_urls = []

        self._build_ui()
        self._apply_paste_menus()
        self._load_courses()
        self._load_config()
        self._load_notes()
        self.after(100, self._poll_log)

    # ── Layout helpers ────────────────────────────────────────────────────────

    def _panel_body(self, parent, title: str, subtitle: str = "") -> ctk.CTkScrollableFrame:
        """Standard panel header + divider + scrollable content area."""
        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.pack(fill="x", padx=28, pady=(24, 0))
        ctk.CTkLabel(hdr, text=title,
                     font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w")
        if subtitle:
            ctk.CTkLabel(hdr, text=subtitle,
                         font=ctk.CTkFont(size=12), text_color=_TEXT_DIM).pack(anchor="w", pady=(3, 0))
        ctk.CTkFrame(parent, height=1, fg_color=_DIVIDER).pack(fill="x", padx=28, pady=(14, 0))
        body = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=(8, 12))
        return body

    def _section_label(self, parent, text: str):
        ctk.CTkLabel(parent, text=text,
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=_TEXT_FAINT).pack(anchor="w", pady=(14, 3))

    def _log_box(self, parent, height: int) -> ctk.CTkTextbox:
        """Styled log output area with a subtle border."""
        border = ctk.CTkFrame(parent, fg_color=_LOG_BORDER, corner_radius=8)
        border.pack(fill="x", pady=(10, 0))
        box = ctk.CTkTextbox(
            border, height=height, state="disabled",
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=_LOG_BG, corner_radius=6, text_color="#b8c4da",
            border_width=0,
        )
        box.pack(fill="x", padx=2, pady=2)
        return box

    def _apply_paste_menus(self, root=None):
        def walk(widget):
            if isinstance(widget, ctk.CTkEntry):
                self._bind_paste_menu(widget)
            for child in widget.winfo_children():
                walk(child)
        walk(root or self)

    def _bind_paste_menu(self, entry: ctk.CTkEntry):
        import tkinter as tk

        def paste():
            try:
                text = entry.clipboard_get()
            except Exception:
                return
            try:
                entry._entry.delete("sel.first", "sel.last")
            except Exception:
                pass
            entry._entry.insert("insert", text)

        def cut():
            try:
                text = entry._entry.selection_get()
                entry.clipboard_clear()
                entry.clipboard_append(text)
                entry._entry.delete("sel.first", "sel.last")
            except Exception:
                pass

        def copy():
            try:
                text = entry._entry.selection_get()
                entry.clipboard_clear()
                entry.clipboard_append(text)
            except Exception:
                pass

        def select_all():
            entry._entry.selection_range(0, "end")
            entry._entry.icursor("end")

        def clear():
            entry.delete(0, "end")

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Cut",        command=cut)
        menu.add_command(label="Copy",       command=copy)
        menu.add_command(label="Paste",      command=paste)
        menu.add_separator()
        menu.add_command(label="Select All", command=select_all)
        menu.add_command(label="Clear",      command=clear)

        def show(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        entry.bind("<Button-3>", show)

    # ── UI layout ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        sidebar = ctk.CTkFrame(self, width=200, corner_radius=0, fg_color=_SIDEBAR_BG)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            sidebar, text="Brightspace\nAutomator",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color="white", justify="left",
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(28, 20))

        nav_items = [
            ("Staging",              "  Staging"),
            ("Quiz Automator",       "  Quizzes"),
            ("Assignment Automator", "  Assignments"),
            ("Course Outline",       "  Course Outline"),
            ("Notes",                "  Notes"),
        ]
        self._nav_btns = {}
        for r, (key, label) in enumerate(nav_items, start=1):
            btn = ctk.CTkButton(
                sidebar, text=label, anchor="w", height=40,
                fg_color="transparent", hover_color=_NAV_HOVER,
                text_color=_TEXT_DIM, font=ctk.CTkFont(size=13),
                corner_radius=6,
                command=lambda k=key: self._show_panel(k),
            )
            btn.grid(row=r, column=0, sticky="ew", padx=8, pady=2)
            self._nav_btns[key] = btn

        ctk.CTkFrame(sidebar, height=1, fg_color=_DIVIDER).grid(
            row=6, column=0, sticky="ew", padx=16, pady=(8, 0),
        )
        ctk.CTkLabel(
            sidebar, text="  OPTIONAL",
            font=ctk.CTkFont(size=10), text_color=_TEXT_FAINT,
        ).grid(row=7, column=0, sticky="w", padx=8, pady=(2, 0))
        for r, (key, label) in enumerate([("Timer Fix", "  Timer Fix"), ("Queue", "  Queue"), ("History", "  History")], start=8):
            btn = ctk.CTkButton(
                sidebar, text=label, anchor="w", height=40,
                fg_color="transparent", hover_color=_NAV_HOVER,
                text_color=_TEXT_DIM, font=ctk.CTkFont(size=13),
                corner_radius=6,
                command=lambda k=key: self._show_panel(k),
            )
            btn.grid(row=r, column=0, sticky="ew", padx=8, pady=2)
            self._nav_btns[key] = btn

        sidebar.grid_rowconfigure(11, weight=1)
        ctk.CTkFrame(sidebar, height=1, fg_color=_DIVIDER).grid(
            row=11, column=0, sticky="sew", padx=16, pady=(0, 4),
        )
        settings_btn = ctk.CTkButton(
            sidebar, text=f"  Settings  {VERSION}", anchor="w", height=40,
            fg_color="transparent", hover_color=_NAV_HOVER,
            text_color=_TEXT_DIM, font=ctk.CTkFont(size=13),
            corner_radius=6,
            command=lambda: self._show_panel("Settings"),
        )
        settings_btn.grid(row=12, column=0, sticky="ew", padx=8, pady=(0, 16))
        self._nav_btns["Settings"] = settings_btn

        # Content area
        content = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self._panels = {}
        for key, builder in [
            ("Quiz Automator",       self._build_quiz_panel),
            ("Assignment Automator", self._build_assignment_panel),
            ("Timer Fix",            self._build_timer_fix_panel),
            ("Course Outline",       self._build_outline_panel),
            ("Staging",              self._build_staging_panel),
            ("Queue",                self._build_queue_panel),
            ("Notes",                self._build_notes_panel),
            ("History",              self._build_history_panel),
            ("Settings",             self._build_settings_panel),
        ]:
            panel = ctk.CTkFrame(content, corner_radius=0, fg_color="transparent")
            panel.grid(row=0, column=0, sticky="nsew")
            panel.grid_rowconfigure(0, weight=1)
            panel.grid_columnconfigure(0, weight=1)
            self._panels[key] = panel
            builder(panel)

        self._show_panel("Staging")

    def _show_panel(self, name: str):
        for panel in self._panels.values():
            panel.grid_remove()
        self._panels[name].grid()
        for key, btn in self._nav_btns.items():
            if key == name:
                btn.configure(fg_color=_NAV_ACTIVE, text_color="white")
            else:
                btn.configure(fg_color="transparent", text_color=_TEXT_DIM)
        if name == "History":
            self.after(10, self._load_history_tab)

    # ── Quiz panel ────────────────────────────────────────────────────────────

    def _build_quiz_panel(self, parent):
        body = self._panel_body(parent, "Quiz Automator",
                                "Bulk-update quiz settings across courses")

        self._section_label(body, "COURSE URLS")
        self._urls_container = ctk.CTkFrame(body)
        self._urls_container.pack(fill="x", pady=(0, 4))

        ctk.CTkButton(
            body, text="＋  Add course URL", height=32,
            fg_color="transparent", border_width=1,
            command=self._add_url_row,
        ).pack(anchor="w", pady=(0, 12))

        self._section_label(body, "SETTINGS")
        sf = ctk.CTkFrame(body)
        sf.pack(fill="x", pady=(0, 16))

        self._gradebook_var  = ctk.BooleanVar(value=True)
        self._autosubmit_var = ctk.BooleanVar(value=True)
        self._quiz_dryrun    = ctk.BooleanVar(value=False)

        ctk.CTkCheckBox(sf, text="Add to Grade Book",
                        variable=self._gradebook_var).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkCheckBox(sf, text="Auto-submit on timer expiry",
                        variable=self._autosubmit_var).pack(anchor="w", padx=16, pady=4)
        ctk.CTkCheckBox(sf, text="Dry run  (preview only — nothing will be saved)",
                        variable=self._quiz_dryrun,
                        text_color="#f0a500").pack(anchor="w", padx=16, pady=(4, 14))

        self._quiz_run_btn = ctk.CTkButton(
            body, text="▶  Run Quizzes", height=52,
            font=ctk.CTkFont(size=17, weight="bold"),
            command=self._start_quiz_run,
        )
        self._quiz_run_btn.pack(fill="x", pady=(0, 6))

        self._quiz_pause_btn = ctk.CTkButton(
            body, text="⏸   PAUSE", height=36,
            fg_color="#555555", hover_color="#444444",
            command=self._toggle_quiz_pause, state="disabled",
        )
        self._quiz_pause_btn.pack(fill="x", pady=(0, 6))

        self._quiz_verify_btn = ctk.CTkButton(
            body, text="🔍   VERIFY SETTINGS  (read-only check, no changes)", height=38,
            fg_color="#2a3a2a", hover_color="#3a5a3a",
            command=self._start_quiz_verify,
        )
        self._quiz_verify_btn.pack(fill="x", pady=(0, 12))

        self._quiz_log = self._log_box(body, height=220)

    # ── Assignment panel ──────────────────────────────────────────────────────

    def _build_assignment_panel(self, parent):
        body = self._panel_body(parent, "Assignment Automator",
                                "Bulk-update assignment settings across courses")

        self._section_label(body, "ASSIGNMENT PAGE URLS")
        self._assign_urls_container = ctk.CTkFrame(body)
        self._assign_urls_container.pack(fill="x", pady=(0, 4))
        self._assign_url_rows = []

        ctk.CTkButton(
            body, text="＋  Add assignment page URL", height=32,
            fg_color="transparent", border_width=1,
            command=self._add_assign_url_row,
        ).pack(anchor="w", pady=(0, 12))

        self._section_label(body, "SETTINGS")
        sf = ctk.CTkFrame(body)
        sf.pack(fill="x", pady=(0, 16))

        self._assign_gradebook_var = ctk.BooleanVar(value=True)
        self._assign_dryrun        = ctk.BooleanVar(value=False)

        ctk.CTkCheckBox(sf, text="Add to Grade Book",
                        variable=self._assign_gradebook_var).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkCheckBox(sf, text="Dry run  (preview only — nothing will be saved)",
                        variable=self._assign_dryrun,
                        text_color="#f0a500").pack(anchor="w", padx=16, pady=(4, 14))

        self._assign_run_btn = ctk.CTkButton(
            body, text="▶  Run Assignments", height=52,
            font=ctk.CTkFont(size=17, weight="bold"),
            command=self._start_assignment_run,
        )
        self._assign_run_btn.pack(fill="x", pady=(0, 6))

        self._assign_pause_btn = ctk.CTkButton(
            body, text="⏸   PAUSE", height=36,
            fg_color="#555555", hover_color="#444444",
            command=self._toggle_assign_pause, state="disabled",
        )
        self._assign_pause_btn.pack(fill="x", pady=(0, 12))

        self._assign_log = self._log_box(body, height=220)
        self._add_assign_url_row()

    # ── Timer Fix panel ───────────────────────────────────────────────────────

    def _build_timer_fix_panel(self, parent):
        body = self._panel_body(parent, "Timer Fix",
                                "Re-run only the auto-submit timer fix — skips grade book entirely")

        self._section_label(body, "QUIZ PAGE URLS")
        self._tfix_urls_container = ctk.CTkFrame(body)
        self._tfix_urls_container.pack(fill="x", pady=(0, 4))
        self._tfix_url_rows = []

        ctk.CTkButton(
            body, text="＋  Add quiz page URL", height=32,
            fg_color="transparent", border_width=1,
            command=self._add_tfix_url_row,
        ).pack(anchor="w", pady=(0, 12))

        sf = ctk.CTkFrame(body)
        sf.pack(fill="x", pady=(0, 16))
        self._tfix_dryrun = ctk.BooleanVar(value=False)
        self._tfix_testmode = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(sf, text="Dry run  (preview only — nothing will be saved)",
                        variable=self._tfix_dryrun,
                        text_color="#f0a500").pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkCheckBox(sf, text="Test mode  (first quiz only)",
                        variable=self._tfix_testmode,
                        text_color="#f0a500").pack(anchor="w", padx=16, pady=(0, 14))

        self._tfix_run_btn = ctk.CTkButton(
            body, text="▶  Run Timer Fix", height=52,
            font=ctk.CTkFont(size=17, weight="bold"),
            command=self._start_timer_fix,
        )
        self._tfix_run_btn.pack(fill="x", pady=(0, 16))

        self._tfix_log = self._log_box(body, height=280)
        self._add_tfix_url_row()

    # ── Course Outline panel ──────────────────────────────────────────────────

    def _build_outline_panel(self, parent):
        body = self._panel_body(parent, "Course Outline",
                                "Download, convert and paste the course outline into Brightspace")

        self._section_label(body, "COURSE  (CRN number  or  full Brightspace URL)")
        self._outline_url = ctk.CTkEntry(
            body, placeholder_text="e.g.  80147  or  https://learn.okanagancollege.ca/…",
            height=38,
        )
        self._outline_url.pack(fill="x", pady=(0, 16))

        sf = ctk.CTkFrame(body)
        sf.pack(fill="x", pady=(0, 16))
        self._outline_dryrun = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            sf,
            text="Dry run  (download + convert only — nothing pasted into Brightspace)",
            variable=self._outline_dryrun, text_color="#f0a500",
        ).pack(anchor="w", padx=16, pady=14)

        self._outline_run_btn = ctk.CTkButton(
            body, text="▶  Run Course Outline", height=52,
            font=ctk.CTkFont(size=17, weight="bold"),
            command=self._start_outline_run,
        )
        self._outline_run_btn.pack(fill="x", pady=(0, 8))

        self._section_label(body, "TEST INDIVIDUAL STEPS")
        self._test_step4_btn = ctk.CTkButton(
            body, text="▶   TEST STEP 4 ONLY  (paste existing HTML into Brightspace)",
            height=38, font=ctk.CTkFont(size=13),
            fg_color="#2a4a2a", hover_color="#3a6a3a",
            command=self._start_test_step4,
        )
        self._test_step4_btn.pack(fill="x", pady=(0, 12))

        self._outline_log = self._log_box(body, height=220)

    # ── Staging panel ─────────────────────────────────────────────────────────

    def _build_staging_panel(self, parent):
        body = self._panel_body(parent, "Staging",
                                "Automate the Brightspace staging process one step at a time")

        self._section_label(body, "COURSE  —  CRN or Brightspace URL")
        self._staging_crn = ctk.CTkEntry(
            body, placeholder_text="e.g. 31899  or  https://learn.okanagancollege.ca/d2l/home/…",
            height=38,
        )
        self._staging_crn.pack(fill="x", pady=(0, 10))
        self._staging_crn.bind("<Return>",   lambda e: self._auto_extract_crn())
        self._staging_crn.bind("<FocusOut>", lambda e: self._auto_extract_crn())

        self._staging_dryrun = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(body, text="Dry run  (navigate only, no changes)",
                        variable=self._staging_dryrun,
                        text_color="#f0a500").pack(anchor="w", pady=(0, 18))

        self._staging_steps12_btn = ctk.CTkButton(
            body, text="▶  Stage Course", height=52,
            font=ctk.CTkFont(size=17, weight="bold"),
            fg_color=_BTN_PRIMARY, hover_color=_BTN_PRIMARY_H,
            command=self._start_staging_steps_1_2,
        )
        self._staging_steps12_btn.pack(fill="x", pady=(0, 16))

        self._staging_log = self._log_box(body, height=320)

    # ── Queue panel ───────────────────────────────────────────────────────────

    def _build_queue_panel(self, parent):
        body = self._panel_body(parent, "Staging Queue",
                                "Track which courses have been staged")

        # ── Top row: refresh + status ──────────────────────────────────────────
        top = ctk.CTkFrame(body, fg_color="transparent")
        top.pack(fill="x", pady=(0, 10))
        top.columnconfigure(0, weight=1)

        self._staging_refresh_btn = ctk.CTkButton(
            top, text="⟳  Refresh Queue", height=36,
            fg_color=_BTN_MUTED, hover_color=_BTN_MUTED_H,
            command=self._start_staging_refresh,
        )
        self._staging_refresh_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self._queue_status_label = ctk.CTkLabel(
            body, text="", font=ctk.CTkFont(size=12), text_color=_TEXT_DIM,
        )
        self._queue_status_label.pack(anchor="w", pady=(0, 6))

        # ── Add course row ─────────────────────────────────────────────────────
        add_row = ctk.CTkFrame(body, fg_color="transparent")
        add_row.pack(fill="x", pady=(0, 10))
        add_row.columnconfigure(0, weight=1)
        self._queue_add_entry = ctk.CTkEntry(
            add_row, placeholder_text="Add a course (e.g. MATH-100-001-31899.202530)…",
            height=34,
        )
        self._queue_add_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._queue_add_entry.bind("<Return>", lambda e: self._queue_add_course())
        ctk.CTkButton(
            add_row, text="+ Add", width=70, height=34,
            fg_color=_BTN_ADD, hover_color=_BTN_ADD_H,
            command=self._queue_add_course,
        ).grid(row=0, column=1)

        # ── Sub-tabs ───────────────────────────────────────────────────────────
        tabs = ctk.CTkTabview(body, height=400)
        tabs.pack(fill="both", expand=True)
        tabs.add("To Do")
        tabs.add("Done")

        self._queue_todo_frame = ctk.CTkScrollableFrame(tabs.tab("To Do"), fg_color="transparent")
        self._queue_todo_frame.pack(fill="both", expand=True)

        self._queue_done_frame = ctk.CTkScrollableFrame(tabs.tab("Done"), fg_color="transparent")
        self._queue_done_frame.pack(fill="both", expand=True)

        self._load_staging_queue_list()

    def _queue_add_course(self):
        course = self._queue_add_entry.get().strip()
        if not course:
            return
        queue_file = STAGING_QUEUE_FILE
        try:
            with open(queue_file, encoding="utf-8") as f:
                existing = [l.strip() for l in f if l.strip()]
        except FileNotFoundError:
            existing = []
        if course not in existing:
            existing.append(course)
            with open(queue_file, "w", encoding="utf-8") as f:
                f.write("\n".join(existing) + "\n")
        self._queue_add_entry.delete(0, "end")
        self._load_staging_queue_list()

    def _queue_delete_course(self, course: str):
        queue_file = STAGING_QUEUE_FILE
        try:
            with open(queue_file, encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip() and l.strip() != course]
        except FileNotFoundError:
            lines = []
        with open(queue_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        done = self._done_set()
        done.discard(course)
        self._save_done_set(done)
        self._load_staging_queue_list()

    # ── Notes panel ───────────────────────────────────────────────────────────

    def _build_notes_panel(self, parent):
        body = self._panel_body(parent, "Course Notes",
                                "Auto-populated from staging run. Editable.")

        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 8))
        ctk.CTkButton(
            btn_row, text="Copy All", width=100, height=32,
            command=self._notes_copy,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            btn_row, text="Clear", width=80, height=32,
            fg_color=_BTN_DANGER, hover_color=_BTN_DANGER_H,
            command=self._notes_clear,
        ).pack(side="left")

        self._notes_box = ctk.CTkTextbox(
            body, font=ctk.CTkFont(family="Consolas", size=12),
        )
        self._notes_box.pack(fill="both", expand=True)
        self._notes_box.bind("<KeyRelease>", lambda e: self._save_notes())

    def _notes_copy(self):
        text = self._notes_box.get("1.0", "end").strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)

    def _notes_clear(self):
        self._notes_box.delete("1.0", "end")
        self._save_notes()

    def append_note(self, text: str):
        """Append a note line to the Notes tab (called from worker threads via queue)."""
        self._notes_box.insert("end", text + "\n")
        self._save_notes()

    def _save_notes(self):
        try:
            with open(NOTES_FILE, "w", encoding="utf-8") as f:
                f.write(self._notes_box.get("1.0", "end"))
        except Exception:
            pass

    def _load_notes(self):
        try:
            with open(NOTES_FILE, encoding="utf-8") as f:
                content = f.read()
            if content.strip():
                self._notes_box.insert("1.0", content)
        except FileNotFoundError:
            pass

    # ── History panel ─────────────────────────────────────────────────────────

    def _build_history_panel(self, parent):
        body = self._panel_body(parent, "History", "Completed quiz and assignment runs")
        self._history_search = ctk.CTkEntry(body, placeholder_text="Search by URL…", height=32)
        self._history_search.pack(fill="x", padx=0, pady=(0, 8))
        self._history_search.bind("<KeyRelease>", lambda e: self._load_history_tab())
        self._history_scroll = ctk.CTkScrollableFrame(body, fg_color="transparent")
        self._history_scroll.pack(fill="both", expand=True)

    # ── Settings panel ────────────────────────────────────────────────────────

    def _build_settings_panel(self, parent):
        body = self._panel_body(parent, "Settings",
                                "Credentials and global configuration")

        self._section_label(body, "COURSEBRIDGE")
        cf = ctk.CTkFrame(body)
        cf.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(cf, text="Email").pack(anchor="w", padx=16, pady=(14, 2))
        self._cb_email = ctk.CTkEntry(cf, height=36)
        self._cb_email.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(cf, text="Password").pack(anchor="w", padx=16, pady=(0, 2))
        self._cb_password = ctk.CTkEntry(cf, height=36, show="●")
        self._cb_password.pack(fill="x", padx=16, pady=(0, 14))

        self._section_label(body, "BRIGHTSPACE SESSION")
        bf = ctk.CTkFrame(body)
        bf.pack(fill="x", pady=(0, 16))

        session_exists = os.path.exists(SESSION_FILE_GUI)
        self._bs_status = ctk.CTkLabel(
            bf,
            text="✓  Session saved" if session_exists else "✗  No session — log in first",
            font=ctk.CTkFont(size=12),
            text_color="#4caf50" if session_exists else "#f0a500",
            justify="left",
        )
        self._bs_status.pack(anchor="w", padx=16, pady=(14, 8))

        btn_row = ctk.CTkFrame(bf, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 14))
        self._bs_login_btn = ctk.CTkButton(
            btn_row, text="Login to Brightspace", width=180, height=36,
            command=self._start_bs_login,
        )
        self._bs_login_btn.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            btn_row, text="Clear Session", width=120, height=36,
            fg_color=_BTN_DANGER, hover_color=_BTN_DANGER_H,
            command=self._clear_bs_session,
        ).pack(side="left")

        self._section_label(body, "ERROR REPORTING (SENTRY)")
        sf = ctk.CTkFrame(body)
        sf.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(sf, text="Sentry DSN  (leave blank to disable)", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=16, pady=(14, 2))
        self._sentry_dsn = ctk.CTkEntry(sf, height=36, placeholder_text="https://...@sentry.io/...")
        self._sentry_dsn.pack(fill="x", padx=16, pady=(0, 14))

        self._save_settings_btn = ctk.CTkButton(
            body, text="Save Settings", height=42, width=160,
            command=self._save_settings,
        )
        self._save_settings_btn.pack(anchor="w")

    # ── Config persistence ────────────────────────────────────────────────────

    def _load_config(self):
        try:
            with open(OUTLINE_CFG) as f:
                cfg = json.load(f)
            if cfg.get("course_url"):
                self._outline_url.insert(0, cfg["course_url"])
            if cfg.get("cb_email"):
                self._cb_email.delete(0, "end")
                self._cb_email.insert(0, cfg["cb_email"])
            if cfg.get("cb_password"):
                self._cb_password.delete(0, "end")
                self._cb_password.insert(0, cfg["cb_password"])
            if cfg.get("sentry_dsn"):
                self._sentry_dsn.delete(0, "end")
                self._sentry_dsn.insert(0, cfg["sentry_dsn"])
                _init_sentry(cfg["sentry_dsn"])
            else:
                _init_sentry()
        except (FileNotFoundError, json.JSONDecodeError):
            _init_sentry()

    def _save_config(self, course_url=None, email=None, password=None, sentry_dsn=None):
        try:
            with open(OUTLINE_CFG) as f:
                cfg = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            cfg = {}
        if course_url is not None:
            cfg["course_url"] = course_url
        if email is not None:
            cfg["cb_email"] = email
        if password is not None:
            cfg["cb_password"] = password
        if sentry_dsn is not None:
            cfg["sentry_dsn"] = sentry_dsn
        with open(OUTLINE_CFG, "w") as f:
            json.dump(cfg, f)

    def _start_bs_login(self):
        self._bs_login_btn.configure(state="disabled", text="Opening browser…")
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
                self.after(0, lambda: self._bs_status.configure(
                    text="✓  Session saved", text_color="#4caf50"
                ))
            except Exception as e:
                _sentry_capture(e)
                q.put(("outline", f"✗  Login failed: {e}"))
            finally:
                sys.stdout = old
                self.after(0, lambda: self._bs_login_btn.configure(
                    state="normal", text="Login to Brightspace"
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _clear_bs_session(self):
        session_file = SESSION_FILE_GUI
        if os.path.exists(session_file):
            os.remove(session_file)
        self._bs_status.configure(text="✗  No session — log in first", text_color="#f0a500")

    def _save_settings(self):
        dsn = self._sentry_dsn.get().strip()
        self._save_config(
            email=self._cb_email.get().strip(),
            password=self._cb_password.get().strip(),
            sentry_dsn=dsn,
        )
        _init_sentry(dsn)
        self._save_settings_btn.configure(text="✓  Saved")
        self.after(1500, lambda: self._save_settings_btn.configure(text="Save Settings"))

    # ── URL row helpers ───────────────────────────────────────────────────────

    def _add_url_row(self, url=""):
        row = ctk.CTkFrame(self._urls_container, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=5)
        entry = ctk.CTkEntry(row, placeholder_text="Paste course page URL here…", height=38)
        entry.pack(side="left", fill="x", expand=True)
        self._bind_paste_menu(entry)
        if url:
            entry.insert(0, url)
        def remove():
            self._url_rows = [(f, e) for f, e in self._url_rows if f is not row]
            row.destroy()
        ctk.CTkButton(row, text="✕", width=38, height=38,
                      fg_color="transparent", text_color="gray",
                      hover_color="#3a3a3a", command=remove).pack(side="left", padx=(6, 0))
        self._url_rows.append((row, entry))

    def _add_assign_url_row(self, url=""):
        row = ctk.CTkFrame(self._assign_urls_container, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=5)
        entry = ctk.CTkEntry(row, placeholder_text="Paste course page URL here…", height=38)
        entry.pack(side="left", fill="x", expand=True)
        self._bind_paste_menu(entry)
        if url:
            entry.insert(0, url)
        def remove():
            self._assign_url_rows = [(f, e) for f, e in self._assign_url_rows if f is not row]
            row.destroy()
        ctk.CTkButton(row, text="✕", width=38, height=38,
                      fg_color="transparent", text_color="gray",
                      hover_color="#3a3a3a", command=remove).pack(side="left", padx=(6, 0))
        self._assign_url_rows.append((row, entry))

    def _add_tfix_url_row(self, url=""):
        row = ctk.CTkFrame(self._tfix_urls_container, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=5)
        entry = ctk.CTkEntry(row, placeholder_text="Paste quiz page URL here…", height=38)
        entry.pack(side="left", fill="x", expand=True)
        self._bind_paste_menu(entry)
        if url:
            entry.insert(0, url)
        def remove():
            self._tfix_url_rows = [(f, e) for f, e in self._tfix_url_rows if f is not row]
            row.destroy()
        ctk.CTkButton(row, text="✕", width=38, height=38,
                      fg_color="transparent", text_color="gray",
                      hover_color="#3a3a3a", command=remove).pack(side="left", padx=(6, 0))
        self._tfix_url_rows.append((row, entry))

    # ── Course persistence ────────────────────────────────────────────────────

    def _load_courses(self):
        try:
            with open(COURSES_FILE) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        self._add_url_row(line)
        except FileNotFoundError:
            pass
        if not self._url_rows:
            self._add_url_row()

    def _save_courses(self, urls):
        with open(COURSES_FILE, "w") as f:
            for url in urls:
                f.write(url + "\n")

    # ── Log helpers ───────────────────────────────────────────────────────────

    def _append(self, box, text):
        box.configure(state="normal")
        box.insert("end", text + "\n")
        box.see("end")
        box.configure(state="disabled")

    def _poll_log(self):
        try:
            while True:
                tag, msg = self._log_queue.get_nowait()
                box = {
                    "quiz":    self._quiz_log,
                    "assign":  self._assign_log,
                    "tfix":    self._tfix_log,
                    "staging": self._staging_log,
                }.get(tag, self._outline_log)

                if tag == "note":
                    self.append_note(msg)
                    self._append(self._staging_log, "📝  Note added — review and edit in the Notes tab")
                    continue
                elif msg == "__QUIZ_DONE__":
                    self._quiz_run_btn.configure(state="normal", text="▶  Run Quizzes")
                    self._quiz_pause_btn.configure(state="disabled", text="⏸   PAUSE", fg_color="#555555")
                    self._quiz_verify_btn.configure(state="normal", text="🔍   VERIFY SETTINGS  (read-only check, no changes)")
                    self._resume_event.set()
                    self.after(0, self._post_quiz_review)
                elif msg == "__ASSIGN_DONE__":
                    self._assign_run_btn.configure(state="normal", text="▶  Run Assignments")
                    self._assign_pause_btn.configure(state="disabled", text="⏸   PAUSE", fg_color="#555555")
                    self._resume_event.set()
                    self.after(0, self._post_assign_review)
                elif msg == "__DONE__":
                    if tag == "quiz":
                        self._quiz_run_btn.configure(state="normal", text="▶  Run Quizzes")
                        self._quiz_pause_btn.configure(state="disabled", text="⏸   PAUSE", fg_color="#555555")
                        self._quiz_verify_btn.configure(state="normal", text="🔍   VERIFY SETTINGS  (read-only check, no changes)")
                        self._resume_event.set()
                    elif tag == "assign":
                        self._assign_run_btn.configure(state="normal", text="▶  Run Assignments")
                        self._assign_pause_btn.configure(state="disabled", text="⏸   PAUSE", fg_color="#555555")
                        self._resume_event.set()
                    elif tag == "tfix":
                        self._tfix_run_btn.configure(state="normal", text="▶  Run Timer Fix")
                    elif tag == "staging":
                        self._staging_steps12_btn.configure(state="normal", text="▶  Stage Course")
                    else:
                        self._outline_run_btn.configure(state="normal", text="▶  Run Course Outline")
                else:
                    self._append(box, msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    # ── Ask-start-from dialog ─────────────────────────────────────────────────

    def _make_ask_fn(self):
        result = [1, None]  # [start, end]
        event  = threading.Event()

        def ask(total, label):
            def show():
                result[0] = 1
                result[1] = total
                dlg = ctk.CTkToplevel(self)
                dlg.title("Select range")
                dlg.resizable(False, False)
                dlg.attributes("-topmost", True)
                dlg.lift()
                dlg.focus_force()

                ctk.CTkLabel(
                    dlg,
                    text=f"Found {total} {label}(s).\nProcess which range?",
                    justify="center",
                ).pack(padx=24, pady=(20, 10))

                row = ctk.CTkFrame(dlg, fg_color="transparent")
                row.pack(padx=24, pady=(0, 12))
                ctk.CTkLabel(row, text="From:").pack(side="left", padx=(0, 6))
                start_entry = ctk.CTkEntry(row, width=60, justify="center")
                start_entry.insert(0, "1")
                start_entry.pack(side="left", padx=(0, 16))
                ctk.CTkLabel(row, text="To:").pack(side="left", padx=(0, 6))
                end_entry = ctk.CTkEntry(row, width=60, justify="center")
                end_entry.insert(0, str(total))
                end_entry.pack(side="left")

                start_entry.focus_set()
                start_entry.select_range(0, "end")

                def ok(_=None):
                    try:
                        s = int(start_entry.get())
                        if 1 <= s <= total:
                            result[0] = s
                    except ValueError:
                        pass
                    try:
                        e = int(end_entry.get())
                        if 1 <= e <= total:
                            result[1] = e
                    except ValueError:
                        pass
                    dlg.destroy()
                    event.set()

                def cancel():
                    dlg.destroy()
                    event.set()

                end_entry.bind("<Return>", ok)
                start_entry.bind("<Return>", lambda _: end_entry.focus_set())
                dlg.protocol("WM_DELETE_WINDOW", cancel)

                btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
                btn_frame.pack(padx=24, pady=(0, 20))
                ctk.CTkButton(btn_frame, text="OK", width=80, command=ok).pack(side="left", padx=5)
                ctk.CTkButton(btn_frame, text="Cancel", width=80, command=cancel, fg_color="gray50").pack(side="left", padx=5)

            self.after(0, show)
            event.wait()
            return result[0], result[1]

        return ask

    # ── Quiz run ──────────────────────────────────────────────────────────────

    def _start_quiz_run(self):
        urls = [e.get().strip() for _, e in self._url_rows if e.get().strip()]
        if not urls:
            self._append(self._quiz_log, "⚠  No URLs entered.")
            return
        self._save_courses(urls)
        self._last_quiz_urls = urls
        self._quiz_run_btn.configure(state="disabled", text="Running…")
        self._quiz_pause_btn.configure(state="normal")
        self._resume_event.set()
        self._quiz_log.configure(state="normal")
        self._quiz_log.delete("1.0", "end")
        self._quiz_log.configure(state="disabled")
        settings = {
            "set_in_gradebook": self._gradebook_var.get(),
            "set_auto_submit":  self._autosubmit_var.get(),
        }
        dry_run = self._quiz_dryrun.get()
        ask_fn  = self._make_ask_fn()
        q       = self._log_queue
        resume  = self._resume_event

        def pause_fn():
            if not resume.is_set():
                q.put(("quiz", "⏸  Paused — click Resume to continue..."))
                resume.wait()
                q.put(("quiz", "▶  Resuming..."))

        review_event = threading.Event()

        def review_fn():
            def show():
                self._popup_info(
                    "Quizzes Complete",
                    "All quizzes processed.\n\n"
                    "Review the browser for any errors, then click OK to close it.",
                )
                review_event.set()
            self.after(0, show)
            review_event.wait()

        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("quiz", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            success = False
            try:
                _sentry_context("quizzes", urls[0] if urls else "")
                from browser import run as browser_run
                asyncio.run(browser_run(urls=urls, dry_run=dry_run, settings=settings,
                                        pause_fn=pause_fn, ask_fn=ask_fn, review_fn=review_fn))
                success = True
                self._append_history(urls, "quiz")
            except Exception as e:
                _sentry_capture(e)
                q.put(("quiz", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("quiz", "__QUIZ_DONE__" if success else "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_quiz_pause(self):
        if self._resume_event.is_set():
            self._resume_event.clear()
            self._quiz_pause_btn.configure(text="▶   RESUME", fg_color="#2a4a2a")
        else:
            self._resume_event.set()
            self._quiz_pause_btn.configure(text="⏸   PAUSE", fg_color="#555555")

    # ── Quiz verify ───────────────────────────────────────────────────────────

    def _start_quiz_verify(self):
        urls = [e.get().strip() for _, e in self._url_rows if e.get().strip()]
        if not urls:
            self._append(self._quiz_log, "⚠  No course URLs entered.")
            return
        self._quiz_verify_btn.configure(state="disabled", text="Verifying…")
        self._quiz_log.configure(state="normal")
        self._quiz_log.delete("1.0", "end")
        self._quiz_log.configure(state="disabled")
        q = self._log_queue

        def worker():
            from browser import run_verify
            class W:
                def write(self, t):
                    if t.strip(): q.put(("quiz", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try:
                asyncio.run(run_verify(urls))
            except Exception as e:
                _sentry_capture(e)
                q.put(("quiz", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("quiz", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    # ── Assignment run ────────────────────────────────────────────────────────

    def _start_assignment_run(self):
        urls = [e.get().strip() for _, e in self._assign_url_rows if e.get().strip()]
        if not urls:
            self._append(self._assign_log, "⚠  No URLs entered.")
            return
        self._last_assign_urls = urls
        self._assign_run_btn.configure(state="disabled", text="Running…")
        self._assign_pause_btn.configure(state="normal")
        self._resume_event.set()
        self._assign_log.configure(state="normal")
        self._assign_log.delete("1.0", "end")
        self._assign_log.configure(state="disabled")
        settings = {"set_in_gradebook": self._assign_gradebook_var.get()}
        dry_run  = self._assign_dryrun.get()
        ask_fn   = self._make_ask_fn()
        q        = self._log_queue
        resume   = self._resume_event

        def pause_fn():
            if not resume.is_set():
                q.put(("assign", "⏸  Paused — click Resume to continue..."))
                resume.wait()
                q.put(("assign", "▶  Resuming..."))

        review_event = threading.Event()

        def review_fn():
            def show():
                self._popup_info(
                    "Assignments Complete",
                    "All assignments processed.\n\n"
                    "Review the browser for any errors, then click OK to close it.",
                )
                review_event.set()
            self.after(0, show)
            review_event.wait()

        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("assign", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            success = False
            try:
                _sentry_context("assignments", urls[0] if urls else "")
                from browser import run_assignments
                asyncio.run(run_assignments(urls=urls, dry_run=dry_run, settings=settings,
                                            pause_fn=pause_fn, ask_fn=ask_fn, review_fn=review_fn))
                success = True
                self._append_history(urls, "assignment")
            except Exception as e:
                _sentry_capture(e)
                q.put(("assign", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("assign", "__ASSIGN_DONE__" if success else "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_assign_pause(self):
        if self._resume_event.is_set():
            self._resume_event.clear()
            self._assign_pause_btn.configure(text="▶   RESUME", fg_color="#2a4a2a")
        else:
            self._resume_event.set()
            self._assign_pause_btn.configure(text="⏸   PAUSE", fg_color="#555555")

    # ── Themed popups (fall back to native messagebox if package missing) ─────

    def _popup_info(self, title: str, message: str):
        if CTkMessagebox:
            CTkMessagebox(master=self, title=title, message=message,
                          icon="check").get()
        else:
            messagebox.showinfo(title, message)

    def _popup_yesno(self, title: str, message: str) -> bool:
        if CTkMessagebox:
            box = CTkMessagebox(master=self, title=title, message=message,
                                icon="question", option_1="No", option_2="Yes")
            return box.get() == "Yes"
        return messagebox.askyesno(title, message)

    # ── Post-run review prompts ───────────────────────────────────────────────

    def _post_quiz_review(self):
        if self._popup_yesno(
            "Run Assignments?",
            "Would you also like to run the Assignment Automator\n"
            "for the same course(s)?",
        ):
            self._run_assignments_for(self._last_quiz_urls)

    def _post_assign_review(self):
        if self._popup_yesno(
            "Run Quizzes?",
            "Would you also like to run the Quiz Automator\n"
            "for the same course(s)?",
        ):
            self._run_quizzes_for(self._last_assign_urls)

    def _run_assignments_for(self, urls: list[str]):
        """Start assignment run with given URLs, using current assignment-panel settings."""
        if not urls:
            return
        self._show_panel("Assignment Automator")
        self._last_assign_urls = urls
        self._assign_run_btn.configure(state="disabled", text="Running…")
        self._assign_pause_btn.configure(state="normal")
        self._resume_event.set()
        self._assign_log.configure(state="normal")
        self._assign_log.delete("1.0", "end")
        self._assign_log.configure(state="disabled")
        settings = {"set_in_gradebook": self._assign_gradebook_var.get()}
        dry_run  = self._assign_dryrun.get()
        ask_fn   = self._make_ask_fn()
        q        = self._log_queue
        resume   = self._resume_event

        def pause_fn():
            if not resume.is_set():
                q.put(("assign", "⏸  Paused — click Resume to continue..."))
                resume.wait()
                q.put(("assign", "▶  Resuming..."))

        review_event2 = threading.Event()

        def review_fn2():
            def show():
                self._popup_info(
                    "All Done!",
                    "Quizzes and assignments are both complete.\n\n"
                    "Review the browser for any errors, then click OK to close it.",
                )
                review_event2.set()
            self.after(0, show)
            review_event2.wait()

        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("assign", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            success = False
            try:
                from browser import run_assignments
                asyncio.run(run_assignments(urls=urls, dry_run=dry_run, settings=settings,
                                            pause_fn=pause_fn, ask_fn=ask_fn, review_fn=review_fn2))
                success = True
            except Exception as e:
                _sentry_capture(e)
                q.put(("assign", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("assign", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    def _run_quizzes_for(self, urls: list[str]):
        """Start quiz run with given URLs, using current quiz-panel settings."""
        if not urls:
            return
        self._show_panel("Quiz Automator")
        self._last_quiz_urls = urls
        self._quiz_run_btn.configure(state="disabled", text="Running…")
        self._quiz_pause_btn.configure(state="normal")
        self._resume_event.set()
        self._quiz_log.configure(state="normal")
        self._quiz_log.delete("1.0", "end")
        self._quiz_log.configure(state="disabled")
        settings = {
            "set_in_gradebook": self._gradebook_var.get(),
            "set_auto_submit":  self._autosubmit_var.get(),
        }
        dry_run = self._quiz_dryrun.get()
        ask_fn  = self._make_ask_fn()
        q       = self._log_queue
        resume  = self._resume_event

        def pause_fn():
            if not resume.is_set():
                q.put(("quiz", "⏸  Paused — click Resume to continue..."))
                resume.wait()
                q.put(("quiz", "▶  Resuming..."))

        review_event3 = threading.Event()

        def review_fn3():
            def show():
                self._popup_info(
                    "All Done!",
                    "Assignments and quizzes are both complete.\n\n"
                    "Review the browser for any errors, then click OK to close it.",
                )
                review_event3.set()
            self.after(0, show)
            review_event3.wait()

        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("quiz", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            success = False
            try:
                _sentry_context("quizzes", urls[0] if urls else "")
                from browser import run as browser_run
                asyncio.run(browser_run(urls=urls, dry_run=dry_run, settings=settings,
                                        pause_fn=pause_fn, ask_fn=ask_fn, review_fn=review_fn3))
                success = True
            except Exception as e:
                _sentry_capture(e)
                q.put(("quiz", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("quiz", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    # ── Timer Fix run ─────────────────────────────────────────────────────────

    def _start_timer_fix(self):
        urls = [e.get().strip() for _, e in self._tfix_url_rows if e.get().strip()]
        if not urls:
            self._append(self._tfix_log, "⚠  No URLs entered.")
            return
        self._tfix_run_btn.configure(state="disabled", text="Running…")
        self._tfix_log.configure(state="normal")
        self._tfix_log.delete("1.0", "end")
        self._tfix_log.configure(state="disabled")
        dry_run   = self._tfix_dryrun.get()
        test_mode = self._tfix_testmode.get()
        ask_fn    = self._make_ask_fn()
        q = self._log_queue

        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("tfix", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try:
                _sentry_context("timer_fix", urls[0] if urls else "")
                from browser import run_timer_fix
                asyncio.run(run_timer_fix(urls=urls, dry_run=dry_run, ask_fn=ask_fn,
                                          limit=1 if test_mode else None))
            except Exception as e:
                _sentry_capture(e)
                q.put(("tfix", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("tfix", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    # ── Course Outline run ────────────────────────────────────────────────────

    def _start_outline_run(self):
        course_url = self._outline_url.get().strip()
        email      = self._cb_email.get().strip()
        password   = self._cb_password.get().strip()

        if not course_url:
            self._append(self._outline_log, "⚠  Course URL is required.")
            return
        if not email or not password:
            self._append(self._outline_log, "⚠  CourseBridge credentials required — go to Settings.")
            return

        self._outline_run_btn.configure(state="disabled", text="Running…")
        self._outline_log.configure(state="normal")
        self._outline_log.delete("1.0", "end")
        self._outline_log.configure(state="disabled")
        self._save_config(course_url=course_url, email=email, password=password)
        dry_run  = self._outline_dryrun.get()
        prompter = _GUIPrompter(self)
        q        = self._log_queue

        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("outline", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try:
                from course_outline_automator import run as outline_run
                asyncio.run(outline_run(
                    dry_run=dry_run,
                    course_url=course_url,
                    email=email,
                    password=password,
                    prompt_fn=prompter,
                ))
            except Exception as e:
                _sentry_capture(e)
                q.put(("outline", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("outline", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    def _start_test_step4(self):
        course_url = self._outline_url.get().strip()
        if not course_url:
            self._append(self._outline_log, "⚠  Course URL or CRN is required.")
            return
        self._test_step4_btn.configure(state="disabled", text="Running…")
        self._outline_log.configure(state="normal")
        self._outline_log.delete("1.0", "end")
        self._outline_log.configure(state="disabled")
        q = self._log_queue

        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("outline", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try:
                from course_outline_automator import test_step4
                asyncio.run(test_step4(course_url=course_url))
            except Exception as e:
                _sentry_capture(e)
                q.put(("outline", f"✗  {e}"))
            finally:
                sys.stdout = old
                self.after(0, lambda: self._test_step4_btn.configure(
                    state="normal",
                    text="▶   TEST STEP 4 ONLY  (paste existing HTML into Brightspace)",
                ))

        threading.Thread(target=worker, daemon=True).start()

    # ── Staging run ───────────────────────────────────────────────────────────

    def _start_staging_refresh(self):
        self._save_config(
            email=self._cb_email.get().strip(),
            password=self._cb_password.get().strip(),
        )
        self._staging_refresh_btn.configure(state="disabled", text="Refreshing…")
        self._staging_log.configure(state="normal")
        self._staging_log.delete("1.0", "end")
        self._staging_log.configure(state="disabled")
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
                if skipped:
                    from staging_scraper import get_dept, TRADES_CODES
                    import re as _re
                    print("\nSkipped courses:")
                    for c in sorted(courses):
                        if should_process(c):
                            continue
                        dept = get_dept(c)
                        m = _re.search(r'\.(\d+)$', c)
                        sem = m.group(1) if m else "?"
                        reasons = []
                        if dept not in TRADES_CODES:
                            reasons.append(f"dept '{dept}' not in TRADES_CODES")
                        if not (sem.endswith("10") or sem.endswith("20") or sem.endswith("30")):
                            reasons.append(f"semester '{sem}' doesn't end in 10/20/30")
                        print(f"   {c}  →  {', '.join(reasons) or 'unknown'}")
            except Exception as e:
                _sentry_capture(e)
                q.put(("staging", f"✗  {e}"))
            finally:
                sys.stdout = old
                self.after(0, lambda: (
                    self._staging_refresh_btn.configure(
                        state="normal", text="⟳  Refresh Queue",
                    ),
                    self._load_staging_queue_list(),
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _done_set(self) -> set:
        try:
            with open(STAGING_DONE_FILE, encoding="utf-8") as f:
                return set(json.load(f))
        except (FileNotFoundError, Exception):
            return set()

    def _save_done_set(self, done: set):
        with open(STAGING_DONE_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(done), f, indent=2)

    def _toggle_course_done(self, course: str):
        done = self._done_set()
        if course in done:
            done.discard(course)
        else:
            done.add(course)
        self._save_done_set(done)
        self._load_staging_queue_list()

    def _load_staging_queue_list(self):
        if not hasattr(self, "_queue_todo_frame"):
            return

        for w in self._queue_todo_frame.winfo_children():
            w.destroy()
        for w in self._queue_done_frame.winfo_children():
            w.destroy()

        queue_file = STAGING_QUEUE_FILE
        try:
            with open(queue_file, encoding="utf-8") as f:
                courses = [l.strip() for l in f if l.strip()]
        except FileNotFoundError:
            courses = []

        done    = self._done_set()
        pending = [c for c in courses if c not in done]
        completed = [c for c in courses if c in done]

        total = len(courses)
        ndone = len(completed)
        if hasattr(self, "_queue_status_label"):
            self._queue_status_label.configure(
                text=f"{ndone} of {total} done  ·  {total - ndone} remaining" if total
                else "No courses yet — click Refresh or add one above"
            )

        def _make_row(parent, course, is_done):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=4, pady=2)
            row.columnconfigure(0, weight=1)

            ctk.CTkButton(
                row, text=f"  {course}",
                height=30,
                font=ctk.CTkFont(family="Consolas", size=12),
                fg_color="#1c1c2e" if not is_done else "#141a14",
                hover_color="#22334a" if not is_done else "#1a2a1a",
                text_color="#b0b8cc" if not is_done else "#4a7a4a",
                anchor="w",
                command=lambda c=course: self._toggle_course_done(c),
            ).grid(row=0, column=0, sticky="ew", padx=(0, 4))

            ctk.CTkButton(
                row, text="×", width=28, height=30,
                font=ctk.CTkFont(size=14),
                fg_color="transparent",
                hover_color="#3a1a1a",
                text_color="#554444",
                command=lambda c=course: self._queue_delete_course(c),
            ).grid(row=0, column=1)

        if pending:
            for course in pending:
                _make_row(self._queue_todo_frame, course, is_done=False)
        else:
            ctk.CTkLabel(
                self._queue_todo_frame,
                text="Nothing left to do!" if courses else "No courses yet — click Refresh or add one above",
                text_color=_TEXT_FAINT, font=ctk.CTkFont(size=12),
            ).pack(anchor="w", padx=8, pady=10)

        if completed:
            for course in completed:
                _make_row(self._queue_done_frame, course, is_done=True)
        else:
            ctk.CTkLabel(
                self._queue_done_frame,
                text="No completed courses yet.",
                text_color=_TEXT_FAINT, font=ctk.CTkFont(size=12),
            ).pack(anchor="w", padx=8, pady=10)

    def _load_history_tab(self):
        if not hasattr(self, "_history_scroll"):
            return
        for w in self._history_scroll.winfo_children():
            w.destroy()

        term = self._history_search.get().strip().lower() if hasattr(self, "_history_search") else ""

        try:
            with open(COURSE_HISTORY_FILE, encoding="utf-8") as f:
                entries = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            entries = []

        filtered = [e for e in reversed(entries) if not term or term in e.get("url", "").lower()]

        if not filtered:
            ctk.CTkLabel(
                self._history_scroll,
                text="No history yet." if not term else "No matches.",
                text_color=_TEXT_FAINT, font=ctk.CTkFont(size=12),
            ).pack(anchor="w", padx=8, pady=10)
            return

        for entry in filtered:
            url   = entry.get("url", "")
            kind  = entry.get("type", "quiz")
            ts    = entry.get("timestamp", "")[:16].replace("T", " ")
            icon  = "[Q]" if kind == "quiz" else "[A]"
            short = url[-72:] if len(url) > 72 else url

            row = ctk.CTkFrame(self._history_scroll, fg_color=_CARD, corner_radius=6)
            row.pack(fill="x", padx=4, pady=2)
            row.columnconfigure(0, weight=1)
            ctk.CTkLabel(
                row, text=f"{icon}  {short}",
                font=ctk.CTkFont(family="Consolas", size=11),
                text_color="#8899bb", anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=(8, 4), pady=5)
            ctk.CTkLabel(
                row, text=ts,
                font=ctk.CTkFont(size=10), text_color="#445566", anchor="e",
            ).grid(row=0, column=1, padx=(0, 8))

    def _append_history(self, urls: list[str], kind: str):
        from datetime import datetime
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
            self.after(0, self._load_history_tab)
        except Exception:
            pass

    def _auto_extract_crn(self, on_done=None):
        val = self._staging_crn.get().strip()
        if not val.startswith("http"):
            return
        if getattr(self, "_crn_extracting", False):
            return
        # Don't retry a URL that already failed (unless explicitly triggered by a button)
        if not on_done and val == getattr(self, "_crn_last_failed_url", None):
            return
        self._crn_extracting = True
        q = self._log_queue

        def worker():
            from playwright.async_api import async_playwright
            import re as _re
            import json as _json

            async def run():
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    context = await browser.new_context(
                        storage_state=SESSION_FILE_GUI if os.path.exists(SESSION_FILE_GUI) else None
                    )
                    page = await context.new_page()
                    await page.goto(val)
                    await page.wait_for_load_state("domcontentloaded")
                    await page.wait_for_timeout(1500)

                    # For /d2l/home/{id} URLs, try the LP API — returns full course code as JSON
                    home_m = _re.search(r'/d2l/home/(\d+)', val)
                    if home_m:
                        from urllib.parse import urlparse
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

                    # Fall back: search the visible page text
                    text = await page.title()
                    text += " " + await page.evaluate("document.body.innerText")
                    await browser.close()
                    return text

            try:
                text = asyncio.run(run())
                m = _re.search(r'[A-Z][A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+-(\d+)\.\d+', text)
                if m:
                    crn = m.group(1)
                    self._crn_last_failed_url = None
                    self.after(0, lambda: (
                        self._staging_crn.delete(0, "end"),
                        self._staging_crn.insert(0, crn),
                    ))
                    q.put(("staging", f"✓  Extracted CRN: {crn}"))
                    if on_done:
                        self.after(100, on_done)
                else:
                    self._crn_last_failed_url = val
                    import re as _re2
                    if _re2.search(r'/d2l/home/\d+', val):
                        q.put(("staging", "ℹ  No CRN on this page — URL will be used directly."))
                    else:
                        q.put(("staging", "⚠  Could not find a course code on that page."))
            except Exception as e:
                q.put(("staging", f"✗  {e}"))
            finally:
                self._crn_extracting = False

        threading.Thread(target=worker, daemon=True).start()

    def _start_staging_step1(self):
        crn = self._staging_crn.get().strip()
        if not crn:
            queue_file = STAGING_QUEUE_FILE
            try:
                with open(queue_file) as f:
                    lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
                if not lines:
                    self._append(self._staging_log, "⚠  Staging queue is empty. Refresh first or enter a CRN.")
                    return
                course_code = lines[0]
                from staging_scraper import extract_crn
                crn = extract_crn(course_code) or course_code
                self._append(self._staging_log, f"Using queue: {course_code}  (CRN: {crn})")
            except FileNotFoundError:
                self._append(self._staging_log, "⚠  No staging queue found. Refresh first or enter a CRN.")
                return

        self._staging_step1_btn.configure(state="disabled", text="Running…")
        self._staging_log.configure(state="normal")
        self._staging_log.delete("1.0", "end")
        self._staging_log.configure(state="disabled")
        dry_run = self._staging_dryrun.get()
        q = self._log_queue

        def worker():
            from staging_automator import run_step1
            class W:
                def write(self, t):
                    if t.strip(): q.put(("staging", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try:
                _sentry_context("staging", crn)
                asyncio.run(run_step1(crn, dry_run=dry_run))
            except Exception as e:
                _sentry_capture(e)
                q.put(("staging", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("staging", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    def _start_staging_steps_1_2(self):
        crn = self._staging_crn.get().strip()
        if not crn:
            self._append(self._staging_log, "⚠  Enter a CRN or URL, or click a course from the list above.")
            return
        if crn.startswith("http") and not __import__("re").search(r'/d2l/home/\d+', crn):
            self._append(self._staging_log, "⚠  URL is missing the course ID — use the full URL, e.g. https://learn.okanagancollege.ca/d2l/home/12345")
            return
        self._staging_steps12_btn.configure(state="disabled", text="Running…")
        self._staging_log.configure(state="normal")
        self._staging_log.delete("1.0", "end")
        self._staging_log.configure(state="disabled")
        dry_run = self._staging_dryrun.get()
        q = self._log_queue

        prompter = _GUIPrompter(self)

        def worker():
            from staging_automator import run_steps_1_2
            class W:
                def write(self, t):
                    if t.strip(): q.put(("staging", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try:
                asyncio.run(run_steps_1_2(crn, dry_run=dry_run, prompt_fn=prompter, note_fn=lambda t: q.put(("note", t))))
            except Exception as e:
                _sentry_capture(e)
                q.put(("staging", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("staging", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    App().mainloop()
