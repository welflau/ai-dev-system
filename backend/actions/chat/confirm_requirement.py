"""
ConfirmRequirementAction / ConfirmRequirementsBatchAction

单条：识别到一个需求时用。
批量：一次识别出多条需求（文档分析、规划拆解等）时用，产出单张带 checkbox 的确认卡片。
前端拿到卡片后用户勾选、点「确认创建」才走 CREATE_REQUIREMENT 接口。
"""
from typing import Any, Dict, List
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


class ConfirmRequirementsBatchAction(ActionBase):
    """一次识别多条需求，产出单张带 checkbox 的确认卡片。"""

    @property
    def name(self) -> str:
        return "confirm_requirements_batch"

    @property
    def description(self) -> str:
        return "识别到多条需求时，产出带勾选框的批量确认卡片，用户勾选后一次性创建。"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "当从文档分析、规划拆解或用户描述中识别到 **2 条或以上**需求时使用。\n"
                "产出单张带勾选框的卡片，用户勾选想要创建的需求后一次性提交。\n"
                "每条需求需包含 title / description / priority。\n"
                "单条需求仍用 confirm_requirement；多条时必须用此工具，不要分多次调单条工具。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "requirements": {
                        "type": "array",
                        "description": "需求列表，每条包含 title / description / priority",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "需求标题，简短明确"},
                                "description": {"type": "string", "description": "详细描述"},
                                "priority": {
                                    "type": "string",
                                    "enum": list(_VALID_PRIORITIES),
                                    "description": "优先级，默认 medium",
                                },
                            },
                            "required": ["title", "description"],
                        },
                        "minItems": 2,
                    },
                    "summary": {
                        "type": "string",
                        "description": "对整批需求的简短说明（可选），显示在卡片标题区",
                    },
                },
                "required": ["requirements"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        raw = context.get("requirements") or []
        if not isinstance(raw, list) or len(raw) == 0:
            return ActionResult(success=False, error="requirements 不能为空")

        items: List[Dict[str, Any]] = []
        for r in raw:
            if not isinstance(r, dict):
                continue
            title = (r.get("title") or "").strip()
            if not title:
                continue
            priority = r.get("priority") or "medium"
            if priority not in _VALID_PRIORITIES:
                priority = "medium"
            items.append({
                "title": title,
                "description": (r.get("description") or "").strip(),
                "priority": priority,
            })

        if not items:
            return ActionResult(success=False, error="requirements 中没有有效条目")

        return ActionResult(
            success=True,
            data={
                "type": "confirm_requirements_batch",
                "requirements": items,
                "summary": (context.get("summary") or "").strip(),
                "message": f"识别到 {len(items)} 条需求，请勾选要创建的项",
            },
        )
