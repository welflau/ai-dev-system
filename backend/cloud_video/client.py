"""系统公共云端生视频 client —— 纯 transport + 协议编排，零业务依赖。

只依赖 `config.settings` 与标准库（urllib / asyncio / json / base64 / uuid）。
不 import plugins.* / actions.* / database / events / git_manager，
不返回 ActionResult、不写时间轴、不判 env_missing（这些由调用方 Plugin/Action 负责）。

契约来源（F:/A_Works/ComicAI，接入时实读）：
  backend/app/api/v1/endpoints/video_mnmx.py  转发端点全文
  Docs/鼠鼠工具-视频生成API文档.md           权威契约 v3.0
  frontend/src/api/index.ts:2504-2747        上层编排（并发/重试/轮询）

端点（上游 runlive.top/mnmx）：
  POST /api/v1/tasks                 multipart：task_name/prompt/resolution/duration/aspect_ratio + 文件
  GET  /api/v1/tasks/{id}            查询状态 queued|processing|completed|failed
  GET  /api/v1/tasks/{id}/file-url   完成后取带时效的签名直链
  鉴权头 X-Card-Key: sk_...（白名单制，403=卡未放行，402=积分不足，429=限速）
"""
from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import settings
from cloud_video.queue import CloudVideoQueue, QueueStats, build_queue_from_settings

logger = logging.getLogger("cloud_video.client")

# 系统公共云端生视频的全局生成任务队列（模块级单例，进程内有效）。
# 单 uvicorn worker 部署；多 worker 需换成 Redis 等跨进程队列（见方案 §16）。
_queue: Optional[CloudVideoQueue] = None


def get_queue() -> CloudVideoQueue:
    """懒构造全局队列（避免 import 时读配置的时序问题，也便于测试替换）。"""
    global _queue
    if _queue is None:
        _queue = build_queue_from_settings()
    return _queue


def set_queue(q: CloudVideoQueue) -> None:
    """测试/运维注入用：替换全局队列实例。"""
    global _queue
    _queue = q


def queue_stats() -> QueueStats:
    """队列可观测性：当前活跃数、等待数、上限、是否闲时、时区。"""
    return get_queue().stats()


class CloudVideoUnavailable(RuntimeError):
    """未启用 / 缺卡密钥 / 网络不通 / 超时。调用方应转成 env_missing → blocked。"""


class CloudVideoError(RuntimeError):
    """上游返回失败、参数错误或协议异常。调用方按普通失败处理。"""


@dataclass
class CloudVideoFile:
    """一个 multipart 文件字段。data 为原始字节。"""
    field: str          # first_frame / last_frame / ref_0..ref_5 / ref_audio_0..ref_audio_2
    filename: str
    mime: str
    data: bytes

    @classmethod
    def from_path(cls, field: str, path: str | Path) -> "CloudVideoFile":
        p = Path(path)
        if not p.is_file():
            raise CloudVideoError(f"参考文件不存在: {p}")
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        return cls(field=field, filename=p.name, mime=mime, data=p.read_bytes())


# provider 注册表 —— 系统公共云端生视频的**单一真源**。
# Plugin 层（director / videoclaw）从这里取后端名，不再各自维护一份。
# 后续加官方 MiniMax / Ark / LibTV 时在此登记，配置仍走系统配置。
PROVIDERS: Dict[str, Dict[str, str]] = {
    "lightai": {
        "label": "LightAI 云端（Kling / 即梦）",
        "base_setting": "LIGHTAI_API_BASE",
        "key_setting": "LIGHTAI_API_KEY",
        "auth_header": "Authorization: Bearer",
        "note": "复用 image_processor 的公共 HTTP/信号量；实现见 cloud_video/lightai.py",
    },
    "minimax_h3": {
        "label": "MiniMax H3 云端（鼠鼠工具卡密中转）",
        "base_setting": "MINIMAX_H3_BASE_URL",
        "key_setting": "MINIMAX_H3_CARD_KEY",
        "auth_header": "X-Card-Key",
        "note": "第三方卡密中转，非 MiniMax 官方 API；无 Bearer / 无 GroupID",
    },
}

