"""
AI 自动开发系统 - 工单 API
"""
import json
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks, Body
from database import db
from models import (
    TicketStatus,
    TicketUpdate,
    TicketRejectRequest,
    DirectTicketCreate,
    validate_ticket_transition,
    STATUS_LABELS,
    BOARD_COLUMNS,
)
from utils import generate_id, now_iso

logger = logging.getLogger("api.tickets")
from events import event_manager

router = APIRouter(tags=["tickets"])

# 后台任务面板「停止」可取消的在途状态（不含人审 *_ready，避免误关确认卡）
_STOPPABLE_TICKET_STATUSES = (
    "pending", "queued", "todo",
    "running", "in_progress", "executing",
    "waiting_subtasks",
)
_UNSTOPPABLE_TICKET_STATUSES = {
    "cancelled", "blocked", "deployed", "completed", "done", "success", "error",
}
_UNSTOPPABLE_TICKET_SUFFIXES = ("_ready", "_done", "_failed", "_rejected", "_passed")


def ticket_status_is_stoppable(status: str) -> bool:
    """pending / in_progress / director_visual_in_progress 可停；人审 *_ready 不停。"""
    s = (status or "").strip()
    if not s or s in _UNSTOPPABLE_TICKET_STATUSES:
        return False
    if s.endswith(_UNSTOPPABLE_TICKET_SUFFIXES):
        return False
    if s in _STOPPABLE_TICKET_STATUSES:
        return True
    return s.endswith("_in_progress")


def compute_ticket_action_progress(
    started_at: str | None,
    updated_at: str | None,
    *,
    now: datetime | None = None,
) -> dict:
    """elapsed / silence / health。

    `now_iso()` 写的是本地 naive ISO。若按 UTC 解析，东八区会出现负 elapsed，
    health 会一直是 active，前端就永远不提示「卡住了」。
    """
    now_aw = now or datetime.now().astimezone()
    if now_aw.tzinfo is None:
        now_aw = now_aw.replace(tzinfo=datetime.now().astimezone().tzinfo)

    def _parse(s: str | None):
        if not s:
            return None
        raw = str(s).strip()
        try:
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            dt = datetime.fromisoformat(raw)
        except Exception:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=now_aw.tzinfo)
        return dt.astimezone(now_aw.tzinfo)

    started = _parse(started_at)
    updated = _parse(updated_at)

    elapsed_ms = None
    if started is not None:
        elapsed_ms = max(0, int((now_aw - started).total_seconds() * 1000))

    silence_ms = None
    if updated is not None:
        silence_ms = max(0, int((now_aw - updated).total_seconds() * 1000))

    if updated is None:
        if elapsed_ms is None or elapsed_ms < 60_000:
            health = "starting"
        elif elapsed_ms < 300_000:
            health = "silent"
        else:
            health = "zombie"
    elif silence_ms is None or silence_ms < 60_000:
        health = "active"
    elif silence_ms < 300_000:
        health = "silent"
    else:
        health = "zombie"

    return {
        "elapsed_ms": elapsed_ms,
        "silence_ms": silence_ms,
        "health": health,
    }


def _cancelled_ticket_fields() -> dict:
    return {
        "status": "cancelled",
        "updated_at": now_iso(),
        "current_action": None,
        "current_action_latest_log": None,
    }


def _posix_rel(path) -> str:
    return str(path or "").replace("\\", "/").strip().lstrip("./")


def _gate_matches_ticket(data: dict | None, ticket_id: str) -> bool:
    if not isinstance(data, dict):
        return False
    gid = str(data.get("ticket_id") or "")
    if gid and ticket_id and gid != ticket_id:
        return False
    return True


def _gate_paths(data: dict | None) -> list:
    if not isinstance(data, dict):
        return []
    paths = [p for p in (data.get("preview_paths") or []) if p]
    for item in data.get("preview_urls") or []:
        if isinstance(item, dict) and item.get("path"):
            paths.append(item["path"])
    return paths


def _paths_have_video_clip(paths) -> bool:
    for p in paths or []:
        s = str(p or "").replace("\\", "/").lower()
        if s.endswith(".mp4") or s.endswith(".webm"):
            return True
    return False


def _gate_fits_status(data: dict | None, status: str) -> bool:
    """试片确认卡必须带 mp4；别的阶段的旧卡不能拿来充数。"""
    if not isinstance(data, dict):
        return False
    if str(status or "") == "director_clip_trial_ready":
        return _paths_have_video_clip(_gate_paths(data))
    return True


def collect_ticket_output_files(
    *,
    artifacts=None,
    result=None,
    pending_gate=None,
    ticket_id: str = "",
) -> list:
    """工单可点开的产物路径：确认卡 preview > result > artifacts 表。"""
    paths: list = []
    seen = set()

    def add(raw) -> None:
        s = _posix_rel(raw)
        if not s or s.endswith(".ads-waiting-human.json") or s in seen:
            return
        seen.add(s)
        paths.append(s)

    gate = pending_gate if isinstance(pending_gate, dict) else {}
    if not _gate_matches_ticket(gate, ticket_id):
        gate = {}
    for p in gate.get("preview_paths") or []:
        add(p)
    for item in gate.get("preview_urls") or []:
        if isinstance(item, dict):
            add(item.get("path"))

    result = result if isinstance(result, dict) else {}
    waiting = result.get("waiting_human") if isinstance(result.get("waiting_human"), dict) else {}
    if not _gate_matches_ticket(waiting, ticket_id):
        waiting = {}
    for p in (waiting or {}).get("preview_paths") or []:
        add(p)
    for art in result.get("artifacts") or []:
        if isinstance(art, dict):
            add(art.get("path"))
    for out in result.get("outputs") or []:
        s = _posix_rel(out)
        if not s:
            continue
        if s.startswith(("works/", "artifacts/", "docs/")):
            add(s)
        elif "/" in s:
            add("works/" + s)
        else:
            add(s)

    for art in artifacts or []:
        if isinstance(art, dict):
            add(art.get("path"))
    return paths[:30]


def _parse_ticket_result(ticket: dict) -> dict:
    raw = (ticket or {}).get("result")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


_READY_GATE_TITLES = {
    "director_brief_ready": "确认 Mode 与简报",
    "director_script_ready": "确认讲稿与拆解",
    "director_visual_ready": "确认人物与音色",
    "director_clip_trial_ready": "确认试生成片段",
}


def _normalize_pending_gate(raw: dict, ticket: dict | None) -> dict:
    data = dict(raw or {})
    data["type"] = data.get("type") or "confirm_video_gate"
    data["waiting_human"] = True
    data["_state"] = "pending"
    if ticket:
        data["ticket_id"] = data.get("ticket_id") or ticket.get("id") or ""
        data["project_id"] = data.get("project_id") or ticket.get("project_id") or ""
        status = str(ticket.get("status") or "")
        if not data.get("title"):
            data["title"] = _READY_GATE_TITLES.get(status, "确认当前制作产物")
    data.setdefault("title", "确认当前制作产物")
    data.setdefault("summary", "")
    data.setdefault("preview_paths", [])
    data.setdefault("preview_urls", [])
    data.setdefault("work_slug", "")
    return data


