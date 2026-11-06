"""LightAI 视频：提交异步任务、轮询、下载。复用 image_processor 的信号量与 HTTP。"""
from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import settings

logger = logging.getLogger("plugins.director.lightai_video")

_VIDEO_EXTS = (".mp4", ".webm", ".mov")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
_AUDIO_EXTS = (".wav", ".mp3", ".m4a")


def _as_list(val: Any) -> List[str]:
    if not val:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        s = val.strip()
        if s.startswith("["):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
        return [s] if s else []
    return []


def _is_http(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _extract_video_url(result: dict) -> Optional[str]:
    from image_processor import _collect_http_strings

    urls: List[str] = []
    _collect_http_strings(result, urls)
    uniq = list(dict.fromkeys(urls))
    for u in uniq:
        lower = u.lower().split("?", 1)[0]
        if lower.endswith(_VIDEO_EXTS):
            return u
    for u in uniq:
        lower = u.lower().split("?", 1)[0]
        if not any(lower.endswith(ext) for ext in _IMAGE_EXTS):
            return u
    return uniq[0] if uniq else None


def _upload_cos_sync(local_path: Path) -> str:
    """把本地参考文件传到 LightAI COS，返回可访问 URL。失败返回空串。"""
    from image_processor import _SSL_CTX, _lightai_headers

    if not local_path.is_file():
        return ""
    mime = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
    boundary = f"----ADS{uuid.uuid4().hex}"
    cos_path = f"ads/director/{int(time.time())}_{local_path.name}"
    data = local_path.read_bytes()
    parts = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="cos_path"\r\n\r\n'
        f"{cos_path}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="cover"\r\n\r\n'
        f"0\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image_file"; filename="{local_path.name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8")
    body = parts + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    url = f"{settings.LIGHTAI_API_BASE.rstrip('/')}/api/lightai/upload_cos"
    headers = _lightai_headers()
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120, context=_SSL_CTX) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning("COS 上传失败 %s: %s", local_path, e)
        return ""
    for key in ("url", "cos_url", "download_url"):
        val = payload.get(key)
        if isinstance(val, str) and _is_http(val):
            return val
    data_obj = payload.get("data")
    if isinstance(data_obj, dict):
        for key in ("url", "cos_url", "download_url"):
            val = data_obj.get(key)
            if isinstance(val, str) and _is_http(val):
                return val
    if isinstance(data_obj, str) and _is_http(data_obj):
        return data_obj
    return ""


async def resolve_media_url(raw: str, repo_path: str = "") -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if _is_http(text):
        return text
    p = Path(text)
    if not p.is_file() and repo_path:
        p = Path(repo_path) / text
    if not p.is_file():
        return ""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _upload_cos_sync, p.resolve())


def _build_payload(req: Dict[str, Any]) -> Dict[str, Any]:
    engine = str(req.get("engine") or "kling").lower()
    if engine in ("keling", "可灵"):
        engine = "kling"
    prompt = str(req.get("prompt") or "").strip()
    duration = int(req.get("duration") or 15)
    ratio = str(req.get("aspect_ratio") or "16:9")
    resolution = str(req.get("resolution") or "720p")
    sound = "on" if req.get("sound") else "off"
    refs: Sequence[str] = req.get("ref_images") or []
    first = str(req.get("first_frame") or "")
    last = str(req.get("last_frame") or "")
    audio = str(req.get("ref_audio") or "")

    if engine == "jimeng":
        duration = max(5, min(duration, 10))
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt or "让画面动起来"}]
        image_url = first or (refs[0] if refs else "")
        if image_url:
            content.append({"type": "image_url", "image_url": {"url": image_url}})
        if audio:
            content.append({"type": "audio_url", "audio_url": {"url": audio}})
        task_json = {
            "model": "doubao-seedance-1-5-pro-251215",
            "ratio": "adaptive",
            "duration": duration,
            "resolution": resolution if resolution in ("480p", "720p", "1080p") else "720p",
            "generate_audio": sound == "on",
            "content": content,
            "watermark": False,
        }
        return {
            "service_name": "volces_ark",
            "api_name": "video30_generate",
            "app_info": {"model": "doubao-seedance-1-5-pro-251215", "mode": ""},
            "task_query": {"path": {}, "params": {}, "json": task_json, "data": {}, "file": {}},
            "custom_data": {},
        }

    duration = max(3, min(duration, 15))
    model = "kling-v3"
    mode = "pro"
    task_json: Dict[str, Any] = {
        "prompt": prompt,
        "model_name": model,
        "duration": duration,
        "aspect_ratio": ratio,
        "mode": mode,
        "sound": sound,
    }
    api_name = "text_to_video"
    if first or last:
        api_name = "image_to_video"
        if first:
            task_json["image"] = first
        if last:
            task_json["image_tail"] = last
        if not prompt:
            task_json.pop("prompt", None)
    elif len(refs) >= 1:
        api_name = "image_to_video"
        if len(refs) == 1 and not last:
            task_json["image"] = refs[0]
        else:
            task_json["image_list"] = list(refs[:4])
    if audio:
        task_json["sound"] = "on"
        task_json["audio"] = audio

    return {
        "service_name": "keling",
        "api_name": api_name,
        "app_info": {"model": model, "mode": mode},
        "task_query": {"path": {}, "params": {}, "json": task_json, "data": {}, "file": {}},
        "custom_data": {},
    }


