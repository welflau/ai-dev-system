"""
ReviewAgent — 代码审查 Agent (Role)

作为独立 SOP 阶段运行：dev 完成 → code_review → acceptance。
CodeReviewAction 已读实际代码 + 用 ActionNode + 读 SOP 配置，不是盲审。
详见 docs/20260421_03_盲审修复P0实现方案.md
"""
import logging
from typing import Any, Dict
from agents.base import BaseAgent, ReactMode
from actions.code_review import CodeReviewAction

logger = logging.getLogger("agent.review")


class ReviewAgent(BaseAgent):

    action_classes = [CodeReviewAction]
    react_mode = ReactMode.SINGLE
    watch_actions = {"write_code"}

    @property
    def agent_type(self) -> str:
        return "ReviewAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """路由到 CodeReviewAction。总是返回 review_passed——低分由 orchestrator
        转成 warning 级 ticket_log，不阻塞流程（block_on_low_score=false 默认）。"""
        if task_name == "code_review":
            result = await self.run_action("code_review", context)
            # 标记状态为审查通过（默认不阻塞；未来开启硬门控时再扩展 review_rejected）
            result["status"] = "review_passed"
            return result
        return {"status": "error", "message": f"ReviewAgent 未知任务: {task_name}"}
