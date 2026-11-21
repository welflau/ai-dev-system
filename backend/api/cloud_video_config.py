"""系统公共云端生视频：AI 配置面板的「生视频」Tab 后端。

三个端点（照 api/image_gen.py 的形状，但独立 router，不污染 llm_config）：
  GET  /api/cloud-video/config/status   配置状态（密钥只给布尔，绝不回传）
  POST /api/cloud-video/config          热更新 settings.* + 回写 backend/.env（只改传入键）
  POST /api/cloud-video/config/test     测试连接：probe_provider（不联网）+ ping（联网验卡）

字段归口以 cloud_video.PROVIDERS 与 config.py 的 MINIMAX_H3_* / VIDEOCLAW_* 为准。
⚠️ MiniMax H3 是第三方「鼠鼠工具」卡密中转，不是 MiniMax 官方 API（config.py:112-115）。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter
from pydantic import BaseModel

from config import BASE_DIR, settings

logger = logging.getLogger("api.cloud_video_config")

router = APIRouter(prefix="/api/cloud-video", tags=["cloud-video"])

# .env 读-改-写串行化：现有 main.py / image_gen.py 的写法无锁，三个端点并发保存会丢更新。
_env_lock = asyncio.Lock()

# ── 字段表：payload key -> (settings 属性, .env 键, 解析器) ──────────────────
# 「密钥」类：空输入跳过（保留旧值）；bool 写 "true"/"false"（config.py 用 .lower() 解析）。

def _s(v: Any) -> str:
    return str(v).strip()


def _i(v: Any) -> int:
    return int(v)


def _f(v: Any) -> float:
    return float(v)


def _b(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _env_bool(v: bool) -> str:
    return "true" if v else "false"


# (payload key, settings attr, env key, parser, is_secret, env_writer)
_FIELDS: Tuple[Tuple[str, str, str, Any, bool, Any], ...] = (
    ("minimax_h3_card_key",  "MINIMAX_H3_CARD_KEY",  "MINIMAX_H3_CARD_KEY",  _s, True,  _s),
    ("minimax_h3_base_url",  "MINIMAX_H3_BASE_URL",  "MINIMAX_H3_BASE_URL",  _s, False, _s),
    ("minimax_h3_enabled",   "MINIMAX_H3_ENABLED",   "MINIMAX_H3_ENABLED",   _b, False, _env_bool),
    ("minimax_h3_timeout",   "MINIMAX_H3_TIMEOUT",   "MINIMAX_H3_TIMEOUT",   _i, False, str),
    ("minimax_h3_poll_interval", "MINIMAX_H3_POLL_INTERVAL", "MINIMAX_H3_POLL_INTERVAL", _i, False, str),
    ("minimax_h3_max_polls", "MINIMAX_H3_MAX_POLLS", "MINIMAX_H3_MAX_POLLS", _i, False, str),
    # 生成任务排队
    ("minimax_h3_queue_enabled",      "MINIMAX_H3_QUEUE_ENABLED",      "MINIMAX_H3_QUEUE_ENABLED",      _b, False, _env_bool),
    ("minimax_h3_queue_idle_limit",   "MINIMAX_H3_QUEUE_IDLE_LIMIT",   "MINIMAX_H3_QUEUE_IDLE_LIMIT",   _i, False, str),
    ("minimax_h3_queue_idle_start",   "MINIMAX_H3_QUEUE_IDLE_START",   "MINIMAX_H3_QUEUE_IDLE_START",   _i, False, str),
    ("minimax_h3_queue_idle_end",     "MINIMAX_H3_QUEUE_IDLE_END",     "MINIMAX_H3_QUEUE_IDLE_END",     _i, False, str),
    ("minimax_h3_queue_tz",           "MINIMAX_H3_QUEUE_TZ",           "MINIMAX_H3_QUEUE_TZ",           _s, False, _s),
    ("minimax_h3_queue_tz_offset",    "MINIMAX_H3_QUEUE_TZ_OFFSET",    "MINIMAX_H3_QUEUE_TZ_OFFSET",    _f, False, str),
    ("minimax_h3_queue_wait_timeout", "MINIMAX_H3_QUEUE_WAIT_TIMEOUT", "MINIMAX_H3_QUEUE_WAIT_TIMEOUT", _f, False, str),
    # VideoClaw sidecar（无密钥，key 在 VC 仓库 config.yaml）
    ("videoclaw_base_url",       "VIDEOCLAW_BASE_URL",       "VIDEOCLAW_BASE_URL",       _s, False, _s),
    ("videoclaw_timeout",        "VIDEOCLAW_TIMEOUT",        "VIDEOCLAW_TIMEOUT",        _i, False, str),
    ("videoclaw_video_timeout",  "VIDEOCLAW_VIDEO_TIMEOUT",  "VIDEOCLAW_VIDEO_TIMEOUT",  _i, False, str),
    ("videoclaw_enabled",        "VIDEOCLAW_ENABLED",        "VIDEOCLAW_ENABLED",        _b, False, _env_bool),
)

_SECRET_ATTRS = {"MINIMAX_H3_CARD_KEY"}


def _public_status() -> Dict[str, Any]:
    from cloud_video import ALLOWED_PROVIDERS, PROVIDERS
    from cloud_video import client as cloud_client

    qs = cloud_client.queue_stats()
    providers = {}
    for name in ALLOWED_PROVIDERS:
        meta = PROVIDERS[name]
        pr = cloud_client.probe_provider(name)
        providers[name] = {
            "label": meta["label"],
            "auth_header": meta["auth_header"],
            "note": meta["note"],
            "configured": bool(pr["available"]),
            "hint": pr["hint"],
        }
    return {
        "configured": bool(settings.MINIMAX_H3_CARD_KEY),
        "minimax_h3": {
            "card_key_configured": bool(settings.MINIMAX_H3_CARD_KEY),  # 只给布尔，不回传值
            "base_url": settings.MINIMAX_H3_BASE_URL,
            "enabled": bool(settings.MINIMAX_H3_ENABLED),
            "timeout": settings.MINIMAX_H3_TIMEOUT,
            "poll_interval": settings.MINIMAX_H3_POLL_INTERVAL,
            "max_polls": settings.MINIMAX_H3_MAX_POLLS,
        },
        "queue": {
            "enabled": bool(settings.MINIMAX_H3_QUEUE_ENABLED),
            "idle_limit": settings.MINIMAX_H3_QUEUE_IDLE_LIMIT,
            "idle_start": settings.MINIMAX_H3_QUEUE_IDLE_START,
            "idle_end": settings.MINIMAX_H3_QUEUE_IDLE_END,
            "tz": settings.MINIMAX_H3_QUEUE_TZ,
            "tz_offset": settings.MINIMAX_H3_QUEUE_TZ_OFFSET,
            "wait_timeout": settings.MINIMAX_H3_QUEUE_WAIT_TIMEOUT,
            "stats": {
                "active": qs.active, "waiting": qs.waiting,
                "limit": qs.limit, "unlimited": qs.unlimited,
                "idle_window": qs.idle_window, "tz": qs.tz,
            },
        },
        "videoclaw": {
            "base_url": settings.VIDEOCLAW_BASE_URL,
            "timeout": settings.VIDEOCLAW_TIMEOUT,
            "video_timeout": settings.VIDEOCLAW_VIDEO_TIMEOUT,
            "enabled": bool(settings.VIDEOCLAW_ENABLED),
        },
        "lightai": {
            # LIGHTAI_API_KEY 在「图片生成」Tab 配置，这里只提示是否已配置，避免重复输入
            "configured": bool(settings.LIGHTAI_API_KEY),
            "hint": "在「图片生成」Tab 配置（lightai provider 与图片生成共用同一个 Key）",
        },
        "providers": providers,
        "warning": "MiniMax H3 是第三方「鼠鼠工具」卡密中转（runlive.top），不是 MiniMax 官方 API；官方 api_key + GroupID 不能填在这里。",
    }


@router.get("/config/status")
async def get_status():
    """返回生视频配置状态（前端 AI 配置面板使用）。密钥绝不回传。"""
    return _public_status()


def _rewrite_env(updates: Dict[str, str]) -> None:
    """逐行替换回写 backend/.env：保留注释/空行/顺序，只改传入键，绝不整文件覆盖。

    参照 main.py:989-1003 的保真写法（优于 main.py:648-690 的 dict 重建）。
    """
    env_path: Path = BASE_DIR / ".env"
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
        new_lines = []
        seen = set()
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in updates:
                    new_lines.append(f"{key}={updates[key]}")
                    seen.add(key)
                    continue
            new_lines.append(line)
        for key, value in updates.items():
            if key not in seen:
                new_lines.append(f"{key}={value}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    else:
        env_path.write_text(
            "\n".join(f"{k}={v}" for k, v in updates.items()) + "\n",
            encoding="utf-8",
        )


class CloudVideoConfigBody(BaseModel):
    """所有字段可选；密钥空串 = 不覆盖旧值。"""
    minimax_h3_card_key: Optional[str] = None
    minimax_h3_base_url: Optional[str] = None
    minimax_h3_enabled: Optional[bool] = None
    minimax_h3_timeout: Optional[int] = None
    minimax_h3_poll_interval: Optional[int] = None
    minimax_h3_max_polls: Optional[int] = None
    minimax_h3_queue_enabled: Optional[bool] = None
    minimax_h3_queue_idle_limit: Optional[int] = None
    minimax_h3_queue_idle_start: Optional[int] = None
    minimax_h3_queue_idle_end: Optional[int] = None
    minimax_h3_queue_tz: Optional[str] = None
    minimax_h3_queue_tz_offset: Optional[float] = None
    minimax_h3_queue_wait_timeout: Optional[float] = None
    videoclaw_base_url: Optional[str] = None
    videoclaw_timeout: Optional[int] = None
    videoclaw_video_timeout: Optional[int] = None
    videoclaw_enabled: Optional[bool] = None


@router.post("/config")
async def save_config(body: CloudVideoConfigBody):
    """热更新 settings.* 并回写 .env（只更新提交的字段；密钥留空保留旧值）。"""
    raw = body.model_dump(exclude_none=True)
    updates: Dict[str, str] = {}
    changed: list = []

    async with _env_lock:
        for payload_key, attr, env_key, parser, is_secret, writer in _FIELDS:
            if payload_key not in raw:
                continue
            value = raw[payload_key]
            # 密钥：空串/None 跳过（保留旧值）
            if is_secret and (value is None or str(value).strip() == ""):
                continue
            try:
                parsed = parser(value)
            except (TypeError, ValueError) as e:
                logger.warning("生视频配置 %s 值非法(%r)，跳过: %s", payload_key, value, e)
                continue
            setattr(settings, attr, parsed)
            updates[env_key] = writer(parsed)
            changed.append(env_key)

        if updates:
            _rewrite_env(updates)

    # 队列配置变更后重建全局队列（时段/上限是构造时读的）
    if any(k.startswith("MINIMAX_H3_QUEUE_") for k in changed):
        from cloud_video.client import set_queue
        from cloud_video.queue import build_queue_from_settings
        set_queue(build_queue_from_settings())

    return {"status": "ok", "changed": changed, **_public_status()}


class TestBody(BaseModel):
    """未保存的表单值也能测：临时注入 settings，try/finally 还原。"""
    minimax_h3_card_key: Optional[str] = None
    minimax_h3_base_url: Optional[str] = None
    minimax_h3_enabled: Optional[bool] = None


@router.post("/config/test")
async def test_connection(body: TestBody = None):
    """两个都要：probe_provider（不联网配置检查）+ ping（联网验卡）。"""
    # 用源模块属性（便于测试 monkeypatch），与 director/videoclaw 的适配方式一致；
    # 不用包级 re-export，那是静态绑定，patch 源模块不生效。
    from cloud_video import client as cloud_client

    raw = body.model_dump(exclude_none=True) if body else {}
    # 临时注入（ping 直接读 settings，且要求 ENABLED=true）
    saved: Dict[str, Any] = {}
    inject = {
        "minimax_h3_card_key": ("MINIMAX_H3_CARD_KEY", _s),
        "minimax_h3_base_url": ("MINIMAX_H3_BASE_URL", _s),
        "minimax_h3_enabled": ("MINIMAX_H3_ENABLED", _b),
    }
    for payload_key, (attr, parser) in inject.items():
        if payload_key in raw and raw[payload_key] is not None:
            saved[attr] = getattr(settings, attr)
            try:
                setattr(settings, attr, parser(raw[payload_key]))
            except (TypeError, ValueError):
                pass
    # 测试连接无论表单里的「启用」开关状态如何都强制启用：
    # 目的是验卡，而不是验开关。原值已记入 saved，finally 会还原。
    if "MINIMAX_H3_ENABLED" not in saved:
        saved["MINIMAX_H3_ENABLED"] = getattr(settings, "MINIMAX_H3_ENABLED")
    setattr(settings, "MINIMAX_H3_ENABLED", True)

    try:
        probe = cloud_client.probe_provider("minimax_h3")
        if not probe["available"]:
            return {
                "status": "not_configured",
                "message": probe["hint"] or "卡密钥未配置或未启用",
                "probe": probe,
            }
        ok = await cloud_client.ping()
        return {
            "status": "ok" if ok else "error",
            "message": "卡密钥有效/已放行（鉴权通过）" if ok else "卡密钥无效或未加入白名单（HTTP 401/403）",
            "probe": probe,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)[:200], "probe": None}
    finally:
        for attr, value in saved.items():
            setattr(settings, attr, value)
