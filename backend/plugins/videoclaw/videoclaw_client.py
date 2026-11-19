"""VideoClaw sidecar HTTP 客户端 —— 只发请求，不碰 ADS 业务。

契约来源（VC 仓库，接入时实读）：
  GET  /api/health                         -> {"status":"ok"}
  GET  /api/config                         -> {"config": {models, generation, ...}, "path": ...}
  POST /api/project/start                  -> {"session_id", "status", "params"}
  POST /api/project/{sid}/continue         -> 同步推进工作流
  GET  /api/project/{sid}/status           -> 状态快照
  GET  /api/project/{sid}/artifact/{stage} -> {"stage", "artifact"}
  GET  /code/result/...                    -> 静态产物（app.mount("/code")）

设计约束：
- 模型名从 GET /api/config 动态取，不写死（VC 的 _require_model_fields 是 400 硬校验）。
- 长超时用 VIDEOCLAW_TIMEOUT，不复用 LLM_TIMEOUT(120s)。
- 不可达/未启用抛 VideoClawUnavailable，由 Action 转成 env_missing → blocked，
  绝不判成 *_failed 触发 DevAgent 空改业务代码。
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from config import settings

logger = logging.getLogger("plugins.videoclaw.client")


class VideoClawUnavailable(RuntimeError):
    """sidecar 未启用 / 不可达 / 探活失败。"""


class VideoClawError(RuntimeError):
    """VC 返回错误响应或协议级失败。"""


# VC config.yaml 的 models 键 -> ProjectStartRequest 字段名
_MODEL_MAP = {
    "llm": "llm_model",
    "vlm": "vlm_model",
    "image_t2i": "image_t2i_model",
    "image_it2i": "image_it2i_model",
    "video": "video_model",
    "video_first_frame": "video_first_frame_model",
    "video_start_end": "video_start_end_model",
    "video_reference": "video_reference_model",
}

# 6 个生产阶段（VC core/orchestrator.py:32-51 STAGE_ORDER）
STAGES = (
    "script_generation",
    "character_design",
    "storyboard",
    "reference_generation",
    "video_generation",
    "post_production",
)


def _base() -> str:
    return str(settings.VIDEOCLAW_BASE_URL).rstrip("/")


def _timeout() -> float:
    return float(settings.VIDEOCLAW_TIMEOUT)


def _request(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
    url = _base() + path
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise VideoClawError(f"VC {method} {path} -> HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, OSError) as e:
        raise VideoClawUnavailable(f"VC sidecar 不可达 {_base()}: {e}") from e
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise VideoClawError(f"VC {method} {path} 返回非 JSON") from e


async def _call(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
    # urllib 是同步的，丢到线程里避免阻塞事件循环
    return await asyncio.to_thread(_request, method, path, body)


async def health() -> bool:
    """探活；非 ok 或不可达都返回 False（由 Action 分流到 blocked）。"""
    if not settings.VIDEOCLAW_ENABLED:
        return False
    try:
        data = await _call("GET", "/api/health")
        return str(data.get("status", "")).lower() == "ok"
    except (VideoClawUnavailable, VideoClawError) as e:
        logger.info("VC health 失败: %s", e)
        return False


async def get_config() -> Dict[str, Any]:
    """返回 VC 的完整 config（含 models / generation / api_providers）。"""
    data = await _call("GET", "/api/config")
    cfg = data.get("config") if isinstance(data, dict) else None
    if not isinstance(cfg, dict):
        raise VideoClawError("GET /api/config 未返回 config 对象")
    return cfg


def resolve_start_params(cfg: Dict[str, Any], *, idea: str, episodes: int = 1) -> Dict[str, Any]:
    """把 VC config 的 models 映射成 ProjectStartRequest 的必填字段。

    VC workflow.py:44-52 的 _require_model_fields 要求
    llm_model / vlm_model / image_t2i_model / image_it2i_model 四个非空，
    且 _active_video_model 非空，否则直接 400。
    """
    models = cfg.get("models") or {}
    generation = cfg.get("generation") or {}
    if not isinstance(models, dict):
        raise VideoClawError("VC config.models 不是对象，无法确定模型")
    params: Dict[str, Any] = {"idea": idea, "episodes": episodes}
    for src, dst in _MODEL_MAP.items():
        val = models.get(src)
        if val:
            params[dst] = val
    for key in ("video_generation_mode", "style", "video_ratio", "video_resolution"):
        val = generation.get(key)
        if val:
            params[key] = val
    missing = [k for k in ("llm_model", "vlm_model", "image_t2i_model", "image_it2i_model") if not params.get(k)]
    if missing:
        raise VideoClawError(f"VC config 缺模型配置: {', '.join(missing)}（请检查 VC 的 config.yaml models 段）")
    if not (params.get("video_model") or params.get("video_first_frame_model")):
        raise VideoClawError("VC config 缺视频模型配置")
    return params


async def start_project(cfg: Dict[str, Any], *, idea: str, episodes: int = 1) -> Dict[str, Any]:
    params = resolve_start_params(cfg, idea=idea, episodes=episodes)
    return await _call("POST", "/api/project/start", params)


async def continue_workflow(session_id: str) -> Dict[str, Any]:
    return await _call("POST", f"/api/project/{session_id}/continue", {})


async def get_status(session_id: str) -> Dict[str, Any]:
    return await _call("GET", f"/api/project/{session_id}/status")


async def get_artifact(session_id: str, stage: str) -> Dict[str, Any]:
    return await _call("GET", f"/api/project/{session_id}/artifact/{stage}")


def _download(rel: str, dest: Path) -> int:
    """从 VC 的 /code/ 静态挂载下载产物，返回字节数。"""
    url = _base() + "/code/" + str(rel).lstrip("/")
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:
            content = resp.read()
    except urllib.error.HTTPError as e:
        raise VideoClawError(f"下载 {rel} -> HTTP {e.code}") from e
    except (urllib.error.URLError, OSError) as e:
        raise VideoClawUnavailable(f"下载 {rel} 失败: {e}") from e
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return len(content)


async def download_product(rel: str, dest: Path) -> int:
    return await asyncio.to_thread(_download, rel, dest)
