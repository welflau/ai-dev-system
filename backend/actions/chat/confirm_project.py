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
                "不要调用此工具。\n\n"
                "⚠️ traits 必填 —— 从 trait_taxonomy 选，至少包含 platform:* 和 category:*。"
                "category=game 时必须再加 engine:* 维度。信息不足时**不要调用此工具**，"
                "先反问用户补齐维度。"
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
                    "traits": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "项目特征标签。必填，从 trait_taxonomy 固定词表里选。"
                            "最少必须含 platform:* (web/wechat/desktop/mobile/server/cli) + "
                            "category:* (app/game/service/library)；如 category=game 还要 engine:* "
                            "(ue5/godot4/unity/cocos/none)。示例：[platform:web, category:game, "
                            "engine:none, lang:javascript]"
                        ),
                    },
                    "preset_id": {
                        "type": "string",
                        "description": (
                            "可选 preset 名（webapp / web-game / wechat-miniapp / ue5-game / "
                            "godot-game / unity-game / api-service）。若 traits 是套用某 preset 得来的"
                            "（用户明确选了 preset 或 LLM 推荐后用户同意），填此字段标记来源。"
                            "自由累积 trait 时留空。"
                        ),
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
                "required": ["name", "git_remote_url", "traits"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        name = (context.get("name") or "").strip()
        git_remote_url = (context.get("git_remote_url") or "").strip()
        description = (context.get("description") or "").strip()
        tech_stack = (context.get("tech_stack") or "").strip()
        local_repo_path = (context.get("local_repo_path") or "").strip()
        traits_raw = context.get("traits") or []
        preset_id = (context.get("preset_id") or "").strip() or None

        if not name:
            return ActionResult(success=False, error="项目名称不能为空")
        if not git_remote_url:
            return ActionResult(success=False, error="Git 远程仓库 URL 不能为空")

        # traits 基本校验：必须是 list[str]，至少 2 个（platform + category）
        if not isinstance(traits_raw, list) or not traits_raw:
            return ActionResult(success=False, error="必须提供 traits（至少含 platform:* 和 category:*）")
        traits = [str(t).strip() for t in traits_raw if str(t).strip()]

        has_platform = any(t.startswith("platform:") for t in traits)
        has_category = any(t.startswith("category:") for t in traits)
        if not (has_platform and has_category):
            missing = []
            if not has_platform: missing.append("platform:*")
            if not has_category: missing.append("category:*")
            return ActionResult(
                success=False,
                error=f"traits 缺必填维度：{', '.join(missing)}，请反问用户补齐后再调用",
            )

        has_game = "category:game" in traits
        has_engine = any(t.startswith("engine:") for t in traits)
        if has_game and not has_engine:
            return ActionResult(
                success=False,
                error="traits 含 category:game 但缺 engine:*（ue5/godot4/unity/none 等），请反问用户",
            )

        return ActionResult(
            success=True,
            data={
                "type": "confirm_project",
                "name": name,
                "git_remote_url": git_remote_url,
                "description": description,
                "tech_stack": tech_stack,
                "local_repo_path": local_repo_path,
                "traits": traits,
                "preset_id": preset_id,
            },
        )
