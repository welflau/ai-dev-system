"""
GenerateDocumentAction — 直接生成设计/技术/分析文档并写入 Git 仓库

适合：设计报告、技术方案、API 文档、项目总结、竞品分析等，不需要走开发流程的文档。
"""
import json
import logging
import re
from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from database import db
from events import event_manager
from utils import generate_id, now_iso

logger = logging.getLogger("actions.chat.generate_document")


class GenerateDocumentAction(ActionBase):

    @property
    def name(self) -> str:
        return "generate_document"

    @property
    def description(self) -> str:
        return "生成 Markdown 文档并写入项目仓库 docs/ 目录，自动 commit + push"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "当用户要求生成设计报告、技术方案、API 文档、分析报告、项目总结、竞品分析等文档时使用。"
                "此工具不走开发流程，直接生成完整 Markdown 内容并写入项目仓库的 docs/ 目录（会自动 commit + push）。"
                "content 必须是完整的 Markdown 文档，不要省略。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "英文文件名，以 .md 结尾，例如 api-design.md",
                    },
                    "title": {
                        "type": "string",
                        "description": "文档标题（用于 commit 消息和 artifacts 记录）",
                    },
                    "content": {
                        "type": "string",
                        "description": "完整的 Markdown 文档内容",
                    },
                },
                "required": ["filename", "content"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="缺少 project_id")

        filename = (context.get("filename") or "").strip()
        title = (context.get("title") or "").strip()
        content = (context.get("content") or "").strip()

        if not filename or not content:
            return ActionResult(
                success=False,
                data={"type": "error", "message": "文档文件名和内容不能为空"},
            )

        # 文件名安全化：只保留 \w、- 和 .
        filename = re.sub(r'[^\w\-.]', '', filename)
        if not filename.endswith(".md"):
            filename += ".md"

        file_path = f"docs/{filename}"

        try:
            from git_manager import git_manager

            if not git_manager.repo_exists(project_id):
                project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
                if project:
                    await git_manager.init_repo(project_id, project["name"])

            await git_manager.write_file(project_id, file_path, content)

            commit_hash = await git_manager.commit(
                project_id,
                f"[Doc] {title or filename}",
                author="ChatAssistant",
            )
            await git_manager.push(project_id)

            await db.insert("artifacts", {
                "id": generate_id("ART"),
                "project_id": project_id,
                "requirement_id": None,
                "ticket_id": None,
                "type": "document",
                "name": title or filename,
                "path": file_path,
                "content": content,
                "metadata": json.dumps({"source": "chat_assistant", "commit": commit_hash}),
                "created_at": now_iso(),
            })

            await event_manager.publish_to_project(
                project_id,
                "document_generated",
                {"filename": filename, "path": file_path, "title": title},
            )

            logger.info("📄 文档已生成: %s (commit: %s)", file_path, commit_hash)

            return ActionResult(
                success=True,
                data={
                    "type": "document_generated",
                    "title": title or filename,
                    "path": file_path,
                    "commit": commit_hash,
                    "message": f"文档「{title or filename}」已生成并保存到 {file_path}",
                },
            )
        except Exception as e:
            logger.error("生成文档失败: %s", e)
            return ActionResult(
                success=False,
                data={"type": "error", "message": f"生成文档失败: {str(e)}"},
            )
