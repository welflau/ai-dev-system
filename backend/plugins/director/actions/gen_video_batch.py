"""批量生成：内部处理后续片段，LLM 只调一次。"""
from __future__ import annotations

from typing import Any, Dict, List

from actions.base import ActionBase, ActionResult
from plugins.director.actions.gen_video import GenVideoAction


class GenVideoBatchAction(ActionBase):
    available_for_traits = {"any_of": ["category:video", "pipeline:video"]}

    @property
    def name(self) -> str:
        return "gen_video_batch"

    @property
    def description(self) -> str:
        return (
            "按 shot_prompts 批量生成片段 2 及之后的视频。"
            "跳过已确认的片段 1。缺 Key 时整批停止，不改讲稿。"
        )

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "clips": {
                        "type": "array",
                        "description": "[{filename, prompt, duration?}]",
                        "items": {"type": "object"},
                    },
                    "work_slug": {"type": "string"},
                    "backend": {"type": "string"},
                    "aspect_ratio": {"type": "string"},
                    "resolution": {"type": "string"},
                },
                "required": ["clips"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        clips = context.get("clips") or []
        if not isinstance(clips, list) or not clips:
            return ActionResult(success=False, error="clips 不能为空")
        gen = GenVideoAction()
        results: List[Dict[str, Any]] = []
        for item in clips:
            if not isinstance(item, dict):
                continue
            filename = str(item.get("filename") or "")
            if filename in {"片段01.mp4", "clip01.mp4"}:
                continue
            sub = {
                **context,
                "prompt": item.get("prompt") or "",
                "filename": filename,
                "duration": item.get("duration") or context.get("duration") or 15,
            }
            one = await gen.run(sub)
            results.append({
                "filename": filename,
                "success": one.success,
                "error": one.error,
                "data": one.data,
            })
            if not one.success and (one.data or {}).get("env_missing"):
                return ActionResult(
                    success=False,
                    error=one.error,
                    data={
                        "env_missing": True,
                        "command": str((one.data or {}).get("command") or "gen_video_batch"),
                        "task_id": (one.data or {}).get("task_id") or "",
                        "results": results,
                    },
                )
        failed = [r for r in results if not r["success"]]
        return ActionResult(
            success=not failed,
            error=("部分片段失败" if failed else ""),
            data={
                "command": "gen_video_batch",
                "results": results,
            },
            message=f"批量 {len(results)} 段，失败 {len(failed)}",
        )
