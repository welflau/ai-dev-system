"""单段视频生成。阻塞到下载完成；无 Key 时 env_missing，不写空文件。"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

from actions.base import ActionBase, ActionResult
from plugins.director.work_package import find_existing_slug, package_dir

logger = logging.getLogger("plugins.director.gen_video")

_SAFE_NAME = re.compile(r"^(片段\d{2}|clip\d{2}|[A-Za-z0-9_.-]+)\.mp4$")
_ASPECT = ("16:9", "9:16", "1:1")
# 后端真源只有一份：plugins/director/backends.py::ALLOWED_BACKENDS
# （由系统公共层 cloud_video.ALLOWED_PROVIDERS + 本插件 CLI 后端组成）。
# 此前本文件另定义过一份重复的后端字面量（含 jimeng），现已消除。
from plugins.director.backends import ALLOWED_BACKENDS as _BACKENDS
_ENGINES = ("kling", "jimeng", "keling")


async def _dir_record(provider: str, prompt: str, context: Dict[str, Any], engine: str = "") -> str:
    """记一条 director 私有生视频任务（CLI 后端 / LightAI 直连）为 running。

    云端分支（_run_cloud_provider → cloud_video.generate_video_with_provider）已统一记录，
    这里只覆盖不走 dispatch 的两条路径，避免双重计数。
    """
    try:
        from ai_gen_tasks import record_task
        return await record_task(
            kind="video", provider=provider, status="running",
            prompt=prompt, engine=engine, source="director",
            project_id=str(context.get("project_id") or ""),
            ticket_id=str(context.get("ticket_id") or ""),
        )
    except Exception:
        return ""


async def _dir_finish(aigen_id: str, status: str, **fields) -> None:
    if not aigen_id:
        return
    try:
        from ai_gen_tasks import update_task
        await update_task(aigen_id, status=status, **fields)
    except Exception:
        pass


class GenVideoAction(ActionBase):
    available_for_traits = {"any_of": ["category:video", "pipeline:video"]}

    @property
    def name(self) -> str:
        return "gen_video"

    @property
    def description(self) -> str:
        return (
            "生成一段视频并下载到 works/<slug>/video/。"
            "会阻塞直到下载完成，不要为同一段重复调用。"
            "缺 API Key 或 CLI 时失败，不要改讲稿。"
        )

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "filename": {"type": "string", "description": "如 片段01.mp4"},
                    "duration": {"type": "integer", "description": "秒，默认 15，最大 15"},
                    "aspect_ratio": {"type": "string", "enum": list(_ASPECT)},
                    "resolution": {"type": "string", "description": "默认 720p"},
                    "backend": {"type": "string", "enum": list(_BACKENDS),
                                "description": "lightai / libtv / dreamina。指定后失败不换后端"},
                    "engine": {"type": "string", "description": "lightai 时 kling 或 jimeng"},
                    "allow_cost_unlock": {"type": "boolean", "description": "Drama 偏离 720p 需用户二次确认"},
                    "libtv_project": {"type": "string"},
                    "session": {"type": "string", "description": "dreamina session id"},
                    "work_slug": {"type": "string"},
                    "mode": {"type": "string", "description": "text2video / image2video / multimodal"},
                    "ref_images": {"type": "array", "items": {"type": "string"}},
                    "ref_audio": {"type": "array", "items": {"type": "string"}},
                    "first_frame": {"type": "string"},
                    "last_frame": {"type": "string"},
                    "sound": {"type": "boolean"},
                },
                "required": ["prompt", "filename"],
            },
        }

    @staticmethod
    def _safe_filename(raw: str) -> Optional[str]:
        name = (raw or "").strip()
        if not name or "/" in name or "\\" in name or ".." in name:
            return None
        if not _SAFE_NAME.match(name):
            return None
        return name

    def _out_dir(self, context: Dict[str, Any]) -> Optional[Path]:
        repo = str(context.get("repo_path") or "")
        if not repo:
            return None
        slug = str(context.get("work_slug") or context.get("slug") or "")
        slug = slug or find_existing_slug(repo) or ""
        if not slug:
            return None
        video = package_dir(repo, slug) / "video"
        video.mkdir(parents=True, exist_ok=True)
        return video

    @staticmethod
    async def _trace(context: Dict[str, Any], command: str, cwd: str, status: str) -> str:
        try:
            from command_log import record_traced_command
            return await record_traced_command(
                source="director",
                tool="gen_video",
                command=command,
                cwd=cwd,
                status=status,
                ticket_id=str(context.get("ticket_id") or ""),
                requirement_id=str(context.get("requirement_id") or ""),
                project_id=str(context.get("project_id") or ""),
                agent_type=str(context.get("agent_type") or "SkillAgent"),
            )
        except Exception as e:
            logger.debug("record_traced_command 跳过: %s", e)
            return ""

    @staticmethod
    def _local_media(raw: str, repo: str) -> str:
        s = str(raw or "").strip()
        if not s or s.startswith("http://") or s.startswith("https://"):
            return ""
        p = Path(s)
        if p.is_file():
            return str(p)
        if repo:
            cand = Path(repo) / s.replace("\\", "/")
            if cand.is_file():
                return str(cand)
        return ""

    async def _run_cli_backend(
        self,
        context: Dict[str, Any],
        *,
        dest: Path,
        out_dir: Path,
        filename: str,
        prompt: str,
        duration: int,
        ratio: str,
        resolution: str,
        backend: str,
        command: str,
        probe,
    ) -> ActionResult:
        if not probe.available:
            task_id = await self._trace(context, probe.command or command, str(out_dir), "error")
            return ActionResult(
                success=False,
                error=probe.hint or f"后端 {backend} 不可用",
                data={
                    "env_missing": True,
                    "backend": backend,
                    "command": probe.command or command,
                    "task_id": task_id,
                },
            )

        repo = str(context.get("repo_path") or "")
        from plugins.director.lightai_video import _as_list
        images, missing = [], []
        for raw in _as_list(context.get("ref_images")):
            loc = self._local_media(raw, repo)
            if loc:
                images.append(loc)
            elif raw:
                missing.append(raw)
        first = self._local_media(str(context.get("first_frame") or ""), repo)
        if first:
            images.insert(0, first)
        audios = []
        for raw in _as_list(context.get("ref_audio")):
            loc = self._local_media(raw, repo)
            if loc:
                audios.append(loc)
            elif raw:
                missing.append(raw)
        if missing:
            task_id = await self._trace(context, command, str(out_dir), "error")
            return ActionResult(
                success=False,
                error=("CLI 后端只接受本地参考文件，无法解析："
                       + ", ".join(missing[:6])
                       + "。停止，不改打 LightAI。"),
                data={"backend": backend, "command": command, "task_id": task_id},
            )

        aigen_id = await _dir_record(backend, prompt, context)
        if backend == "libtv":
            from plugins.director.cli_video import generate_libtv
            ok, data, err = await generate_libtv(
                dest=dest,
                prompt=prompt,
                project_uuid=str(
                    context.get("libtv_project") or context.get("project_uuid") or ""
                ),
            )
        else:
            from plugins.director.cli_video import generate_dreamina
            ok, data, err = await generate_dreamina(
                dest=dest,
                prompt=prompt,
                duration=duration,
                ratio=ratio,
                resolution=resolution,
                ref_images=images,
                ref_audio=audios,
                session=str(context.get("session") or ""),
                model=str(context.get("model") or "seedance2.0fast"),
            )
        await _dir_finish(aigen_id, "done" if ok else "failed",
                          error="" if ok else str(err or "CLI 生成失败")[:400],
                          result_path=str(dest) if ok else "")

        data = dict(data or {})
        data.setdefault("command", command)
        data.setdefault("backend", backend)
        data["filename"] = filename
        status = "success" if ok else "error"
        traced = await self._trace(context, str(data.get("command") or command), str(out_dir), status)
        data["task_id"] = data.get("task_id") or traced
        if not ok:
            data.setdefault("env_missing", bool(data.get("env_missing")))
            return ActionResult(success=False, error=err or f"{backend} 生成失败", data=data)

        rel = ""
        try:
            rel = str(dest.relative_to(Path(repo))) if repo else str(dest)
        except ValueError:
            rel = str(dest)
        data["path"] = str(dest)
        data["rel_path"] = rel.replace("\\", "/")
        data["bytes"] = dest.stat().st_size
        return ActionResult(success=True, data=data, message=f"已生成 {filename}（{dest.stat().st_size} bytes）")

    async def _run_cloud_provider(
        self,
        context: Dict[str, Any],
        *,
        dest: Path,
        out_dir: Path,
        filename: str,
        prompt: str,
        duration: int,
        ratio: str,
        resolution: str,
        backend: str,
        command: str,
        probe,
    ) -> ActionResult:
        """系统公共云端 provider（minimax_h3 等）：经 cloud_video 统一入口调用。

        公共层只抛分层异常，env_missing / command / task_id 分流仍由本 Action 负责
        （准入规范约束 2/3）。原有 lightai / libtv / dreamina 分支完全不动。
        """
        if not probe.available:
            task_id = await self._trace(context, probe.command or command, str(out_dir), "error")
            return ActionResult(
                success=False,
                error=probe.hint or f"云端后端 {backend} 不可用",
                data={
                    "env_missing": True,
                    "backend": backend,
                    "command": probe.command or command,
                    "task_id": task_id,
                },
            )

        from cloud_video import CloudVideoError, CloudVideoUnavailable
        from cloud_video import client as cloud_client

        # director 的 ratio/resolution 是 "16:9"/"720p"，鼠鼠要整串与三档编码
        _RATIO_MAP = {
            "16:9": "16:9 (Widescreen)", "9:16": "9:16 (Portrait Widescreen)",
            "1:1": "1:1 (Square)", "4:3": "4:3 (Standard)",
            "3:4": "3:4 (Portrait Standard)", "21:9": "21:9 (Ultrawide)",
        }
        _RES_MAP = {"480p": "0.4", "768p": "1", "720p": "1", "1080p": "2"}
        aspect = _RATIO_MAP.get(ratio, "16:9 (Widescreen)")
        res = _RES_MAP.get(resolution.lower(), "1")

        try:
            result = await cloud_client.generate_video_with_provider(
                backend,
                prompt=prompt,
                dest=dest,
                duration=min(duration, 15),
                aspect_ratio=aspect,
                resolution=res,
            )
        except CloudVideoUnavailable as e:
            task_id = await self._trace(context, command, str(out_dir), "error")
            return ActionResult(
                success=False, error=str(e),
                data={"env_missing": True, "backend": backend,
                      "command": command, "task_id": task_id},
            )
        except CloudVideoError as e:
            task_id = await self._trace(context, command, str(out_dir), "error")
            return ActionResult(
                success=False, error=str(e),
                data={"env_missing": False, "backend": backend,
                      "command": command, "task_id": task_id},
            )

        task_id = await self._trace(context, command, str(out_dir), "success")
        repo = str(context.get("repo_path") or "")
        rel = ""
        try:
            rel = str(dest.relative_to(Path(repo))) if repo else str(dest)
        except ValueError:
            rel = str(dest)
        return ActionResult(
            success=True,
            data={
                "path": str(dest),
                "rel_path": rel.replace("\\", "/"),
                "filename": filename,
                "task_id": task_id,
                "backend": backend,
                "provider": result.get("provider", backend),
                "vc_task_id": result.get("task_id", ""),
                "command": command,
                "url": result.get("url", ""),
                "bytes": result.get("bytes") or dest.stat().st_size,
                "downloaded": bool(result.get("downloaded")),
            },
            message=f"已生成 {filename}（云端 {backend}）",
        )

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        prompt = str(context.get("prompt") or "").strip()
        if not prompt:
            return ActionResult(success=False, error="prompt 不能为空")
        filename = self._safe_filename(str(context.get("filename") or ""))
        if not filename:
            return ActionResult(
                success=False,
                error=(f"filename 非法: {context.get('filename')!r}。"
                       "只能是不含路径的 mp4，如 片段01.mp4"),
            )
        from plugins.director.backends import (
            ALLOWED_BACKENDS,
            apply_cost_lock,
            probe_backend,
            resolve_backend,
        )

        duration = int(context.get("duration") or 15)
        ratio = str(context.get("aspect_ratio") or "16:9")
        if ratio not in _ASPECT:
            ratio = "16:9"
        resolution = str(context.get("resolution") or "720p")
        duration, resolution, lock_err = apply_cost_lock(
            context, duration=duration, resolution=resolution,
        )
        if lock_err:
            return ActionResult(success=False, error=lock_err, data={"cost_lock": True})

        backend, backend_src = resolve_backend(context)
        if backend not in ALLOWED_BACKENDS:
            return ActionResult(
                success=False,
                error=(f"未知后端 {backend!r}（来源 {backend_src}）。"
                       f"允许：{', '.join(ALLOWED_BACKENDS)}。不会改打 lightai。"),
                data={"env_missing": False, "backend": backend},
            )
        engine = str(context.get("engine") or "kling").lower()
        if engine not in _ENGINES:
            engine = "kling"

        out_dir = self._out_dir(context)
        if out_dir is None:
            return ActionResult(
                success=False,
                error="无法定位 works/<slug>/video/，先调用 init_work_package",
            )
        dest = out_dir / filename
        command = (
            f"gen_video backend={backend} engine={engine} file={filename} "
            f"duration={duration} ratio={ratio} resolution={resolution}"
        )
        probe = probe_backend(backend)

        # 系统公共云端 provider（minimax_h3 等）：新增的可选后端分支，
        # 走 cloud_video 统一入口。原有 lightai / libtv / dreamina 分支不变。
        from cloud_video import ALLOWED_PROVIDERS as _CLOUD_PROVIDERS
        if backend in _CLOUD_PROVIDERS and backend != "lightai":
            return await self._run_cloud_provider(
                context, dest=dest, out_dir=out_dir, filename=filename,
                prompt=prompt, duration=duration, ratio=ratio,
                resolution=resolution, backend=backend, command=command,
                probe=probe,
            )

        if backend != "lightai":
            return await self._run_cli_backend(
                context, dest=dest, out_dir=out_dir, filename=filename,
                prompt=prompt, duration=duration, ratio=ratio,
                resolution=resolution, backend=backend, command=command,
                probe=probe,
            )

        from config import settings
        if not settings.LIGHTAI_API_KEY:
            task_id = await self._trace(context, command, str(out_dir), "error")
            return ActionResult(
                success=False,
                error="LIGHTAI_API_KEY 未配置，无法生视频",
                data={"env_missing": True, "command": command, "task_id": task_id},
            )

        from plugins.director.lightai_video import (
            _as_list,
            create_and_poll_video,
            download_url,
            resolve_media_url,
        )

        repo = str(context.get("repo_path") or "")
        ref_images = []
        for raw in _as_list(context.get("ref_images")):
            url = await resolve_media_url(raw, repo)
            if url:
                ref_images.append(url)
        first = await resolve_media_url(str(context.get("first_frame") or ""), repo)
        last = await resolve_media_url(str(context.get("last_frame") or ""), repo)
        audios = _as_list(context.get("ref_audio"))
        ref_audio = await resolve_media_url(audios[0], repo) if audios else ""
        sound = context.get("sound")
        if sound is None:
            sound = bool(ref_audio)

        req = {
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": ratio,
            "resolution": resolution,
            "engine": engine,
            "ref_images": ref_images,
            "first_frame": first,
            "last_frame": last,
            "ref_audio": ref_audio,
            "sound": bool(sound),
        }
        logger.info("🎬 gen_video 开始 engine=%s file=%s prompt=%.60s", engine, filename, prompt)
        aigen_id = await _dir_record("lightai", prompt, context, engine=engine)
        task_id, url, err = await create_and_poll_video(req)
        if not task_id or not url:
            await _dir_finish(aigen_id, "failed", error=str(err or "LightAI 视频生成失败")[:400])
            traced = await self._trace(context, command, str(out_dir), "error")
            return ActionResult(
                success=False,
                error=err or "LightAI 视频生成失败",
                data={
                    "env_missing": False,
                    "backend": backend,
                    "engine": engine,
                    "command": command,
                    "task_id": task_id or traced,
                    "planned_path": str(dest),
                },
            )

        ok, dl_err = await download_url(url, dest)
        if not ok:
            await _dir_finish(aigen_id, "failed", error=str(dl_err or "下载失败")[:400],
                              result_url=url)
            traced = await self._trace(context, command, str(out_dir), "error")
            return ActionResult(
                success=False,
                error=dl_err or "下载失败",
                data={
                    "env_missing": False,
                    "backend": backend,
                    "command": command,
                    "task_id": task_id or traced,
                    "url": url,
                    "planned_path": str(dest),
                },
            )

        await _dir_finish(aigen_id, "done", external_task_id=str(task_id or ""),
                          result_url=url, result_path=str(dest))
        traced = await self._trace(context, command, str(out_dir), "success")
        rel = ""
        try:
            rel = str(dest.relative_to(Path(repo))) if repo else str(dest)
        except ValueError:
            rel = str(dest)
        pid = str(context.get("project_id") or "")
        public_url = (
            f"/api/projects/{pid}/git/file-raw?path={rel.replace(chr(92), '/')}"
            if pid and rel else ""
        )
        return ActionResult(
            success=True,
            data={
                "path": str(dest),
                "rel_path": rel.replace("\\", "/"),
                "filename": filename,
                "task_id": task_id or traced,
                "backend": backend,
                "engine": engine,
                "model": "kling-v3" if engine != "jimeng" else "doubao-seedance-1-5-pro-251215",
                "command": command,
                "url": url,
                "public_url": public_url,
                "bytes": dest.stat().st_size,
            },
            message=f"已生成 {filename}（{dest.stat().st_size} bytes）",
        )
