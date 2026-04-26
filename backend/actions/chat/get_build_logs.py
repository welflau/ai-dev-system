"""
GetBuildLogsAction — 查询项目最近的构建日志和错误信息

对 LLM 暴露为 tool。AI 助手在以下场景自动调用：
- 用户说"编译报错了"/"Build 失败"/"出问题了"
- 用户上报 CI 构建相关问题

数据来源（合并两条路径）：
1. ci_builds 表：CI 触发路径（手动点"编译(UBT)"按钮等）
2. ticket_logs 表：SOP 驱动路径（orchestrator 跑 engine_compile/play_test/self_test stage）

返回最近 5 次构建的状态 + 错误摘要，让 AI 不再需要用户手动粘贴日志。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.get_build_logs")


class GetBuildLogsAction(ActionBase):

    @property
    def name(self) -> str:
        return "get_build_logs"

    @property
    def description(self) -> str:
        return "查询项目最近的构建/编译日志和错误详情"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "当用户提到编译失败、构建报错、UBT 错误、CI 出问题等情况时调用此工具。"
                "自动查询最近的构建记录、编译错误、测试失败信息，无需用户手动粘贴日志。\n\n"
                "适用场景：\n"
                "- '编译报错了' / '点了编译有错' / 'Build 失败'\n"
                "- 'UBT 出错了' / '有编译错误'\n"
                "- '测试失败' / 'CI 挂了'\n"
                "- 需要查看最近的构建状态时"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "返回最近几次构建记录，默认 5",
                        "default": 5,
                    },
                    "failed_only": {
                        "type": "boolean",
                        "description": "true=只返回失败记录，false=全部，默认 false",
                        "default": False,
                    },
                },
                "required": [],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="请在项目内使用此工具（未找到 project_id）")

        limit = min(int(context.get("limit") or 5), 20)
        failed_only = bool(context.get("failed_only", False))

        from database import db

        # ===== 1. CI 触发路径：ci_builds 表 =====
        status_filter = "AND status = 'failed'" if failed_only else ""
        ci_rows = await db.fetch_all(
            f"""SELECT id, build_type, branch, status, trigger, error_message,
                       build_log, created_at, completed_at, started_at
               FROM ci_builds
               WHERE project_id = ? {status_filter}
               ORDER BY created_at DESC LIMIT ?""",
            (project_id, limit),
        )

        ci_builds = []
        for row in ci_rows:
            build = {
                "source": "ci_trigger",
                "build_id": row["id"],
                "build_type": row["build_type"],
                "branch": row["branch"] or "-",
                "status": row["status"],
                "trigger": row["trigger"],
                "created_at": row["created_at"],
                "duration": _calc_duration(row.get("started_at"), row.get("completed_at")),
            }
            # 错误摘要
            if row.get("error_message"):
                build["error_summary"] = row["error_message"][:500]

            # 解析 build_log 找关键错误
            if row.get("build_log"):
                try:
                    log_steps = json.loads(row["build_log"]) if isinstance(row["build_log"], str) else row["build_log"]
                    failed_steps = [s for s in (log_steps or []) if not s.get("passed", True)]
                    if failed_steps:
                        build["failed_steps"] = [
                            {"step": s.get("step"), "msg": (s.get("msg") or "")[:300]}
                            for s in failed_steps[:3]
                        ]
                except Exception:
                    pass
            ci_builds.append(build)

        # ===== 2. SOP 驱动路径：ticket_logs 表（拉 reject 日志里的编译错误）=====
        reject_rows = await db.fetch_all(
            f"""SELECT tl.id, tl.ticket_id, tl.agent_type, tl.action,
                       tl.message, tl.detail, tl.created_at,
                       t.title, t.status
               FROM ticket_logs tl
               LEFT JOIN tickets t ON t.id = tl.ticket_id
               WHERE tl.project_id = ? AND tl.action = 'reject'
               {"AND tl.message LIKE '%失败%' OR tl.message LIKE '%error%' OR tl.message LIKE '%ERROR%'" if failed_only else ""}
               ORDER BY tl.created_at DESC LIMIT ?""",
            (project_id, limit),
        )

        sop_failures = []
        for row in reject_rows:
            fail = {
                "source": "sop_stage",
                "ticket_id": row["ticket_id"],
                "ticket_title": row.get("title") or "-",
                "ticket_status": row.get("status") or "-",
                "agent": row["agent_type"],
                "message": (row["message"] or "")[:300],
                "created_at": row["created_at"],
            }
            # 结构化错误详情（engine_compile_failed / play_test_failed / self_test_failed）
            if row.get("detail"):
                try:
                    det = json.loads(row["detail"]) if isinstance(row["detail"], str) else row["detail"]
                    # UBT 编译错误
                    errors = det.get("errors") or []
                    if errors:
                        fail["compile_errors"] = [
                            {
                                "file": (e.get("file") or "?").split("\\")[-1].split("/")[-1],
                                "line": e.get("line"),
                                "code": e.get("code"),
                                "msg": (e.get("msg") or "")[:180],
                                "category": e.get("category"),
                            }
                            for e in errors[:5]
                        ]
                    # UE lint 静态错误
                    issues = det.get("issues") or []
                    if issues:
                        fail["lint_issues"] = [
                            {
                                "rule": i.get("rule"),
                                "file": (i.get("file") or "?").split("/")[-1],
                                "line": i.get("line"),
                                "msg": (i.get("msg") or "")[:180],
                                "suggest": (i.get("suggest") or "")[:100],
                            }
                            for i in issues[:5]
                        ]
                    # playtest 失败
                    tests = det.get("tests") or []
                    if tests:
                        fail["failed_tests"] = [
                            {"name": t.get("name"), "errors": (t.get("errors") or [])[:2]}
                            for t in tests[:3]
                        ]
                    fail["err_brief"] = det.get("err_brief") or ""
                except Exception:
                    pass
            sop_failures.append(fail)

        # ===== 汇总 =====
        all_recent = ci_builds + sop_failures
        has_failures = any(
            (r.get("status") in ("failed",) or r.get("action") == "reject")
            for r in all_recent
        )

        result = {
            "type": "build_logs",
            "project_id": project_id,
            "ci_builds": ci_builds,
            "sop_failures": sop_failures,
            "total_ci": len(ci_builds),
            "total_sop": len(sop_failures),
            "has_failures": has_failures,
            "summary": _make_summary(ci_builds, sop_failures),
        }

        return ActionResult(
            success=True,
            data=result,
            message=f"找到 {len(ci_builds)} 条 CI 构建记录 + {len(sop_failures)} 条工单失败记录",
        )


def _calc_duration(started_at: Optional[str], completed_at: Optional[str]) -> Optional[str]:
    if not started_at or not completed_at:
        return None
    try:
        from datetime import datetime
        fmt = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
        t0, t1 = fmt(started_at), fmt(completed_at)
        if t0 and t1:
            sec = int((t1 - t0).total_seconds())
            if sec >= 60:
                return f"{sec // 60}m {sec % 60}s"
            return f"{sec}s"
    except Exception:
        pass
    return None


def _make_summary(ci: list, sop: list) -> str:
    lines = []
    failed_ci = [r for r in ci if r.get("status") == "failed"]
    if failed_ci:
        r = failed_ci[0]
        lines.append(f"最近 CI 构建失败：{r['build_type']} · {r.get('error_summary') or r.get('failed_steps', [{}])[0].get('msg', '')[:200]}")
    elif ci:
        r = ci[0]
        lines.append(f"最近 CI 构建：{r['build_type']} · {r['status']}")

    failed_sop = [r for r in sop if r]
    if failed_sop:
        r = failed_sop[0]
        ce = r.get("compile_errors") or r.get("lint_issues") or r.get("failed_tests") or []
        brief = r.get("err_brief") or r.get("message") or ""
        lines.append(f"最近工单失败：{r.get('ticket_title')} · {brief[:200]}")
        if ce:
            top = ce[0]
            f = top.get("file") or top.get("name", "?")
            m = top.get("msg") or top.get("errors", ["?"])[0] if isinstance(top.get("errors"), list) else "?"
            lines.append(f"  首个错误：{f} — {m[:150]}")

    if not lines:
        return "未找到近期失败记录"
    return "\n".join(lines)
