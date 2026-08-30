"""Checkpoint 写上下文（contextvars），供 git_manager 等无 ticket 形参的漏斗读取。"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Dict, Optional

_CTX: ContextVar[Optional[Dict[str, Any]]] = ContextVar("ads_checkpoint_ctx", default=None)


def set_checkpoint_context(
    *,
    project_id: str = "",
    ticket_id: str = "",
    agent_type: str = "",
    action: str = "",
    repo_path: str = "",
) -> None:
    cur = dict(_CTX.get() or {})
    if project_id:
        cur["project_id"] = project_id
    if ticket_id:
        cur["ticket_id"] = ticket_id
    if agent_type:
        cur["agent_type"] = agent_type
    if action:
        cur["action"] = action
    if repo_path:
        cur["repo_path"] = repo_path
    _CTX.set(cur)


def clear_checkpoint_context() -> None:
    _CTX.set(None)


def get_checkpoint_context() -> Dict[str, Any]:
    return dict(_CTX.get() or {})