async def _chat_pending_video_gate(project_id: str, ticket_id: str):
    from database import db as _db
    try:
        rows = await _db.fetch_all(
            """SELECT id, session_id, action_data, action_state, created_at
               FROM chat_messages
               WHERE project_id = ? AND action_type = 'confirm_video_gate'
               ORDER BY created_at DESC LIMIT 30""",
            (project_id,),
        )
    except Exception as e:
        logger.debug("读取 pending gate 失败: %s", e)
        return None
    for row in rows or []:
        try:
            data = json.loads(row.get("action_data") or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        if str(data.get("ticket_id") or "") != ticket_id:
            continue
        state = str(row.get("action_state") or data.get("_state") or "pending")
        data["_message_id"] = row.get("id") or data.get("_message_id") or ""
        data["session_id"] = row.get("session_id") or data.get("session_id") or ""
        data["_state"] = state
        if state == "pending":
            return data
    return None


async def _gate_message_still_pending(message_id: str) -> bool:
    mid = str(message_id or "").strip()
    if not mid:
        return True
    from database import db as _db
    try:
        row = await _db.fetch_one(
            "SELECT action_state FROM chat_messages WHERE id = ?", (mid,),
        )
    except Exception:
        return True
    if not row:
        return True
    return str(row.get("action_state") or "pending") == "pending"


async def _gate_from_work_marker(project_id: str, ticket: dict | None):
    """CLI 人审卡常写在 works/<slug>/.ads-waiting-human.json，对话里可能没有。"""
    from database import db as _db
    from pathlib import Path
    row = await _db.fetch_one(
        "SELECT git_repo_path FROM projects WHERE id = ?", (project_id,),
    )
    repo = str((row or {}).get("git_repo_path") or "")
    if not repo:
        return None
    works = Path(repo) / "works"
    if not works.is_dir():
        return None
    tid = str((ticket or {}).get("id") or "")
    status = str((ticket or {}).get("status") or "")
    markers = sorted(
        works.glob("*/.ads-waiting-human.json"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    for path in markers:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or not data.get("waiting_human"):
            continue
        if not _gate_matches_ticket(data, tid):
            continue
        if tid and not str(data.get("ticket_id") or ""):
            continue
        if not _gate_fits_status(data, status):
            continue
        if not await _gate_message_still_pending(data.get("_message_id") or ""):
            continue
        return _normalize_pending_gate(data, ticket)
    return None


async def load_ticket_pending_gate(project_id: str, ticket_id: str, ticket=None):
    """工单抽屉的人审卡。对话里有 pending 卡优先；没有时，*_ready 工单从 result / 工作包标记合成。"""
    from database import db as _db
    if not project_id or not ticket_id:
        return None
    chat_gate = await _chat_pending_video_gate(project_id, ticket_id)
    if chat_gate:
        return chat_gate
    if ticket is None:
        try:
            ticket = await _db.fetch_one(
                "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
                (ticket_id, project_id),
            )
        except Exception:
            ticket = None
    status = str((ticket or {}).get("status") or "")
    if not status.endswith("_ready"):
        return None
    result = _parse_ticket_result(ticket or {})
    waiting = result.get("waiting_human") if isinstance(result.get("waiting_human"), dict) else {}
    if (
        _gate_matches_ticket(waiting, ticket_id)
        and _gate_fits_status(waiting, status)
        and (waiting.get("waiting_human") or waiting.get("preview_paths") or waiting.get("title"))
        and await _gate_message_still_pending(waiting.get("_message_id") or "")
    ):
        return _normalize_pending_gate(waiting, ticket)
    disk = await _gate_from_work_marker(project_id, ticket)
    if disk:
        return disk
    files = collect_ticket_output_files(result=result, ticket_id=ticket_id)
    if status == "director_clip_trial_ready" and not _paths_have_video_clip(files):
        return None
    if not files and not waiting:
        return None
    return _normalize_pending_gate({
        "title": _READY_GATE_TITLES.get(status, "确认当前制作产物"),
        "preview_paths": files,
    }, ticket)


def _synthetic_output_artifacts(paths: list) -> list:
    now = now_iso()
    rows = []
    for i, path in enumerate(paths or []):
        rel = _posix_rel(path)
        if not rel:
            continue
        name = rel.rsplit("/", 1)[-1]
        rows.append({
            "id": f"SYN-OUT-{i}",
            "type": "file",
            "kind": "",
            "name": name,
            "path": rel,
            "content": None,
            "metadata": None,
            "created_at": now,
        })
    return rows


async def _abort_ticket_runtime(ticket_id: str) -> int:
    """释放编排占用并杀掉该工单在途 CLI（codebuddy 进程树）。"""
    try:
        from orchestrator import orchestrator
        orchestrator._release_ticket(ticket_id)
    except Exception:
        pass
    try:
        from llm_client import abort_ticket_cli
        return int(await abort_ticket_cli(ticket_id) or 0)
    except Exception as e:
        logger.warning("终止工单 CLI 失败 %s: %s", (ticket_id or "")[:12], e)
        return 0


async def _publish_ticket_cancelled(project_id: str, ticket_id: str, old_status: str) -> None:
    if not project_id:
        return
    try:
        await event_manager.publish_to_project(
            project_id,
            "ticket_status_changed",
            {"ticket_id": ticket_id, "from": old_status, "to": "cancelled", "agent": "Operator"},
        )
    except Exception:
        pass


async def _cancel_ticket_status_only(row: dict, message: str = "工单已取消") -> None:
    """只改状态、停 CLI、释放编排器占用，不回滚仓库。"""
    tid = row["id"]
    old = row.get("status") or ""
    await db.update(
        "tickets",
        _cancelled_ticket_fields(),
        "id = ?",
        (tid,),
    )
    await _abort_ticket_runtime(tid)
    try:
        await _log_ticket(
            row.get("project_id"), row.get("requirement_id"), tid,
            None, "cancelled", old, "cancelled", message,
        )
    except Exception:
        pass
    await _publish_ticket_cancelled(row.get("project_id") or "", tid, old)


# ==================== 工单 CRUD ====================


@router.get("/api/projects/{project_id}/tickets")
async def list_tickets(
    project_id: str,
    status: str = None,
    module: str = None,
    requirement_id: str = None,
):
    """获取工单列表（支持筛选）"""
    sql = "SELECT * FROM tickets WHERE project_id = ?"
    params = [project_id]

    if status:
        sql += " AND status = ?"
        params.append(status)
    if module:
        sql += " AND module = ?"
        params.append(module)
    if requirement_id:
        sql += " AND requirement_id = ?"
        params.append(requirement_id)

    sql += " ORDER BY priority ASC, sort_order ASC, created_at ASC"
    tickets = await db.fetch_all(sql, tuple(params))

    # 附带子任务数 + 子工单数
    for t in tickets:
        st_count = await db.fetch_one(
            "SELECT COUNT(*) as count FROM subtasks WHERE ticket_id = ?", (t["id"],)
        )
        t["subtask_count"] = st_count["count"] if st_count else 0

        child_count = await db.fetch_one(
            "SELECT COUNT(*) as count FROM tickets WHERE parent_ticket_id = ?", (t["id"],)
        )
        t["child_ticket_count"] = child_count["count"] if child_count else 0
        t["status_label"] = STATUS_LABELS.get(t["status"], t["status"])

        # 计算警告 / 错误标记（用于前端标题图标提示）
        has_error = t["status"] in ("testing_failed", "acceptance_rejected", "cancelled")
        has_warning = False
        if not has_error:
            # 从 result JSON 中检测测试警告（pass_rate < 100 但仍 passed）
            result_raw = t.get("result")
            if result_raw:
                try:
                    result_obj = json.loads(result_raw) if isinstance(result_raw, str) else result_raw
                    test_result = result_obj.get("test_result", {})
                    summary = test_result.get("summary", {}) if isinstance(test_result, dict) else {}
                    if isinstance(summary, dict):
                        pass_rate = summary.get("pass_rate", 100)
                        issues = summary.get("issues", [])
                        if pass_rate < 100 or issues:
                            has_warning = True
                except Exception:
                    pass
        t["has_warning"] = has_warning
        t["has_error"] = has_error

    return {"tickets": tickets, "total": len(tickets)}


@router.get("/api/projects/{project_id}/tickets/{ticket_id}")
async def get_ticket(project_id: str, ticket_id: str):
    """获取工单详情"""
    ticket = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not ticket:
        raise HTTPException(404, "工单不存在")

    # 终态但 OpenSpec 停在 applied/proposed：后台软收尾 Verify→Archive（不阻塞响应）
    try:
        _st = ticket.get("status") or ""
        _os = (ticket.get("openspec_stage") or "").strip()
        if _st in ("testing_done", "deployed", "done") and _os in ("proposed", "applied", "verified"):
            import asyncio
            from orchestrator import orchestrator as _orch
            asyncio.create_task(_orch._finalize_openspec_after_done(project_id, ticket_id))
    except Exception:
        pass

    # 子任务
    subtasks = await db.fetch_all(
        "SELECT * FROM subtasks WHERE ticket_id = ? ORDER BY sort_order, created_at",
        (ticket_id,),
    )

    # 日志
    logs = await db.fetch_all(
        "SELECT * FROM ticket_logs WHERE ticket_id = ? ORDER BY created_at DESC LIMIT 100",
        (ticket_id,),
    )

    # 产物
    artifacts = await db.fetch_all(
        "SELECT * FROM artifacts WHERE ticket_id = ? ORDER BY created_at DESC",
        (ticket_id,),
    )

    # 子工单
    child_tickets = await db.fetch_all(
        "SELECT * FROM tickets WHERE parent_ticket_id = ? ORDER BY sort_order, created_at",
        (ticket_id,),
    )
    for ct in child_tickets:
        ct["status_label"] = STATUS_LABELS.get(ct["status"], ct["status"])

    ticket["status_label"] = STATUS_LABELS.get(ticket["status"], ticket["status"])

    # 获取需求的分支名
    branch_name = None
    if ticket.get("requirement_id"):
        req = await db.fetch_one(
            "SELECT branch_name FROM requirements WHERE id = ?",
            (ticket["requirement_id"],),
        )
        if req:
            branch_name = req.get("branch_name")

    # 获取来源消息摘要（用于工单抽屉"创建来源"区块）
    source_message = None
    if ticket.get("source_message_id"):
        src = await db.fetch_one(
            "SELECT id, session_id, content, created_at FROM chat_messages WHERE id = ?",
            (ticket["source_message_id"],),
        )
        if src:
            snippet = (src.get("content") or "")[:120].replace("\n", " ")
            source_message = {
                "message_id": src["id"],
                "session_id": src.get("session_id") or ticket.get("source_session_id"),
                "created_at": src.get("created_at"),
                "snippet": snippet,
            }

    ticket_result = _parse_ticket_result(ticket)
    pending_gate = await load_ticket_pending_gate(project_id, ticket_id, ticket=ticket)
    output_files = collect_ticket_output_files(
        artifacts=artifacts, result=ticket_result, pending_gate=pending_gate,
    )
    if pending_gate and not pending_gate.get("preview_paths") and output_files:
        pending_gate["preview_paths"] = output_files
    existing_paths = {_posix_rel((a or {}).get("path")) for a in (artifacts or [])}
    extra_files = [p for p in output_files if p not in existing_paths]
    if extra_files:
        artifacts = list(artifacts or []) + _synthetic_output_artifacts(extra_files)

    return {
        **ticket,
        "branch_name": branch_name,
        "source_message": source_message,
        "subtasks": subtasks,
        "logs": logs,
        "artifacts": artifacts,
        "child_tickets": child_tickets,
        "pending_gate": pending_gate,
        "output_files": output_files,
    }


@router.get("/api/projects/{project_id}/tickets/{ticket_id}/current-action")
async def get_ticket_current_action(project_id: str, ticket_id: str):
    """v0.19.x 工单面板「📍 当前进度」区数据源

    返回 current_action / started_at / latest_log / updated_at + 后端算好的
    elapsed_ms / silence_ms / health，让前端直接渲染不用自己算。
    """
    ticket = await db.fetch_one(
        "SELECT id, current_action, current_action_started_at, "
        "current_action_latest_log, current_action_updated_at "
        "FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not ticket:
        raise HTTPException(404, "工单不存在")

    current_action = ticket.get("current_action")
    if not current_action:
        return {
            "ticket_id": ticket_id,
            "current_action": None,
            "health": None,
        }

    prog = compute_ticket_action_progress(
        ticket.get("current_action_started_at"),
        ticket.get("current_action_updated_at"),
    )
    return {
        "ticket_id": ticket_id,
        "current_action": current_action,
        "started_at": ticket.get("current_action_started_at"),
        "elapsed_ms": prog["elapsed_ms"],
        "latest_log": ticket.get("current_action_latest_log"),
        "latest_log_at": ticket.get("current_action_updated_at"),
        "silence_ms": prog["silence_ms"],
        "health": prog["health"],
    }


@router.get("/api/projects/{project_id}/_tickets-current-actions")
async def get_tickets_current_actions(project_id: str, ids: str = ""):
    """批量查多个工单的 current_action。ids=T1,T2,T3 逗号分隔。

    看板页面场景：多工单同屏显示"⚡ 运行中"徽标时批量拉一次，避免 N 个请求。
    """
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if not id_list:
        return {"items": {}}

    placeholders = ",".join(["?"] * len(id_list))
    rows = await db.fetch_all(
        f"SELECT id, current_action FROM tickets "
        f"WHERE project_id = ? AND id IN ({placeholders}) "
        f"AND current_action IS NOT NULL",
        (project_id, *id_list),
    )
    return {"items": {r["id"]: r["current_action"] for r in rows}}


@router.put("/api/projects/{project_id}/tickets/{ticket_id}")
async def update_ticket(project_id: str, ticket_id: str, req: TicketUpdate):
    """更新工单基本信息"""
    existing = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")

    update_data = {k: v for k, v in req.dict(exclude_unset=True).items() if v is not None}
    if update_data:
        update_data["updated_at"] = now_iso()
        await db.update("tickets", update_data, "id = ?", (ticket_id,))

    return await get_ticket(project_id, ticket_id)


@router.delete("/api/projects/{project_id}/tickets/{ticket_id}")
async def cancel_ticket(
    project_id: str,
    ticket_id: str,
    revert: bool = False,
):
    """取消工单。

    revert=true 时优先 Checkpoint 还原到 ticket_start；无快照则 Git 路径级回滚。
    默认 revert=false，仅改状态。
    """
    existing = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")

    if existing["status"] == "deployed":
        raise HTTPException(400, "工单已完成或已取消")
    if existing["status"] == "cancelled":
        # 状态已经 cancelled，但仍可能有 CLI 在跑（上次只改了库、没杀进程）
        n = await _abort_ticket_runtime(ticket_id)
        await _publish_ticket_cancelled(project_id, ticket_id, "cancelled")
        return {
            "message": "已停止运行中的任务" if n else "工单已取消",
            "reverted": False,
            "killed": n,
        }

    old_status = existing["status"]
    revert_result = None

    await db.update(
        "tickets",
        _cancelled_ticket_fields(),
        "id = ?",
        (ticket_id,),
    )
    await _abort_ticket_runtime(ticket_id)

    if revert:
        try:
            revert_result = await _revert_ticket_changes(project_id, ticket_id, existing)
        except Exception as e:
            logger.warning("取消工单 revert 失败（仍将取消状态）: %s", e, exc_info=True)
            revert_result = {"ok": False, "error": str(e)}

    msg = "工单已取消"
    if revert:
        rr = revert_result or {}
        strategy = rr.get("strategy") or "git"
        n = len(rr.get("restored") or []) + len(rr.get("deleted") or [])
        if rr.get("openspec_removed"):
            n += 1
        if n:
            msg = f"工单已取消并回滚（{strategy}，{n} 项）"
        else:
            msg = f"工单已取消（{strategy}，无可回滚改动）"

    await _log_ticket(
        project_id, existing["requirement_id"], ticket_id,
        None, "cancelled", old_status, "cancelled", msg
    )
    await _publish_ticket_cancelled(project_id, ticket_id, old_status)
    if revert and revert_result:
        try:
            action = "checkpoint_restore" if revert_result.get("strategy") == "checkpoint" else "revert"
            detail_payload = dict(revert_result) if isinstance(revert_result, dict) else {"raw": revert_result}
            if isinstance(detail_payload, dict) and "message" not in detail_payload:
                detail_payload["message"] = _format_restore_message(detail_payload) if action == "checkpoint_restore" else msg
            await _log_ticket(
                project_id, existing["requirement_id"], ticket_id,
                "Operator", action, old_status, "cancelled",
                json.dumps(detail_payload, ensure_ascii=False)[:2000],
                level="info" if revert_result.get("ok", True) else "warning",
            )
        except Exception:
            pass

    return {
        "message": msg,
        "reverted": bool(revert),
        "revert": revert_result,
    }


@router.post("/api/projects/{project_id}/checkpoints/gc")
async def run_checkpoint_gc(project_id: str, body: dict = Body(default={})):
    """手动触发 Checkpoint GC（TTL + 孤儿 blob）。project_id 仅作鉴权锚点。"""
    project = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")
    from checkpoint.service import checkpoint_service
    ttl = int(body.get("ttl_days") or 14)
    keep = int(body.get("keep_active_writes") or 50)
    stats = await checkpoint_service.gc_expired(ttl_days=max(1, ttl), keep_active_writes=max(5, keep))
    return {"ok": True, "project_id": project_id, **stats}


@router.get("/api/projects/{project_id}/tickets/{ticket_id}/checkpoints")
async def list_ticket_checkpoints(project_id: str, ticket_id: str):
    existing = await db.fetch_one(
        "SELECT id FROM tickets WHERE id=? AND project_id=?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")
    from checkpoint.service import checkpoint_service
    items = await checkpoint_service.list_checkpoints(ticket_id)
    return {"checkpoints": items, "total": len(items)}


@router.get("/api/projects/{project_id}/tickets/{ticket_id}/checkpoints/{checkpoint_id}")
async def get_ticket_checkpoint(project_id: str, ticket_id: str, checkpoint_id: str):
    existing = await db.fetch_one(
        "SELECT id FROM tickets WHERE id=? AND project_id=?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")
    from checkpoint.service import checkpoint_service
    item = await checkpoint_service.get_checkpoint(checkpoint_id, ticket_id)
    if not item:
        raise HTTPException(404, "checkpoint 不存在")
    return item


@router.post("/api/projects/{project_id}/tickets/{ticket_id}/checkpoints/{checkpoint_id}/restore")
async def restore_ticket_checkpoint(
    project_id: str, ticket_id: str, checkpoint_id: str, body: dict = Body(default={}),
):
    if not body.get("confirm"):
        raise HTTPException(400, "需要 confirm=true")
    existing = await db.fetch_one(
        "SELECT * FROM tickets WHERE id=? AND project_id=?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")
    from checkpoint.service import checkpoint_service
    project = await db.fetch_one("SELECT mode FROM projects WHERE id=?", (project_id,))
    mode = (project or {}).get("mode", "auto")
    result = await checkpoint_service.restore_after_checkpoint(
        project_id, ticket_id, checkpoint_id,
        commit=(mode != "manual"),
        message=f"[Operator] restore checkpoint {checkpoint_id[-8:]} ({ticket_id[-8:]})",
    )
    try:
        await _log_ticket(
            project_id, existing["requirement_id"], ticket_id,
            "Operator", "checkpoint_restore", existing["status"], existing["status"],
            json.dumps({
                **{k: result.get(k) for k in (
                    "ok", "strategy", "checkpoint_id", "restored", "deleted",
                    "skipped", "errors", "commit_hash", "file_count",
                )},
                "message": _format_restore_message(result),
            }, ensure_ascii=False)[:2000],
            level="warning" if (result.get("errors") or not result.get("ok")) else "info",
        )
    except Exception:
        pass
    return result


def _format_restore_message(result: dict) -> str:
    """还原结果人可读摘要（主轴展示 / Toast）。"""
    if result.get("ok") is False and not (result.get("restored") or result.get("deleted")):
        return f"还原失败：{result.get('error') or '未知错误'}"
    n = len(result.get("restored") or []) + len(result.get("deleted") or [])
    parts = [f"已还原 {n} 项"]
    sk = len(result.get("skipped") or [])
    er = len(result.get("errors") or [])
    if sk:
        parts.append(f"跳过 {sk}")
    if er:
        parts.append(f"错误 {er}")
    if result.get("commit_hash"):
        parts.append(str(result["commit_hash"])[:8])
    return " · ".join(parts)


@router.get("/api/projects/{project_id}/tickets/{ticket_id}/revert-preview")
async def revert_preview(project_id: str, ticket_id: str):
    """取消前回滚预览：优先 Checkpoint，否则 Git 路径计划。"""
    existing = await db.fetch_one(
        "SELECT id, project_id, title, status FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")

    # 1) Checkpoint
    try:
        from checkpoint.service import checkpoint_service
        cp_plan = await checkpoint_service.preview_restore_to_start(ticket_id)
        if cp_plan.get("has_checkpoint") and cp_plan.get("file_count", 0) > 0:
            return {
                "ticket_id": ticket_id,
                "status": existing["status"],
                "strategy": "checkpoint",
                "has_changes": True,
                "has_checkpoint": True,
                "checkpoint_id": cp_plan.get("checkpoint_id"),
                "files": cp_plan.get("files") or [],
                "file_count": cp_plan.get("file_count") or 0,
                "to_restore": cp_plan.get("to_restore") or [],
                "to_delete": cp_plan.get("to_delete") or [],
                "openspec_change": None,
                "openspec_path": None,
                "commits": [],
            }
        if cp_plan.get("has_checkpoint"):
            # 有锚点但尚无写文件：仍算 checkpoint 策略（空回滚）
            git_plan = await _build_ticket_revert_plan(project_id, ticket_id)
            if git_plan.get("has_changes"):
                return {
                    "ticket_id": ticket_id,
                    "status": existing["status"],
                    "strategy": "git",
                    "has_checkpoint": True,
                    "checkpoint_id": cp_plan.get("checkpoint_id"),
                    **git_plan,
                }
            return {
                "ticket_id": ticket_id,
                "status": existing["status"],
                "strategy": "checkpoint",
                "has_changes": False,
                "has_checkpoint": True,
                "checkpoint_id": cp_plan.get("checkpoint_id"),
                "files": [],
                "file_count": 0,
                "openspec_change": None,
                "openspec_path": None,
                "commits": [],
            }
    except Exception as e:
        logger.debug("checkpoint preview 失败，回退 Git: %s", e)

    plan = await _build_ticket_revert_plan(project_id, ticket_id)
    return {
        "ticket_id": ticket_id,
        "status": existing["status"],
        "strategy": "git" if plan.get("has_changes") else "none",
        "has_checkpoint": False,
        **plan,
    }


async def _build_ticket_revert_plan(project_id: str, ticket_id: str) -> dict:
    """汇总本工单可回滚的文件路径与 OpenSpec change。"""
    import re
    files: set = set()
    commits: list = []

    # 1) ticket_commands.write_file
    cmds = await db.fetch_all(
        "SELECT command_type, command, created_at FROM ticket_commands "
        "WHERE ticket_id = ? ORDER BY created_at ASC",
        (ticket_id,),
    )
    for c in cmds or []:
        ctype = c.get("command_type") or ""
        cmd = c.get("command") or ""
        if ctype == "write_file":
            m = re.match(r"^写入文件:\s*(.+)$", cmd.strip())
            if m:
                files.add(m.group(1).strip().replace("\\", "/"))
        elif ctype == "git_commit":
            m = re.search(r"→\s*([0-9a-fA-F]{7,40})\s*$", cmd)
            if m:
                commits.append({"hash": m.group(1), "at": c.get("created_at")})

    # 2) artifacts.metadata.git
    arts = await db.fetch_all(
        "SELECT path, metadata, type FROM artifacts WHERE ticket_id = ?",
        (ticket_id,),
    )
    for a in arts or []:
        if a.get("path") and a.get("type") in ("code", "file", None):
            p = str(a["path"]).replace("\\", "/").lstrip("/")
            if p and not p.startswith("http"):
                files.add(p)
        meta_raw = a.get("metadata")
        if not meta_raw:
            continue
        try:
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw
        except Exception:
            continue
        git = (meta or {}).get("git") or {}
        for fp in git.get("files") or []:
            if fp:
                files.add(str(fp).replace("\\", "/"))
        if git.get("commit_hash"):
            commits.append({"hash": git["commit_hash"], "at": None})

    # 3) OpenSpec change 目录
    openspec_change = None
    openspec_rel = None
    try:
        from capability_check import _short_ticket_id, _get_repo_path, get_ticket_change_dir
        repo_path = await _get_repo_path(project_id)
        if repo_path:
            change_id = _short_ticket_id(ticket_id)
            change_dir = get_ticket_change_dir(repo_path, ticket_id)
            if change_dir.exists():
                openspec_change = change_id
                openspec_rel = f"openspec/changes/{change_id}"
    except Exception:
        pass

    # 去重 commits（保序）
    seen_h = set()
    uniq_commits = []
    for c in commits:
        h = c["hash"]
        if h and h not in seen_h:
            seen_h.add(h)
            uniq_commits.append(c)

    file_list = sorted(files)
    return {
        "files": file_list,
        "file_count": len(file_list),
        "commits": uniq_commits,
        "openspec_change": openspec_change,
        "openspec_path": openspec_rel,
        "has_changes": bool(file_list or openspec_rel),
    }


async def _revert_ticket_changes(project_id: str, ticket_id: str, ticket_row: dict) -> dict:
    """优先 Checkpoint 还原到 ticket_start；否则 Git 路径级回滚。"""
    from git_manager import git_manager

    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if project and project.get("git_repo_path"):
        from git_manager import PROJECTS_DIR
        default_path = str(PROJECTS_DIR / project_id)
        if project["git_repo_path"] != default_path:
            git_manager.set_project_path(project_id, project["git_repo_path"])

    mode = (project or {}).get("mode", "auto") if project else "auto"
    title = (ticket_row.get("title") or ticket_id)[:40]

    # ── 1) Checkpoint 主路径 ────────────────────────────────
    try:
        from checkpoint.service import checkpoint_service
        cp_prev = await checkpoint_service.preview_restore_to_start(ticket_id)
        if cp_prev.get("has_checkpoint") and cp_prev.get("file_count", 0) > 0:
            result = await checkpoint_service.restore_to_ticket_start(
                project_id, ticket_id,
                commit=(mode != "manual"),
                message=f"[Operator] restore checkpoint (cancel): {title} ({ticket_id[-8:]})",
            )
            result.setdefault("strategy", "checkpoint")
            if mode == "manual":
                result["manual_mode"] = True
            return result
        if cp_prev.get("has_checkpoint") and not cp_prev.get("file_count"):
            plan0 = await _build_ticket_revert_plan(project_id, ticket_id)
            if not plan0.get("has_changes"):
                return {
                    "ok": True, "strategy": "checkpoint",
                    "checkpoint_id": cp_prev.get("checkpoint_id"),
                    "restored": [], "deleted": [], "files": [], "file_count": 0,
                }
    except Exception as e:
        logger.warning("Checkpoint 还原失败，回退 Git: %s", e, exc_info=True)

    # ── 2) Git 兜底 ─────────────────────────────────────────
    plan = await _build_ticket_revert_plan(project_id, ticket_id)
    out = {
        "ok": True,
        "strategy": "git",
        "files": plan["files"],
        "restored": [],
        "deleted": [],
        "skipped": [],
        "errors": [],
        "openspec_removed": False,
        "commit_hash": None,
        "base_ref": None,
    }

    if not git_manager.repo_exists(project_id):
        out["ok"] = False
        out["errors"].append("仓库不存在，跳过文件回滚")
        return out

    base_ref = None
    if plan["commits"]:
        first = plan["commits"][0]["hash"]
        repo_dir = str(git_manager._repo_path(project_id))
        rc, parent, _ = await git_manager._run_git(repo_dir, "rev-parse", f"{first}^")
        if rc == 0 and parent:
            base_ref = parent.strip()

    paths = list(plan["files"])
    if plan.get("openspec_path") and plan["openspec_path"] not in paths:
        paths.append(plan["openspec_path"])

    if not paths:
        out["ok"] = True
        return out

    gr = await git_manager.revert_paths(
        project_id,
        paths,
        base_ref=base_ref,
        commit=(mode != "manual"),
        message=f"[Operator] revert(cancel): {title} ({ticket_id[-8:]})",
        author="Operator",
    )
    out["restored"] = gr.get("restored") or []
    out["deleted"] = gr.get("deleted") or []
    out["skipped"] = gr.get("skipped") or []
    out["errors"].extend(gr.get("errors") or [])
    out["commit_hash"] = gr.get("commit_hash")
    out["base_ref"] = gr.get("base_ref")
    out["openspec_removed"] = bool(
        plan.get("openspec_path") and (
            plan["openspec_path"] in out["deleted"]
            or plan["openspec_path"] in out["restored"]
        )
    )
    if mode == "manual" and (out["restored"] or out["deleted"]):
        out["manual_mode"] = True
    if gr.get("errors") and not (out["restored"] or out["deleted"]):
        out["ok"] = False

    return out


# ==================== 直接创建独立工单 ====================

_VALID_START_STATUSES = {
    "pending",
    "architecture_done",
    "development_in_progress",
}

_STANDALONE_REQ_TITLE = "独立工单"


async def _get_or_create_standalone_req(project_id: str) -> str:
    """查询或创建项目的独立工单桶需求，返回其 ID（幂等）。"""
    row = await db.fetch_one(
        "SELECT id FROM requirements WHERE project_id = ? AND status = 'standalone' LIMIT 1",
        (project_id,),
    )
    if row:
        return row["id"]

    req_id = generate_id("REQ")
    now = now_iso()
    await db.insert("requirements", {
        "id": req_id,
        "project_id": project_id,
        "title": _STANDALONE_REQ_TITLE,
        "description": "项目独立工单集合，由用户直接创建，不经过需求拆单流程。",
        "status": "standalone",
        "priority": "medium",
        "created_at": now,
        "updated_at": now,
    })
    logger.info("创建独立工单桶需求: %s (project=%s)", req_id, project_id)
    return req_id


@router.post("/api/projects/{project_id}/tickets/cancel-active")
async def cancel_active_tickets(project_id: str):
    """取消该项目排队中 / 执行中的工单（不回滚代码）。

    给全局后台任务面板「全部停止」用：列表只展示最早 10 条 pending，
    这里按项目把同类在途工单一并停掉，避免点十次还漏四十条。
    """
    project = await db.fetch_one("SELECT id, name FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")
    placeholders = ",".join("?" * len(_STOPPABLE_TICKET_STATUSES))
    rows = await db.fetch_all(
        f"""SELECT id, status, project_id, requirement_id, title
            FROM tickets
            WHERE project_id = ?
              AND (status IN ({placeholders}) OR status LIKE '%_in_progress')""",
        (project_id, *_STOPPABLE_TICKET_STATUSES),
    )
    cancelled = 0
    for row in rows:
        try:
            await _cancel_ticket_status_only(
                row, message="后台任务面板停止：工单已取消（未回滚代码）"
            )
            cancelled += 1
        except Exception as e:
            logger.warning("cancel-active 跳过 %s: %s", row.get("id"), e)
    return {
        "ok": True,
        "project_id": project_id,
        "project_name": project.get("name") or "",
        "cancelled": cancelled,
    }


@router.post("/api/projects/{project_id}/tickets/create-direct")
async def create_direct_ticket(project_id: str, req: DirectTicketCreate):
    """直接创建独立工单（不经过需求拆单，挂在独立工单桶需求下）。"""
    project = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    # 校验 type
    valid_types = {"feature", "bugfix", "refactor", "test", "doc"}
    ticket_type = req.type if req.type in valid_types else "feature"

    # start_from：用户显式指定优先；默认 pending 时自动分类（对齐 MagicAI Phase -1）
    if req.start_from == "pending":
        try:
            from ticket_classifier import classify_start_from
            start_status = classify_start_from(req.title, req.description, ticket_type)
        except Exception as _ce:
            logger.warning("请求自动分类失败，回退 pending: %s", _ce)
            start_status = "pending"
    else:
        start_status = req.start_from if req.start_from in _VALID_START_STATUSES else "pending"

    # 查询或创建独立工单桶
    standalone_req_id = await _get_or_create_standalone_req(project_id)

    ticket_id = generate_id("TK")
    now = now_iso()
    ticket_data = {
        "id": ticket_id,
        "requirement_id": standalone_req_id,
        "project_id": project_id,
        "title": req.title.strip(),
        "description": req.description.strip(),
        "type": ticket_type,
        "module": req.module or "other",
        "priority": req.priority,
        "status": start_status,
        "estimated_hours": req.estimated_hours,
        "use_aigc": 1 if req.use_aigc else 0,
        "created_at": now,
        "updated_at": now,
    }
    if req.source_message_id:
        ticket_data["source_message_id"] = req.source_message_id
    if req.source_session_id:
        ticket_data["source_session_id"] = req.source_session_id
    if req.material_ids:
        try:
            from materials.registry import material_registry
            ticket_data["description"] = (
                ticket_data["description"] + await material_registry.markdown_links(req.material_ids)
            )
            await material_registry.mark_promoted(req.material_ids, "ticket", ticket_id)
        except Exception as _e:
            logger.debug("附加会话素材失败: %s", _e)
    await db.insert("tickets", ticket_data)

    # 回填聊天草稿卡片为已执行（有 source_message_id 精确更新；否则按标题匹配最近 pending 草稿）
    try:
        import json as _json
        ar_json = _json.dumps(
            {"ticket_id": ticket_id, "title": req.title, "at": now},
            ensure_ascii=False,
        )
        msg_id = req.source_message_id
        if not msg_id and req.title.strip():
            # 流式期间 msg_id 可能未绑到卡片 → 按标题找回 pending 的 confirm_direct_ticket
            title_norm = req.title.strip()
            cands = await db.fetch_all(
                """SELECT id, action_data FROM chat_messages
                   WHERE project_id = ? AND action_type = 'confirm_direct_ticket'
                     AND (action_state IS NULL OR action_state = '' OR action_state = 'pending')
                   ORDER BY created_at DESC LIMIT 30""",
                (project_id,),
            )
            for row in cands or []:
                try:
                    ad = json.loads(row.get("action_data") or "{}")
                except Exception:
                    continue
                if (ad.get("title") or "").strip() == title_norm:
                    msg_id = row["id"]
                    logger.info("create-direct: 按标题回填草稿消息 %s", msg_id[:12])
                    break
        if msg_id:
            await db.execute(
                "UPDATE chat_messages SET action_state='executed', action_result=? WHERE id=?",
                (ar_json, msg_id),
            )
    except Exception as _e:
        logger.debug("更新工单 action_result 失败: %s", _e)

    logger.info("创建直接工单: %s '%s' status=%s", ticket_id, req.title[:40], start_status)

    # 写入创建日志
    from events import event_manager
    log_id = generate_id("LOG")
    await db.execute(
        "INSERT INTO ticket_logs (id, ticket_id, requirement_id, project_id, agent_type, action, detail, level, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (log_id, ticket_id, standalone_req_id, project_id, "Operator", "create",
         json.dumps({"message": f"直接创建工单：{req.title[:60]}"}, ensure_ascii=False),
         "info", now),
    )

    # 若设置了 auto_start，触发 orchestrator 调度
    if req.auto_start and start_status != "pending":
        try:
            from orchestrator import orchestrator
            import asyncio
            asyncio.create_task(orchestrator.process_ticket(project_id, ticket_id))
        except Exception as e:
            logger.warning("触发 orchestrator 失败（不影响工单创建）: %s", e)

    # ── 规范层钩子：直接创建工单也补 PRD + OpenSpec ─────────────
    # 不论 start_from 是什么，都触发：
    #   1. Planner 钩子（仅当 start_from == "pending" 才让 orchestrator 走完整 Planner）
    #   2. OpenSpec Propose（项目已 init openspec/ 时补 spec 目录）
    import asyncio
    _hook_task = asyncio.create_task(
        _post_create_layer_hooks(
            project_id=project_id,
            ticket_id=ticket_id,
            title=req.title.strip(),
            description=req.description.strip(),
            start_from=start_status,
        )
    )
    # fire-and-forget，但别静默：任务异常时打日志（否则 create_task 的异常会被吞）
    def _hook_done(t: "asyncio.Task"):
        try:
            exc = t.exception()
            if exc:
                logger.warning("规范层钩子任务异常（ticket=%s）: %r", ticket_id, exc)
        except asyncio.CancelledError:
            logger.warning("规范层钩子任务被取消（ticket=%s）", ticket_id)
        except Exception:
            pass
    _hook_task.add_done_callback(_hook_done)

    # SSE 通知看板刷新
    await event_manager.publish_to_project(project_id, "ticket_created", {
        "ticket_id": ticket_id,
        "requirement_id": standalone_req_id,
        "title": req.title,
        "status": start_status,
    })

    return {
        "ticket_id": ticket_id,
        "requirement_id": standalone_req_id,
        "status": start_status,
        "message": f"工单「{req.title}」已创建",
    }


# ==================== 工单操作 ====================


@router.patch("/api/projects/{project_id}/tickets/{ticket_id}/status")
async def update_ticket_status(project_id: str, ticket_id: str, body: dict):
    """手动更新工单状态（前端下拉选择触发）"""
    new_status = body.get("status")
    if not new_status:
        raise HTTPException(400, "缺少 status 字段")

    try:
        TicketStatus(new_status)
    except ValueError:
        raise HTTPException(400, f"无效的状态值: {new_status}")

    existing = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")

    old_status = existing["status"]
    if old_status == new_status:
        return {"message": "状态未变", "status": old_status}

    if not validate_ticket_transition(old_status, new_status):
        old_label = STATUS_LABELS.get(old_status, old_status)
        new_label = STATUS_LABELS.get(new_status, new_status)
        raise HTTPException(400, f"不允许从「{old_label}」转换到「{new_label}」")

    update_data = {"status": new_status, "updated_at": now_iso()}
    if new_status == "deployed":
        update_data["completed_at"] = now_iso()
    if new_status in ("architecture_in_progress", "development_in_progress",
                       "testing_in_progress", "deploying") and not existing.get("started_at"):
        update_data["started_at"] = now_iso()

    await db.update("tickets", update_data, "id = ?", (ticket_id,))

    await _log_ticket(
        project_id, existing["requirement_id"], ticket_id,
        None, "update_status", old_status, new_status,
        f"手动变更状态: {STATUS_LABELS.get(old_status, old_status)} → {STATUS_LABELS.get(new_status, new_status)}"
    )

    await event_manager.publish_to_project(
        project_id,
        "ticket_status_changed",
        {"ticket_id": ticket_id, "from_status": old_status, "to_status": new_status,
         "status_label": STATUS_LABELS.get(new_status, new_status)},
    )

    # 手动改为 testing_done 或 deployed 时，触发后续依赖工单流转 + 需求完成检查
    if new_status in ("testing_done", "deployed"):
        import asyncio
        from orchestrator import orchestrator
        asyncio.create_task(orchestrator._trigger_dependents(project_id, ticket_id))
        asyncio.create_task(orchestrator._check_requirement_completion(
            project_id, existing["requirement_id"]
        ))

    # 如果新状态在流转规则中（如 development_done → 验收），自动触发下一步 Agent
    import asyncio
    from orchestrator import orchestrator
    if new_status in orchestrator.transition_rules:
        asyncio.create_task(orchestrator.process_ticket(project_id, ticket_id))

    return {
        "message": "状态已更新",
        "ticket_id": ticket_id,
        "from_status": old_status,
        "to_status": new_status,
        "status_label": STATUS_LABELS.get(new_status, new_status),
    }


@router.post("/api/projects/{project_id}/tickets/{ticket_id}/start")
async def start_ticket(project_id: str, ticket_id: str, background_tasks: BackgroundTasks):
    """启动工单（触发 Agent 流转）"""
    existing = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")

    if existing["status"] != TicketStatus.PENDING.value:
        raise HTTPException(400, f"当前状态「{existing['status']}」不允许启动")

    # 后台启动 Agent 流转
    from orchestrator import orchestrator
    background_tasks.add_task(orchestrator.process_ticket, project_id, ticket_id)

    return {"message": "工单已启动", "ticket_id": ticket_id}


@router.post("/api/projects/{project_id}/tickets/{ticket_id}/reject")
async def reject_ticket(project_id: str, ticket_id: str, req: TicketRejectRequest):
    """打回工单（验收/测试不通过时使用）"""
    existing = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")

    # 只有 development_done 和 testing_in_progress 状态允许打回
    allowed_reject_from = [
        TicketStatus.DEVELOPMENT_DONE.value,
        TicketStatus.TESTING_IN_PROGRESS.value,
    ]
    if existing["status"] not in allowed_reject_from:
        raise HTTPException(400, f"当前状态「{existing['status']}」不允许打回")

    old_status = existing["status"]

    if old_status == TicketStatus.DEVELOPMENT_DONE.value:
        new_status = TicketStatus.ACCEPTANCE_REJECTED.value
        message = f"验收不通过: {req.reason}"
    else:
        new_status = TicketStatus.TESTING_FAILED.value
        message = f"测试不通过: {req.reason}"

    await db.update(
        "tickets",
        {"status": new_status, "updated_at": now_iso()},
        "id = ?",
        (ticket_id,),
    )

    await _log_ticket(
        project_id, existing["requirement_id"], ticket_id,
        "ProductAgent" if old_status == TicketStatus.DEVELOPMENT_DONE.value else "TestAgent",
        "reject", old_status, new_status, message,
    )

    await event_manager.publish_to_project(
        project_id,
        "ticket_rejected",
        {"ticket_id": ticket_id, "from": old_status, "to": new_status, "reason": req.reason},
    )

    return {"message": message, "new_status": new_status}


@router.post("/api/projects/{project_id}/tickets/{ticket_id}/diagnose")
async def diagnose_ticket(project_id: str, ticket_id: str, background_tasks: BackgroundTasks):
    """手动触发/重新触发诊断。结果异步写回 tickets.diagnosis。"""
    existing = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")

    # 从最近一条 error 日志提取 agent/action/error，供诊断使用
    # 若该 ticket 从未产出 error（手动诊断健康工单），也能跑，传空 error
    latest_err = await db.fetch_one(
        "SELECT agent_type, action, detail, from_status FROM ticket_logs "
        "WHERE ticket_id = ? AND level = 'error' "
        "ORDER BY created_at DESC LIMIT 1",
        (ticket_id,),
    )
    agent_name = "?"
    action_name = "?"
    error_msg = ""
    blocked_from = existing["status"]
    if latest_err:
        agent_name = latest_err.get("agent_type") or "?"
        try:
            det = json.loads(latest_err.get("detail") or "{}")
            action_name = det.get("action") or latest_err.get("action") or "?"
            error_msg = det.get("error") or det.get("message") or ""
        except Exception:
            action_name = latest_err.get("action") or "?"
        blocked_from = latest_err.get("from_status") or blocked_from

    from orchestrator import orchestrator
    background_tasks.add_task(
        orchestrator._diagnose_blocked_ticket,
        project_id=project_id,
        ticket_id=ticket_id,
        current_ticket=dict(existing),
        agent_name=agent_name,
        action=action_name,
        error_msg=error_msg,
        blocked_from_status=blocked_from,
    )
    return {"message": "诊断已触发，结果将异步写入 tickets.diagnosis"}


async def _ticket_sop_stages(project_id: str, ticket_type: str | None):
    row = await db.fetch_one("SELECT traits FROM projects WHERE id = ?", (project_id,))
    traits = json.loads((row or {}).get("traits") or "[]")
    if not isinstance(traits, list):
        traits = []
    from sop.loader import compose_sop
    return compose_sop(traits=traits, ticket_type=ticket_type).get("stages", [])


async def _last_blocked_from(ticket_id: str) -> str | None:
    row = await db.fetch_one(
        """SELECT from_status FROM ticket_logs
           WHERE ticket_id = ? AND action = 'blocked'
           ORDER BY created_at DESC LIMIT 1""",
        (ticket_id,),
    )
    return (row or {}).get("from_status")


@router.get("/api/projects/{project_id}/tickets/{ticket_id}/unblock-targets")
async def get_unblock_targets(project_id: str, ticket_id: str):
    """解除 blocked 时给前端的 SOP 感知选项。视频项目不会再推荐 architecture_done。"""
    existing = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")
    from sop.status_repair import build_unblock_targets
    stages = await _ticket_sop_stages(project_id, existing.get("type"))
    blocked_from = await _last_blocked_from(ticket_id)
    return {
        "targets": build_unblock_targets(stages, blocked_from, STATUS_LABELS),
        "blocked_from": blocked_from,
    }


@router.post("/api/projects/{project_id}/tickets/{ticket_id}/unblock")
async def unblock_ticket(project_id: str, ticket_id: str, target_status: str = "pending"):
    """解除 blocked 工单（人工介入后使用）。
    target_status 默认回到 pending 重新跑，也可指定其他状态（如 development_done 跳过未实现的 action）。

    注意：这条 unblock 日志同时是 reject 计数的**清零标记** ——
    orchestrator._reject_count_since_reset() 只数最近一次 unblock 之后的 reject。
    没有它，撞过 max_retries 的工单解除后会立刻被重新判定超限、秒回 blocked。
    """
    existing = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")

    if existing["status"] != TicketStatus.BLOCKED.value:
        raise HTTPException(400, f"当前状态「{existing['status']}」不是 blocked，无需解除")

    # 视频/内容 SOP 没有 architecture：把软件默认项改成可派单的 trigger。
    requested = target_status
    try:
        from sop.status_repair import sop_safe_unblock_target
        stages = await _ticket_sop_stages(project_id, existing.get("type"))
        target_status = sop_safe_unblock_target(
            requested, stages, await _last_blocked_from(ticket_id),
        )
        if target_status != requested:
            logger.info(
                "unblock target remapped %s → %s (ticket %s SOP 无对应软件阶段)",
                requested, target_status, ticket_id,
            )
    except Exception as e:
        logger.warning("unblock SOP remap 失败，沿用原目标 %s: %s", requested, e)

    # 校验 target_status 是合法枚举
    valid_statuses = {s.value for s in TicketStatus}
    if target_status not in valid_statuses:
        raise HTTPException(400, f"目标状态「{target_status}」非法")

    # 解除后不应再停在 blocked（否则等于没解除）
    if target_status == TicketStatus.BLOCKED.value:
        raise HTTPException(400, "目标状态不能仍是 blocked")

    # 清零前**实际生效**的 reject 数，写进日志便于回溯「这次给了几次新机会」。
    # 必须跟 orchestrator 用同一套口径：数全部历史会把上几轮 unblock 之前的
    # 也算进来（解除过两次的工单能报出 12 次），而真正把它顶到上限的只有 5 次。
    try:
        from orchestrator import orchestrator
        cleared = await orchestrator._reject_count_since_reset(ticket_id)
    except Exception as e:
        logger.warning("统计 reject 次数失败: %s", e)
        cleared = 0

    await db.update(
        "tickets",
        {"status": target_status, "updated_at": now_iso()},
        "id = ?",
        (ticket_id,),
    )

    remap_note = (
        f"（已从 {requested} 改到当前 SOP 可派单状态）" if requested != target_status else ""
    )
    await _log_ticket(
        project_id, existing["requirement_id"], ticket_id,
        "Operator", "unblock", TicketStatus.BLOCKED.value, target_status,
        f"工单已从 blocked 解除 → {target_status}{remap_note}"
        + (f"（reject 计数清零，此前累计 {cleared} 次）" if cleared else ""),
    )

    await event_manager.publish_to_project(
        project_id,
        "ticket_unblocked",
        {"ticket_id": ticket_id, "from": TicketStatus.BLOCKED.value, "to": target_status},
    )

    # 立刻派单，别等 30s 轮询
    try:
        from orchestrator import orchestrator
        await orchestrator._publish_ticket_ready(project_id, ticket_id)
    except Exception as e:
        logger.warning("unblock 后触发派单失败（将由轮询兜底）: %s", e)

    return {
        "message": "工单已解除 blocked",
        "new_status": target_status,
        "requested_status": requested,
        "reject_count_cleared": cleared,
    }


async def _last_cancelled_from(ticket_id: str) -> str | None:
    row = await db.fetch_one(
        """SELECT from_status FROM ticket_logs
           WHERE ticket_id = ? AND action = 'cancelled'
           ORDER BY created_at DESC LIMIT 1""",
        (ticket_id,),
    )
    return (row or {}).get("from_status")


def _status_allowed_for_restore(status: str, stages: list) -> bool:
    s = (status or "").strip()
    if not s or s in ("cancelled", "blocked", "deployed"):
        return False
    if s in STATUS_LABELS or s in {x.value for x in TicketStatus}:
        return True
    from sop.status_repair import _ids_and_triggers
    _, triggers, successes = _ids_and_triggers(stages)
    return s in triggers or s in successes or s.endswith("_ready")


@router.get("/api/projects/{project_id}/tickets/{ticket_id}/restore-targets")
async def get_restore_cancelled_targets(project_id: str, ticket_id: str):
    """已取消工单恢复时的 SOP 感知选项。"""
    existing = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")
    if existing["status"] != TicketStatus.CANCELLED.value:
        raise HTTPException(400, f"当前状态「{existing['status']}」不是已取消")
    from sop.status_repair import build_restore_cancelled_targets
    stages = await _ticket_sop_stages(project_id, existing.get("type"))
    cancelled_from = await _last_cancelled_from(ticket_id)
    return {
        "targets": build_restore_cancelled_targets(stages, cancelled_from, STATUS_LABELS),
        "cancelled_from": cancelled_from,
    }


@router.post("/api/projects/{project_id}/tickets/{ticket_id}/restore")
async def restore_cancelled_ticket(
    project_id: str, ticket_id: str, target_status: str = "",
):
    """把已取消工单拉回可派单状态并立刻重跑。默认从取消前那个阶段继续。"""
    existing = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")
    if existing["status"] != TicketStatus.CANCELLED.value:
        raise HTTPException(400, f"当前状态「{existing['status']}」不是已取消")

    stages = await _ticket_sop_stages(project_id, existing.get("type"))
    cancelled_from = await _last_cancelled_from(ticket_id)
    from sop.status_repair import (
        build_restore_cancelled_targets,
        restore_target_from_cancelled_status,
    )
    requested = (target_status or "").strip()
    if not requested:
        requested = restore_target_from_cancelled_status(cancelled_from, stages)
    allowed = {t["status"] for t in build_restore_cancelled_targets(
        stages, cancelled_from, STATUS_LABELS,
    )}
    if requested not in allowed:
        requested = restore_target_from_cancelled_status(cancelled_from, stages)
    if not _status_allowed_for_restore(requested, stages):
        raise HTTPException(400, f"目标状态「{requested}」不可恢复")

    try:
        from llm_client import clear_ticket_cli_abort
        clear_ticket_cli_abort(ticket_id)
    except Exception:
        pass

    cleared_markers = 0
    try:
        proj = await db.fetch_one(
            "SELECT git_repo_path FROM projects WHERE id = ?", (project_id,),
        )
        repo = (proj or {}).get("git_repo_path") or ""
        if repo:
            from pathlib import Path
            from actions.gen_image import clear_image_blocked_markers
            root = Path(repo)
            cleared_markers = clear_image_blocked_markers(root / "works")
            cleared_markers += clear_image_blocked_markers(root)
    except Exception as e:
        logger.warning("恢复时清理生图阻塞标记失败: %s", e)

    await db.update(
        "tickets",
        {
            "status": requested,
            "updated_at": now_iso(),
            "current_action": None,
            "current_action_latest_log": None,
        },
        "id = ?",
        (ticket_id,),
    )
    await _log_ticket(
        project_id, existing["requirement_id"], ticket_id,
        "Operator", "restore_cancelled", "cancelled", requested,
        f"已取消工单恢复 → {requested}"
        + (f"（清掉 {cleared_markers} 个生图阻塞标记）" if cleared_markers else ""),
    )
    try:
        await event_manager.publish_to_project(
            project_id,
            "ticket_status_changed",
            {"ticket_id": ticket_id, "from": "cancelled", "to": requested, "agent": "Operator"},
        )
    except Exception:
        pass
    try:
        from orchestrator import orchestrator
        await orchestrator._publish_ticket_ready(project_id, ticket_id)
    except Exception as e:
        logger.warning("恢复后触发派单失败（将由轮询兜底）: %s", e)

    return {
        "message": f"工单已恢复 → {STATUS_LABELS.get(requested, requested)}",
        "new_status": requested,
        "cancelled_from": cancelled_from,
        "cleared_image_blocked": cleared_markers,
    }


# ==================== 子任务 ====================


@router.get("/api/tickets/{ticket_id}/subtasks")
async def list_subtasks(ticket_id: str):
    """获取子任务列表"""
    subtasks = await db.fetch_all(
        "SELECT * FROM subtasks WHERE ticket_id = ? ORDER BY sort_order, created_at",
        (ticket_id,),
    )
    return {"subtasks": subtasks, "total": len(subtasks)}


@router.put("/api/tickets/{ticket_id}/subtasks/{subtask_id}")
async def update_subtask(ticket_id: str, subtask_id: str, status: str = None):
    """更新子任务状态"""
    existing = await db.fetch_one(
        "SELECT * FROM subtasks WHERE id = ? AND ticket_id = ?",
        (subtask_id, ticket_id),
    )
    if not existing:
        raise HTTPException(404, "子任务不存在")

    update_data = {"updated_at": now_iso()}
    if status:
        update_data["status"] = status
        if status == "completed":
            update_data["completed_at"] = now_iso()

    await db.update("subtasks", update_data, "id = ?", (subtask_id,))
    return {"message": "子任务已更新"}


# ==================== 看板 ====================


def _classify_board_column(status: str, status_map: dict) -> str:
    """将任意工单状态（含 SOP fragments 派生的动态状态）归入看板 5 列之一，保证工单绝不在看板上消失。"""
    s = (status or "").strip()
    if s in status_map:
        return status_map[s]
    if s in ("cancelled", "waiting_subtasks"):
        return s
    if s in ("done", "completed"):
        return "done"
    if s == "todo":
        return "pending"
    if s == "packaged":
        return "in_review"
    if s in ("packaging_pending", "ue_content_pending"):
        return "in_progress"
    if s == "in_progress" or s.endswith("_in_progress"):
        return "in_progress"
    if s == "in_review" or s.endswith(("_passed", "_done", "_ready")):
        return "in_review"
    if s.endswith(("_failed", "_rejected")):
        return "blocked"
    return "in_progress"


@router.get("/api/projects/{project_id}/board")
async def get_board(project_id: str, requirement_id: str = None):
    """获取看板数据（按状态分组）"""
    sql = "SELECT * FROM tickets WHERE project_id = ?"
    params = [project_id]
    if requirement_id:
        sql += " AND requirement_id = ?"
        params.append(requirement_id)
    sql += " ORDER BY priority ASC, sort_order ASC"

    tickets = await db.fetch_all(sql, tuple(params))

    status_map = {}
    for col_name, statuses in BOARD_COLUMNS.items():
        for st in statuses:
            status_map[st.value if hasattr(st, "value") else str(st)] = col_name

    board = {col_name: [] for col_name in BOARD_COLUMNS}
    for t in tickets:
        st = t["status"]
        col = _classify_board_column(st, status_map)
        if col in board:
            board[col].append({
                **t,
                "status_label": STATUS_LABELS.get(st, st),
            })

    # 已取消的单独放
    board["cancelled"] = [
        {**t, "status_label": "已取消"}
        for t in tickets
        if t["status"] == "cancelled"
    ]

    # Phase 4：waiting_subtasks 单独放（前端合并到 pending 列显示）
    # 附上子工单进度（total / done）用于看板卡片显示 ⏳ 1/3
    _done_statuses = {"testing_done", "deployed"}
    waiting_list = []
    for t in tickets:
        if t["status"] != "waiting_subtasks":
            continue
        children = [c for c in tickets if c.get("parent_ticket_id") == t["id"]]
        done_cnt  = sum(1 for c in children if c["status"] in _done_statuses)
        waiting_list.append({
            **t,
            "status_label":       "⏳ 等待子任务",
            "child_total":        len(children),
            "child_done":         done_cnt,
        })
    board["waiting_subtasks"] = waiting_list

    return {"board": board}


@router.get("/api/projects/{project_id}/board/by-module")
async def get_board_by_module(project_id: str):
    """按模块分组视图"""
    tickets = await db.fetch_all(
        "SELECT * FROM tickets WHERE project_id = ? ORDER BY priority, sort_order",
        (project_id,),
    )

    by_module = {}
    for t in tickets:
        module = t["module"] or "other"
        if module not in by_module:
            by_module[module] = []
        t["status_label"] = STATUS_LABELS.get(t["status"], t["status"])
        by_module[module].append(t)

    return {"modules": by_module}


# ==================== 日志 ====================


@router.get("/api/projects/{project_id}/logs")
async def get_project_logs(project_id: str, limit: int = 100, offset: int = 0):
    """项目级日志：ticket_logs（Agent 操作）+ tool_audit_log（AI 聊天工具调用）合并返回"""
    # UNION：ticket_logs 保持原结构，tool_audit_log 适配同格式
    sql = """
        SELECT id, agent_type, action, from_status, to_status,
               requirement_id, ticket_id, project_id, detail, level, created_at
        FROM ticket_logs
        WHERE project_id = ?

        UNION ALL

        SELECT
            'tal-' || CAST(id AS TEXT) AS id,
            COALESCE(agent_type, 'ChatAssistant')  AS agent_type,
            'chat:' || tool_name                   AS action,
            NULL AS from_status,
            NULL AS to_status,
            NULL AS requirement_id,
            ticket_id,
            project_id,
            json_object('message',
                tool_name ||
                CASE WHEN duration_ms IS NOT NULL
                     THEN ' (' || ROUND(duration_ms) || 'ms)'
                     ELSE '' END
            ) AS detail,
            CASE WHEN success = 1 THEN 'info' ELSE 'error' END AS level,
            created_at
        FROM tool_audit_log
        WHERE project_id = ?

        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """
    logs = await db.fetch_all(sql, (project_id, project_id, limit, offset))

    count_sql = """
        SELECT (
            (SELECT COUNT(*) FROM ticket_logs   WHERE project_id = ?) +
            (SELECT COUNT(*) FROM tool_audit_log WHERE project_id = ?)
        ) AS count
    """
    total = await db.fetch_one(count_sql, (project_id, project_id))
    return {"logs": logs, "total": total["count"] if total else 0}


@router.get("/api/tickets/{ticket_id}/logs")
async def get_ticket_logs(ticket_id: str):
    """工单级日志"""
    logs = await db.fetch_all(
        "SELECT * FROM ticket_logs WHERE ticket_id = ? ORDER BY created_at DESC",
        (ticket_id,),
    )
    return {"logs": logs, "total": len(logs)}


# ==================== 统一时间轴 + 评论 ====================

# 次级日志的 action 前缀（默认折叠）
# command_run 进这里：单条命令是执行细节，不是叙事节点；失败的会因 level='error'
# 被 _classify_tier 自动提到 primary，正合需要。
# llm_call 不在这里：它是「Agent 正在跟模型说话」的叙事节点，主时间轴要能看见。
# react_tool / ToolSearch / Read 才是刷屏的工具流水，默认进「工具流水」。
_SECONDARY_ACTIONS = {"chat:", "tool_call", "shell_exec",
                      "react_tool", "skill_step_start", "command_run"}

# OpenSpec / 建单等生命周期事件必须进主时间轴（否则 started=info 会被扔进「详细日志」
# 而 partial=warning 留在主轴，出现「部分完成在前、启动在后」的假乱序）
_PRIMARY_ACTIONS = {
    "create", "assign", "accept", "complete", "blocked", "cancelled",
    "openspec_propose_started", "openspec_propose", "openspec_propose_partial",
    "openspec_propose_failed", "openspec_artifact",
    "openspec_apply_started", "openspec_apply", "openspec_apply_partial",
    "openspec_apply_failed", "openspec_verify", "openspec_verify_failed",
    "openspec_archive",
    "skill_workflow_start", "thought_start", "llm_call",
    "phase_complete", "manual_action", "verification_approved",
    "verification_rejected", "artifact_added", "milestone_architecture",
    # checkpoint / before_write 单独分流；仅 ticket_start、phase_boundary、restore 上主轴
    "checkpoint_restore", "revert",
}


def _classify_tier(item: dict) -> str:
    """判断时间轴条目的展示级别：primary / secondary"""
    if item.get("_type") == "comment":
        return "primary"
    action = item.get("action", "") or ""
    level  = item.get("level", "info") or "info"

    # 错误/警告级别 → primary
    if level in ("error", "warn", "warning"):
        return "primary"
    # 状态变更 → primary
    if item.get("from_status") or item.get("to_status"):
        return "primary"
    # Checkpoint：写前增量进详细日志；起点/阶段边界留主轴（可还原）
    if action == "checkpoint":
        trigger = (item.get("_detail") or {}).get("trigger") or ""
        if trigger == "before_write":
            return "secondary"
        return "primary"
    # 明确的主轴生命周期事件（含 OpenSpec started，避免与 partial 分层导致假乱序）
    if action in _PRIMARY_ACTIONS:
        return "primary"
    # 步骤完成 → primary
    if action == "skill_step_done":
        return "primary"
    # thought_done 标记 Agent 阶段完成 → 一律 primary
    if action == "thought_done":
        return "primary"
    # 工具流水 / 步骤开始 → secondary（llm_call 已在 _PRIMARY_ACTIONS）
    for prefix in _SECONDARY_ACTIONS:
        if action.startswith(prefix) or action == prefix:
            return "secondary"
    return "secondary"


async def _annotate_timeline_stages(ticket_id: str, items: list) -> tuple:
    """给时间轴条目标注所属 SOP 阶段 / UI 大组（前端按此做树形分组）。

    返回 (items, groups)：groups 是 UI 大组的声明序，前端拿它定树干顺序。
    为什么放后端：阶段归属是 SOP 知识（trigger_on、pipeline_view 的分组），
    前端再抄一份必然和 yaml 漂移 —— 装了 ue_test_gen fragment 就多一个阶段，
    前端硬编码的表不会自己长出来。

    三段式判定，顺序有讲究：
      ① action 命中 SOP stage —— 最准（complete/code_review/accept 都带）；
      ② from_status 命中 trigger_on —— 「在 X 状态上干活」= 干活的是 trigger_on==X 那个 stage；
      ③ 都不命中 → **继承前一条**。这条最关键：实测 6584 条 thought_start、
         4093 条 llm_call、197 条 checkpoint 完全没有 action 映射也没有 status，
         只按 ①② 标的话 90% 的日志会挂在「未归类」下，树就白建了。
         时间轴是时序的，一条没有身份的日志属于当时正在跑的那个阶段。

    拿不到 traits / compose 失败 → 原样返回不标注，前端退回平铺（现状），不报错。
    """
    try:
        row = await db.fetch_one(
            "SELECT p.traits AS traits, t.type AS type FROM tickets t "
            "JOIN projects p ON p.id = t.project_id WHERE t.id = ?",
            (ticket_id,),
        )
        traits = json.loads((row or {}).get("traits") or "[]")
        if not isinstance(traits, list) or not traits:
            return items, []

        from sop.loader import build_stage_index, compose_sop
        idx = build_stage_index(
            compose_sop(traits=traits, ticket_type=(row or {}).get("type"))
        )
    except Exception as e:
        logger.warning("时间轴阶段标注失败（%s），退回平铺: %s", ticket_id, e)
        return items, []

    by_action = idx["by_action"]
    by_status = idx["by_from_status"]
    last = None

    for item in items:
        hit = None
        if item.get("_type") == "comment":
            # 评论的 phase 存的就是状态名（development_done / architecture_done…），
            # 'milestone' 之类的非状态值查不到 → 落到继承。
            hit = by_status.get(item.get("phase") or "")
        else:
            hit = by_action.get(item.get("action") or "") \
                or by_status.get(item.get("from_status") or "")

        if hit:
            last = hit
            item["_stage"] = hit["stage"]
            item["_stage_name"] = hit["stage_name"]
            item["_stage_group"] = hit["group"]
            item["_stage_exact"] = True
        elif last:
            item["_stage"] = last["stage"]
            item["_stage_name"] = last["stage_name"]
            item["_stage_group"] = last["group"]
            item["_stage_exact"] = False   # 继承来的，前端不该拿它当权威

    return items, idx["groups"]


async def _annotate_chat_anchors(ticket_id: str, items: list) -> list:
    """标注每条日志在「工单对话」面板里的落点（_chat_anchor），没有就不标。

    为什么放后端：工单对话 Feed 只收一部分 action（见 chat.py::FEED_LOG_ACTIONS，
    全库 27300 条日志里收 20284 条）。前端要给时间轴条目加「💬 对话」跳转链接，
    就得知道"这条在对话里有没有"。把那份白名单抄到前端 = 两份判据各改各的，
    后端加一类 action，前端不知道，链接就指向不存在的条目
    （「📟 后台记录」链接刚踩过这个坑：判据和建表规则脱节，UE 工单全无链接）。
    所以这里 import 同一个集合，前端只认这个字段。

    两类落点：
      · action 在 FEED_LOG_ACTIONS 里 → Feed 的事件条目 id **就是** ticket_logs.id
        （chat.py 里 `"id": lr["id"]`），锚点白送；
      · action == 'llm_call'（3799 条，Feed 不收）→ 它记的是一次 LLM 调用，
        Feed 里对应的是 llm_conversations 那条回复气泡。两张表没有外键，
        只能按时间配对：同工单、时间差 ≤3s 取最近的一条（抽样 18/18 命中）。
        锚点用 `<conv_id>_resp`，即回复气泡（chat.py 给 assistant 消息拼的 id）。
    配不上的一律不标 —— 宁可没链接，也不要点了跳不到的死链。
    """
    try:
        from api.chat import FEED_LOG_ACTIONS
    except Exception as e:      # 理论上不会发生；真出事就退回"没有链接"
        logger.warning("对话锚点标注跳过（导入失败）: %s", e)
        return items

    # llm_call → llm_conversations 的时间配对表（没有 llm_call 就别查库）
    conv_ts: list = []
    if any(i.get("action") == "llm_call" for i in items):
        try:
            convs = await db.fetch_all(
                "SELECT id, created_at FROM llm_conversations "
                "WHERE ticket_id = ? ORDER BY created_at ASC",
                (ticket_id,),
            )
            conv_ts = [(c["created_at"], c["id"]) for c in convs if c["created_at"]]
        except Exception as e:
            logger.debug("llm_conversations 配对跳过: %s", e)

    import bisect
    from datetime import datetime
    ts_keys = [t for t, _ in conv_ts]

    def _pair_llm(created_at: str) -> str:
        """找时间最近的 conversation，差 >3s 就放弃（返回空串 = 不标锚点）"""
        if not created_at or not ts_keys:
            return ""
        pos = bisect.bisect_left(ts_keys, created_at)
        best, best_gap = "", None
        for p in (pos - 1, pos):        # 只看左右两个邻居，已排序
            if 0 <= p < len(conv_ts):
                try:
                    gap = abs((datetime.fromisoformat(created_at)
                               - datetime.fromisoformat(conv_ts[p][0])).total_seconds())
                except Exception:
                    continue
                if gap <= 3 and (best_gap is None or gap < best_gap):
                    best, best_gap = conv_ts[p][1], gap
        return f"{best}_resp" if best else ""

    for item in items:
        if item.get("_type") != "log":
            continue
        action = item.get("action") or ""
        if action in FEED_LOG_ACTIONS:
            item["_chat_anchor"] = item.get("id")
        elif action == "llm_call":
            anchor = _pair_llm(item.get("created_at") or "")
            if anchor:
                item["_chat_anchor"] = anchor

    return items


_TERMINAL_TICKET_STATUSES = {
    "completed", "accepted", "done", "blocked", "cancelled",
}


def _step_pair_key(item: dict) -> tuple:
    detail = item.get("_detail") or {}
    return (
        item.get("agent_type") or "",
        detail.get("step_index") or 0,
        detail.get("step_name") or "",
    )


def _promote_in_flight_steps(items: list, ticket_status: str = "") -> list:
    """把当前轮次里尚未收到 done/error 的 skill_step_start 提上主时间轴。

    为什么不在 _classify_tier 里一刀切把所有 skill_step_start 设为 primary：
    已完成步骤的 start 留在主轴只会让每个步骤出现两行（开始 + 完成）。
    但正在跑的那一步还没有 done，沉在「详细日志」里会让主时间轴停在上一条
    已完成步骤，看不出当前卡在哪。

    只看最后一条 thought_start / tool_start / assign 之后的尾段；若那条
    skill_step_start 后面还没有同步骤的 done/error，且后面也没有 thought_done /
    complete / reject / blocked 收尾，就标 `_tier='primary'` + `_running=True`。
    """
    if (ticket_status or "") in _TERMINAL_TICKET_STATUSES:
        return items

    log_indices = [idx for idx, it in enumerate(items) if it.get("_type") == "log"]
    if not log_indices:
        return items

    # 找最近一次 Agent 动作起点
    boundary = 0
    for idx in reversed(log_indices):
        act = items[idx].get("action") or ""
        if act in ("thought_start", "tool_start", "assign"):
            boundary = idx
            break

    tail = [idx for idx in log_indices if idx >= boundary]
    # 若尾段已经收尾（thought_done / tool_done / complete / reject / blocked），说明不在跑
    for idx in tail:
        if (items[idx].get("action") or "") in (
            "thought_done", "tool_done", "complete", "reject", "blocked", "cancelled",
        ):
            return items

    finished_keys = set()
    for idx in tail:
        act = items[idx].get("action") or ""
        if act in ("skill_step_done", "skill_step_error"):
            finished_keys.add(_step_pair_key(items[idx]))

    # 尾段里同 key 只取最后一条未完结的 start
    in_flight_idx = None
    for idx in tail:
        it = items[idx]
        if (it.get("action") or "") == "skill_step_start":
            if _step_pair_key(it) not in finished_keys:
                in_flight_idx = idx

    from llm_client import get_ticket_live_stream
    live_text = get_ticket_live_stream(items[tail[0]].get("ticket_id") or "")

    if in_flight_idx is not None:
        items[in_flight_idx]["_tier"] = "primary"
        items[in_flight_idx]["_running"] = True
        if live_text:
            items[in_flight_idx]["_live_stream"] = live_text

    # 尾段里把「正在跑」标到人能看懂的节点上：当前步骤 / 当前 LLM / 当前思考。
    # 不要标 react_tool —— 那会把主时间轴变成工具流水。
    marked_llm = False
    marked_thought = False
    for idx in reversed(tail):
        act = items[idx].get("action") or ""
        if not marked_llm and act == "llm_call":
            items[idx]["_tier"] = "primary"
            items[idx]["_running"] = True
            if live_text:
                items[idx]["_live_stream"] = live_text
            marked_llm = True
        if not marked_thought and act in ("thought_start", "tool_start"):
            items[idx]["_running"] = True
            if live_text and in_flight_idx is None and not marked_llm:
                items[idx]["_live_stream"] = live_text
            if act == "tool_start":
                items[idx]["_tier"] = "primary"
            marked_thought = True
        if marked_llm and marked_thought:
            break

    return items


async def _annotate_task_refs(ticket_id: str, items: list) -> list:
    """给有真实命令记录的日志标 `_task_ref`（= ticket_command_log.id）。

    沿用 `_annotate_chat_anchors` 的先例：**判据只留一份在后端，前端只认字段**。
    前端原来是拿 ticket_logs 现编伪任务（app.js:18367，id 形如 `titk-<log.id>`），
    点开只有那条日志本身的散文，没有真 argv / exit_code / 输出。

    配对不靠时间猜：`command_record_hook` 写这两条记录时就把
    `ticket_command_log.log_id` 指向了 `ticket_logs.id`，一条 SELECT 反查即可。
    查不到的**不标** —— 宁可没链接，也不要点了跳不到的死链。
    """
    try:
        rows = await db.fetch_all(
            "SELECT id, log_id FROM ticket_command_log "
            "WHERE ticket_id = ? AND log_id != ''",
            (ticket_id,),
        )
    except Exception as e:
        logger.debug("命令记录标注跳过: %s", e)
        return items

    ref_map = {r["log_id"]: r["id"] for r in rows if r.get("log_id")}
    for item in items:
        rid = ref_map.get(item.get("id"))
        if not rid:
            det = item.get("_detail") or {}
            tid = str(det.get("task_id") or "")
            if tid.startswith("TCMD-"):
                rid = tid
        if rid:
            item["_task_ref"] = rid
    return items


async def _annotate_pending_gate_files(ticket_id: str, items: list) -> list:
    """人审 *_ready 的日志/评论补上产物 chip 和确认卡锚点。"""
    try:
        ticket = await db.fetch_one(
            "SELECT project_id, result, status FROM tickets WHERE id = ?",
            (ticket_id,),
        )
    except Exception:
        return items
    if not ticket:
        return items
    try:
        arts = await db.fetch_all(
            "SELECT path FROM artifacts WHERE ticket_id = ?",
            (ticket_id,),
        )
    except Exception:
        arts = []
    pending = await load_ticket_pending_gate(ticket.get("project_id") or "", ticket_id, ticket=ticket)
    result = _parse_ticket_result(ticket)
    files = collect_ticket_output_files(
        result=result,
        pending_gate=pending,
        ticket_id=ticket_id,
    )
    # 旧评论没写路径时才回退到产物表；有确认卡就只挂卡上的文件，避免把角色图贴到试片确认上。
    if not files:
        files = collect_ticket_output_files(
            artifacts=arts,
            result=result,
            pending_gate=pending,
            ticket_id=ticket_id,
        )
    if not files and not pending:
        return items
    for item in items:
        to_st = str(item.get("to_status") or "")
        phase = str(item.get("phase") or "")
        det = item.get("_detail") or {}
        waiting = (
            det.get("skill_status") == "waiting_human"
            or to_st.endswith("_ready")
            or phase.endswith("_ready")
        )
        if not waiting:
            continue
        if files:
            existing = list(item.get("_report_files") or [])
            for f in files:
                if f not in existing:
                    existing.append(f)
            item["_report_files"] = existing
        if pending:
            item["_gate"] = {
                "message_id": pending.get("_message_id") or "",
                "session_id": pending.get("session_id") or "",
            }
    return items


async def _annotate_media_previews(ticket_id: str, items: list) -> list:
    """为时间轴条目补充 `_media_paths`（仓库相对路径列表），供前端直接渲染缩略图并点击打开到 Tab。

    同时兼容历史数据：
    1. ArtistAgent 的 `generate_assets` 日志与 `assets_ready` 评论：从 `artifacts(type='asset_manifest')`
       的 YAML 内容里提取 `docs/.../assets/placeholder/*.png` 等图片路径；
    2. `self_test` / `h5_playtest` / `acceptance_review` / `run_tests`：从日志 `_detail`、
       `tickets.result` 或仓库 `docs/.../screenshots/` 目录提取对应截图。
    """
    import re as _re

    _IMG_EXT_RE = _re.compile(r"\.(png|jpg|jpeg|gif|svg|webp|bmp)$", _re.IGNORECASE)

    # 1. 从 artifacts 提取本工单的资产图片路径与测试截图路径
    asset_img_paths: list[str] = []
    artifact_shots: list[str] = []
    try:
        arts = await db.fetch_all(
            "SELECT type, path, content FROM artifacts WHERE ticket_id = ? ORDER BY created_at DESC",
            (ticket_id,),
        )
        for a in arts or []:
            atype = a.get("type") or ""
            if atype == "asset_manifest" and a.get("content") and not asset_img_paths:
                raw_c = str(a["content"])
                try:
                    c_obj = json.loads(raw_c)
                    if isinstance(c_obj, dict):
                        files_str = "\n".join(str(v) for v in (c_obj.get("files") or {}).values())
                        raw_c = files_str + "\n" + raw_c
                except Exception:
                    pass
                for m in _re.findall(r"path:\s*([^\s\r\n\"'\\}]+)", raw_c):
                    clean_p = m.strip().replace("\\", "/")
                    if _IMG_EXT_RE.search(clean_p) and clean_p not in asset_img_paths:
                        asset_img_paths.append(clean_p)
            elif atype == "screenshot" and a.get("path"):
                sp = str(a["path"]).strip().replace("\\", "/")
                if sp and sp not in artifact_shots:
                    artifact_shots.append(sp)
    except Exception as e:
        logger.debug("提取工单媒体产物跳过: %s", e)

    # 2. 从 tickets 表 + 磁盘 docs/Reqs/<req_short>/<ticket_short>/ + project_environments 提取截图、报告与预览链接
    self_test_shots: list[str] = []
    playtest_shots: list[str] = []
    acceptance_shots: list[str] = []
    report_map: dict[str, str] = {}
    preview_url: str = ""
    repo_root_posix = ""
    try:
        t_row = await db.fetch_one(
            "SELECT project_id, requirement_id, result FROM tickets WHERE id = ?",
            (ticket_id,),
        )
        project_id = (t_row or {}).get("project_id") or ""
        req_id = (t_row or {}).get("requirement_id") or ""
        rdir = None
        if project_id:
            p_row = await db.fetch_one(
                "SELECT git_repo_path, traits FROM projects WHERE id = ?",
                (project_id,),
            )
            rdir = (p_row or {}).get("git_repo_path")
            if not rdir:
                from git_manager import git_manager
                rdir = git_manager._repo_path(project_id)
            if rdir:
                repo_root_posix = str(rdir).replace("\\", "/").rstrip("/") + "/"

            # 视频/内容没有网页可玩，不要把 H5 试玩链接挂到时间轴上。
            from actions.chat.video_identity import is_video_traits, parse_traits
            _traits = parse_traits((p_row or {}).get("traits"))
            attach_playtest = not (
                is_video_traits(_traits)
                or "pipeline:content" in _traits
                or "category:content" in _traits
            )

            # 查询项目的预览环境地址（优先 running 的 dev/test，其次任意已配置的 url）
            if attach_playtest:
                env_rows = await db.fetch_all(
                    "SELECT env_type, status, url FROM project_environments WHERE project_id = ?",
                    (project_id,),
                )
                by_env = {r["env_type"]: r for r in (env_rows or []) if r.get("url")}
                for pref in ("dev", "test", "prod"):
                    if pref in by_env and by_env[pref].get("status") == "running":
                        preview_url = str(by_env[pref]["url"])
                        break
                if not preview_url:
                    for pref in ("dev", "test", "prod"):
                        if pref in by_env:
                            preview_url = str(by_env[pref]["url"])
                            break

        if t_row and t_row.get("result"):
            try:
                res_obj = json.loads(t_row["result"])
                if isinstance(res_obj, dict):
                    st = res_obj.get("self_test") or {}
                    if isinstance(st, dict):
                        for s in (st.get("screenshots") or []):
                            u = s.get("url") if isinstance(s, dict) else str(s or "")
                            u = u.replace("\\", "/")
                            if u and u not in self_test_shots:
                                self_test_shots.append(u)
                    acc_s = res_obj.get("screenshot_path") or ""
                    if acc_s:
                        acceptance_shots.append(str(acc_s).replace("\\", "/"))
            except Exception:
                pass

        # 直接扫描磁盘 docs/Reqs/<req_short>/<ticket_short>/，即使 tickets.result 已被后续阶段覆盖也能找回所有截图与报告
        if rdir and req_id and ticket_id:
            from pathlib import Path as _P
            req_short = str(req_id).split("-")[-1]
            tk_short = str(ticket_id).split("-")[-1]
            tk_docs_rel = f"docs/Reqs/{req_short}/{tk_short}"
            tk_docs_dir = _P(rdir) / "docs" / "Reqs" / req_short / tk_short
            if tk_docs_dir.is_dir():
                for rpt_name in ("dev-notes.md", "code-review.md", "acceptance-review.md", "PRD.md", "architecture.md"):
                    if (tk_docs_dir / rpt_name).is_file():
                        report_map[rpt_name] = f"{tk_docs_rel}/{rpt_name}"
                shots_dir = tk_docs_dir / "screenshots"
                if shots_dir.is_dir():
                    for png in sorted(shots_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True):
                        rel_png = f"{tk_docs_rel}/screenshots/{png.name}"
                        if png.name.startswith("dev_") and rel_png not in self_test_shots:
                            self_test_shots.append(rel_png)
                        elif png.name == "h5_playtest.png" and rel_png not in playtest_shots:
                            playtest_shots.append(rel_png)
                        elif png.name.startswith("acceptance_") and rel_png not in acceptance_shots:
                            acceptance_shots.append(rel_png)
    except Exception:
        pass

    def _norm_rel(p: str) -> str:
        s = str(p or "").strip().replace("\\", "/")
        if repo_root_posix and s.lower().startswith(repo_root_posix.lower()):
            s = s[len(repo_root_posix):]
        return s

    for item in items:
        media: list[str] = []
        if item.get("_type") == "comment":
            phase = str(item.get("phase") or "")
            content = str(item.get("content") or "")
            if phase == "assets_ready" or "资产落地完成" in content:
                for p in asset_img_paths:
                    np = _norm_rel(p)
                    if np and np not in media:
                        media.append(np)
            elif phase == "development_done" or "自测：" in content:
                for p in self_test_shots[:1]:
                    np = _norm_rel(p)
                    if np and np not in media:
                        media.append(np)
                if preview_url:
                    item["_preview_url"] = preview_url
                if "dev-notes.md" in report_map:
                    item["_report_files"] = [report_map["dev-notes.md"]]
            # 评论正文里若有反引号包裹的图片路径也提取出来
            for m in _re.findall(r"`([^`]+\.(?:png|jpg|jpeg|gif|svg|webp))`", content, _re.IGNORECASE):
                np = _norm_rel(m)
                if np and np not in media:
                    media.append(np)
            if media:
                item["_media_paths"] = media
            if phase.endswith("_ready"):
                quoted = [_norm_rel(m) for m in _re.findall(r"`([^`]+)`", content)]
                files = [p for p in quoted if p and "/" in p and not p.endswith(".ads-waiting-human.json")]
                if files:
                    item["_report_files"] = files
            continue

        det = item.get("_detail") or {}
        act = str(item.get("action") or "")
        ag = str(item.get("agent_type") or "")
        to_st = str(item.get("to_status") or "")
        msg = str(item.get("_message") or det.get("message") or "")
        step_name = str(det.get("step_name") or "")

        # 先收集 detail 里显式带的图片路径（file_paths / files / media_paths / screenshots）
        for key in ("media_paths", "screenshots", "file_paths", "git_files", "files"):
            val = det.get(key)
            if not isinstance(val, list):
                continue
            for entry in val:
                raw_p = entry.get("url") if isinstance(entry, dict) else str(entry or "")
                np = _norm_rel(raw_p)
                if np and ("/" in np) and _IMG_EXT_RE.search(np) and np not in media:
                    media.append(np)

        # 补充历史 ArtistAgent 完成日志（仅挂在 generate_assets / thought_done 上，避免 thought_start 和 checkpoint 重复出现）
        if ag == "ArtistAgent" and act in ("generate_assets", "thought_done", "complete") and asset_img_paths:
            for p in asset_img_paths:
                np = _norm_rel(p)
                if np and np not in media:
                    media.append(np)

        # 补充自测验证步骤或开发完成日志的自测截图 + 预览链接 + 自测报告
        if (act == "skill_step_done" and step_name == "自测验证") or (
            act == "complete" and ag == "DevAgent" and ("自测" in msg or to_st == "development_done")
        ):
            for p in self_test_shots[:1]:
                np = _norm_rel(p)
                if np and np not in media:
                    media.append(np)
            if preview_url:
                item["_preview_url"] = preview_url
            if "dev-notes.md" in report_map:
                item["_report_files"] = [report_map["dev-notes.md"]]

        # 补充 H5 试玩步骤与完成日志的试玩截图 + 预览链接（不挂在 skill_step_start 上）
        if (act in ("skill_step_done", "skill_step_error") and "H5 试玩" in step_name) or (
            ag == "TestAgent" and act in ("complete", "reject") and (to_st in ("h5_playtest_passed", "h5_playtest_failed") or "H5 试玩" in msg)
        ):
            for p in playtest_shots:
                np = _norm_rel(p)
                if np and np not in media:
                    media.append(np)
            if preview_url or det.get("preview_url"):
                item["_preview_url"] = str(det.get("preview_url") or preview_url)

        # 补充代码审查报告芯片
        if ag == "ReviewAgent" and act == "code_review" and "code-review.md" in report_map:
            item["_report_files"] = [report_map["code-review.md"]]

        # 补充产品验收截图 + 验收报告芯片 + 预览链接
        if ag == "ProductAgent" and act in ("thought_done", "accept", "reject"):
            for p in acceptance_shots[:1]:
                np = _norm_rel(p)
                if np and np not in media:
                    media.append(np)
            if preview_url:
                item["_preview_url"] = preview_url
            if "acceptance-review.md" in report_map:
                item["_report_files"] = [report_map["acceptance-review.md"]]

        # 补充 TestAgent 测试截图 + 预览链接
        if ag == "TestAgent" and act == "complete" and ("测试通过" in msg or to_st == "testing_done"):
            for p in (artifact_shots or playtest_shots or self_test_shots[:1]):
                np = _norm_rel(p)
                if np and np not in media:
                    media.append(np)
            if preview_url:
                item["_preview_url"] = preview_url

        # 补充 DeployAgent 部署完成的在线预览链接
        if ag == "DeployAgent" and act == "complete":
            if det.get("preview_url") or preview_url:
                item["_preview_url"] = str(det.get("preview_url") or preview_url)

        if media:
            item["_media_paths"] = media[:12]

        # skill 人审：把产物路径挂到 complete / *_ready 评论上，前端渲染成可点 chip
        det_files = []
        for key in ("file_paths", "files", "outputs"):
            val = det.get(key)
            if isinstance(val, list):
                for entry in val:
                    raw_p = entry.get("path") if isinstance(entry, dict) else str(entry or "")
                    np = _norm_rel(raw_p)
                    if np and np not in det_files:
                        det_files.append(np)
        waiting = (
            det.get("skill_status") == "waiting_human"
            or to_st.endswith("_ready")
        )
        if waiting and det_files:
            existing = list(item.get("_report_files") or [])
            for f in det_files:
                if f not in existing:
                    existing.append(f)
            item["_report_files"] = existing

    return items


@router.get("/api/tickets/{ticket_id}/command-logs")
async def get_ticket_command_logs(ticket_id: str, include_noise: int = 0):
    """工单执行期真实跑过的命令。

    默认过滤 `noise=1`（git status / rev-parse 这类例行 plumbing）。
    诊断时传 `?include_noise=1` —— 「什么都没跑」和「跑了但没输出」的区别，
    只有把噪音也拉出来才看得见。
    """
    where = "WHERE ticket_id = ?" + ("" if include_noise else " AND noise = 0")
    rows = await db.fetch_all(
        f"""SELECT id, log_id, source, tool, agent_type, command, cwd, exit_code,
                   status, duration_ms, output, output_bytes, truncated, noise, created_at
            FROM ticket_command_log {where} ORDER BY created_at ASC""",
        (ticket_id,),
    )
    return {"records": rows, "total": len(rows)}


@router.get("/api/ticket-command-logs/{record_id}")
async def get_command_log(record_id: str):
    """单条命令记录全量（刷新页面后前端按 id 直接拉，不依赖内存）。"""
    row = await db.fetch_one(
        "SELECT * FROM ticket_command_log WHERE id = ?", (record_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="命令记录不存在")
    return row


@router.get("/api/tickets/{ticket_id}/timeline")
async def get_ticket_timeline(ticket_id: str):
    """统一时间轴：ticket_logs + ticket_comments 按时间合并"""
    logs = await db.fetch_all(
        "SELECT * FROM ticket_logs WHERE ticket_id = ? ORDER BY created_at ASC",
        (ticket_id,),
    )
    comments = await db.fetch_all(
        "SELECT * FROM ticket_comments WHERE ticket_id = ? ORDER BY created_at ASC",
        (ticket_id,),
    )

    items = []
    # 建 log_id → item 索引快查表，用于把 reply 评论注入到对应 log 下方
    log_id_to_idx: dict = {}

    # 处理日志条目
    for log in logs:
        item = dict(log)
        item["_type"] = "log"
        item["_inline_comments"] = []   # 该 log 下挂的评论
        try:
            detail_obj = json.loads(item.get("detail") or "{}")
            item["_message"] = detail_obj.get("message", "")
            item["_detail"] = detail_obj
        except Exception:
            item["_message"] = item.get("detail", "")
            item["_detail"] = {}
        item["_tier"] = _classify_tier(item)
        log_id_to_idx[item["id"]] = len(items)
        items.append(item)

    # 处理评论条目：先建索引，再做两次遍历
    # 第一遍：收集所有 human 评论和未绑定的 loose 评论
    comment_id_to_item: dict = {}
    log_bound: list = []      # 绑定到 log 的评论
    loose_comments: list = [] # 独立评论（含 human 评论和无父的 agent 评论）

    for comment in comments:
        item = dict(comment)
        item["_type"] = "comment"
        item["_tier"] = "primary"
        item["_replies"] = []   # agent 回复将注入到这里
        comment_id_to_item[item["id"]] = item

        reply_log_id = item.get("reply_to_log_id")
        if reply_log_id and reply_log_id in log_id_to_idx:
            log_bound.append(item)
        else:
            loose_comments.append(item)

    # 第二遍：把有 reply_to_comment_id 的 agent 评论嵌入到父评论的 _replies
    standalone_loose: list = []
    for item in loose_comments:
        parent_id = item.get("reply_to_comment_id")
        if parent_id and parent_id in comment_id_to_item:
            comment_id_to_item[parent_id]["_replies"].append(item)
            # agent 回复不再独立出现，不加入主列表
        else:
            standalone_loose.append(item)

    # 把绑定到 log 的评论注入
    for item in log_bound:
        items[log_id_to_idx[item["reply_to_log_id"]]]["_inline_comments"].append(item)

    # 把无绑定评论加入主列表
    items.extend(standalone_loose)

    # 按时间升序合并
    items.sort(key=lambda x: x.get("created_at") or "")

    # 排序**之后**才标阶段：继承逻辑依赖时序，先标后排会把继承串错
    items, stage_groups = await _annotate_timeline_stages(ticket_id, items)

    t_row = await db.fetch_one("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
    ticket_status = (t_row or {}).get("status") or ""
    items = _promote_in_flight_steps(items, ticket_status=ticket_status)

    # 标注「这条在工单对话里的落点」，前端据此决定要不要渲染跳转链接
    items = await _annotate_chat_anchors(ticket_id, items)

    # 标注「这条背后有真实命令记录」，前端据此渲染「📟 后台记录」链接
    items = await _annotate_task_refs(ticket_id, items)

    # 标注「这条日志或评论关联的截图 / 资产图片」（兼容历史已落库记录）
    items = await _annotate_media_previews(ticket_id, items)

    # 人审节点：把产物路径和确认卡锚点挂到 *_ready 条目（兼容旧评论没写路径）
    items = await _annotate_pending_gate_files(ticket_id, items)

    return {"timeline": items, "total": len(items), "stage_groups": stage_groups}


@router.post("/api/tickets/{ticket_id}/comments")
async def add_ticket_comment(ticket_id: str, body: dict, background_tasks: BackgroundTasks):
    """新增人工评论，保存后立刻异步触发 Agent 回复"""
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="评论内容不能为空")

    # 获取工单，校验存在并拿到 project_id
    ticket = await db.fetch_one("SELECT project_id FROM tickets WHERE id = ?", (ticket_id,))
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")

    comment_id = "CMT-" + generate_id()
    created_at = now_iso()
    reply_to_log_id = body.get("reply_to_log_id") or None
    reply_to_comment_id = body.get("reply_to_comment_id") or None
    await db.insert("ticket_comments", {
        "id": comment_id,
        "ticket_id": ticket_id,
        "project_id": ticket["project_id"],
        "author": "你",
        "author_type": "human",
        "content": content,
        "phase": body.get("phase"),
        "reply_to_log_id": reply_to_log_id,
        "reply_to_comment_id": reply_to_comment_id,
        "created_at": created_at,
    })

    # SSE 推送
    await event_manager.publish_to_project(ticket["project_id"], "comment_added", {
        "ticket_id": ticket_id,
        "comment_id": comment_id,
        "author_type": "human",
        "content": content,
        "reply_to_log_id": reply_to_log_id,
        "reply_to_comment_id": reply_to_comment_id,
        "created_at": created_at,
    })

    # 立刻异步触发 Agent 回复（不阻塞接口响应）
    from orchestrator import orchestrator as _orchestrator
    background_tasks.add_task(
        _orchestrator.reply_to_comment,
        ticket_id=ticket_id,
        project_id=ticket["project_id"],
        comment_content=content,
        comment_id=comment_id,
    )

    return {"id": comment_id, "created_at": created_at}


@router.delete("/api/tickets/{ticket_id}/comments/{comment_id}")
async def delete_ticket_comment(ticket_id: str, comment_id: str):
    """删除人工评论（仅允许删除 human 类型）"""
    comment = await db.fetch_one(
        "SELECT * FROM ticket_comments WHERE id = ? AND ticket_id = ?",
        (comment_id, ticket_id),
    )
    if not comment:
        raise HTTPException(status_code=404, detail="评论不存在")
    if comment["author_type"] != "human":
        raise HTTPException(status_code=403, detail="只能删除人工评论")
    await db.delete("ticket_comments", "id = ?", (comment_id,))
    return {"ok": True}


@router.get("/api/requirements/{req_id}/logs")
async def get_requirement_logs(req_id: str):
    """需求级日志"""
    logs = await db.fetch_all(
        "SELECT * FROM ticket_logs WHERE requirement_id = ? ORDER BY created_at DESC",
        (req_id,),
    )
    return {"logs": logs, "total": len(logs)}


# ==================== 统计 ====================


@router.get("/api/projects/{project_id}/stats")
async def get_project_stats(project_id: str):
    """项目统计数据"""
    # 需求统计
    req_stats = await db.fetch_all(
        "SELECT status, COUNT(*) as count FROM requirements WHERE project_id = ? GROUP BY status",
        (project_id,),
    )

    # 工单统计
    ticket_stats = await db.fetch_all(
        "SELECT status, COUNT(*) as count FROM tickets WHERE project_id = ? GROUP BY status",
        (project_id,),
    )

    # 模块统计
    module_stats = await db.fetch_all(
        "SELECT module, COUNT(*) as count FROM tickets WHERE project_id = ? GROUP BY module",
        (project_id,),
    )

    # Agent 工作量统计
    agent_stats = await db.fetch_all(
        "SELECT agent_type, COUNT(*) as count FROM ticket_logs WHERE project_id = ? AND agent_type IS NOT NULL GROUP BY agent_type",
        (project_id,),
    )

    # 总数
    total_tickets = await db.fetch_one(
        "SELECT COUNT(*) as count FROM tickets WHERE project_id = ?", (project_id,)
    )
    completed_tickets = await db.fetch_one(
        "SELECT COUNT(*) as count FROM tickets WHERE project_id = ? AND status = 'deployed'",
        (project_id,),
    )

    total = total_tickets["count"] if total_tickets else 0
    completed = completed_tickets["count"] if completed_tickets else 0
    completion_rate = round(completed / total * 100, 1) if total > 0 else 0

    return {
        "total_tickets": total,
        "completed_tickets": completed,
        "completion_rate": completion_rate,
        "requirement_stats": {r["status"]: r["count"] for r in req_stats},
        "ticket_stats": {t["status"]: t["count"] for t in ticket_stats},
        "module_stats": {m["module"] or "other": m["count"] for m in module_stats},
        "agent_stats": {a["agent_type"]: a["count"] for a in agent_stats},
    }


# ==================== LLM 会话日志 ====================


@router.get("/api/tickets/{ticket_id}/llm-logs")
async def get_ticket_llm_logs(ticket_id: str):
    """获取工单关联的 LLM 会话记录"""
    logs = await db.fetch_all(
        "SELECT * FROM llm_conversations WHERE ticket_id = ? ORDER BY created_at DESC",
        (ticket_id,),
    )
    return {"conversations": logs, "total": len(logs)}


@router.get("/api/requirements/{req_id}/llm-logs")
async def get_requirement_llm_logs(req_id: str):
    """获取需求关联的 LLM 会话记录"""
    logs = await db.fetch_all(
        "SELECT * FROM llm_conversations WHERE requirement_id = ? ORDER BY created_at DESC",
        (req_id,),
    )
    return {"conversations": logs, "total": len(logs)}


# ==================== 产出文件 ====================


@router.get("/api/tickets/{ticket_id}/artifacts")
async def get_ticket_artifacts(ticket_id: str):
    """获取工单产出文件"""
    artifacts = await db.fetch_all(
        "SELECT * FROM artifacts WHERE ticket_id = ? ORDER BY created_at DESC",
        (ticket_id,),
    )
    return {"artifacts": artifacts, "total": len(artifacts)}


@router.get("/api/requirements/{req_id}/artifacts")
async def get_requirement_artifacts(req_id: str):
    """获取需求关联的全部产出文件"""
    artifacts = await db.fetch_all(
        "SELECT a.*, t.title as ticket_title FROM artifacts a LEFT JOIN tickets t ON a.ticket_id = t.id WHERE a.requirement_id = ? ORDER BY a.created_at DESC",
        (req_id,),
    )
    return {"artifacts": artifacts, "total": len(artifacts)}


# ==================== SSE 事件 ====================


@router.get("/api/projects/{project_id}/events")
async def project_events(project_id: str):
    """项目事件流（SSE）"""
    from sse_starlette.sse import EventSourceResponse

    return EventSourceResponse(
        event_manager.event_generator(f"project:{project_id}")
    )


@router.get("/api/tickets/{ticket_id}/events")
async def ticket_events(ticket_id: str):
    """工单事件流（SSE）"""
    from sse_starlette.sse import EventSourceResponse

    return EventSourceResponse(
        event_manager.event_generator(f"ticket:{ticket_id}")
    )


    # 全局 SSE 端点已移至 main.py（/api/events/global）


# ==================== 内部方法 ====================


async def _post_create_layer_hooks(
    project_id: str,
    ticket_id: str,
    title: str,
    description: str,
    start_from: str,
) -> None:
    """直接创建工单后的"规范层"钩子（fire-and-forget 任务）

    互斥策略（避免重复触发）：
    - start_from == "pending"：
        Planner 钩子把工单推到 planning_in_progress，orchestrator 走完整
        Planner → Architect → OpenSpec Propose。**OpenSpec 钩子跳过**，
        让 Architect 阶段统一触发，避免 new change 重复创建。
    - start_from in ("architecture_done", "development_in_progress")：
        Planner 钩子跳过（用户已选跳过规划）。**OpenSpec 钩子触发**，
        单独补 spec 目录。

    任一钩子失败都仅 warning，不影响工单本身。
    """
    try:
        from capability_check import has_openspec, _get_repo_path
        from orchestrator import orchestrator as orch
        from database import db
        from utils import now_iso

        # ── 1. Planner 钩子（仅 start_from="pending" 才走）────────
        if start_from == "pending":
            try:
                # 把工单推到 planning_in_progress，让 orchestrator 走完整 Planner 流程
                await db.execute(
                    "UPDATE tickets SET status='planning_in_progress', updated_at=? "
                    "WHERE id=? AND status='pending'",
                    (now_iso(), ticket_id),
                )
                await orch.process_ticket(project_id, ticket_id)
                logger.info("🔧 [规范层] Planner 钩子触发（ticket=%s, start_from=pending → 走完整 SOP）", ticket_id[:12])
            except Exception as _pe:
                logger.warning("Planner 钩子失败（不影响工单）: %s", _pe, exc_info=True)
            return  # 关键：pending 路径下不再单独触发 OpenSpec，让 Architect 阶段统一处理

        # ── 2. OpenSpec 钩子（仅 start_from != "pending" 才补）────
        try:
            repo_path = await _get_repo_path(project_id)
            if repo_path and await has_openspec(project_id, repo_path):
                from agents.architect import ArchitectAgent
                await ArchitectAgent()._run_openspec_propose({
                    "project_id": project_id,
                    "ticket_id": ticket_id,
                    "ticket_title": title,
                    "ticket_description": description,
                    "repo_path": repo_path,
                })
                logger.info("📐 [规范层] OpenSpec Propose 钩子触发（ticket=%s, start_from=%s）",
                            ticket_id[:12], start_from)
            else:
                logger.debug("OpenSpec 钩子跳过：项目未安装 OpenSpec（project=%s）", project_id[:12])
        except Exception as _oe:
            logger.warning("OpenSpec Propose 钩子失败（不影响工单）: %s", _oe, exc_info=True)
    except Exception as _e:
        logger.warning("_post_create_layer_hooks 顶层异常: %s", _e, exc_info=True)


async def _log_ticket(
    project_id: str,
    requirement_id: str,
    ticket_id: str,
    agent_type: str,
    action: str,
    from_status: str,
    to_status: str,
    message: str,
    level: str = "info",
):
    """记录工单操作日志并推送 SSE 事件"""
    log_id = generate_id("LOG")
    created_at = now_iso()
    detail_json = json.dumps({"message": message}, ensure_ascii=False)

    await db.insert("ticket_logs", {
        "id": log_id,
        "ticket_id": ticket_id,
        "subtask_id": None,
        "requirement_id": requirement_id,
        "project_id": project_id,
        "agent_type": agent_type,
        "action": action,
        "from_status": from_status,
        "to_status": to_status,
        "detail": detail_json,
        "level": level,
        "created_at": created_at,
    })

    # 实时推送日志
    await event_manager.publish_to_project(
        project_id,
        "log_added",
        {
            "id": log_id,
            "ticket_id": ticket_id,
            "requirement_id": requirement_id,
            "agent_type": agent_type,
            "action": action,
            "from_status": from_status,
            "to_status": to_status,
            "detail": detail_json,
            "level": level,
            "created_at": created_at,
        },
    )


# ==================== 执行命令 (配置 Tab) ====================


@router.get("/api/tickets/{ticket_id}/commands")
async def get_ticket_commands(ticket_id: str):
    """获取工单执行命令列表"""
    commands = await db.fetch_all(
        "SELECT * FROM ticket_commands WHERE ticket_id = ? ORDER BY created_at, step_order",
        (ticket_id,),
    )
    return {"commands": commands, "total": len(commands)}


@router.get("/api/requirements/{requirement_id}/commands")
async def get_requirement_commands(requirement_id: str):
    """获取需求下所有执行命令"""
    commands = await db.fetch_all(
        "SELECT * FROM ticket_commands WHERE requirement_id = ? ORDER BY created_at, step_order",
        (requirement_id,),
    )
    return {"commands": commands, "total": len(commands)}


@router.get("/api/projects/{project_id}/ticket-graph")
async def get_ticket_graph(project_id: str, requirement_id: str = None):
    """获取工单关系图数据（节点 + 边）"""
    if requirement_id:
        tickets = await db.fetch_all(
            "SELECT * FROM tickets WHERE project_id = ? AND requirement_id = ? ORDER BY sort_order, created_at",
            (project_id, requirement_id),
        )
    else:
        tickets = await db.fetch_all(
            "SELECT * FROM tickets WHERE project_id = ? ORDER BY sort_order, created_at",
            (project_id,),
        )

    nodes = []
    edges = []
    ticket_map = {t["id"]: t for t in tickets}

    for t in tickets:
        nodes.append({
            "id": t["id"],
            "title": t["title"],
            "status": t["status"],
            "status_label": STATUS_LABELS.get(t["status"], t["status"]),
            "type": t.get("type", "feature"),
            "module": t.get("module", "other"),
            "priority": t.get("priority", 3),
            "assigned_agent": t.get("assigned_agent"),
            "parent_ticket_id": t.get("parent_ticket_id"),
            "estimated_hours": t.get("estimated_hours"),
        })

        # 父子关系边
        if t.get("parent_ticket_id") and t["parent_ticket_id"] in ticket_map:
            edges.append({
                "source": t["parent_ticket_id"],
                "target": t["id"],
                "type": "parent_child",
            })

        # 依赖关系边
        deps_json = t.get("dependencies", "[]")
        try:
            deps = json.loads(deps_json) if deps_json else []
        except (json.JSONDecodeError, TypeError):
            deps = []

        for dep_id in deps:
            if isinstance(dep_id, str) and dep_id in ticket_map:
                edges.append({
                    "source": dep_id,
                    "target": t["id"],
                    "type": "dependency",
                })

    return {"nodes": nodes, "edges": edges}


@router.post("/api/tickets/{ticket_id}/video-gate")
async def resolve_director_video_gate(ticket_id: str, body: dict = Body(...)):
    """确认或打回 Director 人审节点（``*_ready`` → ``*_done`` / 打回后重跑本 skill）。"""
    action = str(body.get("action") or "").strip().lower()
    if action not in ("confirm", "reject"):
        raise HTTPException(400, "action 必须是 confirm 或 reject")
    ticket = await db.fetch_one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    if not ticket:
        raise HTTPException(404, "工单不存在")
    current = str(ticket["status"] or "")
    if not current.endswith("_ready"):
        raise HTTPException(400, f"当前状态不是待确认（{current}）")
    prefix = current[: -len("_ready")]
    reason = str(body.get("reason") or "").strip()
    if action == "reject" and not reason:
        raise HTTPException(400, "打回必须填写原因")
    new_status = f"{prefix}_done" if action == "confirm" else f"{prefix}_rejected"
    now = now_iso()
    archived = []
    if action == "reject":
        slug = str(body.get("work_slug") or "").strip()
        paths = body.get("preview_paths") or []
        if not isinstance(paths, list):
            paths = [paths] if paths else []
        try:
            project = await db.fetch_one(
                "SELECT * FROM projects WHERE id = ?", (ticket["project_id"],)
            )
            repo = str((project or {}).get("git_repo_path") or "")
            if repo:
                from plugins.director.work_package import archive_paths, find_existing_slug
                slug = slug or find_existing_slug(repo) or ""
                if slug:
                    archived = archive_paths(repo, slug, [str(p) for p in paths if p])
        except Exception as e:
            logger.warning("video-gate 归档失败: %s", e)
        try:
            from orchestrator import orchestrator
            await orchestrator._write_phase_comment(
                ticket["project_id"], ticket_id, "Operator",
                f"人审打回 {prefix}：{reason}",
                phase=new_status,
            )
        except Exception:
            pass

    await db.update("tickets", {"status": new_status, "updated_at": now}, "id = ?", (ticket_id,))
    try:
        from plugins.director.work_package import package_dir, find_existing_slug
        project = await db.fetch_one(
            "SELECT git_repo_path FROM projects WHERE id = ?", (ticket["project_id"],),
        )
        repo = str((project or {}).get("git_repo_path") or "")
        waiting = (_parse_ticket_result(ticket) or {}).get("waiting_human") or {}
        slug = str(
            body.get("work_slug")
            or (waiting.get("work_slug") if isinstance(waiting, dict) else "")
            or ""
        ).strip()
        if repo:
            slug = slug or find_existing_slug(repo) or ""
            if slug:
                marker = package_dir(repo, slug) / ".ads-waiting-human.json"
                if marker.is_file():
                    marker.unlink()
    except Exception as e:
        logger.warning("video-gate 清理 waiting_human 标记失败: %s", e)
    msg_id = str(body.get("message_id") or "").strip()
    if msg_id:
        try:
            await db.execute(
                "UPDATE chat_messages SET action_state=? WHERE id=?",
                ("executed" if action == "confirm" else "cancelled", msg_id),
            )
        except Exception:
            pass
    await event_manager.publish_to_project(
        ticket["project_id"], "ticket_status_changed",
        {"ticket_id": ticket_id, "from": current, "to": new_status, "agent": "Operator"},
    )

    dispatch_status = new_status
    if action == "reject":
        try:
            project = await db.fetch_one(
                "SELECT traits FROM projects WHERE id = ?", (ticket["project_id"],)
            )
            traits = []
            raw_traits = (project or {}).get("traits")
            if isinstance(raw_traits, list):
                traits = raw_traits
            elif isinstance(raw_traits, str) and raw_traits.strip():
                try:
                    parsed = json.loads(raw_traits)
                    if isinstance(parsed, list):
                        traits = parsed
                except json.JSONDecodeError:
                    traits = []
            from sop.loader import compose_sop
            cfg = compose_sop(traits=traits, ticket_type=ticket.get("type") or "feature")
            stage = next((s for s in cfg.get("stages") or [] if s.get("id") == prefix), None)
            if stage and stage.get("trigger_on"):
                dispatch_status = stage["trigger_on"]
                await db.update(
                    "tickets",
                    {"status": dispatch_status, "updated_at": now_iso()},
                    "id = ?", (ticket_id,),
                )
        except Exception as e:
            logger.warning("video-gate 打回重跑定位失败: %s", e)

    try:
        from orchestrator import orchestrator
        import asyncio
        asyncio.create_task(orchestrator.process_ticket(ticket["project_id"], ticket_id))
    except Exception as e:
        logger.warning("video-gate 触发调度失败: %s", e)
    return {
        "ok": True,
        "ticket_id": ticket_id,
        "from": current,
        "to": dispatch_status,
        "gate_status": new_status,
        "reason": reason,
        "archived": archived,
    }
