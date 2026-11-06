"""确定性 Mode 资产自检。缺口时失败，禁止发人审卡。"""
from __future__ import annotations

from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from plugins.director.mode_check import check_gate, check_mode_assets
from plugins.director.work_package import find_existing_slug


class CheckModeAssetsAction(ActionBase):
    available_for_traits = {"any_of": ["category:video", "pipeline:video"]}

    @property
    def name(self) -> str:
        return "check_mode_assets"

    @property
    def description(self) -> str:
        return (
            "按 Mode 检查工作包资产是否齐（Drama：场景卡、人物参考、音色计划、连续性矩阵）。"
            "有缺口时失败，不要调用 confirm_video_gate。"
        )

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "work_slug": {"type": "string"},
                    "mode": {"type": "string"},
                    "gate": {
                        "type": "string",
                        "description": "brief / script / visual / clip；缺省按 visual 全量",
                    },
                },
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        repo = str(context.get("repo_path") or "")
        slug = str(context.get("work_slug") or context.get("slug") or "")
        slug = slug or (find_existing_slug(repo) or "")
        mode = str(context.get("mode") or "")
        gate = str(context.get("gate") or "visual").strip().lower()
        if gate in ("", "visual", "all"):
            report = check_mode_assets(repo, slug, mode)
        else:
            report = check_gate(gate, repo, slug, mode)
        gaps = report.get("gaps") or []
        data = {
            "type": "check_mode_assets",
            "ok": bool(report.get("ok")),
            "mode": report.get("mode") or mode,
            "slug": report.get("slug") or slug,
            "gaps": gaps,
            "command": f"check_mode_assets gate={gate} slug={slug}",
        }
        if report.get("ok"):
            return ActionResult(success=True, data=data, message="Mode 资产检查通过")
        lines = "；".join(g.get("message") or g.get("code") for g in gaps[:8])
        return ActionResult(
            success=False,
            error=f"资产未齐，不能进人审：{lines}",
            data=data,
        )
