"""VideoClaw 单次生图 / 生视频 —— 直接调 VC 现成的 sandbox 接口。

契约：VC api/routers/sandbox.py:294-440（t2i / i2i / video）
  - 同步接口，HTTP 挂到生成完成才返回；失败也是 HTTP 200 + {success:false}
  - 生图取 result[]，生视频取 video_path（result 是会过期的远端 URL）
  - VC 没有纯文生视频，video 必须给首帧图；本 Action 在缺 image 时自动先 t2i

准入约束（docs/20261023_01_插件套件准入规范与五道约束.md）：
- 环境缺失 → env_missing=True / success=False，绝不 *_failed 触发 DevAgent 返工
- data["command"] 必须是 str；外部调用走 record_traced_command 落时间轴
- Action 名 vc_ 前缀：registry 全局 name 唯一，不能撞 gen_image / gen_video
"""
from __future__ import annotations

import logging
import re
import shlex
from pathlib import Path
from typing import Any, Dict, Optional

from actions.base import ActionBase, ActionResult
from config import settings

from plugins.videoclaw import videoclaw_client as vc

logger = logging.getLogger("plugins.videoclaw.vc_media")

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4")


def _safe_filename(raw: str, default_ext: str) -> str:
    s = str(raw or "").strip()
    if not s or "/" in s or "\\" in s or ".." in s:
        s = ""
    if s and not _SAFE_NAME.match(s):
        s = ""
    if not s:
        s = f"vc_media{default_ext}"
    if not s.lower().endswith(default_ext):
        s += default_ext
    return s


def _out_dir(context: Dict[str, Any], subdir: str) -> Optional[Path]:
    """产物落 works/<slug>/videoclaw/<subdir>/；没有 repo_path 则不落盘。"""
    repo = str(context.get("repo_path") or "").strip()
    if not repo:
        return None
    slug = str(context.get("work_slug") or context.get("slug") or "videoclaw").strip() or "videoclaw"
    if not _SAFE_NAME.match(slug):
        slug = "videoclaw"
    d = Path(repo) / "works" / slug / "videoclaw" / subdir
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _trace(context: Dict[str, Any], tool: str, command: str, status: str) -> str:
    try:
        from command_log import record_traced_command
        return await record_traced_command(
            source="videoclaw",
            tool=tool,
            command=command,
            status=status,
            ticket_id=str(context.get("ticket_id") or ""),
            requirement_id=str(context.get("requirement_id") or ""),
            project_id=str(context.get("project_id") or ""),
            agent_type=str(context.get("agent_type") or "SkillAgent"),
        )
    except Exception as e:
        logger.debug("record_traced_command 跳过: %s", e)
        return ""


def _blocked(tool: str, command: str, task_id: str, error: str) -> ActionResult:
    return ActionResult(
        success=False,
        error=error,
        data={"env_missing": True, "command": command, "task_id": task_id, "tool": tool},
    )


def _failed(tool: str, command: str, task_id: str, error: str, **extra) -> ActionResult:
    return ActionResult(
        success=False,
        error=error,
        data={"env_missing": False, "command": command, "task_id": task_id, "tool": tool, **extra},
    )


async def _prepare(context: Dict[str, Any], tool: str, command: str):
    """返回 (cfg, models, task_id, blocked_result)；blocked_result 非 None 时直接返回它。"""
    if not settings.VIDEOCLAW_ENABLED:
        return None, None, "", _blocked(tool, command, "", "VIDEOCLAW_ENABLED=false，VideoClaw sidecar 未启用")
    if not await vc.health():
        task_id = await _trace(context, tool, command, "error")
        return None, None, task_id, _blocked(
            tool, command, task_id, f"VideoClaw sidecar 不可达 {settings.VIDEOCLAW_BASE_URL}，请先启动服务"
        )
    try:
        cfg = await vc.get_config()
        models = vc.resolve_sandbox_models(cfg)
    except vc.VideoClawUnavailable as e:
        task_id = await _trace(context, tool, command, "error")
        return None, None, task_id, _blocked(tool, command, task_id, str(e))
    except vc.VideoClawError as e:
        task_id = await _trace(context, tool, command, "error")
        return None, None, task_id, _failed(tool, command, task_id, str(e))
    return cfg, models, "", None


