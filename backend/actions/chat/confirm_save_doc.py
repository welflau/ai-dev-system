"""
ConfirmSaveDocAction — 全局聊天中让用户确认"将 AI 总结保存为项目文档"

调用时机：用户说"把这个/刚才的总结保存成文档""存到项目里"等。
AI 调此工具产出确认卡片，用户点确认后前端调 POST /projects/{id}/chat/save-to-repo 落库。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("action.confirm_save_doc")


class ConfirmSaveDocAction(ActionBase):

    @property
    def name(self) -> str:
        return "confirm_save_doc"

    @property
    def description(self) -> str:
        return "将 AI 生成的内容保存为项目文档"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "当用户要求把当前对话中 AI 生成的总结/分析/方案保存为项目文档时调用。\n"
                "产出确认卡片，用户点击确认后才真正写入项目仓库的 docs/ 目录。\n"
                "⚠️ 重要：必须在拿到文档内容的同一轮立即调用，不要分两轮（第一轮问用户选哪个项目，第二轮才调）。\n"
                "对话历史会被压缩，延迟调用会导致 content 被截断丢失。\n"
                "content 应为完整的 Markdown 文档内容（不要省略）。\n"
                "project_id 从已有项目列表中自行选取最合适的，用户会在确认卡片上看到项目名并可取消。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "目标项目 ID，从已有项目列表中选取",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "目标项目名称（用于卡片展示）",
                    },
                    "filename": {
                        "type": "string",
                        "description": "保存的文件名（英文，以 .md 结尾），如 skill-analysis.md",
                    },
                    "title": {
                        "type": "string",
                        "description": "文档标题（中文，用于卡片展示）",
                    },
                    "content": {
                        "type": "string",
                        "description": "要保存的完整 Markdown 文档内容",
                    },
                },
                "required": ["project_id", "filename", "content"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = (context.get("project_id") or "").strip()
        project_name = (context.get("project_name") or project_id).strip()
        filename = (context.get("filename") or "").strip()
        title = (context.get("title") or filename).strip()
        content = (context.get("content") or "").strip()

        if not project_id or not filename or not content:
            return ActionResult(success=False, error="project_id / filename / content 不能为空")

        if not filename.endswith(".md"):
            filename += ".md"

        logger.info("confirm_save_doc: project=%s file=%s", project_id, filename)

        return ActionResult(
            success=True,
            data={
                "type": "confirm_save_doc",
                "project_id": project_id,
                "project_name": project_name,
                "filename": filename,
                "title": title,
                "content": content,
                "message": f"是否将「{title}」保存到项目「{project_name}」的 docs/{filename}？",
            },
        )
