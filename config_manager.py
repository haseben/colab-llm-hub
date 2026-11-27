# -*- coding: utf-8 -*-
"""Configuration and credential manager.
Strictly adheres to Zero Hardcoded Credentials:
All sensitive tokens and user settings are stored in local git-ignored config.json
or dynamically generated on demand.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
    MEI_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    APP_DIR = Path(__file__).resolve().parent
    MEI_DIR = APP_DIR

DEFAULT_CONFIG_PATH = APP_DIR / "config.json"
USER_DATA_DIR = Path.home() / ".colab_launcher"
LOG_FILE_PATH = USER_DATA_DIR / "app.log"
DEFAULT_KEY_DIR = APP_DIR / "秘钥"
DEFAULT_KEY_PATH = DEFAULT_KEY_DIR / "colab_tunnel_ed25519"
APP_VERSION = "1.0.0"

GPU_VRAM_MAP: dict[str, float] = {
    "T4": 15.0,
    "L4": 22.5,
    "A100": 40.0,
    "CPU": 0.0,
}


def get_gpu_vram_limit(gpu_type: str) -> float:
    return GPU_VRAM_MAP.get(str(gpu_type or "T4").upper(), 15.0)


def append_app_log(line: str) -> None:
    """Append a line to ~/.colab_launcher/app.log with a lightweight 2 MB cap."""
    try:
        LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if LOG_FILE_PATH.exists() and LOG_FILE_PATH.stat().st_size > 2 * 1024 * 1024:
            backup = LOG_FILE_PATH.with_suffix(".log.old")
            if backup.exists():
                backup.unlink()
            LOG_FILE_PATH.rename(backup)
        with open(LOG_FILE_PATH, "a", encoding="utf-8", errors="replace") as f:
            f.write(line if line.endswith("\n") else line + "\n")
    except Exception:
        pass


@dataclass
class AppConfig:
    api_key: str = field(default_factory=lambda: f"colab-sk-{secrets.token_hex(16)}")
    api_port: int = 18080
    colab_session: str = "colab-llm-server"
    colab_gpu: str = "T4"
    hf_token: str = ""
    ssh_key_path: str = str(DEFAULT_KEY_PATH)
    selected_repo: str = "Qwen/Qwen2.5-7B-Instruct-GGUF"
    selected_file: str = "qwen2.5-7b-instruct-q4_k_m.gguf"
    selected_model_alias: str = "qwen2.5-7b"
    ctx_size: int = 4096
    enable_gdrive_cache: bool = True
    keep_alive_interval: int = 180
    dark_mode: bool = True
    language: str = "zh"
    llama_cpp_tag: str = "b12556"

    @property
    def api_base_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}/v1"

    @property
    def health_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}/health"


class ConfigManager:
    """Manages loading, saving, and verifying local configurations."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        should_save = not self.config_path.exists()
        self.config = self.load()
        if should_save:
            try:
                self.save()
            except Exception as e:
                print(f"[ConfigManager] 保存初始配置文件异常: {e}")

    def load(self) -> AppConfig:
        data: dict[str, Any] = {}
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                print(f"[ConfigManager] 读取配置文件异常: {e}，将采用默认配置。")

        # Load environment variables if available and not set in JSON
        if not data.get("api_key") and os.getenv("LLM_API_KEY"):
            data["api_key"] = os.getenv("LLM_API_KEY")
        if not data.get("hf_token") and os.getenv("HF_TOKEN"):
            data["hf_token"] = os.getenv("HF_TOKEN")
        if not data.get("colab_session") and os.getenv("COLAB_SESSION_NAME"):
            data["colab_session"] = os.getenv("COLAB_SESSION_NAME")

        cfg = AppConfig(**{k: v for k, v in data.items() if k in AppConfig.__dataclass_fields__})
        return cfg

    def save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(asdict(self.config), f, indent=2, ensure_ascii=False)

    def ensure_ssh_key(self) -> str:
        """Verifies or generates a dedicated ED25519 keypair with strict NTFS permissions."""
        raw_key = str(self.config.ssh_key_path or "").strip()
        key_path = Path(raw_key) if raw_key else Path()
        if not raw_key or not key_path.is_file():
            candidates = [
                DEFAULT_KEY_PATH,
                MEI_DIR / "秘钥" / "colab_tunnel_ed25519",
                APP_DIR / "秘钥" / "colab_tunnel_ed25519",
                USER_DATA_DIR / "colab_tunnel_ed25519",
            ]
            for cand in candidates:
                if cand.is_file():
                    self.config.ssh_key_path = str(cand)
                    key_path = cand
                    break

        if not key_path.is_file():
            key_path = USER_DATA_DIR / "colab_tunnel_ed25519"
            key_path.parent.mkdir(parents=True, exist_ok=True)
            self.config.ssh_key_path = str(key_path)
            if not key_path.is_file():
                print(f"[ConfigManager] 未找到 SSH 密钥，正在生成专用 ED25519 密钥对: {key_path}")
                extra_kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL}
                if sys.platform == "win32":
                    extra_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                    si = subprocess.STARTUPINFO()
                    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    si.wShowWindow = 0  # SW_HIDE
                    extra_kwargs["startupinfo"] = si

                # Generate ed25519 key without passphrase
                res = subprocess.run(
                    ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path), "-C", "colab-tunnel"],
                    capture_output=True,
                    text=True,
                    **extra_kwargs,
                )
                if res.returncode != 0:
                    raise RuntimeError(f"生成 SSH 密钥失败: {(res.stderr or res.stdout).strip()}")

                # Windows NTFS permissions fix
                if sys.platform == "win32":
                    username = os.environ.get("USERNAME", "")
                    if username:
                        subprocess.run(
                            ["icacls", str(key_path), "/inheritance:r", "/grant:r", f"{username}:(R)"],
                            capture_output=True,
                            **extra_kwargs,
                        )

        return str(key_path)


# Global singleton instance
config_mgr = ConfigManager()
