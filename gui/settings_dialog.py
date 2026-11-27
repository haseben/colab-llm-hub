# -*- coding: utf-8 -*-
"""Settings Dialog - Bilingual (ZH/EN) Configuration & Diagnostics."""

from __future__ import annotations

import re
import secrets
import shutil
from pathlib import Path
from PySide6.QtWidgets import QDialog, QFileDialog, QFormLayout, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    CaptionLabel,
    CheckBox,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    SimpleCardWidget,
    SpinBox,
    StrongBodyLabel,
)

from colab_orchestrator import colab_orchestrator
from config_manager import APP_VERSION, LOG_FILE_PATH, config_mgr
from gui.auth_dialog import ColabAuthDialog
from gui.theme import (
    BG_CANVAS,
    BG_GLASS_CARD,
    BG_GLASS_SUBTLE,
    BORDER_GLASS,
    MONO_FONT,
    TEXT_ICY_CYAN,
    TEXT_MUTED,
    TEXT_WHITE,
)
from i18n import tr


class SettingsDialog(QDialog):
    """Modal dialog for editing application configurations."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lang = config_mgr.config.language or "zh"
        self.setWindowTitle(f"{tr('settings_title', self._lang)} (v{APP_VERSION})")
        self.setMinimumWidth(580)
        self.setStyleSheet(f"background-color: {BG_CANVAS}; color: {TEXT_WHITE};")
        self.setup_ui()
        self.load_settings()

    def setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header note card
        header_card = SimpleCardWidget(self)
        header_card.setStyleSheet(f"background-color: {BG_GLASS_SUBTLE}; border: 1px solid {BORDER_GLASS}; border-radius: 6px;")
        h_lay = QVBoxLayout(header_card)
        h_lay.setContentsMargins(12, 10, 12, 10)
        h_title = StrongBodyLabel(f"CONFIGURATION // LOCAL ISOLATION  •  v{APP_VERSION}")
        h_title.setStyleSheet(f"{MONO_FONT} font-size: 11px; letter-spacing: 0.5px; color: {TEXT_ICY_CYAN};")
        self.h_desc = CaptionLabel(tr("settings_sub", self._lang))
        self.h_desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self.env_lbl = CaptionLabel("")
        self.env_lbl.setStyleSheet(f"{MONO_FONT} color: {TEXT_ICY_CYAN}; font-size: 11px;")
        h_lay.addWidget(h_title)
        h_lay.addWidget(self.h_desc)
        h_lay.addWidget(self.env_lbl)
        layout.addWidget(header_card)

        # Form card
        form_card = SimpleCardWidget(self)
        form_card.setStyleSheet(f"background-color: {BG_GLASS_CARD}; border: 1px solid {BORDER_GLASS}; border-radius: 6px;")
        self.form = QFormLayout(form_card)
        self.form.setContentsMargins(14, 14, 14, 14)
        self.form.setSpacing(10)

        # Language selector
        self.lang_combo = ComboBox(self)
        self.lang_combo.addItem("简体中文", userData="zh")
        self.lang_combo.addItem("English", userData="en")
        self.form.addRow(tr("settings_lang", self._lang), self.lang_combo)

        # API Key
        key_layout = QHBoxLayout()
        key_layout.setSpacing(6)
        self.key_edit = LineEdit(self)
        self.key_edit.setPlaceholderText("Bearer API Key")
        self.key_edit.setStyleSheet(f"{MONO_FONT} font-size: 11px;")
        self.btn_gen_key = PushButton(tr("settings_gen", self._lang), self, FluentIcon.SYNC)
        self.btn_gen_key.clicked.connect(self.generate_new_key)
        key_layout.addWidget(self.key_edit, 1)
        key_layout.addWidget(self.btn_gen_key)
        self.form.addRow(tr("settings_key", self._lang), key_layout)

        # API Port
        self.port_spin = SpinBox(self)
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(18080)
        self.port_spin.setStyleSheet(f"{MONO_FONT} font-size: 12px;")
        self.form.addRow(tr("settings_port", self._lang), self.port_spin)

        # Colab Session
        self.session_edit = LineEdit(self)
        self.session_edit.setPlaceholderText("colab-llm-server")
        self.session_edit.setStyleSheet(f"{MONO_FONT} font-size: 11px;")
        self.form.addRow(tr("settings_session", self._lang), self.session_edit)

        # GPU Type (Free + Pro + Pro+ tiers)
        self.gpu_combo = ComboBox(self)
        for label, code in [
            ("T4 (15 GB · Free / Pro)", "T4"),
            ("L4 (22.5 GB · Pro / Pro+)", "L4"),
            ("A100 (40 GB · Pro / Pro+)", "A100"),
            ("H100 (80 GB · Pro+)", "H100"),
            ("G4 / RTX Pro 6000 (96 GB · Pro+)", "G4"),
            ("CPU (No GPU)", "CPU"),
        ]:
            self.gpu_combo.addItem(label, userData=code)
        self.form.addRow(tr("settings_gpu", self._lang), self.gpu_combo)

        # High-RAM VM option
        self.high_mem_check = CheckBox(tr("settings_high_mem", self._lang), self)
        self.form.addRow("", self.high_mem_check)

        # llama.cpp Release Tag
        self.llama_tag_edit = LineEdit(self)
        self.llama_tag_edit.setPlaceholderText("b12556")
        self.llama_tag_edit.setStyleSheet(f"{MONO_FONT} font-size: 11px;")
        self.form.addRow(tr("settings_llama_tag", self._lang), self.llama_tag_edit)

        # Hugging Face Token
        self.hf_token_edit = PasswordLineEdit(self)
        self.hf_token_edit.setPlaceholderText(tr("settings_hf_ph", self._lang))
        self.hf_token_edit.setStyleSheet(f"{MONO_FONT} font-size: 11px;")
        self.form.addRow(tr("settings_hf_token", self._lang), self.hf_token_edit)

        # Keep-Alive Interval
        self.keepalive_spin = SpinBox(self)
        self.keepalive_spin.setRange(30, 900)
        self.keepalive_spin.setValue(180)
        self.keepalive_spin.setStyleSheet(f"{MONO_FONT} font-size: 12px;")
        self.form.addRow(tr("settings_keepalive", self._lang), self.keepalive_spin)

        # SSH Key Path
        key_path_layout = QHBoxLayout()
        key_path_layout.setSpacing(6)
        self.ssh_key_edit = LineEdit(self)
        self.ssh_key_edit.setStyleSheet(f"{MONO_FONT} font-size: 11px;")
        self.btn_browse_key = PushButton(tr("settings_browse", self._lang), self, FluentIcon.FOLDER)
        self.btn_browse_key.clicked.connect(self.browse_ssh_key)
        key_path_layout.addWidget(self.ssh_key_edit, 1)
        key_path_layout.addWidget(self.btn_browse_key)
        self.form.addRow(tr("settings_ssh_key", self._lang), key_path_layout)

        # Google Drive cache
        self.gdrive_check = CheckBox(tr("settings_gdrive", self._lang), self)
        self.gdrive_check.setChecked(True)
        self.form.addRow("", self.gdrive_check)

        layout.addWidget(form_card)

        # Bottom Buttons (Auth + Export Log + Cancel + Save)
        btn_layout = QHBoxLayout()
        self.btn_auth = PushButton(tr("settings_auth_btn", self._lang), self, FluentIcon.PEOPLE)
        self.btn_auth.clicked.connect(self.open_auth_wizard)

        self.btn_export = PushButton(tr("settings_export_btn", self._lang), self, FluentIcon.SAVE_AS)
        self.btn_export.clicked.connect(self.export_diagnostic_log)

        btn_layout.addWidget(self.btn_auth)
        btn_layout.addWidget(self.btn_export)
        btn_layout.addStretch()

        self.btn_cancel = PushButton(tr("settings_cancel", self._lang), self)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_save = PrimaryPushButton(tr("settings_save", self._lang), self, FluentIcon.SAVE)
        self.btn_save.clicked.connect(self.save_settings)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

    def refresh_env_status(self) -> None:
        env = colab_orchestrator.check_environment()
        parts = [
            f"SSH:{'OK' if env['has_ssh'] and env['has_ssh_keygen'] else 'MISSING'}",
            f"CLI:{'OK' if env['has_cli'] else 'MISSING'}",
            f"OAuth:{'OK' if env['has_auth'] else 'NOT_SIGNED_IN'}",
        ]
        self.env_lbl.setText(tr("settings_env_box", self._lang, summary=" | ".join(parts)))

    def open_auth_wizard(self) -> None:
        dlg = ColabAuthDialog(self, lang=self._lang)
        if dlg.exec():
            self.refresh_env_status()

    def export_diagnostic_log(self) -> None:
        dest, _ = QFileDialog.getSaveFileName(
            self,
            tr("settings_export_btn", self._lang),
            str(Path.home() / "colab_model_hub_diag.log"),
            "Log Files (*.log *.txt)",
        )
        if not dest:
            return
        try:
            if LOG_FILE_PATH.is_file():
                shutil.copy(LOG_FILE_PATH, dest)
            else:
                Path(dest).write_text("No diagnostic log file created yet.\n", encoding="utf-8")
            InfoBar.success(
                tr("copied_title", self._lang),
                dest,
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2500,
            )
        except Exception as e:
            InfoBar.error(tr("settings_save_fail", self._lang), str(e), parent=self, position=InfoBarPosition.TOP)

    def generate_new_key(self) -> None:
        new_key = f"colab-sk-{secrets.token_hex(16)}"
        self.key_edit.setText(new_key)

    def browse_ssh_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("settings_ssh_key", self._lang), str(Path.home()))
        if path:
            self.ssh_key_edit.setText(path)

    def load_settings(self) -> None:
        cfg = config_mgr.config
        lang_idx = 1 if str(cfg.language).lower().startswith("en") else 0
        self.lang_combo.setCurrentIndex(lang_idx)
        self.key_edit.setText(cfg.api_key)
        self.port_spin.setValue(cfg.api_port)
        self.session_edit.setText(cfg.colab_session)
        gpu_code = str(cfg.colab_gpu or "T4").upper()
        gpu_idx = next((i for i in range(self.gpu_combo.count()) if self.gpu_combo.itemData(i) == gpu_code), 0)
        self.gpu_combo.setCurrentIndex(gpu_idx)
        self.high_mem_check.setChecked(bool(cfg.high_mem))
        self.llama_tag_edit.setText(cfg.llama_cpp_tag or "b12556")
        self.hf_token_edit.setText(cfg.hf_token)
        self.keepalive_spin.setValue(cfg.keep_alive_interval)
        self.ssh_key_edit.setText(cfg.ssh_key_path)
        self.gdrive_check.setChecked(cfg.enable_gdrive_cache)
        self.refresh_env_status()

    def save_settings(self) -> None:
        cfg = config_mgr.config
        cfg.language = self.lang_combo.currentData() or "zh"
        cfg.api_key = self.key_edit.text().strip() or f"colab-sk-{secrets.token_hex(16)}"
        cfg.api_port = self.port_spin.value()
        raw_session = self.session_edit.text().strip() or "colab-llm-server"
        cfg.colab_session = re.sub(r"\s+", "-", raw_session)
        cfg.colab_gpu = self.gpu_combo.currentData() or "T4"
        cfg.high_mem = self.high_mem_check.isChecked()
        cfg.llama_cpp_tag = self.llama_tag_edit.text().strip() or "b12556"
        cfg.hf_token = self.hf_token_edit.text().strip()
        cfg.keep_alive_interval = self.keepalive_spin.value()
        cfg.ssh_key_path = self.ssh_key_edit.text().strip()
        cfg.enable_gdrive_cache = self.gdrive_check.isChecked()

        try:
            config_mgr.save()
            config_mgr.ensure_ssh_key()
            self.accept()
        except Exception as e:
            InfoBar.error(
                tr("settings_save_fail", cfg.language),
                str(e),
                parent=self,
                position=InfoBarPosition.TOP,
            )
