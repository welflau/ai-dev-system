"""把工单状态从「当前 SOP 里不存在的软件阶段」拉回可派单的 trigger。

典型坑：视频/内容项目 unblock 菜单默认给「退回开发 → architecture_done」，
但 pipeline:video 已经裁掉 architecture/development。工单进 审核中 却没有任何
SOP 规则能接，于是一直挂着。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set

_SOFTWARE_UNBLOCK = [
    {
        "status": "architecture_done",
        "label": "退回开发（推荐）— 保留架构，重写代码",
        "recommended": True,
    },
    {
        "status": "pending",
        "label": "从头重跑 — 需求/架构/开发全走一遍",
        "recommended": False,
    },
    {
        "status": "development_done",
        "label": "跳过开发 — 直接进审查/验收",
        "recommended": False,
    },
]


def _ids_and_triggers(stages: Iterable[Dict[str, Any]]):
    ids: Set[str] = set()
    triggers: List[str] = []
    successes: Set[str] = set()
    for stage in stages:
        sid = stage.get("id")
        if sid:
            ids.add(sid)
        trig = stage.get("trigger_on")
        if trig:
            triggers.append(trig)
        succ = stage.get("success_status")
        if succ:
            successes.add(succ)
    return ids, triggers, successes


def has_software_stages(stage_ids: Set[str]) -> bool:
    return "architecture" in stage_ids or "development" in stage_ids


def build_unblock_targets(
    stages: List[Dict[str, Any]],
    blocked_from: Optional[str] = None,
    status_labels: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    ids, triggers, _ = _ids_and_triggers(stages)
    if has_software_stages(ids):
        return [dict(item) for item in _SOFTWARE_UNBLOCK]

    labels = status_labels or {}
    allowed = set(triggers) | {"pending"}
    rec = (
        blocked_from if blocked_from in allowed
        else next((t for t in triggers if t and t != "pending"), "pending")
    )
    rec_label = labels.get(rec, rec)
    targets = [{
        "status": rec,
        "label": f"重跑卡住的阶段（推荐）— 回到「{rec_label}」",
        "recommended": True,
    }]
    if rec != "pending":
        targets.append({
            "status": "pending",
            "label": "从头重跑 — 策划起整条链路",
            "recommended": False,
        })
    return targets


def restore_target_from_cancelled_status(
    from_status: Optional[str],
    stages: List[Dict[str, Any]],
) -> str:
    """取消前的状态 → 可再派单的 trigger。

    停在 `director_visual_in_progress` 时不能写回去（那是执行中，没有 SOP 规则），
    要回到该阶段的 trigger_on（`director_script_done`）才会重跑 visual。
    """
    s = (from_status or "").strip()
    if not s or s in ("cancelled", "blocked"):
        return "pending"
    _, triggers, successes = _ids_and_triggers(stages)
    if s == "pending" or s in triggers:
        return s
    if s.endswith("_in_progress"):
        stage_id = s[: -len("_in_progress")]
        for stage in stages:
            if stage.get("id") == stage_id:
                return stage.get("trigger_on") or "pending"
        return "pending"
    if s.endswith("_ready") or s in successes:
        return s
    return "pending"


def build_restore_cancelled_targets(
    stages: List[Dict[str, Any]],
    cancelled_from: Optional[str] = None,
    status_labels: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    labels = status_labels or {}
    rec = restore_target_from_cancelled_status(cancelled_from, stages)
    rec_label = labels.get(rec, rec)
    targets = [{
        "status": rec,
        "label": f"从停下的阶段继续（推荐）— 回到「{rec_label}」",
        "recommended": True,
    }]
    if rec != "pending":
        targets.append({
            "status": "pending",
            "label": "从头重跑 — 策划起整条链路",
            "recommended": False,
        })
    return targets


def sop_safe_unblock_target(
    requested: str,
    stages: List[Dict[str, Any]],
    blocked_from: Optional[str] = None,
) -> str:
    """软件默认项 architecture_done 在视频 SOP 里不存在时，改成可派单的 trigger。"""
    targets = build_unblock_targets(stages, blocked_from)
    allowed = {t["status"] for t in targets}
    if requested in allowed:
        return requested
    return targets[0]["status"] if targets else "pending"


# 软件阶段残留态：只在「当前 SOP 已经裁掉 architecture/development」时才回退。
# 不能对任意「SOP 里没有的状态」动手——bug 工单没有 ux_design 阶段，但
# ux_design_done 是历史停靠点，回退会把半年前的 JumpGame BUG 整条流水线跑起来。
_SOFTWARE_LEFTOVER_STATUSES = {
    "architecture_done",
    "development_done",
    "review_passed",
    "ux_design_done",
    "art_design_done",
    "html_prototype_done",
}


def next_status_if_outside_sop(
    status: str, stages: List[Dict[str, Any]],
) -> Optional[str]:
    """仅当视频/内容流水线误停在软件阶段 success 态时，回到可派单 trigger。

    人审 *_ready、执行中 *_in_progress、blocked/cancelled、以及仍含
    architecture/development 的软件项目，一律不改。
    """
    if not status or status in ("blocked", "cancelled", "pending"):
        return None
    if status.endswith("_in_progress") or status.endswith("_ready"):
        return None
    ids, triggers, successes = _ids_and_triggers(stages)
    if has_software_stages(ids):
        return None
    if status in triggers or status in successes:
        return None
    if status not in _SOFTWARE_LEFTOVER_STATUSES:
        return None
    new = next((t for t in triggers if t and t != "pending"), "pending")
    if not new or new == status:
        return None
    return new