async def _save(rel: str, out_dir: Optional[Path], filename: str) -> Dict[str, Any]:
    """把 VC 产物下载到 works/；返回 data 片段。out_dir 为 None 时只给远端 URL。"""
    norm = vc.normalize_media_rel(rel)
    url = vc.media_url(norm) if norm and not norm.startswith("http") else norm
    info: Dict[str, Any] = {"vc_rel": norm, "url": url, "downloaded": False}
    if out_dir is None:
        return info
    dest = out_dir / filename
    size = await vc.download_product(norm or url, dest)
    info.update({
        "downloaded": True,
        "path": str(dest),
        "filename": filename,
        "bytes": size,
    })
    return info


class VCGenImageAction(ActionBase):
    available_for_traits = {"any_of": ["category:video", "pipeline:video"]}

    @property
    def name(self) -> str:
        return "vc_gen_image"

    @property
    def description(self) -> str:
        return (
            "用 VideoClaw 单次接口生成一张图（文生图；给 reference_image 则图生图），"
            "产物下载到 works/<slug>/videoclaw/image/。缺服务时 env_missing → blocked。"
        )

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "reference_image": {"type": "string", "description": "http(s)/本地路径/VC /code/ URL，给了走 i2i"},
                    "model": {"type": "string", "description": "留空则从 VC /api/config 动态取"},
                    "ratio": {"type": "string", "enum": list(_RATIOS)},
                    "filename": {"type": "string", "description": "如 cover.png"},
                },
                "required": ["prompt"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        tool = "vc_gen_image"
        prompt = str(context.get("prompt") or "").strip()
        ref = str(context.get("reference_image") or "").strip()
        ratio = str(context.get("ratio") or "16:9")
        if ratio not in _RATIOS:
            ratio = "16:9"
        filename = _safe_filename(str(context.get("filename") or ""), ".png")
        command = (
            f"{tool} prompt={shlex.quote(prompt)} ratio={ratio} "
            f"ref={shlex.quote(ref or '-')} file={shlex.quote(filename)}"
        )
        if not prompt:
            return _failed(tool, command, "", "prompt 不能为空")

        cfg, models, task_id, blocked = await _prepare(context, tool, command)
        if blocked is not None:
            return blocked
        model = str(context.get("model") or models["image_t2i"])
        if ref and not models.get("image_it2i"):
            return _failed(tool, command, task_id, "VC config 缺 image_it2i 模型，无法图生图")

        out_dir = _out_dir(context, "image")
        try:
            if ref:
                data = await vc.sandbox_i2i(
                    model=models.get("image_it2i") or model, prompt=prompt,
                    image=ref, ratio=ratio,
                )
            else:
                data = await vc.sandbox_t2i(model=model, prompt=prompt, ratio=ratio)
            paths = data.get("result") or []
            if not isinstance(paths, list) or not paths:
                raise vc.VideoClawError("VC 生图未返回产物路径（result 为空）")
            saved = await _save(str(paths[0]), out_dir, filename)
        except vc.VideoClawUnavailable as e:
            tid = await _trace(context, tool, command, "error")
            return _blocked(tool, command, tid, str(e))
        except vc.VideoClawError as e:
            tid = await _trace(context, tool, command, "error")
            return _failed(tool, command, tid, str(e))

        tid = await _trace(context, tool, command, "success")
        return ActionResult(
            success=True,
            data={
                "env_missing": False,
                "command": command,
                "task_id": tid,
                "tool": tool,
                "model": model,
                "record_id": data.get("record_id", ""),
                **saved,
            },
            message=f"已生成 {filename}" if saved["downloaded"] else "已生成（未提供 repo_path，仅返回 VC URL）",
        )


class VCGenVideoAction(ActionBase):
    available_for_traits = {"any_of": ["category:video", "pipeline:video"]}

    @property
    def name(self) -> str:
        return "vc_gen_video"

    @property
    def description(self) -> str:
        return (
            "用 VideoClaw 单次接口生成一段视频（图生视频）。VC 没有纯文生视频："
            "未给 image 时会先用同一 prompt 自动 t2i 出首帧（两次付费调用）。"
            "产物下载到 works/<slug>/videoclaw/video/。缺服务时 env_missing → blocked。"
        )

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "image": {"type": "string", "description": "首帧图 http(s)/本地路径；留空则自动 t2i 生成"},
                    "model": {"type": "string", "description": "留空则从 VC /api/config 动态取"},
                    "ratio": {"type": "string", "enum": list(_RATIOS)},
                    "resolution": {"type": "string", "description": "默认 720P"},
                    "duration": {"type": "integer", "description": "秒，默认 5"},
                    "filename": {"type": "string", "description": "如 clip01.mp4"},
                },
                "required": ["prompt"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        tool = "vc_gen_video"
        prompt = str(context.get("prompt") or "").strip()
        image = str(context.get("image") or "").strip()
        ratio = str(context.get("ratio") or "16:9")
        if ratio not in _RATIOS:
            ratio = "16:9"
        resolution = str(context.get("resolution") or "720P")
        try:
            duration = max(1, min(int(context.get("duration") or 5), 15))
        except (TypeError, ValueError):
            duration = 5
        filename = _safe_filename(str(context.get("filename") or ""), ".mp4")
        command = (
            f"{tool} prompt={shlex.quote(prompt)} ratio={ratio} "
            f"resolution={shlex.quote(resolution)} duration={duration} "
            f"image={shlex.quote(image or 'auto-t2i')} file={shlex.quote(filename)}"
        )
        if not prompt:
            return _failed(tool, command, "", "prompt 不能为空")

        cfg, models, task_id, blocked = await _prepare(context, tool, command)
        if blocked is not None:
            return blocked
        model = str(context.get("model") or models["video"])
        out_dir = _out_dir(context, "video")
        auto_frame = ""

        try:
            # VC 的 video provider 全部要求首帧图（models/video_dashscope.py:257）。
            # 没给就自动先 t2i，并把产物拼成 VC 自己可访问的 /code/ URL 传回去。
            if not image:
                frame = await vc.sandbox_t2i(
                    model=models["image_t2i"], prompt=prompt, ratio=ratio,
                )
                frames = frame.get("result") or []
                if not isinstance(frames, list) or not frames:
                    raise vc.VideoClawError("自动首帧 t2i 未返回产物路径")
                auto_frame = vc.normalize_media_rel(str(frames[0]))
                image = vc.media_url(auto_frame)

            data = await vc.sandbox_video(
                model=model, prompt=prompt, image=image, ratio=ratio,
                resolution=resolution, duration=duration,
            )
            # result 是远端过期 URL，产物必须取 video_path
            rel = data.get("video_path") or data.get("result") or ""
            if not rel:
                raise vc.VideoClawError("VC 生视频未返回 video_path / result")
            saved = await _save(str(rel), out_dir, filename)
        except vc.VideoClawUnavailable as e:
            tid = await _trace(context, tool, command, "error")
            return _blocked(tool, command, tid, str(e))
        except vc.VideoClawError as e:
            tid = await _trace(context, tool, command, "error")
            return _failed(tool, command, tid, str(e), auto_frame=auto_frame)

        tid = await _trace(context, tool, command, "success")
        return ActionResult(
            success=True,
            data={
                "env_missing": False,
                "command": command,
                "task_id": tid,
                "tool": tool,
                "model": model,
                "record_id": data.get("record_id", ""),
                "auto_first_frame": auto_frame,
                **saved,
            },
            message=f"已生成 {filename}" if saved["downloaded"] else "已生成（未提供 repo_path，仅返回 VC URL）",
        )
