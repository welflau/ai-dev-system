"""
ConfirmProjectAction — 识别到用户想新建项目时，返回前端展示的确认卡片

对 LLM 暴露为 tool（Anthropic tool_use），ChatAssistantAgent 在 P2 接入后
全局聊天里 LLM 识别"建项目"意图即调用本工具产出草稿卡片。

与 CreateProjectAction 的区别：
- ConfirmProjectAction 只生成草稿卡片，不碰 Git、不碰数据库
- CreateProjectAction 真正落库（用户在前端点击确认后，由 /confirm-create-project 端点触发）
"""
from typing import Any, Dict
from actions.base import ActionBase, ActionResult


class ConfirmProjectAction(ActionBase):

    @property
    def name(self) -> str:
        return "confirm_project"

    @property
    def description(self) -> str:
        return "识别到用户想新建项目时，生成项目草稿让用户确认。不直接创建，不碰 Git 不写库。"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "当用户明确表达想要新建项目时使用（例如「帮我建个项目」「新建一个 xxx 项目」"
                "「clone 一个仓库开始开发」）。此工具只产出草稿给用户确认，不会真的创建项目，"
                "也不会 clone 仓库或写任何数据。若用户只是在提问、描述现有项目、查看状态等，"
                "不要调用此工具。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "项目名称，简短明确",
                    },
                    "git_remote_url": {
                        "type": "string",
                        "description": "Git 远程仓库 URL，如 https://github.com/user/repo.git 或 git@...",
                    },
                    "description": {
                        "type": "string",
                        "description": "项目简要描述，可选",
                    },
                    "tech_stack": {
                        "type": "string",
                        "description": "技术栈，如 Python/FastAPI、React/TypeScript，可选",
                    },
                    "local_repo_path": {
                        "type": "string",
                        "description": "本地仓库路径，留空则自动生成到 backend/projects/ 下",
                    },
                },
                "required": ["name", "git_remote_url"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        name = (context.get("name") or "").strip()
        git_remote_url = (context.get("git_remote_url") or "").strip()
        description = (context.get("description") or "").strip()
        tech_stack = (context.get("tech_stack") or "").strip()
        local_repo_path = (context.get("local_repo_path") or "").strip()

        if not name:
            return ActionResult(success=False, error="项目名称不能为空")
        if not git_remote_url:
            return ActionResult(success=False, error="Git 远程仓库 URL 不能为空")

        return ActionResult(
            success=True,
            data={
                "type": "confirm_project",
                "name": name,
                "git_remote_url": git_remote_url,
                "description": description,
                "tech_stack": tech_stack,
                "local_repo_path": local_repo_path,
            },
        )
