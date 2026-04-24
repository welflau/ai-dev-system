"""
DiagnoseTicketAction — 卡壳工单自动诊断 Action

触发场景：ticket 进入 BLOCKED 状态（orchestrator 检测到 Agent 返回 error）。
把 ticket 描述 + 失败的 action/agent + 最近 N 条日志 + SOP 阶段上下文
交给 LLM 出一份结构化诊断（症状/根因/建议动作），写回 tickets.diagnosis。

输入 context:
  ticket_id             : str  工单 ID
  ticket_title          : str
  ticket_description    : str
  project_id            : str
  project_traits        : list[str]
  current_status        : str  进入 blocked 前的状态
  failed_agent          : str  返回 error 的 agent 名
  failed_action         : str  对应 action（如 run_engine_compile）
  failed_error_message  : str  agent.execute 返回的 message
  recent_logs           : list[dict]  最近 N 条 ticket_logs（含 action/status/detail）
  sop_stage             : dict?  该 action 对应的 SOP 阶段定义（id/name/description）

输出 data.diagnosis:
  {
    "symptom": str,                       # 现象一句话
    "root_cause": str,                    # 根因定位
    "severity": "low" | "medium" | "high",
    "suggested_actions": [                # 按优先级排序的建议（最多 4 条）
      {"action": "文字描述", "who": "developer" / "system" / "config", "priority": 1}
    ],
    "confidence": float,                  # 0..1
    "related_files": list[str],           # 若能定位到文件/配置
    "created_at": ISO时间
  }

降级：LLM 调用失败 → 返回最小诊断（只把 error_message 回显）。
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from actions.base import ActionBase, ActionResult
from llm_client import llm_client

logger = logging.getLogger("actions.diagnose")


_SYSTEM_PROMPT = """你是资深 DevOps 运维工程师，正在诊断一条自动化流水线工单卡住的原因。

硬要求：
- 根因定位要具体（到 action 名 / agent 名 / 配置项 / 代码路径），不要空话
- 建议动作必须可操作：重试 / 跳过阶段 / 实现某方法 / 移除某 trait
- 输出严格 JSON，不要 markdown 包裹
- confidence: 证据充分（有明确 error + 已知模式）0.8+；证据间接 0.4~0.7；基本靠猜 <0.3"""


def _parse_json_lenient(raw: str) -> Dict[str, Any]:
    s = (raw or "").strip()
    if s.startswith("```"):
        lines = [ln for ln in s.split("\n") if not ln.strip().startswith("```")]
        s = "\n".join(lines).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        return json.loads(s[start:end + 1])
    raise ValueError("无法从 LLM 输出解析出 JSON")


def _format_recent_logs(logs: List[Dict[str, Any]], max_n: int = 8) -> str:
    if not logs:
        return "(无)"
    lines = []
    for lg in logs[:max_n]:
        ts = (lg.get("created_at") or "")[:19]
        act = lg.get("action") or "?"
        frm = lg.get("from_status") or "?"
        to = lg.get("to_status") or "?"
        agt = lg.get("agent_type") or "?"
        detail = (lg.get("detail") or "")[:160]
        lines.append(f"[{ts}] {agt}.{act} {frm}→{to} | {detail}")
    if len(logs) > max_n:
        lines.append(f"... 还有 {len(logs) - max_n} 条更早的日志")
    return "\n".join(lines)


def _minimal_diagnosis(error_msg: str, note: str = "") -> Dict[str, Any]:
    return {
        "symptom": "工单进入 blocked 状态",
        "root_cause": (error_msg or "Agent 返回 error，无详细信息")[:500],
        "severity": "medium",
        "suggested_actions": [
            {"action": "检查 Agent 日志定位 error 来源", "who": "developer", "priority": 1},
            {"action": "如果是 action 未实现，考虑从 project traits 移除触发该 action 的 trait", "who": "config", "priority": 2},
        ],
        "confidence": 0.2,
        "related_files": [],
        "note": note or "LLM 诊断未执行（降级回显 error）",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }


class DiagnoseTicketAction(ActionBase):

    @property
    def name(self) -> str:
        return "diagnose_ticket"

    @property
    def description(self) -> str:
        return "诊断卡壳（blocked）工单，定位根因并给出建议"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        ticket_title = context.get("ticket_title", "") or "(无标题)"
        ticket_desc = context.get("ticket_description", "") or ""
        current_status = context.get("current_status", "") or "?"
        failed_agent = context.get("failed_agent", "") or "?"
        failed_action = context.get("failed_action", "") or "?"
        error_msg = context.get("failed_error_message", "") or ""
        recent_logs = context.get("recent_logs") or []
        sop_stage = context.get("sop_stage") or {}
        project_traits = context.get("project_traits") or []

        # 构建 LLM 输入
        sop_block = "(无 SOP 阶段上下文)"
        if sop_stage:
            sop_block = (
                f"- stage id: {sop_stage.get('id', '?')}\n"
                f"- stage name: {sop_stage.get('name', '?')}\n"
                f"- agent/action: {sop_stage.get('agent', '?')}.{sop_stage.get('action', '?')}\n"
                f"- description: {sop_stage.get('description', '')[:200]}"
            )

        user_prompt = f"""## 诊断任务
