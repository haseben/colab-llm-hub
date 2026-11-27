# -*- coding: utf-8 -*-
"""Interactive Google Colab OAuth2 Sign-In Wizard Dialog."""

from __future__ import annotations

import threading
from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SimpleCardWidget,
    StrongBodyLabel,
)

from colab_orchestrator import colab_orchestrator
from gui.theme import BG_CANVAS, BG_GLASS_CARD, BORDER_GLASS, MONO_FONT, TEXT_ICY_CYAN, TEXT_MUTED, TEXT_WHITE
from i18n import tr


class _AuthBridge(QObject):
    url_ready = Signal(object, str)
    url_error = Signal(str)
    done = Signal(bool, str)


class ColabAuthDialog(QDialog):
    """Guides first-time users through Google Colab OAuth2 authorization inside the GUI."""

    def __init__(self, parent=None, lang: str | None = None) -> None:
        super().__init__(parent)
        self._lang = lang
        self._flow = None
        self._auth_url = ""
        self._bridge = _AuthBridge()
        self._bridge.url_ready.connect(self._on_url_ready)
        self._bridge.url_error.connect(self._on_url_error)
        self._bridge.done.connect(self._on_auth_done)

        self.setWindowTitle(tr("auth_dialog_title", self._lang))
        self.setMinimumWidth(560)
        self.setStyleSheet(f"background-color: {BG_CANVAS}; color: {TEXT_WHITE};")
        self._setup_ui()
        self._prepare_flow()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        card = SimpleCardWidget(self)
        card.setStyleSheet(f"background-color: {BG_GLASS_CARD}; border: 1px solid {BORDER_GLASS}; border-radius: 8px;")
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(16, 14, 16, 14)
        c_lay.setSpacing(10)

        title = StrongBodyLabel(tr("auth_dialog_title", self._lang))
        title.setStyleSheet(f"font-size: 14px; color: {TEXT_ICY_CYAN};")
        desc = CaptionLabel(tr("auth_dialog_desc", self._lang))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        c_lay.addWidget(title)
        c_lay.addWidget(desc)

        step1_lbl = CaptionLabel(tr("auth_step1", self._lang))
        step1_lbl.setWordWrap(True)
        step1_lbl.setStyleSheet(f"color: {TEXT_WHITE}; font-size: 12px;")
        c_lay.addWidget(step1_lbl)

        btn_row = QHBoxLayout()
        self.btn_open = PrimaryPushButton(tr("auth_open_browser", self._lang), self, FluentIcon.GLOBE)
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self._open_browser)

        self.btn_copy = PushButton(tr("auth_copy_url", self._lang), self, FluentIcon.COPY)
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self._copy_url)

        btn_row.addWidget(self.btn_open)
        btn_row.addWidget(self.btn_copy)
        btn_row.addStretch()
        c_lay.addLayout(btn_row)

        step2_lbl = CaptionLabel(tr("auth_step2", self._lang))
        step2_lbl.setWordWrap(True)
        step2_lbl.setStyleSheet(f"color: {TEXT_WHITE}; font-size: 12px; margin-top: 4px;")
        c_lay.addWidget(step2_lbl)

        self.code_edit = LineEdit(self)
        self.code_edit.setPlaceholderText(tr("auth_code_ph", self._lang))
        self.code_edit.setStyleSheet(f"{MONO_FONT} font-size: 12px;")
        self.code_edit.returnPressed.connect(self._submit_code)
        c_lay.addWidget(self.code_edit)

        layout.addWidget(card)

        foot = QHBoxLayout()
        foot.addStretch()
        self.btn_cancel = PushButton(tr("settings_cancel", self._lang), self)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_submit = PrimaryPushButton(tr("auth_submit", self._lang), self, FluentIcon.ACCEPT)
        self.btn_submit.setEnabled(False)
        self.btn_submit.clicked.connect(self._submit_code)
        foot.addWidget(self.btn_cancel)
        foot.addWidget(self.btn_submit)
        layout.addLayout(foot)

    def _prepare_flow(self) -> None:
        def _worker():
            try:
                flow, url = colab_orchestrator.start_oauth_flow()
                self._bridge.url_ready.emit(flow, url)
            except Exception as e:
                self._bridge.url_error.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_url_ready(self, flow, url: str) -> None:
        self._flow = flow
        self._auth_url = url
        self.btn_open.setEnabled(True)
        self.btn_copy.setEnabled(True)
        self.btn_submit.setEnabled(True)

    def _on_url_error(self, err: str) -> None:
        InfoBar.error(
            tr("warn_title", self._lang),
            tr("auth_fail", self._lang, err=err),
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )

    def _open_browser(self) -> None:
        if self._auth_url:
            QDesktopServices.openUrl(QUrl(self._auth_url))
            self.code_edit.setFocus()

    def _copy_url(self) -> None:
        if self._auth_url:
            QApplication.clipboard().setText(self._auth_url)
            InfoBar.success(
                tr("copied_title", self._lang),
                tr("copied_msg", self._lang, name="URL"),
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000,
            )

    def _submit_code(self) -> None:
        code = self.code_edit.text().strip()
        if not code or not self._flow:
            return
        self.btn_submit.setEnabled(False)
        flow = self._flow

        def _worker():
            try:
                colab_orchestrator.finish_oauth_flow(flow, code)
                self._bridge.done.emit(True, "")
            except Exception as e:
                self._bridge.done.emit(False, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_auth_done(self, ok: bool, err: str) -> None:
        self.btn_submit.setEnabled(True)
        if ok:
            InfoBar.success(
                tr("copied_title", self._lang),
                tr("auth_success", self._lang),
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2500,
            )
            self.accept()
        else:
            InfoBar.error(
                tr("warn_title", self._lang),
                tr("auth_fail", self._lang, err=err),
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000,
            )
