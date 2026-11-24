"""止损用的计数：工单被打回了几次，同一个失败原因连续出现了几次，验收重派了几次。

所有计数都以最近一次人工解除 blocked 的时间点（`last_reset_at`）为起点，解除之后历史记录清零，
工单才能真正重跑。`process_ticket` 的熔断检查读这些数字决定要不要把工单标成 blocked。

约定（`orchestration` 包里按职责拆出的模块都一样）：

- 函数体从 `TicketOrchestrator` 的同名方法原样搬来，函数名去掉了前导下划线。改动只有
  `self` 写成 `orch`，以及下面单独列出的几处。
- `TicketOrchestrator` 上保留同名方法，只做转发。这里的函数互相调用、调用别的模块里的
  逻辑都走 `orch.xxx`，测试给实例打的桩才会生效。
- `db` 由转发方法在调用时传入，这里不导入它。测试用
  `monkeypatch.setattr(orchestrator, "db", test_db)` 换库，函数必须拿到同一个对象。
- 状态都放在 `orch` 上，这个模块自己不存状态。
- 函数内的延迟导入保持原样，测试的打桩打在这些源模块上。
"""
import json
from typing import Optional


async def last_reset_at(orch, db, ticket_id: str) -> Optional[str]:
    """最近一次人工解除 blocked / 重置计数的时间点，作为所有止损计数的共同起点。

    人工解除是显式的「问题已排查，重新给机会」信号。全局 reject 计数、
    连续同因失败计数、验收重派计数都以此清零，保证解除后工单能真正重跑，
    而不是被历史计数秒回 blocked（TK-20261110-48b6af 曾因此连点 4 次都解不开）。

    防无限续命不靠「限制清零次数」，而靠解除后重新累计的止损闸门：
    连续 3 次同因失败 / 5 次 reject 会再次熔断，自动循环最多烧 3 次 LLM 即停。
    """
    row = await db.fetch_one(
        """SELECT created_at FROM ticket_logs
               WHERE ticket_id = ? AND action IN ('unblock', 'reject_reset')
               ORDER BY created_at DESC LIMIT 1""",
        (ticket_id,),
    )
    return (row or {}).get("created_at")


async def reject_count_since_reset(
    orch, db, ticket_id: str, to_status: Optional[str] = None,
) -> int:
    """工单被打回的次数，**只数最近一次人工解除 blocked 之后的**。

    原先 `MAX_UNBLOCK_RESETS=2` 会把计数起点钉死在第 2 次 unblock：工单
    解除过 2 次后，之后所有 unblock 都不再生效、历史 reject 全数计入 →
    永久锁死 blocked。现改为始终以最近一次 unblock 为界。

    to_status 非空时只数打回到该状态的（供按阶段止损的 max_retries 用）。
    """
    since = await orch._last_reset_at(ticket_id)

    sql = "SELECT COUNT(*) AS c FROM ticket_logs WHERE ticket_id = ? AND action = 'reject'"
    params: list = [ticket_id]
    if to_status:
        sql += " AND to_status = ?"
        params.append(to_status)
    if since:
        sql += " AND created_at > ?"
        params.append(since)

    row = await db.fetch_one(sql, tuple(params))
    return (row or {}).get("c", 0) or 0


def failure_fingerprint(detail: str) -> str:
    """把 reject 原因归一化成稳定指纹：去掉动态数字、截长度。无原因返回空串。

    同一失败反复出现时 reason 完全一致（如「LLM 输出无效。项目已有代码…」），
    只是耗时/文件数会变，去数字即可对齐；空原因（验收打回）不参与熔断判定。
    """
    try:
        d = json.loads(detail)
        reason = str(d.get("reason") or d.get("message") or "")
    except (ValueError, TypeError):
        reason = str(detail or "")
    # 连续数字压缩成单个 #：耗时 12345ms 与 999ms 归一化后必须一致
    out, in_digit = [], False
    for ch in reason:
        if ch.isdigit():
            if not in_digit:
                out.append("#")
            in_digit = True
        else:
            out.append(ch)
            in_digit = False
    return "".join(out).strip()[:120]


async def consecutive_same_failure(orch, db, ticket_id: str) -> tuple:
    """最近连续出现同一失败原因的 reject 次数（跳过无原因的验收打回）。

    以最近一次 unblock 为界：解除后历史同因失败清零，工单能真正重跑；
    解除后若又连续出现同一原因失败，重新累计到 3 次即再次熔断（防烧 token）。
    """
    since = await orch._last_reset_at(ticket_id)
    sql = """SELECT detail, to_status FROM ticket_logs
                 WHERE ticket_id = ? AND action = 'reject'"""
    params: list = [ticket_id]
    if since:
        sql += " AND created_at > ?"
        params.append(since)
    sql += " ORDER BY created_at DESC LIMIT 20"
    rows = await db.fetch_all(sql, tuple(params))
    count, fingerprint = 0, ""
    for row in rows:
        # 验收打回与 development_failed 交替出现，若计入会把连续链切断
        # （TK-20261110-48b6af 实测：10+ 次同一句「LLM 输出无效…」中间夹着验收打回）。
        # 验收环节的止损由全局 MAX_RETRIES 与阶段级 max_retries 兜底，此处只盯开发失败。
        if (row.get("to_status") or "") == "acceptance_rejected":
            continue
        fp = orch._failure_fingerprint(str(row.get("detail") or ""))
        if not fp:
            continue
        if not fingerprint:
            fingerprint = fp
        if fp != fingerprint:
            break
        count += 1
    return count, fingerprint


async def acceptance_retry_count(orch, db, ticket_id: str) -> int:
    """本工单因「验收 LLM 降级」已重派验收的次数（自最近一次 unblock 起）。

    与 _reject_count_since_reset 口径一致，但统计的是独立的
    `acceptance_retry` 日志动作 —— 它不是 `reject`，因此不进全局
    MAX_RETRIES / 同因熔断 / Failure Library，也不触发返工链。
    """
    since = await orch._last_reset_at(ticket_id)
    sql = ("SELECT COUNT(*) AS c FROM ticket_logs "
           "WHERE ticket_id = ? AND action = 'acceptance_retry'")
    params: list = [ticket_id]
    if since:
        sql += " AND created_at > ?"
        params.append(since)
    row = await db.fetch_one(sql, tuple(params))
    return (row or {}).get("c", 0) or 0