一条工单在流水线中卡住了（状态变成 blocked）。分析根因并建议下一步。

## 工单
- 标题: {ticket_title}
- 描述: {ticket_desc[:400]}
- 进入 blocked 前状态: {current_status}

## 失败点
- Agent: {failed_agent}
- Action: {failed_action}
- Error: {error_msg[:400]}

## 该 action 对应的 SOP 阶段
{sop_block}

## 项目 traits
{', '.join(project_traits) if project_traits else '(无)'}

## 最近日志（最新在前）
{_format_recent_logs(recent_logs)}

## 输出要求：严格 JSON（不要 markdown 包裹）
{{
  "symptom": "一句话描述现象（用户角度）",
  "root_cause": "具体到 action/agent/配置项/文件的根因",
  "severity": "low | medium | high",
  "suggested_actions": [
    {{"action": "具体动作描述", "who": "developer | system | config", "priority": 1}}
  ],
  "confidence": 0.0,
  "related_files": ["若能定位到文件或配置路径"]
}}
只输出 JSON。"""

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            raw = await llm_client.chat(messages, temperature=0.2, max_tokens=1200)
            diag = _parse_json_lenient(raw)

            # 字段兜底
            diag.setdefault("symptom", f"{failed_agent}.{failed_action} 失败")
            diag.setdefault("root_cause", error_msg[:300] or "未定位")
            sev = (diag.get("severity") or "medium").lower()
            diag["severity"] = sev if sev in ("low", "medium", "high") else "medium"
            diag.setdefault("suggested_actions", [])
            if not isinstance(diag["suggested_actions"], list):
                diag["suggested_actions"] = []
            diag.setdefault("related_files", [])
            if not isinstance(diag["related_files"], list):
                diag["related_files"] = [str(diag["related_files"])]
            try:
                diag["confidence"] = max(0.0, min(1.0, float(diag.get("confidence", 0.5))))
            except (TypeError, ValueError):
                diag["confidence"] = 0.5
            diag["created_at"] = datetime.utcnow().isoformat() + "Z"

            logger.info(
                "🩺 诊断: %s | 根因: %s | 置信度=%.2f",
                diag["symptom"][:80],
                diag["root_cause"][:100],
                diag["confidence"],
            )
        except Exception as e:
            logger.warning("🩺 诊断降级（LLM/JSON 失败）: %s", e)
            diag = _minimal_diagnosis(error_msg, note=f"LLM 失败: {e}")

        return ActionResult(success=True, data={"diagnosis": diag})
