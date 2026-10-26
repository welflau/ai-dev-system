"""工单命令执行记录 — Action 侧「交出」结构化记录，hook 侧「取走」落库。

## 为什么要 ContextVar

POST_TOOL_USE 拿到的 `ctx.output` 是 adapter 拼好的 `result_text` **字符串**
（`query_engine/engine.py:759`），`ActionResult.data` 在那之前就丢了。而
`GenericCLIAction` / `ShellAction` 早就把 command / exit_code / output 准备
成 dict 了，只是没人接。

试过的另外两条路，都不划算：

- **正则倒解 `result_text`**：`ShellAction.message` 把命令截到 60 字，output
  根本不在 message 里。倒推等于再造一份判据 —— 这仓库已经为「两份判据脱节」
  写过两遍血泪注释（`app.js:18337`、`api/tickets.py:1471`）。
- **改 adapter 回传 `.data`**：`action_data` 在 `engine.py:785` 会驱动
  `final_action`。`OrchestratorToolExecutorAdapter` 现在恒返回 None，改了就会
  让 orchestrator 的 ReAct 路径开始有 `final_action` —— 协议级行为变更，
  为了记个日志不值当。

所以走 ContextVar。这也是本仓库既定手法（`checkpoint/context.py`、
`llm_client._LLMContext`、`skills._current_skills` 三处同构），而且 Action
**本来就没有实例状态**（`actions/base.py` 是纯 ABC，`acceptance_review.py:197`
还留着「写 self.agent_type 结果 AttributeError」的疤），也只能走 ContextVar。
"""
from __future__ import annotations

import logging
import re
from contextvars import ContextVar
from typing import Any, Dict, Optional

from database import db
from utils import generate_id, now_iso

logger = logging.getLogger("command_log")

# ---- 输出体积 ----------------------------------------------------------
# 这库已经 955.9 MB，artifacts 一张表独占 614.9 MB，原始输出直塞 SQLite
# 正是它涨成这样的原因。这里从一开始就设上限。
MAX_OUTPUT_BYTES = 64 * 1024
_HEAD_BYTES = 8 * 1024
_TAIL_BYTES = MAX_OUTPUT_BYTES - _HEAD_BYTES

# ANSI 在**写入侧**剥：存一次干净的，所有读者都省事（渲染侧、复制、全文搜索）。
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

_PENDING: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "ads_cmd_pending", default=None
)


def offer_command_record(**fields: Any) -> None:
    """Action 在 return 前调用，交出一份结构化命令记录。

    没有 hook 来取也无所谓（比如单测直接 run Action）—— 下一次 offer 覆盖它，
    take 一次清一次，不会无限堆积。
    """
    _PENDING.set(dict(fields))


def take_command_record() -> Optional[Dict[str, Any]]:
    """hook 取走待记录的命令。**取走即清。**

    实测：adapter 里 set 的值，在 engine 的 async generator 里 emit
    POST_TOOL_USE 时读得到（同一 Context，没跨 Task）；但调用方 Context
    同样看得见，不清的话上一条命令会漏给下一个工具，串成假记录。
    """
    rec = _PENDING.get()
    if rec is not None:
        _PENDING.set(None)
    return rec


def _truncate_output(text: str) -> tuple[str, int, bool]:
    """返回 (截断后文本, 原始字节数, 是否截断)。

    超限时**头尾都留**（沿用 `ci/strategies/ue.py:288` 的 raw_head/raw_tail
    约定）：头部有「跑的什么、环境如何」，尾部有「错在哪」，只留一端都会
    在排查时缺另一半。
    """
    text = _ANSI_RE.sub("", text or "")
    raw = text.encode("utf-8", errors="replace")
    size = len(raw)
    if size <= MAX_OUTPUT_BYTES:
        return text, size, False
    head = raw[:_HEAD_BYTES].decode("utf-8", errors="ignore")
    tail = raw[-_TAIL_BYTES:].decode("utf-8", errors="ignore")
    omitted = size - _HEAD_BYTES - _TAIL_BYTES
    marker = f"\n\n... [输出截断：原文共 {size} 字节，中间省略 {omitted} 字节] ...\n\n"
    return head + marker + tail, size, True