# 公共层支持的云端 provider（Plugin 的 CLI 后端 libtv/dreamina 不在此列，
# 那些是 director 私有业务，留在 plugin 内）。
ALLOWED_PROVIDERS = tuple(PROVIDERS.keys())

_PROVIDER_ALIASES = {
    "lightai": "lightai", "kling": "lightai", "可灵": "lightai",
    "minimax_h3": "minimax_h3", "minimax": "minimax_h3", "h3": "minimax_h3",
    "mnmx": "minimax_h3", "鼠鼠": "minimax_h3",
}


def normalize_provider(raw: Any) -> str:
    key = str(raw or "").strip().lower()
    return _PROVIDER_ALIASES.get(key, key)


def probe_provider(provider: str) -> Dict[str, Any]:
    """轻量配置探活（不联网）：返回 {provider, available, hint, command}。"""
    name = normalize_provider(provider)
    if name not in PROVIDERS:
        return {
            "provider": name or "", "available": False,
            "hint": f"未知云端 provider {provider!r}，允许：{', '.join(ALLOWED_PROVIDERS)}。",
            "command": f"cloud_video probe={provider}",
        }
    meta = PROVIDERS[name]
    key = str(getattr(settings, meta["key_setting"], "") or "").strip()
    enabled = True
    if name == "minimax_h3":
        enabled = bool(getattr(settings, "MINIMAX_H3_ENABLED", False))
    ok = bool(key) and enabled
    if not ok:
        extra = "，且需 MINIMAX_H3_ENABLED=true" if name == "minimax_h3" else ""
        return {
            "provider": name, "available": False,
            "hint": f"系统配置 {meta['key_setting']} 未设置{extra}，无法用 {meta['label']}。",
            "command": f"cloud_video provider={name}",
        }
    return {"provider": name, "available": True, "hint": "", "command": f"cloud_video provider={name}"}

TASK_T2V = "minimax_h3_v2"           # 文生 / 首帧 / 首尾帧
TASK_MULTI_REF = "minimax_h3_multi_ref"  # 多参考（最多 6 图 + 3 音频）

# 文档 :76-83 —— aspect_ratio 必须整串填写
ASPECT_RATIOS = (
    "21:9 (Ultrawide)",
    "16:9 (Widescreen)",
    "4:3 (Standard)",
    "1:1 (Square)",
    "3:4 (Portrait Standard)",
    "9:16 (Portrait Widescreen)",
)
_RESOLUTIONS = ("0.4", "1", "2")  # 480P / 768P / 1080P（1080P 仅 v2）
_RETRYABLE = (429, 502, 503, 504)


def _base() -> str:
    return str(settings.MINIMAX_H3_BASE_URL).rstrip("/")


def _require_key() -> str:
    if not settings.MINIMAX_H3_ENABLED:
        raise CloudVideoUnavailable("MINIMAX_H3_ENABLED=false，系统公共云端生视频未启用")
    key = str(settings.MINIMAX_H3_CARD_KEY or "").strip()
    if not key:
        raise CloudVideoUnavailable("MINIMAX_H3_CARD_KEY 未配置（backend/.env），无法调用鼠鼠工具")
    return key


def _error_message(payload: Any, fallback: str) -> str:
    """上游错误落在 HTTP 状态码 + detail/message/error（video_mnmx.py:68-77）。"""
    if isinstance(payload, dict):
        for field in ("detail", "message", "error"):
            v = payload.get(field)
            if isinstance(v, str) and v:
                return v
            if isinstance(v, dict) and v.get("message"):
                return str(v["message"])
    return fallback


def _encode_multipart(fields: Dict[str, Any], files: Sequence[CloudVideoFile]) -> Tuple[bytes, str]:
    """手搓 multipart/form-data（urllib 无原生支持）。"""
    boundary = "----ADSCloudVideo" + uuid.uuid4().hex
    chunks: List[bytes] = []
    for name, value in fields.items():
        if value is None:
            continue
        chunks.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode("utf-8")
        )
    for f in files:
        chunks.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{f.field}"; filename="{f.filename}"\r\n'
            f"Content-Type: {f.mime}\r\n\r\n".encode("utf-8")
        )
        chunks.append(f.data)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), boundary


