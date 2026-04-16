"""Action: 需求拆单（从 ProductAgent.analyze_and_decompose 抽离，使用 ActionNode）"""
import logging
from typing import Any, Dict
from actions.base import ActionBase, ActionResult
from actions.action_node import ActionNode
from actions.schemas import DecomposeOutput
from llm_client import llm_client

logger = logging.getLogger("action.decompose")


class DecomposeAction(ActionBase):

    @property
    def name(self) -> str:
        return "decompose"

    @property
    def description(self) -> str:
        return "分析需求并拆分为可执行工单（读取已有代码上下文）"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        title = context.get("title", "")
        description = context.get("description", "")
        priority = context.get("priority", "medium")
        existing_files = context.get("existing_files", [])
        existing_code = context.get("existing_code", {})
        docs_prefix = context.get("docs_prefix", "docs/")

        # 已有代码上下文
        code_context = ""
        if existing_files:
            code_files = [f for f in existing_files if not f.startswith(("docs/", "tests/", ".git", "build/"))]
            if code_files:
                code_context += f"\n## 项目已有文件\n" + "\n".join(f"  - {f}" for f in code_files[:20]) + "\n"
        if existing_code:
            code_context += "\n## 现有代码（拆单时参考，避免重复）\n"
            for fp, code in list(existing_code.items())[:2]:
                code_context += f"\n### {fp}\n```\n{code[:1000]}\n```\n"

        req_context = f"""## 需求标题
{title}

## 需求描述
{description}

## 优先级
{priority}
{code_context}
## 注意
1. 工单应细粒度、可独立执行（2-8 小时工作量）
2. 按模块分类：frontend/backend/database/api/design/other
3. 标注依赖关系（用数组下标，如 [0] 表示依赖第一个工单）
4. 已有文件的功能不要重复拆单
5. 每个工单含 subtasks 子任务列表"""

        node = ActionNode(
            key="decompose",
            expected_type=DecomposeOutput,
            instruction="作为产品经理，分析需求并拆分为可执行工单。",
        )
        await node.fill(req=req_context, llm=llm_client, max_tokens=4000)

        output = node.instruct_content
        if output and output.tickets:
            prd_md = f"# PRD — {title}\n\n{output.prd_summary}\n"
            logger.info("✅ 需求拆单: %s → %d 个工单", title[:20], len(output.tickets))
            return ActionResult(
                success=True,
                data={
                    "prd_summary": output.prd_summary,
                    "tickets": output.tickets,
                },
                files={f"{docs_prefix}PRD.md": prd_md},
            )

        # 降级
        logger.warning("⚠️ 需求拆单 LLM 失败，使用降级")
        return self._fallback(title, description, docs_prefix)

    def _fallback(self, title: str, description: str, docs_prefix: str) -> ActionResult:
        tickets = [
            {"title": f"{title} - 前端界面开发", "description": f"实现 {description[:100]} 的前端界面",
             "type": "feature", "module": "frontend", "priority": 2, "estimated_hours": 4,
             "subtasks": ["页面布局设计", "交互逻辑实现", "样式优化"], "dependencies": []},
            {"title": f"{title} - 后端服务开发", "description": f"实现 {description[:100]} 的后端接口",
             "type": "feature", "module": "backend", "priority": 2, "estimated_hours": 4,
             "subtasks": ["API 设计", "业务逻辑实现", "数据模型定义"], "dependencies": []},
        ]
        return ActionResult(
            success=True,
            data={"prd_summary": f"[降级] {title}", "tickets": tickets},
            files={f"{docs_prefix}PRD.md": f"# PRD — {title}\n\n{description}\n"},
        )
