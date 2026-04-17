"""
GetRequirementPipelineAction — 返回指定需求的 Pipeline 视图精简版

面向 AI 助手："XX 需求卡在哪 / 阻塞点在哪"类问题。
不照搬前端可视化的完整结构（那个有 ~300 行重逻辑），只给出判断卡点所需的最小信息：
- 需求基本信息
- 5 个阶段的 pending/running/done 状态
- 当前正在跑的工单 + 上次活动时间（LLM 据此判断是否真卡住）
- 最近一条 ticket_logs（便于分析失败原因）
"""
import logging
from datetime import datetime
from typing import Any, Dict, List

from actions.base import ActionBase, ActionResult
from database import db

logger = logging.getLogger("actions.chat.get_requirement_pipeline")


# 和 api/requirements.py 的 STAGE_DEFS 保持一致的判定规则
_STAGE_DEFS = [
    {"key": "requirement_analysis", "name": "需求分析"},
    {"key": "architecture",         "name": "架构设计"},
    {"key": "development",          "name": "开发实现"},
    {"key": "testing",              "name": "测试验证"},
    {"key": "merge_develop",        "name": "合入Develop"},
]

# 每阶段状态的"已完成"集合（票据状态 ∈ 这个集合 ⇒ 该阶段已过）
_PAST = {
    "architecture": {"architecture_done", "development_in_progress", "development_done",
                     "acceptance_passed", "acceptance_rejected", "testing_in_progress",
                     "testing_done", "testing_failed", "deploying", "deployed"},
    "development": {"development_done", "acceptance_passed", "acceptance_rejected",
                    "testing_in_progress", "testing_done", "testing_failed",
                    "deploying", "deployed"},
    "testing": {"testing_done", "deploying", "deployed"},
}

_RUNNING_TICKET_STATUSES = {
    "architecture_in_progress", "development_in_progress",
    "acceptance_rejected",  # 等返工也算"在跑"
    "testing_in_progress", "testing_failed",
    "deploying",
}


def _calc_minutes_since(iso_str: str) -> int:
    """返回距某个 ISO 时间的分钟数；解析失败返回 -1"""
    if not iso_str:
        return -1
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        return max(0, int((now - dt).total_seconds() / 60))
    except Exception:
        return -1


