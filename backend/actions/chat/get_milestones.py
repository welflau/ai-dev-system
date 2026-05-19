"""GetMilestonesAction — 查询项目里程碑"""
import logging
from typing import Any, Dict
from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.get_milestones")

_STATUS_ICONS = {"pending": "⏳", "in_progress": "🔄", "completed": "✅", "blocked": "🚫"}


class GetMilestonesAction(ActionBase):

    @property
    def name(self) -> str:
        return "get_milestones"

    @property
    def description(self) -> str:
        return "查询项目里程碑列表（进度、计划时间、完成状态）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "查询当前项目的里程碑列表。\n"
                "返回：标题、状态、计划时间、进度、描述等。\n"
                "适合回答「项目进度如何」「下一个里程碑是什么」等问题。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "状态过滤：pending / in_progress / completed / all（默认 all）",
                        "enum": ["pending", "in_progress", "completed", "blocked", "all"],
                    },
                },
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="需要在项目内使用")

        status = context.get("status", "all")
        try:
            from database import db
            conditions = ["project_id = ?"]
            params: list = [project_id]
            if status and status != "all":
                conditions.append("status = ?")
                params.append(status)

            rows = await db.fetch_all(
                f"""SELECT title, description, status, progress,
                           planned_start, planned_end, actual_end, sort_order
                    FROM milestones WHERE {' AND '.join(conditions)}
                    ORDER BY sort_order ASC, planned_start ASC""",
                tuple(params),
            )
            if not rows:
                return ActionResult(success=True, message="没有找到里程碑",
                                    data={"type": "milestones", "milestones": [], "total": 0})

            lines = [f"共 {len(rows)} 个里程碑：\n"]
            items = []
            for r in rows:
                icon = _STATUS_ICONS.get(r["status"], "❓")
                prog = f" {r['progress']}%" if r["progress"] else ""
                date = r["planned_end"] or r["actual_end"] or ""
                date = date[:10] if date else ""
                lines.append(f"• {icon} **{r['title']}**{prog}（{date}）")
                if r["description"]:
                    lines.append(f"  {r['description'][:80]}")
                items.append(dict(r))

            return ActionResult(success=True, message="\n".join(lines),
                                data={"type": "milestones", "milestones": items, "total": len(items)})
        except Exception as e:
            logger.error("get_milestones 失败: %s", e)
            return ActionResult(success=False, error=str(e))
