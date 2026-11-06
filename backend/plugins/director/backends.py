"""视频生成后端选择。用户指定优先；缺省 LightAI；失败不静默换后端。"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from plugins.director.work_package import find_existing_slug, package_dir

ALLOWED_BACKENDS = ("lightai", "libtv", "dreamina")
_ALIASES = {
    "lightai": "lightai",
    "kling": "lightai",
    "libtv": "libtv",
    "dreamina": "dreamina",
    "jimeng": "dreamina",
    "即梦": "dreamina",
}
DRAMA_MODES = frozenset({"cinematic-drama", "drama"})
_BINARIES = {
    "libtv": ("libtv", "libtv.exe", "libtv.cmd"),
    "dreamina": ("dreamina", "dreamina.exe", "dreamina.cmd"),
}


@dataclass
class ProbeResult:
    backend: str
    available: bool
    binary: str = ""
    hint: str = ""
    command: str = ""


def normalize_backend(raw: Any) -> str:
    key = str(raw or "").strip().lower()
    return _ALIASES.get(key, key)


def normalize_mode(raw: Any) -> str:
    s = str(raw or "").strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "explainer": "animated-explainer",
        "animated-explainer": "animated-explainer",
        "storytime": "storytime-animation",
        "storytime-animation": "storytime-animation",
        "drama": "cinematic-drama",
        "cinematic-drama": "cinematic-drama",
        "cinematicdrama": "cinematic-drama",
    }
    return aliases.get(s, s)


def which_binary(backend: str) -> str:
    names = _BINARIES.get(backend) or ()
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return ""


def probe_backend(backend: str) -> ProbeResult:
    name = normalize_backend(backend)
    if name == "lightai":
        try:
            from config import settings
            ok = bool(getattr(settings, "LIGHTAI_API_KEY", "") or "")
        except Exception:
            ok = False
        return ProbeResult(
            backend="lightai",
            available=ok,
            hint="" if ok else "配置 LIGHTAI_API_KEY 后才能用 LightAI 生视频。",
            command="gen_video backend=lightai",
        )
    if name not in ("libtv", "dreamina"):
        return ProbeResult(
            backend=name or "",
            available=False,
            hint=f"未知后端 {backend!r}，允许：{', '.join(ALLOWED_BACKENDS)}。",
            command=f"probe_backend backend={backend}",
        )
    binary = which_binary(name)
    if name == "libtv":
        hint = (
            "" if binary else
            "本机没有 libtv。请按 LibTV 官方方式安装并登录；"
            "未安装时停止，不会改打 LightAI。"
        )
        cmd = f"{binary or 'libtv'} version"
    else:
        hint = (
            "" if binary else
            "本机没有 dreamina。请安装即梦官方 CLI 并 `dreamina login`；"
            "未安装时停止，不会改打 LightAI。与 LightAI 即梦引擎不是同一条登录。"
        )
        cmd = f"{binary or 'dreamina'} version"
    return ProbeResult(
        backend=name,
        available=bool(binary),
        binary=binary,
        hint=hint,
        command=cmd,
    )


def load_video_brief(repo_path: str, slug: Optional[str] = None) -> Dict[str, Any]:
    if not repo_path:
        return {}
    found = find_existing_slug(repo_path, slug)
    if not found:
        return {}
    path = package_dir(repo_path, found) / "video_brief.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def resolve_backend(context: Dict[str, Any]) -> Tuple[str, str]:
    """返回 (backend, source)。source = user | brief | default。

    用户指定了非法名字也原样返回，由调用方报错，禁止改写成 lightai。
    """
    raw = context.get("backend")
    if raw not in (None, ""):
        return normalize_backend(raw), "user"
    repo = str(context.get("repo_path") or "")
    slug = str(context.get("work_slug") or context.get("slug") or "")
    brief = load_video_brief(repo, slug)
    if brief.get("backend"):
        return normalize_backend(brief.get("backend")), "brief"
    return "lightai", "default"


def resolve_mode(context: Dict[str, Any]) -> str:
    raw = context.get("mode")
    if raw not in (None, ""):
        return normalize_mode(raw)
    repo = str(context.get("repo_path") or "")
    slug = str(context.get("work_slug") or context.get("slug") or "")
    brief = load_video_brief(repo, slug)
    return normalize_mode(brief.get("mode") or "")


def apply_cost_lock(
    context: Dict[str, Any], *, duration: int, resolution: str,
) -> Tuple[int, str, Optional[str]]:
    """Drama 正式片段：720p、时长 ≤ 15s。返回 (duration, resolution, error)。

    只有 `allow_cost_unlock=true` 才允许偏离。失败不得改打其他分辨率。
    """
    if duration < 1:
        duration = 1
    if duration > 15:
        duration = 15
    res = str(resolution or "720p").strip() or "720p"
    mode = resolve_mode(context)
    if mode not in DRAMA_MODES:
        return duration, res, None
    unlock = bool(context.get("allow_cost_unlock"))
    model = str(context.get("model") or "").lower()
    if not unlock and "2.5" in model:
        return duration, res, (
            "Drama 成本锁：不主动升 Seedance 2.5。用户针对本任务二次确认后"
            "才能传 allow_cost_unlock=true。"
        )
    if not unlock and res.lower() not in ("720p", "720"):
        return duration, res, (
            f"Drama 成本锁：正式片段固定 720p，收到 {res}。"
            "用户针对本任务二次确认后才能传 allow_cost_unlock=true。"
        )
    if res.lower() == "720":
        res = "720p"
    return duration, res, None
