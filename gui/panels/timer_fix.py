import asyncio
import sys
import threading

from PyQt6.QtWidgets import QCheckBox, QPushButton, QWidget

from gui.telemetry import _sentry_capture, _sentry_context
from gui.theme import T, _btn, _checkbox_style


class TimerFixPanelMixin:

    def _build_timerfix_panel(self, parent: QWidget):
        layout = self._panel_scroll(parent)
        self._panel_header(
            layout, "Timer Fix",
            "Re-run only the auto-submit timer fix — skips grade book entirely",
        )

        self._section_label(layout, "QUIZ PAGE URLS")
        self._tfix_url_container, _ = self._make_url_rows_container()
        layout.addWidget(self._tfix_url_container)
        layout.addSpacing(6)

        add_btn = QPushButton("＋  Add quiz page URL")
        add_btn.setFixedHeight(32)
        add_btn.setStyleSheet(
            _btn("transparent", T["btn_muted"], T["text_muted"])
            + "QPushButton { border: 1px solid " + T["card_border"] + "; }"
        )
        add_btn.clicked.connect(
            lambda: self._add_url_row(
                self._tfix_url_container,
                self._tfix_url_rows,
                placeholder="Paste quiz page URL here…",
            )
        )
        layout.addWidget(add_btn)
        layout.addSpacing(16)

        self._tfix_dryrun = QCheckBox("Dry run  (preview only — nothing will be saved)")
        self._tfix_dryrun.setStyleSheet(_checkbox_style(warn=True))
        self._tfix_testmode = QCheckBox("Test mode  (first quiz only)")
        self._tfix_testmode.setStyleSheet(_checkbox_style(warn=True))
        for cb in [self._tfix_dryrun, self._tfix_testmode]:
            layout.addWidget(cb)
        layout.addSpacing(20)

        self._tfix_run_btn = QPushButton("▶  Run Timer Fix")
        self._tfix_run_btn.setFixedHeight(52)
        self._tfix_run_btn.setStyleSheet(
            _btn(T["btn_primary"], T["btn_primary_h"]) + "QPushButton { font-size: 16px; }"
        )
        self._tfix_run_btn.clicked.connect(self._start_timer_fix)
        layout.addWidget(self._tfix_run_btn)
        layout.addSpacing(20)

        self._section_label(layout, "LOG")
        self._tfix_log = self._make_log(layout, min_height=280)
        layout.addStretch()

    def _start_timer_fix(self):
        urls = [e.text().strip() for _, e in self._tfix_url_rows if e.text().strip()]
        if not urls:
            self._log_append(self._tfix_log, "⚠  No URLs entered.")
            return
        self._tfix_run_btn.setEnabled(False)
        self._tfix_run_btn.setText("Running…")
        self._tfix_log.clear()
        dry_run   = self._tfix_dryrun.isChecked()
        test_mode = self._tfix_testmode.isChecked()
        ask_fn    = self._make_ask_fn()
        q         = self._log_queue

        def worker():
            from browser import run_timer_fix

            class W:
                def write(self, t):
                    if t.strip(): q.put(("tfix", t.rstrip()))
                def flush(self): pass

            old, sys.stdout = sys.stdout, W()
            try:
                _sentry_context("timer_fix", urls[0] if urls else "")
                asyncio.run(run_timer_fix(
                    urls=urls, dry_run=dry_run,
                    ask_fn=ask_fn,
                    limit=1 if test_mode else None,
                ))
            except Exception as e:
                _sentry_capture(e)
                q.put(("tfix", f"✗  {e}"))
            finally:
                sys.stdout = old
                q.put(("tfix", "__DONE__"))

        threading.Thread(target=worker, daemon=True).start()
