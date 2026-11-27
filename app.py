# -*- coding: utf-8 -*-
"""Colab Model Hub & Gateway Desktop Application Entry Point."""

from __future__ import annotations

import os
import sys

# Force UTF-8 encoding across Windows subprocesses
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

# Subprocess dispatcher mode: allows frozen .exe (and dev mode) to execute bundled colab_cli
if len(sys.argv) >= 2 and sys.argv[1] == "--colab-cli":
    sys.argv = ["colab"] + sys.argv[2:]
    for _stream_name in ("stdout", "stderr"):
        _stream = getattr(sys, _stream_name, None)
        if _stream and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    from colab_cli.cli import main as _colab_cli_main

    _colab_cli_main()
    sys.exit(0)

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from config_manager import APP_DIR, MEI_DIR, config_mgr
from gui.theme import setup_theme
from gui.main_window import MainWindow
from tunnel_daemon import tunnel_daemon


def main() -> None:
    # Ensure config and SSH keys are verified on boot
    config_mgr.ensure_ssh_key()

    app = QApplication(sys.argv)
    app.setApplicationName("Colab Model Hub")
    for ico_cand in (MEI_DIR / "gui" / "assets" / "app.ico", APP_DIR / "gui" / "assets" / "app.ico"):
        if ico_cand.is_file():
            app.setWindowIcon(QIcon(str(ico_cand)))
            break
    # Do not set setApplicationDisplayName to avoid Qt title concatenation repetition
    setup_theme(app)

    window = MainWindow()
    window.show()

    # Ensure tunnel process is terminated when application closes
    def cleanup():
        print("[App] 正在关闭应用并清理后台守护进程...")
        tunnel_daemon.stop()

    app.aboutToQuit.connect(cleanup)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