class GetRequirementPipelineAction(ActionBase):

    @property
    def name(self) -> str:
        return "get_requirement_pipeline"

    @property
    def description(self) -> str:
        return "查看某需求的 Pipeline 进度（各阶段状态 + 当前卡住的工单 + 最近活动）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "查看某个需求的开发 Pipeline 进度，用于诊断『XX 需求卡在哪』『阻塞点在哪』类问题。"
                "返回 5 阶段（需求分析/架构设计/开发实现/测试验证/合入Develop）各自状态，"
                "以及当前正在跑的工单列表（含停滞时长）和最近一条活动日志。"
                "requirement_id 不明确时可传标题关键词，会自动模糊匹配。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "requirement_id": {
                        "type": "string",
                        "description": "需求 ID（REQ-...）或标题关键词",
                    },
                },
                "required": ["requirement_id"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="缺少 project_id")

        requirement_id = (context.get("requirement_id") or "").strip()
        if not requirement_id:
            return ActionResult(success=False, data={"type": "error", "message": "需求 ID/关键词不能为空"})

        # 定位需求：先精确，再模糊
        req = await db.fetch_one(
            "SELECT * FROM requirements WHERE id = ? AND project_id = ?",
            (requirement_id, project_id),
        )
        if not req:
            req = await db.fetch_one(
                "SELECT * FROM requirements WHERE project_id = ? AND title LIKE ? ORDER BY created_at DESC LIMIT 1",
                (project_id, f"%{requirement_id}%"),
            )
            if not req:
                return ActionResult(
                    success=False,
                    data={"type": "error", "message": f"未找到需求「{requirement_id}」"},
                )
            requirement_id = req["id"]

        req_status = req["status"]

        # 拉工单（branch_name 在 requirements 表上，不是 tickets 表）
        tickets = await db.fetch_all(
            "SELECT id, title, status, updated_at FROM tickets WHERE requirement_id = ? ORDER BY sort_order, created_at",
            (requirement_id,),
        )

        # 5 阶段状态判定
        stages: List[Dict[str, Any]] = []

        # 阶段 1：需求分析（看需求本身 status）
        if req_status == "submitted":
            a_stage_status = "pending"
        elif req_status == "analyzing":
            a_stage_status = "running"
        elif req_status == "cancelled":
            a_stage_status = "cancelled"
        else:
            a_stage_status = "done"
        stages.append({"key": "requirement_analysis", "name": "需求分析", "status": a_stage_status})

        # 阶段 2-4：看工单 status 的分布
        # 每阶段"正在跑"对应的 ticket status 集合
        _RUNNING_FOR_STAGE = {
            "architecture": {"architecture_in_progress"},
            "development": {"development_in_progress", "acceptance_rejected"},
            "testing": {"testing_in_progress", "acceptance_passed", "testing_failed"},
        }
        _STAGE_NAME = {s["key"]: s["name"] for s in _STAGE_DEFS}
        for key in ("architecture", "development", "testing"):
            if not tickets:
                stages.append({"key": key, "name": _STAGE_NAME[key], "status": "pending"})
                continue
            non_cancelled = [t for t in tickets if t["status"] != "cancelled"]
            if not non_cancelled:
                stage_status = "cancelled"
            elif all(t["status"] in _PAST[key] for t in non_cancelled):
                stage_status = "done"
            elif any(t["status"] in _RUNNING_FOR_STAGE[key] for t in non_cancelled):
                stage_status = "running"
            else:
                stage_status = "pending"
            stages.append({"key": key, "name": _STAGE_NAME[key], "status": stage_status})

        # 阶段 5：合入 develop
        if req_status == "completed":
            m_stage_status = "done"
        elif tickets and all(t["status"] in {"testing_done", "deployed", "cancelled"} for t in tickets):
            m_stage_status = "running"
        elif req_status == "cancelled":
            m_stage_status = "cancelled"
        else:
            m_stage_status = "pending"
        stages.append({"key": "merge_develop", "name": "合入Develop", "status": m_stage_status})

        # 当前运行/卡顿工单
        running_tickets = []
        for t in tickets:
            if t["status"] in _RUNNING_TICKET_STATUSES:
                idle_min = _calc_minutes_since(t["updated_at"])
                running_tickets.append({
                    "id": t["id"],
                    "title": t["title"],
                    "status": t["status"],
                    "idle_minutes": idle_min,
                })

        # 最近一条活动
        last_log = await db.fetch_one(
            """SELECT agent_type, action, from_status, to_status, level, detail, created_at
               FROM ticket_logs WHERE requirement_id = ? ORDER BY created_at DESC LIMIT 1""",
            (requirement_id,),
        )
        last_activity = None
        if last_log:
            last_activity = {
                "agent": last_log["agent_type"],
                "action": last_log["action"],
                "transition": f"{last_log['from_status']} → {last_log['to_status']}" if last_log["to_status"] else None,
                "level": last_log["level"],
                "at": last_log["created_at"],
                "minutes_ago": _calc_minutes_since(last_log["created_at"]),
                "detail": (last_log["detail"] or "")[:300],  # 截断以省 token
            }

        data = {
            "type": "requirement_pipeline",
            "requirement": {
                "id": requirement_id,
                "title": req["title"],
                "status": req_status,
                "priority": req.get("priority"),
                "branch_name": req.get("branch_name"),
                "created_at": req["created_at"],
                "completed_at": req.get("completed_at"),
            },
            "stages": stages,
            "ticket_count_total": len(tickets),
            "ticket_count_by_status": _count_by_status(tickets),
            "running_tickets": running_tickets,   # 卡顿诊断核心字段
            "last_activity": last_activity,
        }

        logger.info(
            "查询需求 Pipeline: %s（%d 个工单，%d 个在跑）",
            requirement_id, len(tickets), len(running_tickets),
        )

        return ActionResult(success=True, data=data)


def _count_by_status(tickets: List[Dict]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for t in tickets:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    return counts
