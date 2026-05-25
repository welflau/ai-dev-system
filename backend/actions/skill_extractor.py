"""
SkillExtractorAction — 工单验收通过后自动提取可复用 Skill 草案

触发时机：acceptance_passed（由 acceptance_review.py 写状态后异步调用）
特点：降级安全——LLM 失败或无可提取内容时静默跳过，不影响主流程
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("skill_extractor")

_EXTRACT_PROMPT = """你是一个技术知识提炼专家。请分析下面这个已验收通过的开发工单，判断是否有值得提炼为可复用 Skill 的技术模式。

## 工单信息
{ticket_info}

## 开发轨迹摘要
{trajectory}

---

## 判断标准（满足其一即提取）

1. 解决了需要特定领域知识才能处理的问题（如 UE 的某类 Bug 规律、框架的特殊约定）
2. 经过多次 Reflexion 后发现了一个通用策略变化（不是本次才发现的普通知识）
3. 代码里出现了可以被未来工单直接复用的模式或约定

## 不提取的情况

- 通用编程知识（无项目/引擎/框架特异性）
- 过于具体（只适用于本工单，无法泛化到其他类似需求）
- 与已有 Skills 高度重叠

## 输出格式（严格 JSON，不要 markdown 包裹）

{{
  "should_extract": true/false,
  "reason": "一句话说明为什么提取/不提取",
  "skill": {{
    "name": "skill-slug（英文小写连字符，如 ue-softobjectpath-lazy-load）",
    "description": "一行描述，说明何时使用这个 Skill（中文，≤60字）",
    "inject_to": ["DevAgent"],
    "traits_match": {{"any_of": ["engine:ue5"]}},
    "prompt_content": "Skill 正文，Markdown 格式，包含：场景描述、解决方案、注意事项"
  }}
}}

如果 should_extract=false，skill 字段可省略。"""


class SkillExtractorAction(ActionBase):
    name = "skill_extractor"
    description = "工单验收通过后提取可复用 Skill 草案"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        ticket_id = context.get("ticket_id", "")
        project_id = context.get("project_id", "")
        agent_type = context.get("agent_type", "DevAgent")
        project_traits = context.get("project_traits", [])

        if not ticket_id or not project_id:
            return ActionResult(success=False, error="缺少 ticket_id 或 project_id")

        try:
            trajectory = await self._build_trajectory(ticket_id, project_id)
            if not trajectory.get("has_content"):
                logger.info("工单 %s 无足够轨迹数据，跳过 Skill 提取", ticket_id[:8])
                return ActionResult(success=True, data={"extracted": False, "reason": "轨迹数据不足"})

            result = await self._extract_skill(trajectory, project_traits, agent_type)

            if result.get("should_extract") and result.get("skill"):
                skill_draft = result["skill"]
                from skills.pending_skills import pending_skills_manager
                skill_id = await pending_skills_manager.add(
                    ticket_id=ticket_id,
                    project_id=project_id,
                    agent_type=agent_type,
                    skill_draft=skill_draft,
                    source_summary=result.get("reason", ""),
                )
                logger.info("✨ 从工单 %s 提取 Skill 草案: %s (%s)", ticket_id[:8], skill_draft["name"], skill_id)
                return ActionResult(
                    success=True,
                    data={"extracted": True, "skill_id": skill_id, "skill_name": skill_draft["name"]}
                )
            else:
                logger.info("工单 %s 无可提取 Skill: %s", ticket_id[:8], result.get("reason", ""))
                return ActionResult(success=True, data={"extracted": False, "reason": result.get("reason", "")})

        except Exception as e:
            logger.warning("Skill 提取失败（静默降级）: %s", e)
            return ActionResult(success=True, data={"extracted": False, "reason": f"提取异常: {e}"})

    async def _build_trajectory(self, ticket_id: str, project_id: str) -> Dict:
        """从数据库收集工单轨迹信息"""
        from database import db

        ticket = await db.fetch_one(
            "SELECT title, description, status, module FROM tickets WHERE id=?", (ticket_id,)
        )
        if not ticket:
            return {"has_content": False}

        # 获取 reflection logs（有反思记录说明经过了失败-修复循环）
        logs = await db.fetch_all(
            """SELECT log_type, message, detail FROM ticket_logs
               WHERE ticket_id=? AND log_type IN ('reflection','error','action_start','action_end')
               ORDER BY created_at ASC LIMIT 30""",
            (ticket_id,)
        )

        # 获取产出物摘要
        artifacts = await db.fetch_all(
            "SELECT name, content FROM artifacts WHERE ticket_id=? LIMIT 5",
            (ticket_id,)
        )

        has_reflection = any(l["log_type"] == "reflection" for l in logs)
        has_artifacts = len(artifacts) > 0

        return {
            "has_content": has_artifacts or has_reflection or bool(ticket["description"]),
            "ticket": dict(ticket),
            "logs": [dict(l) for l in logs],
            "artifacts": [{"name": a["name"], "content": (a["content"] or "")[:500]} for a in artifacts],
            "has_reflection": has_reflection,
            "log_count": len(logs),
        }

    async def _extract_skill(self, trajectory: Dict, traits: list, agent_type: str) -> Dict:
        """调用 LLM 判断并提取 Skill"""
        from llm_client import llm_client

        ticket = trajectory["ticket"]
        ticket_info = (
            f"标题：{ticket.get('title', '')}\n"
            f"描述：{(ticket.get('description') or '')[:400]}\n"
            f"模块：{ticket.get('module', '')}\n"
            f"Agent：{agent_type}\n"
            f"项目 traits：{', '.join(traits) or '未知'}"
        )

        logs_text = ""
        for log in trajectory.get("logs", [])[:15]:
            content = (log.get("detail") or log.get("message") or "")[:200]
            if content:
                logs_text += f"[{log['log_type']}] {content}\n"

        artifacts_text = ""
        for art in trajectory.get("artifacts", [])[:3]:
            artifacts_text += f"\n### {art['name']}\n{art['content'][:300]}\n"

        traj_text = ""
        if logs_text:
            traj_text += f"**执行日志**（{trajectory['log_count']} 条）：\n{logs_text}\n"
        if trajectory.get("has_reflection"):
            traj_text += "**注**：本工单经历了 Reflexion 反思循环。\n"
        if artifacts_text:
            traj_text += f"**产出物摘要**：{artifacts_text}"

        prompt = _EXTRACT_PROMPT.format(
            ticket_info=ticket_info,
            trajectory=traj_text or "（无详细轨迹）"
        )

        raw = await llm_client.generate(prompt, max_tokens=1200, temperature=0.2)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw[:-3].rstrip()

        result = json.loads(raw)
        return result
