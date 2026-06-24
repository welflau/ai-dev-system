"""
OpenProjectAction — 打开已有项目（前端跳转）

用户说"打开 xxx 项目"/"进入 xxx"/"切换到 xxx"时调用。
不做任何后端操作，直接返回 action 让前端调 showProjectDetail()。
"""
from typing import Any, Dict
from actions.base import ActionBase, ActionResult


class OpenProjectAction(ActionBase):

    @property
    def name(self) -> str:
        return "open_project"

    @property
    def description(self) -> str:
        return "在前端打开/进入一个已有项目。用户说「打开 xxx 项目」「进入 xxx」「切换到 xxx 项目」时调用。"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "当用户想打开/进入/切换到一个已有项目时调用。"
                "直接触发前端跳转到该项目，无需用户再做任何操作。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "要打开的项目 ID（如 PRJ-xxx）。优先用 ID。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "项目名称（当只知道名称、不知道 ID 时填此字段）。",
                    },
                },
            },
        }

    async def run(self, params: Dict[str, Any]) -> ActionResult:
        from database import db

        project_id = (params.get("project_id") or "").strip()
        project_name = (params.get("project_name") or "").strip()

        # 按 ID 查
        if project_id:
            row = await db.fetch_one(
                "SELECT id, name FROM projects WHERE id = ?", (project_id,)
            )
        elif project_name:
            # 模糊匹配名称
            row = await db.fetch_one(
                "SELECT id, name FROM projects WHERE name LIKE ? ORDER BY created_at DESC LIMIT 1",
                (f"%{project_name}%",),
            )
        else:
            return ActionResult(success=False, error="请提供 project_id 或 project_name")

        if not row:
            name_hint = project_id or project_name
            return ActionResult(
                success=False,
                error=f"找不到项目「{name_hint}」，请确认项目名称是否正确。",
            )

        return ActionResult(
            success=True,
            data={
                "type": "open_project",
                "project_id": row["id"],
                "name": row["name"],
                "message": f"正在打开项目「{row['name']}」…",
            },
        )
