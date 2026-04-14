"""
ProductAgent — 产品需求 Agent (Role)
职责：需求分析 + PRD 生成 + 拆单 + 验收
Actions: AcceptanceReviewAction (验收用 ActionNode)
analyze_and_decompose 保留 legacy 模式（逻辑复杂）
"""
import json
from typing import Any, Dict, List
from agents.base import BaseAgent, ReactMode
from actions.acceptance_review import AcceptanceReviewAction
from llm_client import llm_client


class ProductAgent(BaseAgent):

    action_classes = [AcceptanceReviewAction]
    react_mode = ReactMode.SINGLE
    watch_actions = {"write_code"}  # 关心开发完成

    @property
    def agent_type(self) -> str:
        return "ProductAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "analyze_and_decompose":
            return await self.analyze_and_decompose(context)
        elif task_name == "acceptance_review":
            # 使用 ActionNode 结构化验收
            return await self.run_action("acceptance_review", context)
        else:
            return {"status": "error", "message": f"未知任务: {task_name}"}

    async def analyze_and_decompose(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """分析需求并拆分为任务单（保留 legacy，逻辑复杂）"""
        title = context.get("title", "")
        description = context.get("description", "")
        priority = context.get("priority", "medium")
        docs_prefix = context.get("docs_prefix", "docs/")

        prompt = f"""你是一位资深产品经理和项目经理。请分析以下需求，生成 PRD 要点，并将其拆分为可执行的任务单。

## 需求标题
{title}

## 需求描述
{description}

## 优先级
{priority}

## 请以 JSON 格式返回：
{{
  "prd_summary": "200字以内的 PRD 摘要",
  "tickets": [
    {{
      "title": "工单标题（英文+中文）",
      "description": "工单详细描述",
      "type": "feature/bugfix/improvement/refactor",
      "module": "frontend/backend/database/api/design/other",
      "priority": 1-5 数字,
      "estimated_hours": 预估工时,
      "subtasks": ["子任务1", "子任务2"],
      "dependencies": []
    }}
  ]
}}

注意：
1. 工单应该细粒度、可独立执行
2. 工单之间可以有依赖关系（用数组下标表示，如 [0] 表示依赖第一个工单）
3. 每个工单的 module 字段必须准确
4. subtasks 是更细的步骤拆分
"""

        result = await llm_client.chat_json(
            [{"role": "user", "content": prompt}]
        )

        if result and isinstance(result, dict) and result.get("tickets"):
            prd_summary = result.get("prd_summary", "")
            tickets_data = result.get("tickets", [])

            prd_md = f"# PRD - {title}\n\n{prd_summary}\n"
            return {
                "status": "success",
                "prd_summary": prd_summary,
                "tickets": tickets_data,
                "files": {
                    f"{docs_prefix}PRD.md": prd_md,
                },
            }

        # 降级
        return self._fallback_decompose(title, description, priority, docs_prefix)

    def _fallback_decompose(self, title: str, description: str, priority: str, docs_prefix: str) -> Dict:
        """规则引擎降级拆单"""
        tickets = [
            {"title": f"{title} - 前端界面开发", "description": f"实现 {description[:100]} 的前端界面",
             "type": "feature", "module": "frontend", "priority": 2, "estimated_hours": 4,
             "subtasks": ["页面布局设计", "交互逻辑实现", "样式优化"], "dependencies": []},
            {"title": f"{title} - 后端服务开发", "description": f"实现 {description[:100]} 的后端接口",
             "type": "feature", "module": "backend", "priority": 2, "estimated_hours": 4,
             "subtasks": ["API 设计", "业务逻辑实现", "数据模型定义"], "dependencies": []},
        ]
        return {
            "status": "success",
            "prd_summary": f"[规则引擎] {title}",
            "tickets": tickets,
            "files": {f"{docs_prefix}PRD.md": f"# PRD - {title}\n\n{description}\n"},
        }
