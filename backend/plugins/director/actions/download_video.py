"""按任务 ID 或资源 URL 补下载。没有 URL 时不写空 mp4。"""
from __future__ import annotations

from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from plugins.director.actions.gen_video import GenVideoAction


class DownloadVideoAction(ActionBase):
    available_for_traits = {"any_of": ["category:video", "pipeline:video"]}

    @property
    def name(self) -> str:
        return "download_video"

    @property
    def description(self) -> str:
        return "平台已成功但本地文件丢失时，按 url 或 task_id 补下载到 works/<slug>/video/。"

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "filename": {"type": "string"},
                    "work_slug": {"type": "string"},
                    "url": {"type": "string", "description": "若已知资源 URL 可直传"},
                },
                "required": ["filename"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        gen = GenVideoAction()
        filename = gen._safe_filename(str(context.get("filename") or ""))
        if not filename:
            return ActionResult(success=False, error="filename 非法")
        out_dir = gen._out_dir(context)
        if out_dir is None:
            return ActionResult(success=False, error="无法定位 works/<slug>/video/")
        dest = out_dir / filename
        url = str(context.get("url") or "").strip()
        task_id = str(context.get("task_id") or "").strip()
        command = f"download_video file={filename}"

        if not url and task_id:
            from plugins.director.lightai_video import _poll_task
            url, err = await _poll_task(task_id, interval=5, max_wait=120)
            if not url:
                return ActionResult(
                    success=False,
                    error=err or "没有资源 URL，不能写空 mp4",
                    data={"command": command, "task_id": task_id},
                )
        if not url:
            return ActionResult(
                success=False,
                error="没有资源 URL，不能写空 mp4",
                data={"command": command, "task_id": task_id},
            )

        from plugins.director.lightai_video import download_url
        ok, err = await download_url(url, dest)
        if not ok:
            return ActionResult(
                success=False,
                error=err,
                data={"command": command, "task_id": task_id, "url": url},
            )
        return ActionResult(
            success=True,
            data={
                "path": str(dest),
                "filename": filename,
                "command": command,
                "task_id": task_id,
                "url": url,
                "bytes": dest.stat().st_size,
            },
            message=f"已补下载 {filename}",
        )
