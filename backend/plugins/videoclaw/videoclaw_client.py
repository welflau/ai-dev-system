"""VideoClaw sidecar HTTP 客户端 —— 只发请求，不碰 ADS 业务。

契约来源（VC 仓库，接入时实读）：
  GET  /api/health                         -> {"status":"ok"}
  GET  /api/config                         -> {"config": {models, generation, ...}, "path": ...}
  GET  /api/models?model_type=t2i|video    -> {"models":[...]}  可用模型清单
  POST /api/project/start                  -> {"session_id", "status", "params"}
  POST /api/project/{sid}/continue         -> 同步推进工作流
  GET  /api/project/{sid}/status           -> 状态快照
  GET  /api/project/{sid}/artifact/{stage} -> {"stage", "artifact"}
  POST /api/sandbox/t2i                    -> {success, result:[result/...], record_id}
  POST /api/sandbox/i2i                    -> 同上，多一个必填 image
  POST /api/sandbox/video                  -> {success, result:<远端URL>, video_path:<result/...>, record_id}
  GET  /code/result/...                    -> 静态产物（app.mount("/code")）

设计约束：
- 模型名从 GET /api/config 动态取，不写死（VC 的 _require_model_fields 是 400 硬校验）。
- 长超时用 VIDEOCLAW_TIMEOUT；生视频单独用 VIDEOCLAW_VIDEO_TIMEOUT（分钟级，可到 600s+）。
  都不复用 LLM_TIMEOUT(120s)。
- sandbox 是同步接口但**HTTP 200 也可能是失败**（{success:false, error}），必须查 success。
- 生视频取 video_path 不取 result（result 是会过期的远端 URL）。
- VC 的 _normalize_path 有 POSIX 假设，Windows 下会返回
  `result/G:\\...\\code\\result\\...`，必须走 normalize_media_rel() 兜底。
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


def _video_timeout() -> float:
    # 生视频是分钟级：Kling 最坏 poll 600s + 下载，VC 前端都特意绕开代理直连。
    # 缺省 VIDEOCLAW_TIMEOUT(600) 在边界情况会先超时而 VC 后台仍在生成，故单独放宽。
    return float(getattr(settings, "VIDEOCLAW_VIDEO_TIMEOUT", 900))


def _request(
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
) -> Any:
    url = _base() + path
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout or _timeout()) as resp:
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


async def _call(
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
) -> Any:
    # urllib 是同步的，丢到线程里避免阻塞事件循环
    return await asyncio.to_thread(_request, method, path, body, timeout)


def _require_success(data: Any, path: str) -> Dict[str, Any]:
    """sandbox 系列成功/失败都是 HTTP 200，必须查 success 字段。"""
    if not isinstance(data, dict):
        raise VideoClawError(f"VC {path} 返回非对象: {type(data).__name__}")
    if not data.get("success"):
        raise VideoClawError(f"VC {path} 失败: {data.get('error') or '未知错误'}")
    return data


def normalize_media_rel(raw: Any) -> str:
    """把 VC 返回的各种产物路径归一成 /code/ 下的相对路径。

    VC 的 _normalize_path（sandbox.py:56-73）用 path.startswith('/') 判绝对路径，
    这是 POSIX 假设；Windows 下会返回 `result/G:\\...\\code\\result\\sandbox\\...`。
    这里统一：反斜杠转正斜杠 → 取最后一个 `code/` 之后的部分 → 补成 result/...。

    pipelines 返回的是绝对路径（含 <backend>/code/result/task/...），也能一并处理。
    http(s):// 与 data: 是远端/内联产物，原样返回，由调用方决定是否直接下载。
    """
    s = str(raw or "").strip().replace("\\", "/")
    if not s:
        return ""
    if s.startswith(("http://", "https://", "data:", "file://", "oss://")):
        return s
    if "code/" in s:
        s = s.rsplit("code/", 1)[1]
    if s.startswith("code/"):
        s = s[len("code/"):]
    if not s.startswith("result/") and "result/" in s:
        s = "result/" + s.rsplit("result/", 1)[1]
    return s.lstrip("/")


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


# ── sandbox 单次能力（生图 / 生视频）────────────────────────────────────────
# 契约：VC api/routers/sandbox.py:294-440、api/schemas/sandbox.py:19-39。
# 同步接口，HTTP 挂到生成完成才返回；失败也是 HTTP 200 + {success:false}。

async def get_models(model_type: str) -> list:
    """GET /api/models?model_type=t2i|i2i|video|llm|vlm -> 模型清单。"""
    data = await _call("GET", f"/api/models?model_type={model_type}")
    return data.get("models", []) if isinstance(data, dict) else []


def resolve_sandbox_models(cfg: Dict[str, Any]) -> Dict[str, str]:
    """从 VC config.models 取生图/生视频默认模型，不写死。"""
    models = cfg.get("models") or {}
    if not isinstance(models, dict):
        raise VideoClawError("VC config.models 不是对象，无法确定模型")
    out: Dict[str, str] = {}
    for key in ("image_t2i", "image_it2i", "video"):
        if models.get(key):
            out[key] = str(models[key])
    if not out.get("image_t2i"):
        raise VideoClawError("VC config 缺 image_t2i 模型（请检查 config.yaml models 段）")
    if not out.get("video"):
        raise VideoClawError("VC config 缺 video 模型")
    return out


async def sandbox_t2i(*, model: str, prompt: str, ratio: str = "16:9") -> Dict[str, Any]:
    """POST /api/sandbox/t2i -> {success, result:[result/...], record_id}。"""
    data = await _call("POST", "/api/sandbox/t2i", {
        "model": model, "prompt": prompt, "ratio": ratio,
    })
    return _require_success(data, "/api/sandbox/t2i")


async def sandbox_i2i(*, model: str, prompt: str, image: str, ratio: str = "16:9") -> Dict[str, Any]:
    """POST /api/sandbox/i2i；image 为 http(s)/本地存在路径/VC 可访问的 /code/ URL。"""
    data = await _call("POST", "/api/sandbox/i2i", {
        "model": model, "prompt": prompt, "image": image, "ratio": ratio,
    })
    return _require_success(data, "/api/sandbox/i2i")


async def sandbox_video(
    *, model: str, prompt: str, image: str,
    ratio: str = "16:9", resolution: str = "720P", duration: int = 5,
) -> Dict[str, Any]:
    """POST /api/sandbox/video。

    VC 默认 wan2.7-i2v 及所有 video provider 都要求首帧图
    （models/video_dashscope.py:257），没有纯文生视频。image 必须给。
    result 是远端过期 URL，产物路径取 video_path。
    """
    data = await _call("POST", "/api/sandbox/video", {
        "model": model, "prompt": prompt, "image": image, "ratio": ratio,
        "resolution": resolution, "duration": int(duration),
    }, timeout=_video_timeout())
    return _require_success(data, "/api/sandbox/video")


def media_url(rel: str) -> str:
    """把归一化后的 result/... 拼成 VC 自己可访问的绝对 URL（供 i2i/video 当输入）。"""
    return _base() + "/code/" + str(rel).lstrip("/")


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
    """下载 /code/ 下的产物；远端 http(s) URL 直接取，其余先归一化。"""
    s = str(rel or "").strip()
    if not s:
        raise VideoClawError("产物路径为空")
    if s.startswith(("http://", "https://")):
        return await asyncio.to_thread(_download_url, s, dest)
    return await asyncio.to_thread(_download, normalize_media_rel(s), dest)


def _download_url(url: str, dest: Path) -> int:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=_video_timeout()) as resp:
            content = resp.read()
    except urllib.error.HTTPError as e:
        raise VideoClawError(f"下载远端产物 -> HTTP {e.code}") from e
    except (urllib.error.URLError, OSError) as e:
        raise VideoClawUnavailable(f"下载远端产物失败: {e}") from e
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return len(content)
