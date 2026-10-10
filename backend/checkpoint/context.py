"""Checkpoint 写上下文（contextvars），供 git_manager 等无 ticket 形参的漏斗读取。"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Dict, Optional

_CTX: ContextVar[Optional[Dict[str, Any]]] = ContextVar("ads_checkpoint_ctx", default=None)


def set_checkpoint_context(
    *,
    project_id: str = "",
    ticket_id: str = "",
    requirement_id: str = "",
    agent_type: str = "",
    action: str = "",
    repo_path: str = "",
) -> None:
    cur = dict(_CTX.get() or {})
    if project_id:
        cur["project_id"] = project_id
    if ticket_id:
        cur["ticket_id"] = ticket_id
    if requirement_id:
        cur["requirement_id"] = requirement_id
    if agent_type:
        cur["agent_type"] = agent_type
    if action:
        cur["action"] = action
    if repo_path:
        cur["repo_path"] = repo_path
    _CTX.set(cur)


def push_checkpoint_context(**fields: str) -> Token:
    """嵌套设置上下文，返回 token；离开时用 pop_checkpoint_context(token) 还原。

    为什么要有这一对：`set_*` 是 **merge** 语义（只覆盖非空字段），
    `clear_*` 却是无条件 `set(None)` —— 不对称。于是
    `orchestrator.py:1535` 设了工单级上下文后，`agents/base.py` 嵌套再设、
    finally 里一 clear，**把外层工单级的一起清了**，后续 git 操作就成了
    没有 ticket_id 的孤儿（实库里 `ToolError:git:commit_failed` 2921 行
    ticket_id 全空，这是其中一个成因）。

    嵌套点用 push/pop 配对，最外层的 orchestrator 继续用 set/clear。
    """
    prev = _CTX.get()
    cur = dict(prev or {})
    for k, v in fields.items():
        if v:
            cur[k] = v
    return _CTX.set(cur)


def pop_checkpoint_context(token: Optional[Token]) -> None:
    """还原到 push 之前的上下文。token 为 None 时是 no-op（方便 finally 里直接调）。"""
    if token is None:
        return
    try:
        _CTX.reset(token)
    except ValueError:
        # token 来自别的 Context（跨 Task 了），只能退而求其次不还原
        pass


def clear_checkpoint_context() -> None:
    _CTX.set(None)


def get_checkpoint_context() -> Dict[str, Any]:
    return dict(_CTX.get() or {})