def _request(
    method: str,
    path: str,
    *,
    key: str,
    fields: Optional[Dict[str, Any]] = None,
    files: Optional[Sequence[CloudVideoFile]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    url = _base() + path
    headers = {PROVIDERS["minimax_h3"]["auth_header"]: key}
    body = None
    if fields is not None or files:
        body, boundary = _encode_multipart(fields or {}, files or ())
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout or float(settings.MINIMAX_H3_TIMEOUT)) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail_raw = e.read().decode("utf-8", "replace")
        try:
            payload = json.loads(detail_raw)
        except ValueError:
            payload = {"detail": detail_raw[:400]}
        msg = _error_message(payload, f"鼠鼠工具返回 HTTP {e.code}")
        if e.code in (401, 403):
            raise CloudVideoUnavailable(f"卡密钥无效/未放行（HTTP {e.code}）: {msg}") from e
        raise CloudVideoError(f"鼠鼠工具 HTTP {e.code}: {msg}") from e
    except (urllib.error.URLError, OSError) as e:
        raise CloudVideoUnavailable(f"连接鼠鼠工具失败 {_base()}: {e}") from e

    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise CloudVideoError(f"鼠鼠工具 {method} {path} 返回非 JSON") from e
    if not isinstance(data, dict):
        raise CloudVideoError(f"鼠鼠工具 {method} {path} 返回非对象")
    # 上游也可能 200 + {success:false}
    if data.get("success") is False:
        raise CloudVideoError(f"鼠鼠工具 {method} {path} 失败: {_error_message(data, '未知错误')}")
    return data


async def _call(
    method: str,
    path: str,
    *,
    key: str,
    fields: Optional[Dict[str, Any]] = None,
    files: Optional[Sequence[CloudVideoFile]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        _request, method, path, key=key, fields=fields, files=files, timeout=timeout
    )


def _normalize_params(
    *,
    task_name: str,
    resolution: Optional[str],
    duration: Optional[float],
    aspect_ratio: Optional[str],
    has_last_frame: bool,
) -> Dict[str, Any]:
    """按鼠鼠文档 :33-83 做参数归一化，避免上游 400 拒单（拒单不扣分）。"""
    if task_name not in (TASK_T2V, TASK_MULTI_REF):
        raise CloudVideoError(f"task_name 仅支持 {TASK_T2V} / {TASK_MULTI_REF}")
    res = str(resolution or "1")
    if res not in _RESOLUTIONS:
        res = "1"
    if task_name == TASK_MULTI_REF and res == "2":
        res = "1"  # multi_ref 不支持 1080P
    dur = float(duration or 5)
    dur = max(4.0, min(dur, 15.0))
    if has_last_frame and res == "2" and dur > 10:
        dur = 10.0  # 首尾帧 + 1080P 最长 10s
    ratio = aspect_ratio if aspect_ratio in ASPECT_RATIOS else "16:9 (Widescreen)"
    return {
        "task_name": task_name,
        "resolution": res,
        "duration": str(int(dur) if dur.is_integer() else dur),
        "aspect_ratio": ratio,
    }


# ── 四个原语（对齐 ComicAI video_mnmx.py 的 4 个端点）────────────────────────

async def submit(
    *,
    prompt: str,
    task_name: str = TASK_T2V,
    resolution: Optional[str] = "1",
    duration: Optional[float] = 5,
    aspect_ratio: Optional[str] = "16:9 (Widescreen)",
    files: Optional[Sequence[CloudVideoFile]] = None,
    retries: int = 3,
) -> Dict[str, Any]:
    """POST /api/v1/tasks -> {task_id, status, credit_cost}。

    429/502/503/504 退避重试（ComicAI 前端 :2692-2699 的 5s×30 次，这里收敛为可配）。
    """
    if not str(prompt or "").strip():
        raise CloudVideoError("prompt 不能为空")
    key = _require_key()
    file_list = list(files or [])
    params = _normalize_params(
        task_name=task_name, resolution=resolution, duration=duration,
        aspect_ratio=aspect_ratio, has_last_frame=any(f.field == "last_frame" for f in file_list),
    )
    fields = {"prompt": prompt, **params}
    last_err: Optional[Exception] = None
    for attempt in range(max(1, retries)):
        try:
            data = await _call(method="POST", path="/api/v1/tasks", key=key,
                               fields=fields, files=file_list)
            block = data.get("data") or {}
            task_id = block.get("task_id") if isinstance(block, dict) else None
            if not task_id:
                raise CloudVideoError(f"鼠鼠工具未返回 task_id: {str(data)[:200]}")
            return {
                "task_id": str(task_id),
                "status": block.get("status", "queued"),
                "credit_cost": block.get("credit_cost"),
                "task_name": params["task_name"],
            }
        except CloudVideoError as e:
            # 只有 429/502/503/504 值得重试；其余（400/402/403 等）立即抛
            if not any(code in str(e) for code in ("429", "502", "503", "504")):
                raise
            last_err = e
            if attempt + 1 < max(1, retries):
                await asyncio.sleep(5)
        except CloudVideoUnavailable:
            raise
    raise CloudVideoError(f"提交重试耗尽: {last_err}")


async def query(task_id: str) -> Dict[str, Any]:
    """GET /api/v1/tasks/{id} -> 上游 data 块（status / error / queue_position ...）。"""
    key = _require_key()
    data = await _call(method="GET", path=f"/api/v1/tasks/{task_id}", key=key, timeout=30.0)
    block = data.get("data")
    if not isinstance(block, dict):
        raise CloudVideoError(f"查询 {task_id} 未返回 data 块")
    return block


async def file_url(task_id: str) -> Dict[str, str]:
    """GET /api/v1/tasks/{id}/file-url -> {url, filename}（带时效签名直链）。"""
    key = _require_key()
    data = await _call(method="GET", path=f"/api/v1/tasks/{task_id}/file-url", key=key, timeout=30.0)
    block = data.get("data")
    if not isinstance(block, dict) or not block.get("url"):
        raise CloudVideoError(f"鼠鼠工具未返回下载地址: {str(data)[:200]}")
    return {"url": str(block["url"]), "filename": str(block.get("filename") or "")}


async def ping() -> bool:
    """校验卡密钥：用不存在的 task id 反查，403=无效，404=鉴权通过（video_mnmx.py:197-214）。"""
    try:
        key = _require_key()
    except CloudVideoUnavailable:
        return False
    try:
        await _call(method="GET", path="/api/v1/tasks/ping-connectivity-check",
                    key=key, timeout=12.0)
        return True
    except CloudVideoError as e:
        # 404 / 任务不存在 = 鉴权已通过
        return "404" in str(e) or "任务不存在" in str(e)
    except CloudVideoUnavailable:
        return False


async def download(url: str, dest: Path) -> int:
    """下载签名直链到 dest，返回字节数。

    注意：ComicAI DevLog 2026-11-05_10:45 记录直链可能是内网 IP
    （http://172.22.5.8:8177/...），从 ADS 所在机器未必可达。本层照实抛错，
    由调用方决定是改用 url 交付还是另做代理。
    """
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=float(settings.MINIMAX_H3_TIMEOUT)) as resp:
            content = resp.read()
    except urllib.error.HTTPError as e:
        raise CloudVideoError(f"下载视频 -> HTTP {e.code}") from e
    except (urllib.error.URLError, OSError) as e:
        raise CloudVideoUnavailable(f"下载视频失败（直链可能是内网地址）: {e}") from e
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return len(content)


# ── 一站式编排（submit → poll → file-url → 可选下载）────────────────────────

async def generate_video(
    *,
    prompt: str,
    task_name: str = TASK_T2V,
    resolution: Optional[str] = "1",
    duration: Optional[float] = 5,
    aspect_ratio: Optional[str] = "16:9 (Widescreen)",
    files: Optional[Sequence[CloudVideoFile]] = None,
    dest: Optional[Path] = None,
) -> Dict[str, Any]:
    """提交 → 轮询 → 取直链 →（可选）下载，返回结构化结果，不碰 ActionResult。

    轮询遵守查询 1 次/秒限速（文档 :18），间隔取 MINIMAX_H3_POLL_INTERVAL，
    上限 MINIMAX_H3_MAX_POLLS（默认 5s×180=15min，对齐 ComicAI 前端 :2708-2712）。
    """
    started = await submit(
        prompt=prompt, task_name=task_name, resolution=resolution,
        duration=duration, aspect_ratio=aspect_ratio, files=files,
    )
    task_id = started["task_id"]
    interval = max(1.0, float(settings.MINIMAX_H3_POLL_INTERVAL))
    max_polls = max(1, int(settings.MINIMAX_H3_MAX_POLLS))

    status_block: Dict[str, Any] = {}
    for _ in range(max_polls):
        status_block = await query(task_id)
        state = str(status_block.get("status") or "").lower()
        if state == "completed":
            break
        if state == "failed":
            raise CloudVideoError(
                f"鼠鼠工具任务 {task_id} 失败: {status_block.get('error') or '未知原因'}"
            )
        await asyncio.sleep(interval)
    else:
        raise CloudVideoError(
            f"鼠鼠工具任务 {task_id} 轮询超时（{interval:g}s × {max_polls}），最后状态="
            f"{status_block.get('status')}；可凭 task_id 稍后自行 query/file_url"
        )

    link = await file_url(task_id)
    result: Dict[str, Any] = {
        "task_id": task_id,
        "status": status_block.get("status"),
        "credit_cost": status_block.get("credit_cost") or started.get("credit_cost"),
        "url": link["url"],
        "filename": link["filename"],
        "downloaded": False,
    }
    if dest is not None:
        size = await download(link["url"], dest)
        result.update({"downloaded": True, "path": str(dest), "bytes": size})
    return result


# ── 统一 dispatch（供 Plugin 适配调用）──────────────────────────────────────
# 参数用各 provider 原生命名，调用方只传自己关心的字段；未知的由各实现忽略。
# 通过 provider 分流到 lightai / minimax_h3，返回结构统一：
#   {provider, task_id, status, url, filename, downloaded, path?, bytes?}

async def generate_video_with_provider(
    provider: str,
    *,
    prompt: str,
    dest: Optional[Path] = None,
    # minimax_h3 参数
    task_name: str = TASK_T2V,
    resolution: Optional[str] = "1",
    duration: Optional[float] = 5,
    aspect_ratio: Optional[str] = "16:9 (Widescreen)",
    files: Optional[Sequence[CloudVideoFile]] = None,
    # lightai 参数
    lightai_req: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """按 provider 分流的统一入口。Plugin 只需 `from cloud_video import generate_video_with_provider`。

    先做轻量配置探活（不联网）：缺 key → CloudVideoUnavailable（调用方转 blocked）。
    """
    name = normalize_provider(provider)
    probe = probe_provider(name)
    if not probe["available"]:
        raise CloudVideoUnavailable(probe["hint"])

    # 生成任务排队：时段感知 FIFO 信号量，一个名额覆盖「提交 + 429 退避 + 轮询 + 下载」全程。
    # 放在统一 dispatch 层（Plugin 唯一入口），两个 provider 共用同一队列，避免底层
    # generate_video/lightai.generate 各占一次造成双重占用。
    async with get_queue().slot():
        if name == "lightai":
            from cloud_video import lightai
            req = dict(lightai_req or {})
            req.setdefault("prompt", prompt)
            return await lightai.generate(req, dest)

        if name == "minimax_h3":
            result = await generate_video(
                prompt=prompt, task_name=task_name, resolution=resolution,
                duration=duration, aspect_ratio=aspect_ratio, files=files, dest=dest,
            )
            return {"provider": "minimax_h3", **result}

    raise CloudVideoError(f"未实现的 provider: {name}")
