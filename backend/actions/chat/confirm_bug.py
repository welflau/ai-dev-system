"""
ConfirmBugAction — 识别到 BUG 上报时，返回前端展示的确认卡片

与 ConfirmRequirementAction 的区别：
- BUG 是"已有功能出了问题"（报错、崩溃、白屏、接口异常）
- 需求是"希望新增或改变某个功能"
- 默认 priority=high（BUG 比需求更急）
"""
from typing import Any, Dict
from actions.base import ActionBase, ActionResult


_VALID_PRIORITIES = ("critical", "high", "medium", "low")


class ConfirmBugAction(ActionBase):

    @property
    def name(self) -> str:
        return "confirm_bug"

    @property
    def description(self) -> str:
        return "识别到用户描述已有功能出现缺陷/报错/崩溃时，生成 BUG 草稿让用户确认。不直接创建。"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "当用户描述已有功能出现问题（缺陷、报错、崩溃、白屏、接口异常、功能不正常）时使用。"
                "BUG 与需求的区别：BUG 是『已有功能出了问题』，需求是『希望新增或改变某个功能』。"
                "此工具只产出草稿给用户确认，不会真的创建 BUG。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "BUG 标题，简短描述现象",
                    },
                    "description": {
                        "type": "string",
                        "description": "复现步骤/现象描述，越详细越好",
                    },
                    "priority": {
                        "type": "string",
                        "enum": list(_VALID_PRIORITIES),
                        "description": "优先级，默认 high",
                    },
                    "requirement_id": {
                        "type": ["string", "null"],
                        "description": "若能从上下文判断 BUG 属于哪个需求则填写，否则填 null",
                    },
                },
                "required": ["title", "description"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        title = (context.get("title") or "").strip()
        description = (context.get("description") or "").strip()
        priority = context.get("priority") or "high"
        if priority not in _VALID_PRIORITIES:
            priority = "high"
        requirement_id = context.get("requirement_id") or None

        if not title:
            return ActionResult(success=False, error="BUG 标题不能为空")

        return ActionResult(
            success=True,
            data={
                "type": "confirm_bug",
                "title": title,
                "description": description,
                "priority": priority,
                "requirement_id": requirement_id,
            },
        )
