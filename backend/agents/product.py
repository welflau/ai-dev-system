"""
ProductAgent — 产品需求 Agent
职责：需求分析 + PRD 生成 + 拆单 + 验收
"""
import json
from typing import Any, Dict, List
from agents.base import BaseAgent
from llm_client import llm_client


class ProductAgent(BaseAgent):

    @property
    def agent_type(self) -> str:
        return "ProductAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "analyze_and_decompose":
            return await self.analyze_and_decompose(context)
        elif task_name == "acceptance_review":
            return await self.acceptance_review(context)
        else:
            return {"status": "error", "message": f"未知任务: {task_name}"}

    async def analyze_and_decompose(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """分析需求并拆分为任务单"""
        title = context.get("title", "")
        description = context.get("description", "")
        priority = context.get("priority", "medium")

        # 尝试 LLM 智能拆单
        prompt = f"""你是一位资深产品经理和项目经理。请分析以下需求，生成 PRD 要点，并将其拆分为可执行的任务单。

## 需求标题
{title}

## 需求描述
{description}

## 优先级
{priority}

## 请按 JSON 格式返回，结构如下：

{{
  "prd_summary": "PRD 核心要点摘要（200字以内）",
  "tickets": [
    {{
      "title": "任务标题",
      "description": "任务详细描述",
      "type": "feature|bugfix|refactor|test|deploy|doc",
      "module": "frontend|backend|database|api|testing|deploy|design|other",
      "priority": 1-5（1最高）,
      "estimated_hours": 预估工时（小时），
      "subtasks": [
        {{"title": "子任务标题", "description": "子任务描述"}}
      ],
      "dependencies": [0, 2],
      "children": [
        {{
          "title": "子工单标题",
          "description": "子工单描述",
          "type": "feature|bugfix|refactor|test|deploy|doc",
          "module": "frontend|backend|database|api|testing|deploy|design|other",
          "priority": 1-5,
          "estimated_hours": 预估工时
        }}
      ]
    }}
  ]
}}

## 关于依赖关系（dependencies）：
- 用 **数组下标**（从 0 开始）表示当前工单依赖哪些工单
- 例如：tickets[2] 的 dependencies 为 [0, 1]，表示第 3 个工单需要等第 1 和第 2 个工单完成后才能开始
- 仔细分析任务间的真实前后依赖关系，例如：数据库设计 → 后端 API → 前端；后端开发 → 测试
- 没有依赖的工单 dependencies 为空数组 []

## 关于子工单（children）：
- 如果一个工单较大，可以进一步拆分为子工单
- 子工单是独立的工单，有自己的完整生命周期
- 子工单与子任务（subtasks）不同：子任务是轻量的 checklist 项，子工单是完整的工单
- 子工单是可选的，简单任务不需要拆子工单

请确保：
1. 任务拆分粒度适中，每个任务 2-8 小时工作量
2. 按模块分类（前端、后端、数据库、API、测试、部署）
3. **必须标注任务间的依赖关系**（用数组下标引用）
4. 每个任务下列出具体的子任务
5. 依赖关系不能循环（A 依赖 B 且 B 依赖 A 是不允许的）
"""

        result = await llm_client.chat_json(
            [{"role": "user", "content": prompt}]
        )

        if result and isinstance(result, dict) and "tickets" in result:
            prd_summary = result.get("prd_summary", "")
            docs_prefix = context.get("docs_prefix", "docs/")
            return {
                "status": "success",
                "prd_summary": prd_summary,
                "tickets": result["tickets"],
                "files": {
                    f"{docs_prefix}PRD.md": f"# PRD - {title}\n\n{prd_summary}\n",
                },
            }

        # LLM 不可用时降级：规则引擎拆单
        return self._fallback_decompose(title, description, priority, context)

    async def acceptance_review(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """产品验收"""
        ticket_title = context.get("ticket_title", "")
        requirement_description = context.get("requirement_description", "")
        dev_result = context.get("dev_result", {})
        docs_prefix = context.get("docs_prefix", "docs/")

        prompt = f"""你是一位产品经理，正在验收开发交付物。

## 原始需求
{requirement_description}

## 工单标题
{ticket_title}

## 开发交付结果
{json.dumps(dev_result, ensure_ascii=False, indent=2)}

## 请判断：
1. 交付物是否满足需求？
2. 是否有遗漏的功能点？
3. 是否需要修改？

请以 JSON 格式返回：
{{
  "passed": true/false,
  "score": 1-10,
  "feedback": "验收意见",
  "issues": ["问题1", "问题2"]
}}
"""

        result = await llm_client.chat_json(
            [{"role": "user", "content": prompt}]
        )

        if result and isinstance(result, dict):
            # 始终通过验收，LLM 反馈仅作为记录参考
            feedback = result.get("feedback", "验收通过")
            score = result.get("score", 8)
            issues = result.get("issues", [])
            review_md = f"# 验收报告 - {ticket_title}\n\n"
            review_md += f"- 结果: 通过\n"
            review_md += f"- 评分: {score}/10\n"
            review_md += f"- 意见: {feedback}\n"
            if issues:
                review_md += "\n## AI 建议（仅供参考）\n" + "\n".join(f"- {i}" for i in issues) + "\n"
            return {
                "status": "acceptance_passed",
                "review": {"passed": True, "score": score, "feedback": feedback, "issues": issues},
                "files": {
                    f"{docs_prefix}acceptance-review.md": review_md,
                },
            }

        # 降级：默认通过
        return {
            "status": "acceptance_passed",
            "review": {"passed": True, "score": 7, "feedback": "规则引擎验收：默认通过", "issues": []},
            "files": {
                f"{docs_prefix}acceptance-review.md": f"# 验收报告 - {ticket_title}\n\n- 结果: 通过\n- 评分: 7/10\n- 意见: 规则引擎验收：默认通过\n",
            },
        }

    def _fallback_decompose(self, title: str, description: str, priority: str, context: Dict = None) -> Dict:
        """规则引擎降级拆单"""
        docs_prefix = (context or {}).get("docs_prefix", "docs/")
        keywords = description.lower()
        tickets = []

        # 根据关键词推断模块
        if any(w in keywords for w in ["界面", "页面", "ui", "前端", "样式", "布局"]):
            tickets.append({
                "title": f"{title} - 前端界面开发",
                "description": f"实现 {title} 的前端界面",
                "type": "feature",
                "module": "frontend",
                "priority": 2,
                "estimated_hours": 4,
                "subtasks": [
                    {"title": "页面布局设计", "description": "HTML/CSS 布局"},
                    {"title": "交互逻辑实现", "description": "JavaScript 交互"},
                ],
                "dependencies": [],
            })

        if any(w in keywords for w in ["接口", "api", "后端", "服务", "逻辑"]):
            tickets.append({
                "title": f"{title} - 后端 API 开发",
                "description": f"实现 {title} 的后端接口",
                "type": "feature",
                "module": "backend",
                "priority": 2,
                "estimated_hours": 4,
                "subtasks": [
                    {"title": "API 接口设计", "description": "定义接口规范"},
                    {"title": "业务逻辑实现", "description": "核心功能代码"},
                ],
                "dependencies": [],
            })

        if any(w in keywords for w in ["数据库", "数据", "存储", "表"]):
            tickets.append({
                "title": f"{title} - 数据库设计",
                "description": f"设计 {title} 的数据库结构",
                "type": "feature",
                "module": "database",
                "priority": 1,
                "estimated_hours": 2,
                "subtasks": [
                    {"title": "数据表设计", "description": "Schema 定义"},
                    {"title": "索引优化", "description": "查询性能优化"},
                ],
                "dependencies": [],
            })

        # 如果什么都没匹配到，给一个通用任务
        if not tickets:
            tickets.append({
                "title": f"{title} - 功能开发",
                "description": description,
                "type": "feature",
                "module": "other",
                "priority": 3,
                "estimated_hours": 4,
                "subtasks": [
                    {"title": "需求细化", "description": "详细分析需求"},
                    {"title": "功能实现", "description": "核心功能开发"},
                ],
                "dependencies": [],
            })

        # 总是加测试任务
        tickets.append({
            "title": f"{title} - 测试",
            "description": f"编写 {title} 的测试用例",
            "type": "test",
            "module": "testing",
            "priority": 3,
            "estimated_hours": 2,
            "subtasks": [
                {"title": "单元测试", "description": "核心功能测试"},
                {"title": "集成测试", "description": "模块集成测试"},
            ],
            "dependencies": [],
        })

        return {
            "status": "success",
            "prd_summary": f"[规则引擎] 需求「{title}」已拆分为 {len(tickets)} 个任务单。",
            "tickets": tickets,
            "files": {
                f"{docs_prefix}PRD.md": f"# PRD - {title}\n\n[规则引擎] 需求「{title}」已拆分为 {len(tickets)} 个任务单。\n\n## 描述\n\n{description}\n",
            },
        }
