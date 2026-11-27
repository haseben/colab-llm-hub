# -*- coding: utf-8 -*-
"""Cloud Orchestrator for Google Colab (llama-server Native Engine).
Manages Colab VM session lifecycle, dynamically renders deployment scripts with zero hardcoded credentials,
downloads official precompiled Linux CUDA llama-server, and monitors execution output.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from config_manager import APP_DIR, append_app_log


REMOTE_DEPLOY_TEMPLATE = r'''# -*- coding: utf-8 -*-
"""Dynamic Colab VM Model Server Setup Script (llama-server CUDA Mode).
Generated automatically by Colab Launcher Client.
"""

import os
import sys
import time
import shutil
import pathlib
import subprocess
import json
import urllib.request
import re

REPO_ID = __REPO_ID__
FILENAME = __FILENAME__
MODEL_ALIAS = __MODEL_ALIAS__
CTX_SIZE = __CTX_SIZE__
API_KEY = __API_KEY__
HF_TOKEN = __HF_TOKEN__
ENABLE_GDRIVE = __ENABLE_GDRIVE__
LLAMA_CPP_TAG = __LLAMA_CPP_TAG__

print("=" * 60)
print(f">>> 开始在 Colab VM 上部署 llama-server 官方 CUDA 推理引擎")
print(f">>> 目标模型: {MODEL_ALIAS} (Context Window: {CTX_SIZE})")
print(f">>> 来源 Hugging Face: {REPO_ID} -> {FILENAME}")
print("=" * 60, flush=True)

# 1. GPU 硬件检查
print(">>> [1/5] 检查 GPU 硬件环境...", flush=True)
gpu_res = subprocess.run(
    ["bash", "-lc", "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader"],
    capture_output=True,
    text=True,
)
if gpu_res.returncode == 0 and gpu_res.stdout.strip():
    has_gpu = True
    print(f"    GPU 检测成功: {gpu_res.stdout.strip()}", flush=True)
else:
    has_gpu = False
    print("    [警告] 未检测到 GPU，将在 CPU 模式下运行。", flush=True)

# 2. 清理旧服务
print(">>> [2/5] 清理旧后台推理服务 (llama-server)...", flush=True)
subprocess.run(["killall", "-9", "llama-server"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
subprocess.run(["fuser", "-k", "8000/tcp"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)

# 3. 准备 llama-server CUDA 运行时
print(">>> [3/5] 准备 llama-server 官方 CUDA 运行时...", flush=True)
bin_dir = pathlib.Path("/content/llama_bin")
bin_dir.mkdir(parents=True, exist_ok=True)
llama_server_bin = bin_dir / "llama-server"
cuda_backend_so = bin_dir / "libggml-cuda.so"
cublas_so = bin_dir / "libcublas.so.12"

gdrive_mounted = pathlib.Path("/content/drive/MyDrive").is_dir()
drive_tools_dir = pathlib.Path("/content/drive/MyDrive/colab_tools")
drive_bin = drive_tools_dir / "llama-server"

if ENABLE_GDRIVE and gdrive_mounted and drive_bin.exists():
    print(f"    发现 Google Drive 缓存的 llama-server: {drive_bin}，秒级复用！", flush=True)
    shutil.copy(drive_bin, llama_server_bin)
    for so_file in drive_tools_dir.glob("*.so*"):
        shutil.copy(so_file, bin_dir / so_file.name)
    subprocess.run(["chmod", "+x", str(llama_server_bin)], check=False)

if not (llama_server_bin.exists() and cuda_backend_so.exists() and cublas_so.exists()):
    tag = LLAMA_CPP_TAG or "b12556"
    print(f"    正在获取 llama.cpp 官方预编译 Linux CUDA 软件包 ({tag} CUDA 12.8)...", flush=True)
    base_url = f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}"
    packages = [
        f"llama-{tag}-bin-ubuntu-cuda-12.8-x64.tar.gz",
        f"cudart-llama-{tag}-bin-ubuntu-cuda-12.8-x64.tar.gz",
    ]
    for pkg in packages:
        tar_path = bin_dir / pkg
        if not tar_path.exists():
            print(f"    正在高速下载 {pkg} ...", flush=True)
            subprocess.run(["curl", "-L", "-C", "-", "-o", str(tar_path), f"{base_url}/{pkg}"], check=True)
        print(f"    解压 {pkg} ...", flush=True)
        subprocess.run(["tar", "-xzf", str(tar_path), "-C", str(bin_dir)], check=True)

    for p in bin_dir.rglob("llama-server"):
        if p.is_file() and p != llama_server_bin:
            shutil.copy(p, llama_server_bin)
            break

    for so_file in bin_dir.rglob("*.so*"):
        target_so = bin_dir / so_file.name
        if so_file != target_so:
            shutil.copy(so_file, target_so)

    subprocess.run(["chmod", "+x", str(llama_server_bin)], check=False)

    if ENABLE_GDRIVE and gdrive_mounted:
        try:
            drive_tools_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(llama_server_bin, drive_bin)
            for so_file in bin_dir.glob("*.so*"):
                shutil.copy(so_file, drive_tools_dir / so_file.name)
            print("    已成功缓存 llama-server 与 CUDA 依赖至 Google Drive，下次启动可秒级复用！", flush=True)
        except Exception as e:
            print(f"    缓存至 Google Drive 提示: {e}", flush=True)

print(f"    llama-server 运行时已就绪: {llama_server_bin}", flush=True)

# 4. 下载或挂载模型文件
print(">>> [4/5] 准备模型 GGUF 文件...", flush=True)
model_dir = pathlib.Path("/content/models")
model_dir.mkdir(parents=True, exist_ok=True)
target_model_path = model_dir / FILENAME

# 支持分片模型 (例如 *-00001-of-00002.gguf)
shard_match = re.search(r"^(.*?)-(\d{5})-of-(\d{5})\.gguf$", FILENAME, re.IGNORECASE)
files_to_download = []
if shard_match:
    prefix = shard_match.group(1)
    total_parts = int(shard_match.group(3))
    for i in range(1, total_parts + 1):
        files_to_download.append(f"{prefix}-{i:05d}-of-{total_parts:05d}.gguf")
else:
    files_to_download.append(FILENAME)

print(f"    检查分片列表 ({len(files_to_download)} 个文件): {files_to_download}", flush=True)

gdrive_mounted = pathlib.Path("/content/drive/MyDrive").is_dir()
drive_model_dir = pathlib.Path("/content/drive/MyDrive/colab_models")

for cur_fname in files_to_download:
    cur_target = model_dir / cur_fname
    drive_cached = drive_model_dir / cur_fname

    if ENABLE_GDRIVE and gdrive_mounted and drive_cached.exists():
        print(f"    发现 Google Drive 缓存分片: {cur_fname}，秒级复用！", flush=True)
        if not cur_target.exists():
            shutil.copy(drive_cached, cur_target)
    elif not cur_target.exists():
        print(f"    正在从 Hugging Face 下载分片: {cur_fname} ...", flush=True)
        download_url = f"https://huggingface.co/{REPO_ID}/resolve/main/{cur_fname}"

        try:
            from huggingface_hub import hf_hub_download
            token_arg = HF_TOKEN if HF_TOKEN else None
            downloaded = hf_hub_download(
                repo_id=REPO_ID,
                filename=cur_fname,
                local_dir=str(model_dir),
                token=token_arg,
            )
        except Exception as e:
            print(f"    huggingface_hub 下载遇到重试: {e}，调用 curl 高速下载...", flush=True)
            curl_cmd = ["curl", "-L", "-C", "-", "-o", str(cur_target)]
            if HF_TOKEN:
                curl_cmd.extend(["-H", f"Authorization: Bearer {HF_TOKEN}"])
            curl_cmd.append(download_url)
            subprocess.run(curl_cmd, check=True)

        if ENABLE_GDRIVE and gdrive_mounted:
            try:
                drive_model_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy(cur_target, drive_cached)
            except Exception as e:
                print(f"    备份至 Google Drive 提示: {e}", flush=True)

total_bytes = sum((model_dir / f).stat().st_size for f in files_to_download if (model_dir / f).exists())
model_size_gb = round(total_bytes / (1024**3), 2)
print(f"    模型文件全部分片就绪: {target_model_path} (合计 {model_size_gb} GB)", flush=True)

# 5. 启动 llama-server 原生高性能服务
print(f">>> [5/5] 启动 llama-server (端口 8000, {'显存全量卸载' if has_gpu else 'CPU 推理模式'})...", flush=True)
cmd = [
    str(llama_server_bin),
    "--model", str(target_model_path.resolve()),
    "--alias", MODEL_ALIAS,
    "--ctx-size", str(CTX_SIZE),
    "-np", "1",
    "-t", "4",
    "--host", "0.0.0.0",
    "--port", "8000",
    "-ngl", "999" if has_gpu else "0",
    "--metrics",
]
if API_KEY:
    cmd.extend(["--api-key", API_KEY])

env = os.environ.copy()
env["LD_LIBRARY_PATH"] = f"{bin_dir}:/usr/lib64-nvidia:/usr/local/cuda/lib64:" + env.get("LD_LIBRARY_PATH", "")
cuda_so = bin_dir / "libggml-cuda.so"
if cuda_so.exists():
    env["GGML_BACKEND_PATH"] = str(cuda_so)

with open("/tmp/llama-server.log", "w") as log_file:
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setpgrp,
    )

# 轮询 /health 接口确认服务就绪
print("    等待模型装载至 GPU 显存并就绪...", flush=True)
server_ready = False
crashed_early = False
load_start = time.time()
for attempt in range(90):
    if proc.poll() is not None:
        crashed_early = True
        print(f"    [错误] llama-server 进程提前退出 (returncode={proc.returncode})", flush=True)
        break
    time.sleep(1.5)
    try:
        req = urllib.request.Request("http://127.0.0.1:8000/health")
        if API_KEY:
            req.add_header("Authorization", f"Bearer {API_KEY}")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                if body.get("status") == "ok":
                    server_ready = True
                    break
    except Exception:
        pass
    elapsed_load = int(time.time() - load_start)
    print(f"    正在加载权重到显存... ({elapsed_load}s)", flush=True)

if server_ready:
    print(f"\n" + "=" * 60)
    print(f"=== llama-server 推理服务已在云端 8000 端口启动 ===")
    print("=" * 60, flush=True)

    # 6. GPU 算子预热与 JIT 编译（需生成多个 token 以同时预热 Prefill 与 Decode 阶段算子）
    print(">>> [6/6] 正在进行 GPU 显存与 CUDA JIT 内核预热...", flush=True)
    print("    提示: 正在为 Tesla T4 编译 Prefill + Decode 双阶段 CUDA PTX 缓存，预热完成后首轮对话即享高速响应...", flush=True)
    try:
        warmup_payload = json.dumps({
            "model": MODEL_ALIAS,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 10,
            "stream": False,
        }).encode("utf-8")
        warmup_headers = {"Content-Type": "application/json"}
        if API_KEY:
            warmup_headers["Authorization"] = f"Bearer {API_KEY}"
        warmup_req = urllib.request.Request(
            "http://127.0.0.1:8000/v1/chat/completions",
            data=warmup_payload,
            headers=warmup_headers,
        )
        with urllib.request.urlopen(warmup_req, timeout=180) as w_resp:
            if w_resp.status == 200:
                print("    ✔ GPU 算子预热成功！ComputeCache 缓存已生成，后续对话毫秒级响应！", flush=True)
    except Exception as we:
        print(f"    预热已略过: {we}", flush=True)

    print("============================================================")
    print("=== 恭喜！llama-server 已在 8000 端口就绪！ ===")
    print("=== 原生兼容 OpenAI /v1/chat/completions (零转发损耗) ===")
    print("============================================================", flush=True)
else:
    print("    [警告] llama-server 启动检查超时，/tmp/llama-server.log 日志如下：", flush=True)
    if os.path.exists("/tmp/llama-server.log"):
        with open("/tmp/llama-server.log", encoding="utf-8", errors="replace") as f:
            print(f.read()[-2000:], flush=True)
    sys.exit(1)
'''


class ColabOrchestrator:
    """Orchestrates Google Colab sessions and model deployments via embedded or external colab CLI."""

    def __init__(self) -> None:
        self._colab_base = self.get_colab_cmd_prefix()
        self.last_orphan_endpoints: list[str] = []
        self.last_error_code: str = ""

    @staticmethod
    def get_colab_cmd_prefix() -> list[str]:
        """Resolve command prefix to run colab CLI without external shell shims."""
        if getattr(sys, "frozen", False):
            return [sys.executable, "--colab-cli"]
        if importlib.util.find_spec("colab_cli") is not None:
            app_entry = APP_DIR / "app.py"
            if app_entry.is_file():
                return [sys.executable, "-X", "utf8", str(app_entry), "--colab-cli"]
            return [
                sys.executable,
                "-X",
                "utf8",
                "-c",
                "import sys; sys.stdout.reconfigure(encoding='utf-8', errors='replace'); sys.stderr.reconfigure(encoding='utf-8', errors='replace'); from colab_cli.cli import main; main()",
            ]
        uv_python = Path.home() / "AppData" / "Roaming" / "uv" / "tools" / "google-colab-cli" / "Scripts" / "python.exe"
        if uv_python.exists():
            return [
                str(uv_python),
                "-X",
                "utf8",
                "-c",
                "import sys; sys.stdout.reconfigure(encoding='utf-8', errors='replace'); sys.stderr.reconfigure(encoding='utf-8', errors='replace'); from colab_cli.cli import main; main()",
            ]
        return [shutil.which("colab") or "colab"]

    @classmethod
    def get_proxy_command(cls, session_name: str, key_path: str) -> str:
        """Build OpenSSH ProxyCommand reusing the resolved colab CLI command."""
        prefix = cls.get_colab_cmd_prefix()
        if len(prefix) == 2 and prefix[1] == "--colab-cli":
            cmd_head = f'"{prefix[0]}" --colab-cli'
        elif len(prefix) >= 4 and prefix[3] == "--colab-cli":
            cmd_head = f'"{prefix[0]}" -X utf8 "{prefix[2]}" --colab-cli'
        elif len(prefix) >= 4 and prefix[2] == "-c":
            cmd_head = f'"{prefix[0]}" -X utf8 -c "from colab_cli.cli import main; main()"'
        else:
            cmd_head = f'"{prefix[0]}"'
        return f'{cmd_head} ssh --proxy-mode -s "{session_name}" -i "{key_path}"'

    @staticmethod
    def check_auth_non_interactive() -> bool:
        """Check if Google Colab OAuth2 or ADC credentials already exist without prompting."""
        legacy_token = Path.home() / ".config" / "colab-cli" / "token.json"
        if legacy_token.is_file():
            return True
        if importlib.util.find_spec("colab_cli") is not None:
            try:
                from colab_cli.auth import _get_token_from_keyring

                if _get_token_from_keyring():
                    return True
            except Exception:
                pass
        else:
            try:
                import keyring

                if keyring.get_password("google-colab-cli", "oauth_token"):
                    return True
            except Exception:
                pass
        adc_path = Path(os.environ.get("APPDATA", "")) / "gcloud" / "application_default_credentials.json"
        if adc_path.is_file():
            return True
        home_adc = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
        return home_adc.is_file()

    def check_environment(self) -> dict[str, Any]:
        """Verify local OpenSSH tools, colab CLI availability, and OAuth token."""
        has_ssh = bool(shutil.which("ssh"))
        has_ssh_keygen = bool(shutil.which("ssh-keygen"))
        has_cli = bool(
            getattr(sys, "frozen", False)
            or importlib.util.find_spec("colab_cli") is not None
            or (Path.home() / "AppData" / "Roaming" / "uv" / "tools" / "google-colab-cli" / "Scripts" / "python.exe").exists()
            or shutil.which("colab")
        )
        has_auth = self.check_auth_non_interactive()
        return {
            "has_ssh": has_ssh,
            "has_ssh_keygen": has_ssh_keygen,
            "has_cli": has_cli,
            "has_auth": has_auth,
        }

    @staticmethod
    def start_oauth_flow() -> tuple[Any, str]:
        """Prepare Google OAuth2 InstalledAppFlow and return (flow, auth_url) for GUI login."""
        from importlib import resources
        from google_auth_oauthlib.flow import InstalledAppFlow
        from colab_cli.auth import PUBLIC_SCOPES, REMOTE_REDIRECT_URI

        oauth_cfg_path = Path.home() / ".colab-cli-oauth-config.json"
        if oauth_cfg_path.is_file():
            client_config = json.loads(oauth_cfg_path.read_text(encoding="utf-8"))
        else:
            cfg_res = resources.files("colab_cli").joinpath("oauth_config.json")
            client_config = json.loads(cfg_res.read_text(encoding="utf-8"))

        flow = InstalledAppFlow.from_client_config(client_config, PUBLIC_SCOPES)
        flow.redirect_uri = REMOTE_REDIRECT_URI
        auth_url, _ = flow.authorization_url(prompt="consent", token_usage="remote")
        return flow, auth_url

    @staticmethod
    def finish_oauth_flow(flow: Any, auth_code: str) -> None:
        """Exchange pasted Google auth code for credentials and store in OS keyring."""
        from colab_cli.auth import _save_token_to_keyring

        flow.fetch_token(code=auth_code.strip())
        _save_token_to_keyring(flow.credentials.to_json())

    @staticmethod
    def _get_env() -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env.setdefault("COLAB_CLI_REQUEST_TIMEOUT", "60")
        return env

    @staticmethod
    def _get_subprocess_kwargs() -> dict[str, Any]:
        kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE
            kwargs["startupinfo"] = si
        return kwargs

    @staticmethod
    def parse_sessions_output(stdout_str: str) -> tuple[list[str], list[str]]:
        """Parse `colab sessions` output into (named_sessions, orphan_endpoints)."""
        named: list[str] = []
        orphans: list[str] = []
        for raw_line in stdout_str.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("[colab]") or line.startswith("Active") or line.startswith("-"):
                continue
            m = re.match(r"^\[([^\]]+)\]\s+(\S+)", line)
            if m:
                tag, endpoint = m.group(1).strip("* "), m.group(2).strip()
                if tag == "?":
                    orphans.append(endpoint)
                elif tag:
                    named.append(tag)
            else:
                parts = line.split()
                if parts:
                    raw_name = parts[0].strip("[]* ")
                    if raw_name and raw_name != "?":
                        named.append(raw_name)
        return named, orphans

    def list_session_details(self) -> tuple[list[str], list[str]]:
        """List active named sessions and orphan [?] assignments."""
        try:
            res = subprocess.run(
                self._colab_base + ["sessions"],
                capture_output=True,
                check=False,
                env=self._get_env(),
                **self._get_subprocess_kwargs(),
            )
            stdout_str = res.stdout.decode("utf-8", errors="replace") if isinstance(res.stdout, bytes) else str(res.stdout or "")
            return self.parse_sessions_output(stdout_str)
        except Exception:
            return [], []

    def list_sessions(self) -> list[str]:
        """List active session names."""
        named, _ = self.list_session_details()
        return named

    @staticmethod
    def unassign_orphan(endpoint: str) -> bool:
        """Release an orphaned Colab server assignment [?] by endpoint ID."""
        try:
            from colab_cli.auth import AuthProvider
            from colab_cli.common import state

            state.auth_provider = AuthProvider.OAUTH2
            state.client.unassign(endpoint)
            return True
        except Exception as e:
            append_app_log(f"[Orchestrator] unassign_orphan({endpoint}) failed: {e}")
            return False

    def ensure_session(
        self,
        session_name: str,
        gpu_type: str = "T4",
        high_mem: bool = False,
        log_callback: Callable[[str], None] | None = None,
    ) -> bool:
        """Ensure the specified Colab session is created and running with GPU."""
        self.last_orphan_endpoints = []
        self.last_error_code = ""

        def log(msg: str):
            append_app_log(f"[Orchestrator] {msg}")
            if log_callback:
                log_callback(msg)
            print(f"[Orchestrator] {msg}")

        sessions, orphans = self.list_session_details()
        if session_name in sessions:
            log(f"Colab 会话 '{session_name}' 已存在且处于活跃状态。")
            return True
        if orphans:
            self.last_orphan_endpoints = orphans
            log(f"提示: 检测到云端存在未命名的孤立算力实例: {', '.join(orphans)}")

        log(f"正在申请并创建 Colab 会话 '{session_name}' (GPU: {gpu_type}{', High-RAM' if high_mem else ''})...")
        cmd = self._colab_base + ["--logtostderr", "new", "-s", session_name]
        gpu_upper = str(gpu_type or "T4").upper()
        if gpu_upper != "CPU":
            cmd.extend(["--gpu", gpu_upper])
        if high_mem and gpu_upper != "L4":
            cmd.append("--high-mem")

        process = subprocess.Popen(
            cmd,
            env=self._get_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            **self._get_subprocess_kwargs(),
        )

        output_lines: list[str] = []

        def _drain_output():
            if not process.stdout:
                return
            for raw_line in iter(process.stdout.readline, b""):
                try:
                    line_str = raw_line.decode("utf-8").strip()
                except UnicodeDecodeError:
                    line_str = raw_line.decode("gbk", errors="replace").strip()
                if line_str:
                    output_lines.append(line_str)
                    log(line_str)

        reader = threading.Thread(target=_drain_output, daemon=True)
        reader.start()

        start_ts = time.time()
        next_tick = 5
        timed_out = False
        max_wait_sec = 300

        while process.poll() is None:
            elapsed = int(time.time() - start_ts)
            if elapsed >= max_wait_sec:
                timed_out = True
                try:
                    process.kill()
                except Exception:
                    pass
                break
            if elapsed >= next_tick:
                log(f"⏳ 正在等待 Google Colab 分配 {gpu_type} 算力并建立连接... (已等待 {elapsed}s)")
                next_tick += 5
            time.sleep(0.5)

        reader.join(timeout=2)
        if process.returncode == 0 and not timed_out:
            log(f"会话 '{session_name}' 创建成功！")
            return True
        if timed_out:
            self.last_error_code = "timeout"
            log(f"申请会话超时 ({max_wait_sec}s)，请检查代理网络或 Google Colab GPU 排队/可用额度。")
            return False

        tail_msg = "\n".join(output_lines[-5:]).strip()
        if "Allocation refused" in tail_msg or "412" in tail_msg or "TooManyAssignments" in tail_msg:
            self.last_error_code = "412"
            _, orphans_now = self.list_session_details()
            if orphans_now:
                self.last_orphan_endpoints = orphans_now
        elif "Backend rejected accelerator" in tail_msg or "entitlement" in tail_msg.lower():
            self.last_error_code = "400_entitlement"
        log(f"创建会话失败 (exit={process.returncode}): {tail_msg or '未知错误'}")
        return False

    def stop_session(self, session_name: str) -> bool:
        """Stop and release Colab session."""
        try:
            res = subprocess.run(
                self._colab_base + ["stop", "-s", session_name],
                capture_output=True,
                check=False,
                env=self._get_env(),
                **self._get_subprocess_kwargs(),
            )
            return res.returncode == 0
        except Exception:
            return False

    def ping_kernel_activity(self, session_name: str) -> bool:
        """Sends a lightweight kernel activity pulse to reset Google Colab outer Idle timer."""
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
                f.write("print('pong', flush=True)\n")
                tmp_path = f.name

            res = subprocess.run(
                self._colab_base + ["exec", "-s", session_name, "--timeout", "10", "-f", tmp_path],
                capture_output=True,
                check=False,
                env=self._get_env(),
                **self._get_subprocess_kwargs(),
            )
            return res.returncode == 0
        except Exception:
            return False
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    def deploy_model(
        self,
        session_name: str,
        repo_id: str,
        filename: str,
        model_alias: str,
        api_key: str,
        ctx_size: int = 4096,
        hf_token: str = "",
        enable_gdrive: bool = True,
        llama_cpp_tag: str = "b12556",
        log_callback: Callable[[str], None] | None = None,
    ) -> bool:
        """Render the remote deployment script and execute it inside the Colab VM."""
        def log(msg: str):
            append_app_log(f"[Orchestrator] {msg}")
            if log_callback:
                log_callback(msg)
            print(f"[Orchestrator] {msg}")

        rendered = (
            REMOTE_DEPLOY_TEMPLATE.replace("__REPO_ID__", json.dumps(repo_id))
            .replace("__FILENAME__", json.dumps(filename))
            .replace("__MODEL_ALIAS__", json.dumps(model_alias))
            .replace("__CTX_SIZE__", str(int(ctx_size)))
            .replace("__API_KEY__", json.dumps(api_key))
            .replace("__HF_TOKEN__", json.dumps(hf_token))
            .replace("__ENABLE_GDRIVE__", "True" if enable_gdrive else "False")
            .replace("__LLAMA_CPP_TAG__", json.dumps(llama_cpp_tag or "b12556"))
        )

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tmp:
            tmp.write(rendered)
            tmp_path = tmp.name

        try:
            log(f"开始向 Colab 会话 '{session_name}' 推送 llama-server 部署脚本 (Context: {ctx_size})...")
            cmd = self._colab_base + ["exec", "-s", session_name, "--timeout", "0", "-f", tmp_path]

            process = subprocess.Popen(
                cmd,
                env=self._get_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                **self._get_subprocess_kwargs(),
            )

            success = False
            if process.stdout:
                for raw_line in iter(process.stdout.readline, b""):
                    # Dual-layer decoding: UTF-8 first, fallback to GBK
                    try:
                        line_str = raw_line.decode("utf-8").strip()
                    except UnicodeDecodeError:
                        line_str = raw_line.decode("gbk", errors="replace").strip()

                    if line_str:
                        log(line_str)
                        if "llama-server 已在 8000 端口就绪" in line_str:
                            success = True
                try:
                    process.stdout.close()
                except Exception:
                    pass

            process.wait()
            if success:
                log("云端 llama-server 部署任务执行完毕！")
                return True
            else:
                log(f"云端部署未能确认服务就绪 (success={success}, returncode={process.returncode})")
                return False

        except Exception as e:
            log(f"部署执行异常: {e}")
            return False
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


colab_orchestrator = ColabOrchestrator()
