"""
LoadSkillAction — 按需加载单个 Skill 全文到当前对话上下文

主动触发架构的核心：
  system prompt 只含 Skill 索引（名称+描述），AI 推理时按需调用此工具加载具体内容。
  每次调用对应一条思考日志「📚 加载 Skill: xxx」，完全可追踪。

输入：
  skill_id      Skill ID（来自索引表）
  reason        为什么需要这个 Skill（可选，帮助用户理解）

输出：
  type          "skill_loaded"
  skill_id      加载的 Skill ID
  name          Skill 显示名
  content       Skill 全文（注入到当前对话上下文）
  token_count   大约字符数
"""
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.load_skill")


class LoadSkillAction(ActionBase):

    @property
    def name(self) -> str:
        return "load_skill"

    @property
    def description(self) -> str:
        return "当需要特定领域的深度规范知识时，按需加载对应 Skill 文档到当前对话"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "按需加载 Skill 文档。当用户问题需要特定领域知识（如 UE C++ 规范、Git 工程化、"
                "编辑态控制等）时调用。不确定是否需要时可不调用，直接回答。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "skill_id": {
                        "type": "string",
                        "description": "Skill ID，从可用 Skill 索引表中选择",
                    },
                    "reason": {
                        "type": "string",
                        "description": "为什么需要这个 Skill（简短说明）",
                    },
                },
                "required": ["skill_id"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        from skills import skill_loader

        skill_id = (context.get("skill_id") or "").strip()
        reason = context.get("reason", "")
        project_id = context.get("project_id")

        if not skill_id:
            return ActionResult(success=False, error="skill_id 不能为空")

        # 验证 Skill 是否可用（全局库 + 项目自定义）
        available_ids = await _get_available_skill_ids(project_id)
        if skill_id not in available_ids:
            all_ids = list(skill_loader.skills.keys())
            return ActionResult(
                success=False,
                data={"type": "error", "message": f"Skill `{skill_id}` 不可用，可选：{available_ids}"},
                error=f"Skill `{skill_id}` 不在可用列表中",
            )

        # 加载 Skill 全文（自定义 Skill 从文件系统读取，全局 Skill 走 skill_loader）
        if skill_id.startswith("custom.") and project_id:
            content, name = await _load_custom_skill(skill_id, project_id)
        else:
            content = skill_loader.get_skill_prompt(skill_id)
            cfg = skill_loader.skills.get(skill_id, {})
            name = cfg.get("name", skill_id)

        if not content:
            return ActionResult(
                success=False,
                data={"type": "error", "message": f"Skill `{skill_id}` 内容为空"},
                error="Skill 内容为空",
            )

        logger.info("📚 load_skill: %s (%s) reason=%s project=%s",
                    skill_id, name, reason[:60], project_id)

        return ActionResult(
            success=True,
            data={
                "type": "skill_loaded",
                "skill_id": skill_id,
                "name": name,
                "content": content,
                "token_estimate": len(content) // 4,  # 粗略估算
            },
            message=f"已加载 Skill：{name}",
        )


async def _get_available_skill_ids(project_id: str = None) -> list:
    """获取项目可用的 Skill ID 列表（全局库 + 项目自定义配置）"""
    from skills import skill_loader

    # 基础：全局库里所有启用的 Skill
    base_ids = [sid for sid, cfg in skill_loader.skills.items() if cfg.get("enabled", True)]

    if not project_id:
        return base_ids

    # 从 project_skills 表读取项目覆盖配置；表不存在时降级为全局默认
    try:
        from database import db
        rows = await db.fetch_all(
            "SELECT skill_id, enabled FROM project_skills WHERE project_id=?",
            (project_id,),
        )
        if rows:
            # 已有项目配置：用项目配置覆盖
            project_map = {r["skill_id"]: bool(r["enabled"]) for r in rows}
            result = []
            for sid in base_ids:
                if project_map.get(sid, True):  # 默认启用
                    result.append(sid)
            # 加入项目自定义 Skill
            for sid, enabled in project_map.items():
                if enabled and sid not in result:
                    result.append(sid)
            return result
    except Exception:
        pass  # project_skills 表还不存在时降级

    return base_ids


async def _load_custom_skill(skill_id: str, project_id: str):
    """加载项目自定义 Skill 的内容和显示名。返回 (content, name)。"""
    from pathlib import Path
    try:
        from database import db
        row = await db.fetch_one(
            "SELECT custom_path, custom_name FROM project_skills WHERE project_id=? AND skill_id=? AND source='custom'",
            (project_id, skill_id),
        )
        if not row or not row["custom_path"]:
            return None, skill_id

        _BASE = Path(__file__).parent.parent.parent / "data" / "project_skills"
        skill_file = _BASE / row["custom_path"]
        if not skill_file.exists():
            logger.warning("自定义 Skill 文件不存在: %s", skill_file)
            return None, skill_id

        content = skill_file.read_text(encoding="utf-8").strip()
        name = row["custom_name"] or skill_id
        return content, name
    except Exception as e:
        logger.warning("加载自定义 Skill %s 失败: %s", skill_id, e)
        return None, skill_id
