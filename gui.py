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

_HERE        = Path(__file__).parent
COURSES_FILE = str(_HERE / "courses.txt")
OUTLINE_CFG  = str(_HERE / "outline_config.json")


# ── GUI prompt helper (used by course outline automator) ─────────────────────
class _GUIPrompter:
    """Bridges worker-thread input() calls to main-thread dialogs."""

    def __init__(self, root):
        self._root = root

    def __call__(self, prompt: str) -> str:
        result = [""]
        event = threading.Event()

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
        self.geometry("700x800")
        self.resizable(False, False)

        self._log_queue   = queue.Queue()
        self._url_rows    = []

        self._build_ui()
        self._load_courses()
        self._load_outline_config()
        self.after(100, self._poll_log)

    # ── UI layout ────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        header = ctk.CTkFrame(self, fg_color="#1a1a2e", corner_radius=0, height=64)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, text="Brightspace Automator",
            font=ctk.CTkFont(size=20, weight="bold"), text_color="white",
        ).pack(side="left", padx=24, pady=14)

        # Tabs
        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, padx=16, pady=(8, 16))
        tabs.add("Quiz Automator")
        tabs.add("Course Outline")

        self._build_quiz_tab(tabs.tab("Quiz Automator"))
        self._build_outline_tab(tabs.tab("Course Outline"))

    # ── Quiz Automator tab ───────────────────────────────────────────────────

    def _build_quiz_tab(self, parent):
        body = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        body.pack(fill="both", expand=True)
        self._quiz_body = body

        ctk.CTkLabel(body, text="COURSE URLS",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="gray").pack(anchor="w", pady=(8, 4))

        self._urls_container = ctk.CTkFrame(body)
        self._urls_container.pack(fill="x", pady=(0, 6))

        ctk.CTkButton(
            body, text="＋  Add course URL", height=32,
            fg_color="transparent", border_width=1,
            command=self._add_url_row,
        ).pack(anchor="w", pady=(0, 18))

        ctk.CTkLabel(body, text="SETTINGS",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="gray").pack(anchor="w", pady=(0, 4))

        sf = ctk.CTkFrame(body)
        sf.pack(fill="x", pady=(0, 18))

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
        self._quiz_run_btn.pack(fill="x", pady=(0, 18))

        ctk.CTkLabel(body, text="LOG",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="gray").pack(anchor="w", pady=(0, 4))

        self._quiz_log = ctk.CTkTextbox(
            body, height=200, state="disabled",
            font=ctk.CTkFont(family="Courier New", size=12),
        )
        self._quiz_log.pack(fill="x")

    # ── Course Outline tab ───────────────────────────────────────────────────

    def _build_outline_tab(self, parent):
        body = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        body.pack(fill="both", expand=True)

        # Course URL
        ctk.CTkLabel(body, text="COURSE  (CRN number  or  full Brightspace URL)",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="gray").pack(anchor="w", pady=(8, 4))
        self._outline_url = ctk.CTkEntry(body, placeholder_text="e.g.  80147  or  https://learn.okanagancollege.ca/…", height=38)
        self._outline_url.pack(fill="x", pady=(0, 18))

        # CourseBridge credentials
        ctk.CTkLabel(body, text="COURSEBRIDGE CREDENTIALS",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="gray").pack(anchor="w", pady=(0, 4))

        cf = ctk.CTkFrame(body)
        cf.pack(fill="x", pady=(0, 18))

        ctk.CTkLabel(cf, text="Email").pack(anchor="w", padx=16, pady=(14, 2))
        self._cb_email = ctk.CTkEntry(cf, height=36)
        self._cb_email.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(cf, text="Password").pack(anchor="w", padx=16, pady=(0, 2))
        self._cb_password = ctk.CTkEntry(cf, height=36, show="●")
        self._cb_password.pack(fill="x", padx=16, pady=(0, 14))

        # Pre-fill from module defaults (overridden by saved config on startup)
        from course_outline_automator import COURSEBRIDGE_EMAIL, COURSEBRIDGE_PASSWORD
        if COURSEBRIDGE_EMAIL:
            self._cb_email.insert(0, COURSEBRIDGE_EMAIL)
        if COURSEBRIDGE_PASSWORD:
            self._cb_password.insert(0, COURSEBRIDGE_PASSWORD)
        # Note: _load_outline_config() runs after _build_ui() and overwrites these

        # Options
        ctk.CTkLabel(body, text="OPTIONS",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="gray").pack(anchor="w", pady=(0, 4))

        of = ctk.CTkFrame(body)
        of.pack(fill="x", pady=(0, 18))

        self._outline_dryrun = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            of,
            text="Dry run  (download + convert only — nothing pasted into Brightspace)",
            variable=self._outline_dryrun,
            text_color="#f0a500",
        ).pack(anchor="w", padx=16, pady=14)

        self._outline_run_btn = ctk.CTkButton(
            body, text="▶   RUN COURSE OUTLINE AUTOMATOR", height=52,
            font=ctk.CTkFont(size=17, weight="bold"),
            command=self._start_outline_run,
        )
        self._outline_run_btn.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(body, text="TEST INDIVIDUAL STEPS",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="gray").pack(anchor="w", pady=(8, 4))

        self._test_step4_btn = ctk.CTkButton(
            body, text="▶   TEST STEP 4 ONLY  (paste existing HTML into Brightspace)",
            height=38, font=ctk.CTkFont(size=13),
            fg_color="#2a4a2a", hover_color="#3a6a3a",
            command=self._start_test_step4,
        )
        self._test_step4_btn.pack(fill="x", pady=(0, 18))

        ctk.CTkLabel(body, text="LOG",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="gray").pack(anchor="w", pady=(0, 4))

        self._outline_log = ctk.CTkTextbox(
            body, height=220, state="disabled",
            font=ctk.CTkFont(family="Courier New", size=12),
        )
        self._outline_log.pack(fill="x")

    # ── Outline config persistence ────────────────────────────────────────────

    def _load_outline_config(self):
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

    def _save_outline_config(self, course_url, email, password):
        with open(OUTLINE_CFG, "w") as f:
            json.dump({"course_url": course_url, "cb_email": email, "cb_password": password}, f)

    # ── URL rows (quiz tab) ───────────────────────────────────────────────────

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

        ctk.CTkButton(
            row, text="✕", width=38, height=38,
            fg_color="transparent", text_color="gray",
            hover_color="#3a3a3a", command=remove,
        ).pack(side="left", padx=(6, 0))

        self._url_rows.append((row, entry))

    # ── Persistence ──────────────────────────────────────────────────────────

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
                item = self._log_queue.get_nowait()
                tag, msg = item
                box = self._quiz_log if tag == "quiz" else self._outline_log
                if msg == "__DONE__":
                    if tag == "quiz":
                        self._quiz_run_btn.configure(state="normal", text="▶   RUN QUIZ AUTOMATOR")
                    else:
                        self._outline_run_btn.configure(state="normal", text="▶   RUN COURSE OUTLINE AUTOMATOR")
                else:
                    self._append(box, msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    # ── Quiz run ─────────────────────────────────────────────────────────────

    def _start_quiz_run(self):
        urls = [e.get().strip() for _, e in self._url_rows if e.get().strip()]
        if not urls:
            self._append(self._quiz_log, "⚠  No URLs entered.")
            return

        self._save_courses(urls)
        self._quiz_run_btn.configure(state="disabled", text="Running…")
        self._quiz_log.configure(state="normal")
        self._quiz_log.delete("1.0", "end")
        self._quiz_log.configure(state="disabled")

        settings = {
            "set_in_gradebook": self._gradebook_var.get(),
            "set_auto_submit":  self._autosubmit_var.get(),
        }
        dry_run = self._quiz_dryrun.get()
        q = self._log_queue

        def worker():
            class W:
                def write(self, t):
                    if t.strip(): q.put(("quiz", t.rstrip()))
                def flush(self): pass

            old, sys.stdout = sys.stdout, W()
            try:
                from browser import run as browser_run
                asyncio.run(browser_run(urls=urls, dry_run=dry_run, settings=settings))
            except Exception as e:
                q.put(("quiz", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("quiz", "__DONE__"))

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
            self._append(self._outline_log, "⚠  CourseBridge email and password are required.")
            return

        self._outline_run_btn.configure(state="disabled", text="Running…")
        self._outline_log.configure(state="normal")
        self._outline_log.delete("1.0", "end")
        self._outline_log.configure(state="disabled")

        self._save_outline_config(course_url, email, password)
        dry_run    = self._outline_dryrun.get()
        prompter   = _GUIPrompter(self)
        q          = self._log_queue

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

    # ── Test Step 4 ───────────────────────────────────────────────────────────

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
                    text="▶   TEST STEP 4 ONLY  (paste existing HTML into Brightspace)"
                ))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    App().mainloop()