async def _create_task(payload: Dict[str, Any]) -> Tuple[Optional[str], str]:
    from image_processor import (
        _LIGHTAI_429_INTERVAL,
        _LIGHTAI_429_MAX_WAIT,
        _lightai_post,
    )

    deadline = time.time() + _LIGHTAI_429_MAX_WAIT
    attempt = 0
    loop = asyncio.get_event_loop()
    while True:
        attempt += 1
        try:
            result = await loop.run_in_executor(
                None, lambda: _lightai_post("/api/lightai/create_async_task", payload, 120)
            )
            task_id = (
                result.get("task_id")
                or result.get("taskId")
                or (result.get("data") or {}).get("task_id")
                or (result.get("data") or {}).get("taskId")
                or ""
            )
            if task_id:
                return str(task_id), ""
            msg = str(result.get("message") or result.get("error") or "LightAI 未返回 task_id")
            return None, msg
        except urllib.error.HTTPError as e:
            if e.code == 429 and time.time() < deadline:
                logger.warning("LightAI 视频 429，第 %d 次，%.0fs 后重试", attempt, _LIGHTAI_429_INTERVAL)
                await asyncio.sleep(_LIGHTAI_429_INTERVAL)
                continue
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            return None, f"LightAI 创建视频任务失败: HTTP {e.code} {body}"
        except Exception as e:
            return None, f"LightAI 创建视频任务失败: {e}"


async def _poll_task(task_id: str, *, interval: int = 15, max_wait: int = 600) -> Tuple[Optional[str], str]:
    from image_processor import _lightai_get

    elapsed = 0
    await asyncio.sleep(interval)
    elapsed += interval
    loop = asyncio.get_event_loop()
    while elapsed <= max_wait:
        try:
            result = await loop.run_in_executor(
                None, lambda: _lightai_get(f"/api/lightai/get_task_status/{task_id}")
            )
            status = result.get("status")
            if status == 2:
                url = _extract_video_url(result)
                if url:
                    return url, ""
                return None, "任务成功但响应里没有视频 URL，禁止写空文件"
            if status is not None and (status < 0 or status >= 3):
                return None, str(result.get("message") or f"LightAI 任务失败 status={status}")
        except Exception as e:
            logger.warning("LightAI 视频轮询异常: %s", e)
        await asyncio.sleep(interval)
        elapsed += interval
    return None, f"LightAI 视频任务超时: {task_id}"


async def download_url(url: str, dest: Path) -> Tuple[bool, str]:
    from image_processor import _SSL_CTX

    dest.parent.mkdir(parents=True, exist_ok=True)

    def _do():
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=180, context=_SSL_CTX) as resp:
            data = resp.read()
        if not data:
            raise RuntimeError("下载结果为空")
        dest.write_bytes(data)

    try:
        await asyncio.get_event_loop().run_in_executor(None, _do)
        if not dest.is_file() or dest.stat().st_size <= 0:
            if dest.exists():
                dest.unlink()
            return False, "下载后文件为空，已删除"
        return True, ""
    except Exception as e:
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        return False, f"下载视频失败: {e}"


async def create_and_poll_video(req: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], str]:
    """返回 (task_id, video_url, error)。整段占用 LightAI 信号量。"""
    from image_processor import _lightai_sem

    payload = _build_payload(req)
    async with _lightai_sem():
        task_id, err = await _create_task(payload)
        if not task_id:
            return None, None, err or "创建任务失败"
        url, err = await _poll_task(task_id)
        if not url:
            return task_id, None, err or "轮询未拿到视频 URL"
        return task_id, url, ""
