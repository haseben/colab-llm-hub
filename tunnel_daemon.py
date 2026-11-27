# -*- coding: utf-8 -*-
"""Direct SSH Tunnel and Anti-Idle Heartbeat Daemon.
Manages the native OpenSSH port forwarding process via colab-cli WebSocket bridge.
Maintains persistent connection and sends dual-layer heartbeats to prevent Colab idle timeouts,
with built-in duration and idle quota fuses.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from typing import Callable
import requests

from config_manager import append_app_log, config_mgr


class TunnelDaemon:
    """Manages the background SSH tunnel and anti-idle health probes."""

    def __init__(
        self,
        on_status_change: Callable[[str, str], None] | None = None,
        on_log: Callable[[str], None] | None = None,
        on_alert: Callable[[str, str], None] | None = None,
    ) -> None:
        self.on_status_change = on_status_change  # (status: "disconnected"|"connecting"|"connected"|"error", msg)
        self.on_log = on_log  # (log_line: str)
        self.on_alert = on_alert  # (alert_type: "idle"|"duration", msg: str)
        self.process: subprocess.Popen | None = None
        self._running = False
        self._monitor_thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self.start_time: float = 0
        self.last_activity_time: float = 0
        self.last_heartbeat_time: float = 0
        self.last_heartbeat_status: str = "none"
        self._last_outer_ping_time: float = 0
        self._warned_idle = False
        self._warned_duration = False

    def log(self, msg: str) -> None:
        t = time.strftime("%H:%M:%S")
        formatted = f"[{t}] [Tunnel] {msg}"
        append_app_log(formatted)
        print(formatted)
        if self.on_log:
            try:
                self.on_log(formatted)
            except Exception:
                pass

    def emit_status(self, status: str, msg: str) -> None:
        if self.on_status_change:
            try:
                self.on_status_change(status, msg)
            except Exception:
                pass

    def record_activity(self) -> None:
        """Call whenever an inference request or user action occurs."""
        self.last_activity_time = time.time()
        self._warned_idle = False

    def is_port_open(self, host: str = "127.0.0.1", port: int = 18080) -> bool:
        """Check if local TCP port is accepting connections."""
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return True
        except OSError:
            return False

    def check_health(self) -> dict | None:
        """Query the remote llama-server /health endpoint via local forwarded port."""
        cfg = config_mgr.config
        headers = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
        try:
            resp = requests.get(cfg.health_url, headers=headers, timeout=5)
            if resp.status_code == 200:
                self.last_heartbeat_time = time.time()
                self.last_heartbeat_status = "ok"
                return resp.json()
            else:
                self.last_heartbeat_status = f"HTTP {resp.status_code}"
                return None
        except Exception as e:
            self.last_heartbeat_status = f"Error: {e}"
            return None

    def start(self) -> bool:
        """Launch the OpenSSH tunnel process and background heartbeat worker."""
        if self._running:
            self.log("隧道已在运行中。")
            return True

        cfg = config_mgr.config
        key_path = config_mgr.ensure_ssh_key()
        session_name = cfg.colab_session
        local_port = cfg.api_port

        null_device = "NUL" if sys.platform == "win32" else "/dev/null"
        from colab_orchestrator import ColabOrchestrator

        proxy_cmd = ColabOrchestrator.get_proxy_command(session_name, str(key_path))

        ssh_cmd = [
            "ssh",
            "-N",
            "-L",
            f"127.0.0.1:{local_port}:127.0.0.1:8000",
            "-o",
            f"ProxyCommand={proxy_cmd}",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            f"UserKnownHostsFile={null_device}",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "ExitOnForwardFailure=yes",
            "-i",
            str(key_path),
            "root@colab-runtime",
        ]

        self.log(f"正在拉起直连隧道: 本地 127.0.0.1:{local_port} -> Colab 8000...")
        self.emit_status("connecting", "正在建立加密隧道...")

        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        extra_kwargs = {}
        if sys.platform == "win32":
            extra_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE
            extra_kwargs["startupinfo"] = si

        try:
            self.process = subprocess.Popen(
                ssh_cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                **extra_kwargs,
            )
            self._running = True
            self.start_time = time.time()
            self.last_activity_time = time.time()
            self._warned_idle = False
            self._warned_duration = False

            # Launch monitoring thread
            self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()

            # Launch heartbeat keep-alive thread
            self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
            self._heartbeat_thread.start()

            # Wait up to 20s for local forwarded port to start listening
            for _ in range(40):
                if not self._running or not self.process:
                    return False
                if self.process.poll() is not None:
                    self.log("SSH 隧道进程在握手阶段提前退出。")
                    self.stop()
                    return False
                if self.is_port_open(port=local_port):
                    self.log(f"隧道建立成功！本地 API 端口 127.0.0.1:{local_port} 处于监听就绪状态。")
                    self.emit_status("connected", f"隧道已连通 (端口 {local_port})")
                    return True
                time.sleep(0.5)

            self.log(f"隧道握手超时：本地端口 127.0.0.1:{local_port} 未能在 20s 内就绪。")
            self.stop()
            return False

        except Exception as e:
            self.log(f"拉起隧道失败: {e}")
            self.emit_status("error", str(e))
            self.stop()
            return False

    def _monitor_loop(self) -> None:
        """Monitors the SSH process and detects premature exits."""
        while self._running:
            proc = self.process
            if not proc:
                break
            ret = proc.poll()
            if ret is not None:
                err = ""
                try:
                    if proc.stderr and not proc.stderr.closed:
                        err = proc.stderr.read()
                except Exception:
                    pass
                self.log(f"SSH 隧道进程退出，退出码: {ret}。错误输出: {err.strip()}")
                self._running = False
                self.emit_status("disconnected", f"隧道已断开 (code {ret})")
                break
            time.sleep(2)

    def _heartbeat_loop(self) -> None:
        """Dual-layer anti-idle heartbeat to keep Colab VM active and monitor quota limits."""
        interval = max(30, config_mgr.config.keep_alive_interval)
        self.log(f"防休眠心跳守护启动，探针周期: {interval} 秒。")

        while self._running:
            time.sleep(interval)
            if not self._running:
                break

            now = time.time()
            cfg = config_mgr.config

            # 1. Level 1: HTTP /health check via forwarded port
            if self.is_port_open(port=cfg.api_port):
                health = self.check_health()
                if health:
                    self.log(f"💓 应用层心跳正常: llama-server 状态良好 (status: {health.get('status')})")
                else:
                    self.log(f"⚠️ 应用层心跳探针警告: 网关未正常响应: {self.last_heartbeat_status}")
            else:
                self.log("⚠️ 心跳检测: 本地端口未连通。")

            # 2. Level 2: Outer Colab Jupyter Kernel activity pulse (every ~5 minutes = 300s)
            if now - self._last_outer_ping_time >= 300:
                self._last_outer_ping_time = now
                try:
                    from colab_orchestrator import colab_orchestrator
                    if colab_orchestrator.ping_kernel_activity(cfg.colab_session):
                        self.log("⚡ 远端内核活跃探针已发送，已重置 Google Colab 控制台闲置计时器。")
                except Exception as e:
                    self.log(f"⚠️ 发送远端内核探针异常: {e}")

            # 3. Quota Safety Fuse: Idle timeout alert (30 minutes no inference)
            idle_seconds = now - self.last_activity_time
            if idle_seconds >= 1800 and not self._warned_idle:
                self._warned_idle = True
                msg = "已连续 30 分钟无任何模型推理请求。为节省 Colab GPU 免费额度，建议及时释放算力。"
                self.log(f"🔔 [配额安全熔断提示] {msg}")
                if self.on_alert:
                    try:
                        self.on_alert("idle", msg)
                    except Exception:
                        pass

            # 4. Quota Safety Fuse: Continuous duration alert (2 hours)
            duration_seconds = now - self.start_time
            if duration_seconds >= 7200 and not self._warned_duration:
                self._warned_duration = True
                msg = "当前 Colab 会话已连续运行超过 2 小时，请留意单日算力额度消耗。"
                self.log(f"🔔 [运行时长提示] {msg}")
                if self.on_alert:
                    try:
                        self.on_alert("duration", msg)
                    except Exception:
                        pass

    def stop(self) -> None:
        """Gracefully terminate tunnel process and background workers."""
        self._running = False
        proc = self.process
        self.process = None
        if proc:
            self.log("正在关闭 SSH 隧道进程...")
            try:
                proc.terminate()
                proc.wait(timeout=1)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            for stream in (proc.stdout, proc.stderr):
                if stream:
                    try:
                        stream.close()
                    except Exception:
                        pass

        self.emit_status("disconnected", "隧道已关闭")
        self.log("隧道已完全终止。")


tunnel_daemon = TunnelDaemon()
