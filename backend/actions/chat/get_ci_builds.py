"""
GetCIBuildsAction — 查询项目 CI 构建记录
"""
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.get_ci_builds")

_STATUS_ICONS = {
    "success": "✅", "failed": "❌", "running": "🔄",
    "cancelled": "⛔", "pending": "⏳",
}


class GetCIBuildsAction(ActionBase):

    @property
    def name(self) -> str:
        return "get_ci_builds"

    @property
    def description(self) -> str:
        return "查询项目 CI 构建记录（编译结果、错误信息、耗时）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "查询当前项目的 CI 构建历史记录。\n"
                "返回：构建状态、分支、触发原因、错误信息、开始/完成时间等。\n"
                "适合回答「最近编译结果如何」「有哪些构建失败」等问题。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "状态过滤：success / failed / running / all（默认 all）",
                        "enum": ["success", "failed", "running", "cancelled", "all"],
                    },
                    "build_type": {
                        "type": "string",
                        "description": "构建类型过滤：compile / playtest / package / all（默认 all）",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量，默认 10",
                    },
                },
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="需要在项目内使用")

        status = context.get("status", "all")
        build_type = (context.get("build_type") or "all").strip()
        limit = min(int(context.get("limit") or 10), 30)

        try:
            from database import db

            conditions = ["project_id = ?"]
            params: list = [project_id]

            if status and status != "all":
                conditions.append("status = ?")
                params.append(status)
            if build_type and build_type != "all":
                conditions.append("build_type = ?")
                params.append(build_type)

            where = " AND ".join(conditions)
            rows = await db.fetch_all(
                f"""SELECT id, build_type, branch, status, trigger,
                           commit_hash, error_message,
                           started_at, completed_at, created_at
                    FROM ci_builds
                    WHERE {where}
                    ORDER BY created_at DESC
                    LIMIT ?""",
                tuple(params) + (limit,),
            )

            if not rows:
                return ActionResult(
                    success=True,
                    message="没有找到符合条件的构建记录",
                    data={"type": "ci_builds", "builds": [], "total": 0},
                )

            builds = []
            for r in rows:
                icon = _STATUS_ICONS.get(r["status"], "❓")
                duration = ""
                if r["started_at"] and r["completed_at"]:
                    try:
                        from datetime import datetime
                        s = datetime.fromisoformat(r["started_at"].replace("Z", ""))
                        e = datetime.fromisoformat(r["completed_at"].replace("Z", ""))
                        secs = int((e - s).total_seconds())
                        duration = f"{secs // 60}分{secs % 60}秒" if secs >= 60 else f"{secs}秒"
                    except Exception:
                        pass
                builds.append({
                    "id": r["id"][-8:],
                    "build_type": r["build_type"] or "",
                    "branch": r["branch"] or "",
                    "status": r["status"],
                    "trigger": r["trigger"] or "",
                    "commit": (r["commit_hash"] or "")[:8],
                    "error": (r["error_message"] or "")[:200],
                    "duration": duration,
                    "created_at": (r["created_at"] or "")[:16],
                })

            lines = [f"共找到 {len(builds)} 条构建记录：\n"]
            for b in builds:
                icon = _STATUS_ICONS.get(b["status"], "❓")
                dur = f"（{b['duration']}）" if b["duration"] else ""
                lines.append(
                    f"• {icon} [{b['build_type']}] {b['branch'] or 'N/A'} "
                    f"{b['created_at']}{dur}"
                )
                if b["error"]:
                    lines.append(f"  错误：{b['error'][:100]}")

            return ActionResult(
                success=True,
                message="\n".join(lines),
                data={"type": "ci_builds", "builds": builds, "total": len(builds)},
            )
        except Exception as e:
            logger.error("get_ci_builds 失败: %s", e)
            return ActionResult(success=False, error=str(e))
