import asyncio
import json
import os
import queue
import sys
import threading
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

_HERE       = Path(__file__).parent
from config import COURSES_FILE
OUTLINE_CFG = str(_HERE / "outline_config.json")

_SIDEBAR_BG = "#1a1a2e"
_NAV_HOVER  = "#252540"
_NAV_ACTIVE = "#2e2e52"


class _GUIPrompter:
    """Bridges worker-thread input() calls to main-thread dialogs."""

    def __init__(self, root):
        self._root = root

    def __call__(self, prompt: str) -> str:
        result = [""]
        event  = threading.Event()

        def show():
            if "(y/n)" in prompt:
                ans = messagebox.askyesno("Confirmation", prompt.replace("(y/n)", "").strip())
                result[0] = "y" if ans else "n"
            else:
                messagebox.showinfo("Action Required", prompt)
                result[0] = ""
            event.set()

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

        self._build_ui()
        self._load_courses()
        self._load_config()
        self.after(100, self._poll_log)

    # ── Layout helpers ────────────────────────────────────────────────────────

    def _panel_body(self, parent, title: str, subtitle: str = "") -> ctk.CTkScrollableFrame:
        """Standard panel header + divider + scrollable content area."""
        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.pack(fill="x", padx=24, pady=(20, 0))
        ctk.CTkLabel(hdr, text=title,
                     font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w")
        if subtitle:
            ctk.CTkLabel(hdr, text=subtitle,
                         font=ctk.CTkFont(size=12), text_color="gray").pack(anchor="w", pady=(2, 0))
        ctk.CTkFrame(parent, height=1, fg_color="#333355").pack(fill="x", padx=24, pady=(12, 4))
        body = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        return body

    def _section_label(self, parent, text: str):
        ctk.CTkLabel(parent, text=text,
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="gray").pack(anchor="w", pady=(12, 4))

    # ── UI layout ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        sidebar = ctk.CTkFrame(self, width=200, corner_radius=0, fg_color=_SIDEBAR_BG)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(6, weight=1)  # spacer pushes Settings to bottom

        ctk.CTkLabel(
            sidebar, text="Brightspace\nAutomator",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="white", justify="left",
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(28, 20))

        nav_items = [
            ("Quiz Automator",       "  Quizzes"),
            ("Assignment Automator", "  Assignments"),
            ("Timer Fix",            "  Timer Fix"),
            ("Course Outline",       "  Course Outline"),
            ("Staging",              "  Staging"),
        ]
        self._nav_btns = {}
        for r, (key, label) in enumerate(nav_items, start=1):
            btn = ctk.CTkButton(
                sidebar, text=label, anchor="w", height=40,
                fg_color="transparent", hover_color=_NAV_HOVER,
                text_color="#aaaacc", font=ctk.CTkFont(size=13),
                corner_radius=6,
                command=lambda k=key: self._show_panel(k),
            )
            btn.grid(row=r, column=0, sticky="ew", padx=8, pady=2)
            self._nav_btns[key] = btn

        ctk.CTkFrame(sidebar, height=1, fg_color="#2a2a45").grid(
            row=6, column=0, sticky="sew", padx=16, pady=(0, 4),
        )
        settings_btn = ctk.CTkButton(
            sidebar, text="  Settings", anchor="w", height=40,
            fg_color="transparent", hover_color=_NAV_HOVER,
            text_color="#aaaacc", font=ctk.CTkFont(size=13),
            corner_radius=6,
            command=lambda: self._show_panel("Settings"),
        )
        settings_btn.grid(row=7, column=0, sticky="ew", padx=8, pady=(0, 16))
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
            ("Settings",             self._build_settings_panel),
        ]:
            panel = ctk.CTkFrame(content, corner_radius=0, fg_color="transparent")
            panel.grid(row=0, column=0, sticky="nsew")
            panel.grid_rowconfigure(0, weight=1)
            panel.grid_columnconfigure(0, weight=1)
            self._panels[key] = panel
            builder(panel)

        self._show_panel("Quiz Automator")

    def _show_panel(self, name: str):
        for panel in self._panels.values():
            panel.grid_remove()
        self._panels[name].grid()
        for key, btn in self._nav_btns.items():
            if key == name:
                btn.configure(fg_color=_NAV_ACTIVE, text_color="white")
            else:
                btn.configure(fg_color="transparent", text_color="#aaaacc")

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
            body, text="▶   RUN QUIZ AUTOMATOR", height=52,
            font=ctk.CTkFont(size=17, weight="bold"),
            command=self._start_quiz_run,
        )
        self._quiz_run_btn.pack(fill="x", pady=(0, 6))

        self._quiz_pause_btn = ctk.CTkButton(
            body, text="⏸   PAUSE", height=36,
            fg_color="#555555", hover_color="#444444",
            command=self._toggle_quiz_pause, state="disabled",
        )
        self._quiz_pause_btn.pack(fill="x", pady=(0, 12))

        self._section_label(body, "LOG")
        self._quiz_log = ctk.CTkTextbox(
            body, height=200, state="disabled",
            font=ctk.CTkFont(family="Courier New", size=12),
        )
        self._quiz_log.pack(fill="x")

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
            body, text="▶   RUN ASSIGNMENT AUTOMATOR", height=52,
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

        self._section_label(body, "LOG")
        self._assign_log = ctk.CTkTextbox(
            body, height=200, state="disabled",
            font=ctk.CTkFont(family="Courier New", size=12),
        )
        self._assign_log.pack(fill="x")
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
        ctk.CTkCheckBox(sf, text="Dry run  (preview only — nothing will be saved)",
                        variable=self._tfix_dryrun,
                        text_color="#f0a500").pack(anchor="w", padx=16, pady=14)

        self._tfix_run_btn = ctk.CTkButton(
            body, text="▶   RUN TIMER FIX", height=52,
            font=ctk.CTkFont(size=17, weight="bold"),
            command=self._start_timer_fix,
        )
        self._tfix_run_btn.pack(fill="x", pady=(0, 16))

        self._section_label(body, "LOG")
        self._tfix_log = ctk.CTkTextbox(
            body, height=280, state="disabled",
            font=ctk.CTkFont(family="Courier New", size=12),
        )
        self._tfix_log.pack(fill="x")
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
            body, text="▶   RUN COURSE OUTLINE AUTOMATOR", height=52,
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

        self._section_label(body, "LOG")
        self._outline_log = ctk.CTkTextbox(
            body, height=220, state="disabled",
            font=ctk.CTkFont(family="Courier New", size=12),
        )
        self._outline_log.pack(fill="x")

    # ── Staging panel ─────────────────────────────────────────────────────────

    def _build_staging_panel(self, parent):
        body = self._panel_body(parent, "Staging",
                                "Automate the Brightspace staging process one step at a time")

        self._section_label(body, "CRN  (leave blank to use first course in staging queue)")
        self._staging_crn = ctk.CTkEntry(
            body, placeholder_text="Enter CRN…  (leave blank to use first course in queue)",
            height=38,
        )
        self._staging_crn.pack(fill="x", pady=(0, 16))

        sf = ctk.CTkFrame(body)
        sf.pack(fill="x", pady=(0, 16))
        self._staging_dryrun = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(sf, text="Dry run  (find shell + navigate, but do not click anything)",
                        variable=self._staging_dryrun,
                        text_color="#f0a500").pack(anchor="w", padx=16, pady=14)

        self._staging_refresh_btn = ctk.CTkButton(
            body, text="⟳   REFRESH QUEUE FROM COURSEBRIDGE", height=38,
            fg_color="#2a2a4a", hover_color="#3a3a6a",
            command=self._start_staging_refresh,
        )
        self._staging_refresh_btn.pack(fill="x", pady=(0, 8))

        self._staging_step1_btn = ctk.CTkButton(
            body, text="▶   STEP 1 — Hide Blueprint Module", height=52,
            font=ctk.CTkFont(size=17, weight="bold"),
            command=self._start_staging_step1,
        )
        self._staging_step1_btn.pack(fill="x", pady=(0, 16))

        self._section_label(body, "LOG")
        self._staging_log = ctk.CTkTextbox(
            body, height=280, state="disabled",
            font=ctk.CTkFont(family="Courier New", size=12),
        )
        self._staging_log.pack(fill="x")

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

        session_exists = os.path.exists(str(_HERE / "session.json"))
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
            fg_color="#4a2a2a", hover_color="#6a3a3a",
            command=self._clear_bs_session,
        ).pack(side="left")

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
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_config(self, course_url=None, email=None, password=None):
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
                q.put(("outline", f"✗  Login failed: {e}"))
            finally:
                sys.stdout = old
                self.after(0, lambda: self._bs_login_btn.configure(
                    state="normal", text="Login to Brightspace"
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _clear_bs_session(self):
        session_file = str(_HERE / "session.json")
        if os.path.exists(session_file):
            os.remove(session_file)
        self._bs_status.configure(text="✗  No session — log in first", text_color="#f0a500")

    def _save_settings(self):
        self._save_config(
            email=self._cb_email.get().strip(),
            password=self._cb_password.get().strip(),
        )
        self._save_settings_btn.configure(text="✓  Saved")
        self.after(1500, lambda: self._save_settings_btn.configure(text="Save Settings"))

    # ── URL row helpers ───────────────────────────────────────────────────────

    def _add_url_row(self, url=""):
        row = ctk.CTkFrame(self._urls_container, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=5)
        entry = ctk.CTkEntry(row, placeholder_text="Paste quiz page URL here…", height=38)
        entry.pack(side="left", fill="x", expand=True)
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
        entry = ctk.CTkEntry(row, placeholder_text="Paste assignment page URL here…", height=38)
        entry.pack(side="left", fill="x", expand=True)
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

                if msg == "__DONE__":
                    if tag == "quiz":
                        self._quiz_run_btn.configure(state="normal", text="▶   RUN QUIZ AUTOMATOR")
                        self._quiz_pause_btn.configure(state="disabled", text="⏸   PAUSE", fg_color="#555555")
                        self._resume_event.set()
                    elif tag == "assign":
                        self._assign_run_btn.configure(state="normal", text="▶   RUN ASSIGNMENT AUTOMATOR")
                        self._assign_pause_btn.configure(state="disabled", text="⏸   PAUSE", fg_color="#555555")
                        self._resume_event.set()
                    elif tag == "tfix":
                        self._tfix_run_btn.configure(state="normal", text="▶   RUN TIMER FIX")
                    elif tag == "staging":
                        self._staging_step1_btn.configure(state="normal", text="▶   STEP 1 — Hide Blueprint Module")
                    else:
                        self._outline_run_btn.configure(state="normal", text="▶   RUN COURSE OUTLINE AUTOMATOR")
                else:
                    self._append(box, msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    # ── Ask-start-from dialog ─────────────────────────────────────────────────

    def _make_ask_fn(self):
        import tkinter.simpledialog as sd
        result = [1]
        event  = threading.Event()

        def ask(total, label):
            def show():
                val = sd.askinteger(
                    "Start from",
                    f"Found {total} {label}(s).\n\nStart from which number?\n(Leave blank or cancel = start from 1)",
                    minvalue=1, maxvalue=total, initialvalue=1,
                )
                result[0] = val if val else 1
                event.set()
            self.after(0, show)
            event.wait()
            return result[0]

        return ask

    # ── Quiz run ──────────────────────────────────────────────────────────────

    def _start_quiz_run(self):
        urls = [e.get().strip() for _, e in self._url_rows if e.get().strip()]
        if not urls:
            self._append(self._quiz_log, "⚠  No URLs entered.")
            return
        self._save_courses(urls)
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

        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("quiz", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try:
                from browser import run as browser_run
                asyncio.run(browser_run(urls=urls, dry_run=dry_run, settings=settings,
                                        pause_fn=pause_fn, ask_fn=ask_fn))
            except Exception as e:
                q.put(("quiz", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("quiz", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_quiz_pause(self):
        if self._resume_event.is_set():
            self._resume_event.clear()
            self._quiz_pause_btn.configure(text="▶   RESUME", fg_color="#2a4a2a")
        else:
            self._resume_event.set()
            self._quiz_pause_btn.configure(text="⏸   PAUSE", fg_color="#555555")

    # ── Assignment run ────────────────────────────────────────────────────────

    def _start_assignment_run(self):
        urls = [e.get().strip() for _, e in self._assign_url_rows if e.get().strip()]
        if not urls:
            self._append(self._assign_log, "⚠  No URLs entered.")
            return
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

        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("assign", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try:
                from browser import run_assignments
                asyncio.run(run_assignments(urls=urls, dry_run=dry_run, settings=settings,
                                            pause_fn=pause_fn, ask_fn=ask_fn))
            except Exception as e:
                q.put(("assign", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("assign", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_assign_pause(self):
        if self._resume_event.is_set():
            self._resume_event.clear()
            self._assign_pause_btn.configure(text="▶   RESUME", fg_color="#2a4a2a")
        else:
            self._resume_event.set()
            self._assign_pause_btn.configure(text="⏸   PAUSE", fg_color="#555555")

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
        dry_run = self._tfix_dryrun.get()
        ask_fn  = self._make_ask_fn()
        q = self._log_queue

        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("tfix", t.rstrip()))
                def flush(self): pass
            old, sys.stdout = sys.stdout, W()
            try:
                from browser import run_timer_fix
                asyncio.run(run_timer_fix(urls=urls, dry_run=dry_run, ask_fn=ask_fn))
            except Exception as e:
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
                with open(str(_HERE / "staging_queue.txt"), "w", encoding="utf-8") as f:
                    for c in filtered:
                        f.write(c + "\n")
                print(f"\n✓ Queue updated — {len(filtered)} course(s) to stage  ({skipped} skipped)")
                for c in filtered:
                    print(f"   {c}")
            except Exception as e:
                q.put(("staging", f"✗  {e}"))
            finally:
                sys.stdout = old
                self.after(0, lambda: self._staging_refresh_btn.configure(
                    state="normal", text="⟳   REFRESH QUEUE FROM COURSEBRIDGE",
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _start_staging_step1(self):
        crn = self._staging_crn.get().strip()
        if not crn:
            queue_file = str(_HERE / "staging_queue.txt")
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
                asyncio.run(run_step1(crn, dry_run=dry_run))
            except Exception as e:
                q.put(("staging", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("staging", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    App().mainloop()