async def record_command(
    *,
    source: str,
    tool: str,
    command: str,
    cwd: str = "",
    exit_code: Optional[int] = None,
    status: str = "success",
    duration_ms: Optional[int] = None,
    output: str = "",
    noise: bool = False,
    ticket_id: str = "",
    requirement_id: str = "",
    project_id: str = "",
    agent_type: str = "",
    log_id: str = "",
    record_id: str = "",
) -> str:
    """写一行 `ticket_command_log`，返回记录 id。

    `record_id` 可以由调用方先生成再传进来 —— 这是为了让 hook 能**先**把 id
    写进 `ticket_logs.detail.task_id`，两条记录在同一次调用里配好对，不必像
    `_annotate_chat_anchors`（`api/tickets.py:1468`）那样事后按时间差猜。
    """
    rid = record_id or generate_id("TCMD")
    text, raw_bytes, truncated = _truncate_output(output)
    try:
        await db.execute(
            """INSERT INTO ticket_command_log
               (id, ticket_id, requirement_id, project_id, log_id, source, tool,
                agent_type, command, cwd, exit_code, status, duration_ms,
                output, output_bytes, output_file, truncated, noise, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rid, ticket_id or "", requirement_id or "", project_id or "",
                log_id or "", source, tool, agent_type or "",
                command, cwd or "", exit_code, status, duration_ms,
                text, raw_bytes, "", 1 if truncated else 0, 1 if noise else 0,
                now_iso(),
            ),
        )
    except Exception as e:
        # 记录失败绝不能把被记录的命令带下水
        logger.warning("命令记录写入失败 %s %s: %s", source, tool, e)
    return rid


async def record_traced_command(
    *,
    source: str,
    tool: str,
    command: str,
    cwd: str = "",
    exit_code: Optional[int] = None,
    status: str = "success",
    duration_ms: Optional[int] = None,
    output: str = "",
    noise: bool = False,
    ticket_id: str = "",
    requirement_id: str = "",
    project_id: str = "",
    agent_type: str = "",
) -> str:
    """给不经过 POST_TOOL_USE 的命令写时间轴 + 可点的后台记录。

    `command_record_hook` 只在 SkillRunner / run_action 的 hook 链上取
    `offer_command_record`。TestAgent 直接 `action.run(context)` 的路径
    （H5 试玩里的 pip / playwright install / npm install）走不到 hook，
    不在这里成对写入的话，时间轴没有安装过程，也没有「📟 后台记录」。

    配对方式和 hook 相同：先生成 `record_id`，写进 `ticket_logs.detail.task_id`，
    `ticket_command_log.log_id` 指回这条日志。没有 ticket_id 就整段跳过，
    避免再留下 ticket_id='' 的孤儿行。
    """
    if not ticket_id:
        return ""

    record_id = generate_id("TCMD")
    log_id = generate_id("LOG")
    now = now_iso()

    if status == "timeout":
        head = f"⏱ {tool} 超时"
    elif status == "error":
        head = f"❌ {tool} exit={exit_code}"
    else:
        head = f"📟 {tool}"
    message = f"{head} · {command[:100]}"

    import json
    detail = json.dumps({
        "message": message,
        "tool": tool,
        "command": command,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "cwd": cwd or "",
        "status": status,
        "task_id": record_id,
    }, ensure_ascii=False)

    log_ok = False
    try:
        await db.execute(
            "INSERT INTO ticket_logs "
            "(id, ticket_id, project_id, agent_type, action, detail, level, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                log_id, ticket_id, project_id or "__global__",
                agent_type or "System",
                "command_run", detail,
                "error" if status != "success" else "info",
                now,
            ),
        )
        log_ok = True
    except Exception as log_err:
        logger.debug("command_run 时间轴写入失败（记录仍会保留）: %s", log_err)

    await record_command(
        record_id=record_id, log_id=log_id if log_ok else "",
        source=source, tool=tool, command=command, cwd=cwd,
        exit_code=exit_code, status=status, duration_ms=duration_ms,
        output=output, noise=noise,
        ticket_id=ticket_id, project_id=project_id,
        requirement_id=requirement_id, agent_type=agent_type,
    )

    if project_id and log_ok:
        try:
            from events import event_manager
            await event_manager.publish_to_project(project_id, "log_added", {
                "id": log_id,
                "agent_type": agent_type or "System",
                "action": "command_run",
                "detail": detail,
                "level": "error" if status != "success" else "info",
                "created_at": now,
                "ticket_id": ticket_id,
                "_task_ref": record_id,
            })
        except Exception as sse_err:
            logger.debug("record_traced_command SSE 失败（非致命）: %s", sse_err)

    return record_id
