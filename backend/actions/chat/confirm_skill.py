"""
ConfirmSkillAction — 查看、确认或拒绝 AI 自动提取的 Skill 草案

用户命令：
  列出草案  → list_pending_skills()
  查看草案  → get_skill_draft(skill_id)
  确认草案  → confirm_skill(skill_id, edit_content?)
  拒绝草案  → reject_skill(skill_id)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.confirm_skill")


class ConfirmSkillAction(ActionBase):
    name = "confirm_skill"
    description = "查看、确认或拒绝 AI 自动提取的 Skill 草案"

    tool_schema = {
        "name": "confirm_skill",
        "description": (
            "管理 AI 自动提取的 Skill 草案。"
            "用于列出待确认草案、查看草案详情、确认写入技能库或拒绝草案。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "confirm", "reject"],
                    "description": "操作类型：list=列出草案 get=查看详情 confirm=确认 reject=拒绝",
                },
                "skill_id": {
                    "type": "string",
                    "description": "草案 ID（list 操作时可省略）",
                },
                "edit_content": {
                    "type": "string",
                    "description": "可选：修改 Skill 内容后再确认（confirm 操作时使用）",
                },
            },
            "required": ["action"],
        },
    }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        action = context.get("action", "list")
        skill_id = context.get("skill_id", "")
        project_id = context.get("project_id", "")
        edit_content = context.get("edit_content", "")

        from skills.pending_skills import pending_skills_manager

        if action == "list":
            drafts = await pending_skills_manager.list_drafts(project_id=project_id or None)
            if not drafts:
                return ActionResult(
                    success=True,
                    message="当前没有待确认的 Skill 草案。",
                    data={"drafts": []}
                )
            lines = [f"共 {len(drafts)} 条待确认 Skill 草案：\n"]
            for d in drafts:
                lines.append(
                    f"**[{d['id']}]** `{d['name']}` — {d['description']}\n"
                    f"  来源工单：{d.get('ticket_id', '')[:8]}  时间：{d.get('created_at', '')[:10]}"
                )
            return ActionResult(
                success=True,
                message="\n".join(lines),
                data={"drafts": [{"id": d["id"], "name": d["name"], "description": d["description"]} for d in drafts]}
            )

        elif action == "get":
            if not skill_id:
                return ActionResult(success=False, error="请提供 skill_id")
            draft = await pending_skills_manager.get(skill_id)
            if not draft:
                return ActionResult(success=False, error=f"草案 {skill_id} 不存在")
            content = (
                f"**Skill 草案：{draft['name']}**\n\n"
                f"描述：{draft['description']}\n"
                f"注入对象：{draft['inject_to']}\n"
                f"适用 traits：{draft.get('traits_match') or '无限制'}\n"
                f"来源工单：{draft.get('ticket_id', '')[:8]}\n"
                f"提取依据：{draft.get('source_summary', '')}\n\n"
                f"---\n\n{draft['prompt_content']}"
            )
            return ActionResult(success=True, message=content, data=draft)

        elif action == "confirm":
            if not skill_id:
                return ActionResult(success=False, error="请提供 skill_id")
            ok = await pending_skills_manager.confirm(
                skill_id, confirmed_by="user", edit_content=edit_content
            )
            if ok:
                draft = await pending_skills_manager.get(skill_id)
                name = draft["name"] if draft else skill_id
                return ActionResult(
                    success=True,
                    message=f"✅ Skill `{name}` 已确认并写入技能库，下次对话自动生效。"
                )
            return ActionResult(success=False, error=f"确认失败，草案 {skill_id} 不存在")

        elif action == "reject":
            if not skill_id:
                return ActionResult(success=False, error="请提供 skill_id")
            await pending_skills_manager.reject(skill_id)
            return ActionResult(success=True, message=f"草案 {skill_id} 已拒绝。")

        return ActionResult(success=False, error=f"未知 action: {action}")
