import asyncio
import queue
import sys
import threading

import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COURSES_FILE = "courses.txt"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Brightspace Quiz Automator")
        self.geometry("680x740")
        self.resizable(False, False)

        self._log_queue = queue.Queue()
        self._url_rows = []

        self._build_ui()
        self._load_courses()
        self.after(100, self._poll_log)

    # ── UI layout ────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header bar
        header = ctk.CTkFrame(self, fg_color="#1a1a2e", corner_radius=0, height=64)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, text="Brightspace Quiz Automator",
            font=ctk.CTkFont(size=20, weight="bold"), text_color="white",
        ).pack(side="left", padx=24, pady=14)

        # Scrollable body
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=12)
        self._body = body

        # ── Course URLs ──────────────────────────────────────────────────────
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

        # ── Settings ─────────────────────────────────────────────────────────
        ctk.CTkLabel(body, text="SETTINGS",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="gray").pack(anchor="w", pady=(0, 4))

        sf = ctk.CTkFrame(body)
        sf.pack(fill="x", pady=(0, 18))

        self._gradebook_var  = ctk.BooleanVar(value=True)
        self._autosubmit_var = ctk.BooleanVar(value=True)
        self._dryrun_var     = ctk.BooleanVar(value=False)

        ctk.CTkCheckBox(sf, text="Add to Grade Book",
                        variable=self._gradebook_var).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkCheckBox(sf, text="Auto-submit on timer expiry",
                        variable=self._autosubmit_var).pack(anchor="w", padx=16, pady=4)
        ctk.CTkCheckBox(sf, text="Dry run  (preview only — nothing will be saved)",
                        variable=self._dryrun_var,
                        text_color="#f0a500").pack(anchor="w", padx=16, pady=(4, 14))

        # ── Run button ───────────────────────────────────────────────────────
        self._run_btn = ctk.CTkButton(
            body, text="▶   RUN", height=52,
            font=ctk.CTkFont(size=17, weight="bold"),
            command=self._start_run,
        )
        self._run_btn.pack(fill="x", pady=(0, 18))

        # ── Log ──────────────────────────────────────────────────────────────
        ctk.CTkLabel(body, text="LOG",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="gray").pack(anchor="w", pady=(0, 4))

        self._log_box = ctk.CTkTextbox(
            body, height=200, state="disabled",
            font=ctk.CTkFont(family="Courier New", size=12),
        )
        self._log_box.pack(fill="x")

    # ── URL rows ─────────────────────────────────────────────────────────────

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

    # ── Log ──────────────────────────────────────────────────────────────────

    def _append_log(self, text):
        self._log_box.configure(state="normal")
        self._log_box.insert("end", text + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _poll_log(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                if msg == "__DONE__":
                    self._run_btn.configure(state="normal", text="▶   RUN")
                else:
                    self._append_log(msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    # ── Run ──────────────────────────────────────────────────────────────────

    def _start_run(self):
        urls = [e.get().strip() for _, e in self._url_rows if e.get().strip()]
        if not urls:
            self._append_log("⚠  No URLs entered.")
            return

        self._save_courses(urls)
        self._run_btn.configure(state="disabled", text="Running…")
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.configure(state="disabled")

        settings = {
            "set_in_gradebook": self._gradebook_var.get(),
            "set_auto_submit":  self._autosubmit_var.get(),
        }
        dry_run = self._dryrun_var.get()

        def worker():
            class QueueWriter:
                def __init__(self, q):   self.q = q
                def write(self, text):
                    if text.strip():     self.q.put(text.rstrip())
                def flush(self):         pass

            old = sys.stdout
            sys.stdout = QueueWriter(self._log_queue)
            try:
                from browser import run as browser_run
                asyncio.run(browser_run(urls=urls, dry_run=dry_run, settings=settings))
            except Exception as e:
                self._log_queue.put(f"✗  {e}")
            finally:
                sys.stdout = old
                self._log_queue.put("__DONE__")

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    App().mainloop()
