# -*- coding: utf-8 -*-
"""Hugging Face GGUF Model Explorer and Hardware/VRAM Compatibility Evaluator.
Evaluates model quantization files against Google Colab Tesla T4 (15GB VRAM).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
import requests
from huggingface_hub import HfApi


from config_manager import get_gpu_vram_limit


POPULAR_MODELS = [
    {
        "repo_id": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "description": "通义千问 2.5 7B 指令微调版 (通用能力极强，完美适配 T4)",
        "description_en": "Qwen 2.5 7B Instruct (Strong general-purpose, ideal for T4)",
        "likes": 2500,
        "downloads": 500000,
    },
    {
        "repo_id": "unsloth/DeepSeek-R1-Distill-Qwen-7B-GGUF",
        "description": "DeepSeek-R1 蒸馏 Qwen-7B (高推理与数学代码能力)",
        "description_en": "DeepSeek-R1 Distill Qwen-7B (Strong reasoning & coding)",
        "likes": 3200,
        "downloads": 420000,
    },
    {
        "repo_id": "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
        "description": "Meta Llama-3.1 8B 指令版 (全球主流开源模型)",
        "description_en": "Meta Llama-3.1 8B Instruct (Popular open-weights model)",
        "likes": 1800,
        "downloads": 380000,
    },
    {
        "repo_id": "google/gemma-2-9b-it-GGUF",
        "description": "Google Gemma 2 9B (高质量自然语言对话模型)",
        "description_en": "Google Gemma 2 9B IT (High-quality dialogue model)",
        "likes": 1400,
        "downloads": 260000,
    },
    {
        "repo_id": "bartowski/Qwen2.5-14B-Instruct-GGUF",
        "description": "通义千问 2.5 14B 指令微调版 (显存临界，建议 Q4_K_M)",
        "description_en": "Qwen 2.5 14B Instruct (Tight on T4, Q4_K_M / L4+ recommended)",
        "likes": 1900,
        "downloads": 220000,
    },
    {
        "repo_id": "microsoft/Phi-3.5-mini-instruct-gguf",
        "description": "微软 Phi-3.5 Mini 3.8B (轻量高响应，极低显存占用)",
        "description_en": "Microsoft Phi-3.5 Mini 3.8B (Lightweight, ultra-fast)",
        "likes": 1100,
        "downloads": 190000,
    },
]


@dataclass
class QuantFileInfo:
    filename: str
    size_bytes: int
    size_gb: float
    quant_type: str
    vram_required_gb: float
    status: str  # "safe" | "tight" | "overload"
    status_text: str
    badge_color: str  # hex color for UI
    download_url: str = ""


@dataclass
class ModelInfo:
    repo_id: str
    description: str = ""
    downloads: int = 0
    likes: int = 0
    tags: list[str] = field(default_factory=list)
    quants: list[QuantFileInfo] = field(default_factory=list)


def parse_quant_type(filename: str) -> str:
    """Extract quantization type like Q4_K_M, Q5_K_S, Q8_0, BF16 from filename."""
    match = re.search(r"[-_.](q[0-9]_[a-z0-9_]+|f16|bf16|q[0-9]_[0-9]|iq[0-9]_[a-z0-9_]+)", filename, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return "UNKNOWN"


def evaluate_vram(
    size_gb: float,
    ctx_size: int = 4096,
    gpu_type: str = "T4",
    lang: str = "zh",
) -> tuple[float, str, str, str]:
    """Calculate VRAM requirement and compatibility level against selected GPU tier.

    Formula:
      kv_cache = (ctx_size / 1024) * 0.28 (GB)
      vram_est = size_gb * 1.15 + kv_cache + 1.2 (for CUDA runtime buffers)
    """
    kv_cache = (ctx_size / 1024.0) * 0.28
    vram_est = round(size_gb * 1.15 + kv_cache + 1.2, 2)
    is_en = str(lang).lower().startswith("en")
    limit = get_gpu_vram_limit(gpu_type)

    if limit <= 0:
        msg = (
            f"CPU Mode (~{vram_est:.2f} GB RAM)"
            if is_en
            else f"CPU 模式 (约需 {vram_est:.2f} GB 内存)"
        )
        return (vram_est, "safe", msg, "#10b981")

    safe_cutoff = limit - 2.5
    if vram_est <= safe_cutoff:
        msg = (
            f"Est. VRAM {vram_est:.2f} GB / {limit:.2f} GB"
            if is_en
            else f"预计占用 {vram_est:.2f} GB / {limit:.2f} GB"
        )
        return (vram_est, "safe", msg, "#10b981")
    elif vram_est <= limit:
        msg = (
            f"Est. VRAM {vram_est:.2f} GB / {limit:.2f} GB (Tight)"
            if is_en
            else f"预计占用 {vram_est:.2f} GB / {limit:.2f} GB (显存紧张)"
        )
        return (vram_est, "tight", msg, "#f59e0b")
    else:
        msg = (
            f"Est. VRAM {vram_est:.2f} GB / {limit:.2f} GB (Overload)"
            if is_en
            else f"预计占用 {vram_est:.2f} GB / {limit:.2f} GB (显存超限)"
        )
        return (vram_est, "overload", msg, "#ef4444")


def evaluate_t4_vram(size_gb: float, ctx_size: int = 4096) -> tuple[float, str, str, str]:
    """Backward-compatible wrapper defaulting to Tesla T4 (15.00 GB)."""
    return evaluate_vram(size_gb, ctx_size=ctx_size, gpu_type="T4", lang="zh")


class HFExplorer:
    """Searches Hugging Face GGUF models and fetches file details."""

    BASE_URL = "https://huggingface.co/api"

    def __init__(self, token: str | None = None) -> None:
        self.token = token
        self.api = HfApi(token=token if token else None)

    def _sync_token(self) -> None:
        try:
            from config_manager import config_mgr
            t = config_mgr.config.hf_token
            if t and t != self.token:
                self.token = t
                self.api = HfApi(token=t)
        except Exception:
            pass

    def search_models(self, query: Any = "", limit: int = 15, lang: str = "zh") -> list[ModelInfo]:
        """Search models matching query with gguf filter."""
        self._sync_token()
        if not isinstance(query, str):
            query = ""
        query = query.strip()
        is_en = str(lang).lower().startswith("en")
        if not query:
            results = []
            for item in POPULAR_MODELS:
                desc = item["description_en"] if is_en else item["description"]
                results.append(
                    ModelInfo(
                        repo_id=item["repo_id"],
                        description=desc,
                        downloads=item["downloads"],
                        likes=item["likes"],
                        tags=["gguf", "recommended"],
                    )
                )
            return results

        url = f"{self.BASE_URL}/models"
        headers = {"User-Agent": "Colab-Launcher-Client/1.0"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        params: dict[str, Any] = {
            "search": query,
            "filter": "gguf",
            "sort": "downloads",
            "direction": "-1",
            "limit": limit,
            "full": "false",
        }

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            items = resp.json()

            results = []
            for item in items:
                repo_id = item.get("id") or item.get("modelId", "")
                if not repo_id:
                    continue
                results.append(
                    ModelInfo(
                        repo_id=repo_id,
                        description=item.get("description", "") or f"HuggingFace model {repo_id}",
                        downloads=item.get("downloads", 0),
                        likes=item.get("likes", 0),
                        tags=item.get("tags", []),
                    )
                )
            return results
        except Exception as e:
            print(f"[HFExplorer] 搜索模型出错: {e}")
            return []

    def get_model_quants(
        self,
        repo_id: str,
        ctx_size: int = 4096,
        gpu_type: str = "T4",
        lang: str = "zh",
    ) -> list[QuantFileInfo]:
        """Fetch all .gguf files in the repository and parse quantization tiers in a single call."""
        self._sync_token()
        try:
            model_info = self.api.model_info(repo_id, files_metadata=True)
            shard_pattern = re.compile(r"^(.*?)-(\d{5})-of-(\d{5})\.gguf$", re.IGNORECASE)
            single_files = []
            sharded_groups: dict[str, list[tuple[int, int, int, str]]] = {}

            for s in model_info.siblings or []:
                fname = s.rfilename or ""
                fname_lower = fname.lower()
                # 严格过滤非 GGUF 文件及多模态投影权重 (mmproj)
                if not fname_lower.endswith(".gguf") or "mmproj" in fname_lower:
                    continue

                size_bytes = s.size or 0
                m = shard_pattern.match(fname)
                if m:
                    prefix = m.group(1)
                    idx = int(m.group(2))
                    total = int(m.group(3))
                    sharded_groups.setdefault(prefix, []).append((idx, total, size_bytes, fname))
                else:
                    single_files.append((fname, size_bytes))

            quants: list[QuantFileInfo] = []

            for fname, size_bytes in single_files:
                size_gb = round(size_bytes / (1024**3), 2)
                quant_type = parse_quant_type(fname)
                vram_est, status, status_text, badge_color = evaluate_vram(
                    size_gb, ctx_size, gpu_type=gpu_type, lang=lang
                )
                quants.append(
                    QuantFileInfo(
                        filename=fname,
                        size_bytes=size_bytes,
                        size_gb=size_gb,
                        quant_type=quant_type,
                        vram_required_gb=vram_est,
                        status=status,
                        status_text=status_text,
                        badge_color=badge_color,
                        download_url=f"https://huggingface.co/{repo_id}/resolve/main/{fname}",
                    )
                )

            for prefix, shards in sharded_groups.items():
                shards.sort(key=lambda x: x[0])
                total_bytes = sum(x[2] for x in shards)
                primary_fname = shards[0][3]
                size_gb = round(total_bytes / (1024**3), 2)
                quant_type = parse_quant_type(prefix)
                vram_est, status, status_text, badge_color = evaluate_vram(
                    size_gb, ctx_size, gpu_type=gpu_type, lang=lang
                )
                quants.append(
                    QuantFileInfo(
                        filename=primary_fname,
                        size_bytes=total_bytes,
                        size_gb=size_gb,
                        quant_type=quant_type,
                        vram_required_gb=vram_est,
                        status=status,
                        status_text=status_text,
                        badge_color=badge_color,
                        download_url=f"https://huggingface.co/{repo_id}/resolve/main/{primary_fname}",
                    )
                )

            # Prioritize standard quants: safe/tight status first, then Q4_K_M, Q4_0, Q5, Q3, etc.
            def sort_key(q: QuantFileInfo):
                qt = q.quant_type.upper()
                if "Q4_K_M" in qt:
                    tier = 0
                elif "Q4_0" in qt or "Q4_K_S" in qt:
                    tier = 1
                elif "Q5_K_M" in qt or "Q5_0" in qt:
                    tier = 2
                elif "Q3_K" in qt:
                    tier = 3
                elif "Q8_0" in qt:
                    tier = 4
                else:
                    tier = 5
                status_prio = 0 if q.status == "safe" else (1 if q.status == "tight" else 2)
                return (status_prio, tier, q.size_gb)

            quants.sort(key=sort_key)
            return quants

        except Exception as e:
            print(f"[HFExplorer] 获取模型文件列表失败 ({repo_id}): {e}")
            return []


# Global singleton instance
hf_explorer = HFExplorer()
