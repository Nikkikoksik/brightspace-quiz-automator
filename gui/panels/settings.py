import asyncio
import os
import sys
import threading

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from gui.constants import SESSION_FILE_GUI
from gui.telemetry import _init_sentry, _sentry_capture
from gui.theme import T, _btn, _card, _entry_style


class SettingsPanelMixin:

    def _build_settings_panel(self, parent: QWidget):
        layout = self._panel_scroll(parent)
        self._panel_header(layout, "Settings", "Credentials and global configuration")

        self._section_label(layout, "COURSEBRIDGE")
        cb_frame  = QFrame()
        cb_frame.setStyleSheet(_card())
        cb_layout = QVBoxLayout(cb_frame)
        cb_layout.setContentsMargins(16, 16, 16, 16)
        cb_layout.setSpacing(8)
        cb_layout.addWidget(QLabel("Email"))
        self._cb_email = QLineEdit()
        self._cb_email.setFixedHeight(36)
        self._cb_email.setStyleSheet(_entry_style())
        cb_layout.addWidget(self._cb_email)
        cb_layout.addWidget(QLabel("Password"))
        self._cb_password = QLineEdit()
        self._cb_password.setFixedHeight(36)
        self._cb_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._cb_password.setStyleSheet(_entry_style())
        cb_layout.addWidget(self._cb_password)
        layout.addWidget(cb_frame)
        layout.addSpacing(16)

        self._section_label(layout, "BRIGHTSPACE SESSION")
        bs_frame  = QFrame()
        bs_frame.setStyleSheet(_card())
        bs_layout = QVBoxLayout(bs_frame)
        bs_layout.setContentsMargins(16, 16, 16, 16)
        bs_layout.setSpacing(8)
        bs_layout.addWidget(QLabel("Username"))
        self._bs_username = QLineEdit()
        self._bs_username.setFixedHeight(36)
        self._bs_username.setStyleSheet(_entry_style())
        bs_layout.addWidget(self._bs_username)
        bs_layout.addWidget(QLabel("Password"))
        self._bs_password = QLineEdit()
        self._bs_password.setFixedHeight(36)
        self._bs_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._bs_password.setStyleSheet(_entry_style())
        bs_layout.addWidget(self._bs_password)
        session_exists = os.path.exists(SESSION_FILE_GUI)
        self._bs_status = QLabel(
            "✓  Session saved" if session_exists else "✗  No session — log in first"
        )
        self._bs_status.setStyleSheet(
            f"color: {T['success'] if session_exists else T['warn']}; font-size: 12px;"
        )
        bs_layout.addWidget(self._bs_status)
        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(8)
        self._bs_login_btn = QPushButton("Login to Brightspace")
        self._bs_login_btn.setFixedHeight(36)
        self._bs_login_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"]))
        self._bs_login_btn.clicked.connect(self._start_bs_login)
        clear_sess_btn = QPushButton("Clear Session")
        clear_sess_btn.setFixedHeight(36)
        clear_sess_btn.setStyleSheet(_btn(T["btn_danger"], T["btn_danger_h"]))
        clear_sess_btn.clicked.connect(self._clear_bs_session)
        btn_row2.addWidget(self._bs_login_btn)
        btn_row2.addWidget(clear_sess_btn)
        btn_row2.addStretch()
        bs_layout.addLayout(btn_row2)
        layout.addWidget(bs_frame)
        layout.addSpacing(16)

        self._section_label(layout, "ERROR REPORTING (SENTRY)")
        sentry_frame  = QFrame()
        sentry_frame.setStyleSheet(_card())
        sentry_layout = QVBoxLayout(sentry_frame)
        sentry_layout.setContentsMargins(16, 16, 16, 16)
        sentry_layout.setSpacing(8)
        sentry_layout.addWidget(QLabel("Sentry DSN  (leave blank to disable)"))
        self._sentry_dsn = QLineEdit()
        self._sentry_dsn.setPlaceholderText("https://...@sentry.io/...")
        self._sentry_dsn.setFixedHeight(36)
        self._sentry_dsn.setStyleSheet(_entry_style())
        sentry_layout.addWidget(self._sentry_dsn)
        layout.addWidget(sentry_frame)
        layout.addSpacing(16)

        self._section_label(layout, "AI PROVIDER (GRADEBOOK)")
        ai_frame  = QFrame()
        ai_frame.setStyleSheet(_card())
        ai_layout = QVBoxLayout(ai_frame)
        ai_layout.setContentsMargins(16, 16, 16, 16)
        ai_layout.setSpacing(8)
        ai_layout.addWidget(QLabel("Provider"))
        self._ai_provider_combo = QComboBox()
        self._ai_provider_combo.addItems(["Claude", "GPT", "Gemini"])
        self._ai_provider_combo.setFixedHeight(36)
        self._ai_provider_combo.setStyleSheet(_entry_style())
        ai_layout.addWidget(self._ai_provider_combo)
        self._ai_key_fields = {}
        for label, key in [("Claude API key", "claude"), ("GPT API key", "gpt"),
                           ("Gemini API key", "gemini")]:
            ai_layout.addWidget(QLabel(label))
            field = QLineEdit()
            field.setFixedHeight(36)
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setStyleSheet(_entry_style())
            ai_layout.addWidget(field)
            self._ai_key_fields[key] = field
        layout.addWidget(ai_frame)
        layout.addSpacing(20)

        self._save_settings_btn = QPushButton("Save Settings")
        self._save_settings_btn.setFixedHeight(42)
        self._save_settings_btn.setFixedWidth(160)
        self._save_settings_btn.setStyleSheet(_btn(T["btn_primary"], T["btn_primary_h"]))
        self._save_settings_btn.clicked.connect(self._save_settings)
        layout.addWidget(self._save_settings_btn)
        layout.addStretch()

    def _save_settings(self):
        dsn = self._sentry_dsn.text().strip()
        self._save_config(
            email=self._cb_email.text().strip(),
            password=self._cb_password.text().strip(),
            sentry_dsn=dsn,
            bs_username=self._bs_username.text().strip(),
            bs_password=self._bs_password.text().strip(),
            ai_provider=self._ai_provider_combo.currentText().lower(),
            claude_api_key=self._ai_key_fields["claude"].text().strip(),
            gpt_api_key=self._ai_key_fields["gpt"].text().strip(),
            gemini_api_key=self._ai_key_fields["gemini"].text().strip(),
        )
        _init_sentry(dsn)
        self._save_settings_btn.setText("✓  Saved")
        QTimer.singleShot(1500, lambda: self._save_settings_btn.setText("Save Settings"))

    def _start_bs_login(self):
        self._bs_login_btn.setEnabled(False)
        self._bs_login_btn.setText("Opening browser…")
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
                QTimer.singleShot(0, lambda: (
                    self._bs_status.setText("✓  Session saved"),
                    self._bs_status.setStyleSheet(f"color: {T['success']}; font-size: 12px;"),
                ))
            except Exception as e:
                _sentry_capture(e)
                q.put(("outline", f"✗  Login failed: {e}"))
            finally:
                sys.stdout = old
                QTimer.singleShot(0, lambda: (
                    self._bs_login_btn.setEnabled(True),
                    self._bs_login_btn.setText("Login to Brightspace"),
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _clear_bs_session(self):
        if os.path.exists(SESSION_FILE_GUI):
            os.remove(SESSION_FILE_GUI)
        self._bs_status.setText("✗  No session — log in first")
        self._bs_status.setStyleSheet(f"color: {T['warn']}; font-size: 12px;")
