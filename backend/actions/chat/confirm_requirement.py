"""
ConfirmRequirementAction — 识别到新需求时，返回前端展示的确认卡片

注意：不直接创建需求。前端拿到卡片后用户点击「确认创建」才走 CREATE_REQUIREMENT 接口。
"""
from typing import Any, Dict
from actions.base import ActionBase, ActionResult


_VALID_PRIORITIES = ("critical", "high", "medium", "low")


class ConfirmRequirementAction(ActionBase):

    @property
    def name(self) -> str:
        return "confirm_requirement"

    @property
    def description(self) -> str:
        return "识别到用户想新增/开发某个功能时，生成需求草稿让用户确认。不直接创建。"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        """Anthropic tool_use 格式 schema，供 ChatAssistantAgent 在 P2 接入时使用"""
        return {
            "name": self.name,
            "description": (
                "当用户明确表达想要新增/开发某个功能时使用（例如「我想要…」「帮我开发…」"
                "「新增一个…」「做一个…」）。此工具只产出草稿给用户确认，不会真的创建需求。"
                "若用户只是在提问、描述现有问题、报 BUG，则不要调用此工具。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "需求标题，简短明确",
                    },
                    "description": {
                        "type": "string",
                        "description": "详细描述：做什么、放在哪、风格要求等",
                    },
                    "priority": {
                        "type": "string",
                        "enum": list(_VALID_PRIORITIES),
                        "description": "优先级，默认 medium",
                    },
                },
                "required": ["title", "description"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        title = (context.get("title") or "").strip()
        description = (context.get("description") or "").strip()
        priority = context.get("priority") or "medium"
        if priority not in _VALID_PRIORITIES:
            priority = "medium"

        if not title:
            return ActionResult(success=False, error="需求标题不能为空")

        return ActionResult(
            success=True,
            data={
                "type": "confirm_requirement",
                "title": title,
                "description": description,
                "priority": priority,
            },
        )
