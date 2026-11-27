# -*- coding: utf-8 -*-
"""Embedded Chat Playground widget - Bilingual & Figma Glassmorphism Style."""

from __future__ import annotations

import json
import threading
import time
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    LineEdit,
    PlainTextEdit,
    PrimaryPushButton,
    TransparentPushButton,
)
import requests

from config_manager import config_mgr
from gui.theme import MONO_FONT, TEXT_ICY_CYAN, TEXT_WHITE
from i18n import tr


class ChatSignalBridge(QObject):
    """Thread-safe signal bridge for streaming chat completions."""
    token_received = Signal(int, str)
    finished = Signal(int, float, float)  # stream_gen, ttft, total_duration in seconds
    error_occurred = Signal(int, str)


class ChatWidget(QWidget):
    """Interactive chat playground testing the local API endpoint."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.messages: list[dict] = []
        self._current_reply: str = ""
        self._stream_gen: int = 0
        self._http_session = requests.Session()
        self._bridge = ChatSignalBridge()
        self._bridge.token_received.connect(self.on_token)
        self._bridge.finished.connect(self.on_finished)
        self._bridge.error_occurred.connect(self.on_error)
        self.setup_ui()

    def setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        # Header bar
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(2, 0, 2, 0)
        self.status_lbl = CaptionLabel(tr("chat_header", port=config_mgr.config.api_port))
        self.status_lbl.setStyleSheet(f"color: {TEXT_ICY_CYAN}; {MONO_FONT} font-size: 11px; letter-spacing: 0.5px;")

        self.btn_clear = TransparentPushButton(tr("chat_clear"), self, FluentIcon.DELETE)
        self.btn_clear.clicked.connect(self.clear_chat)

        header_layout.addWidget(self.status_lbl)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_clear)
        layout.addLayout(header_layout)

        # Chat history display (opaque dark surface for lag-free streaming)
        self.chat_display = PlainTextEdit(self)
        self.chat_display.setReadOnly(True)
        self.chat_display.setMaximumBlockCount(5000)
        self.chat_display.setStyleSheet(
            f"border-radius: 6px; padding: 10px; {MONO_FONT} font-size: 12px; color: {TEXT_WHITE};"
        )
        layout.addWidget(self.chat_display, 1)

        # Bottom Input row
        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)
        self.msg_input = LineEdit(self)
        self.msg_input.setPlaceholderText(tr("chat_placeholder"))
        self.msg_input.setStyleSheet(f"{MONO_FONT} font-size: 12px; color: {TEXT_WHITE};")
        self.msg_input.returnPressed.connect(self.send_message)

        self.btn_send = PrimaryPushButton(tr("chat_send"), self, FluentIcon.SEND)
        self.btn_send.clicked.connect(self.send_message)

        input_layout.addWidget(self.msg_input, 1)
        input_layout.addWidget(self.btn_send)
        layout.addLayout(input_layout)

    def append_text(self, text: str) -> None:
        if not text:
            return
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.chat_display.setTextCursor(cursor)
        self.chat_display.ensureCursorVisible()

    def refresh_endpoint(self) -> None:
        self.status_lbl.setText(tr("chat_header", port=config_mgr.config.api_port))

    def retranslate_ui(self) -> None:
        self.refresh_endpoint()
        self.btn_clear.setText(tr("chat_clear"))
        self.msg_input.setPlaceholderText(tr("chat_placeholder"))
        self.btn_send.setText(tr("chat_send"))

    def send_message(self) -> None:
        if not self.btn_send.isEnabled():
            return
        text = self.msg_input.text().strip()
        if not text:
            return

        cfg = config_mgr.config
        from tunnel_daemon import tunnel_daemon

        # Guard: check if local gateway port is open
        if not tunnel_daemon.is_port_open(port=cfg.api_port):
            t = time.strftime("%H:%M:%S")
            self.append_text(f"[{t}] USER:\n{text}\n\n[{t}] ASSISTANT:\n")
            self.append_text(tr("chat_offline_hint", port=cfg.api_port))
            self.msg_input.clear()
            self.msg_input.setFocus()
            return

        try:
            tunnel_daemon.record_activity()
        except Exception:
            pass

        self.msg_input.clear()
        self.btn_send.setEnabled(False)
        self.msg_input.setEnabled(False)
        self._current_reply = ""
        self._stream_gen += 1
        stream_gen = self._stream_gen

        # Append user message in terminal format
        t = time.strftime("%H:%M:%S")
        self.append_text(f"[{t}] USER:\n{text}\n\n[{t}] ASSISTANT:\n")
        self.messages.append({"role": "user", "content": text})

        # Launch streaming worker in daemon thread
        messages_snapshot = list(self.messages)
        base_url = cfg.api_base_url
        api_key = cfg.api_key
        model = cfg.selected_model_alias

        def _stream_worker():
            start_time = time.time()
            first_token_time = None
            url = f"{base_url.rstrip('/')}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
            payload = {
                "model": model,
                "messages": messages_snapshot,
                "stream": True,
                "temperature": 0.7,
            }

            try:
                with self._http_session.post(url, json=payload, headers=headers, stream=True, timeout=120) as resp:
                    if resp.status_code != 200:
                        err_text = resp.content.decode("utf-8", errors="replace")
                        self._bridge.error_occurred.emit(stream_gen, f"HTTP {resp.status_code}: {err_text}")
                        return

                    # Explicitly decode as UTF-8 bytes and disable chunk buffering for real-time SSE streaming
                    for line in resp.iter_lines(chunk_size=1):
                        if not line:
                            continue
                        line_str = line.decode("utf-8", errors="replace")
                        if line_str.startswith("data: "):
                            raw_data = line_str[6:].strip()
                            if raw_data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(raw_data)
                                delta = chunk["choices"][0]["delta"].get("content", "")
                                if delta:
                                    if first_token_time is None:
                                        first_token_time = time.time()
                                    self._bridge.token_received.emit(stream_gen, delta)
                            except Exception:
                                pass

                end_time = time.time()
                total_duration = round(end_time - start_time, 2)
                ttft = round((first_token_time - start_time), 2) if first_token_time else total_duration
                self._bridge.finished.emit(stream_gen, ttft, total_duration)

            except Exception as e:
                self._bridge.error_occurred.emit(stream_gen, str(e))

        threading.Thread(target=_stream_worker, daemon=True).start()

    def on_token(self, stream_gen: int, token: str) -> None:
        if stream_gen != self._stream_gen:
            return
        self._current_reply += token
        self.append_text(token)

    def on_finished(self, stream_gen: int, ttft: float, total_duration: float) -> None:
        if stream_gen != self._stream_gen:
            return
        if self._current_reply:
            self.messages.append({"role": "assistant", "content": self._current_reply})
        elif self.messages and self.messages[-1].get("role") == "user":
            self.messages.pop()
        self.append_text(tr("chat_done_metrics", ttft=ttft, total=total_duration))
        self.btn_send.setEnabled(True)
        self.msg_input.setEnabled(True)
        self.msg_input.setFocus()

    def on_error(self, stream_gen: int, err_msg: str) -> None:
        if stream_gen != self._stream_gen:
            return
        if self.messages and self.messages[-1].get("role") == "user":
            self.messages.pop()
        port = config_mgr.config.api_port
        if "10061" in err_msg or "refused" in err_msg.lower():
            self.append_text(f"\n  [{tr('chat_refused', port=port)}]\n\n")
        else:
            self.append_text(f"\n  [error: {err_msg}]\n\n")
        self.btn_send.setEnabled(True)
        self.msg_input.setEnabled(True)
        self.msg_input.setFocus()

    def clear_chat(self) -> None:
        self._stream_gen += 1
        self._current_reply = ""
        self.messages.clear()
        self.chat_display.clear()
        self.btn_send.setEnabled(True)
        self.msg_input.setEnabled(True)
        self.append_text(tr("chat_reset"))
