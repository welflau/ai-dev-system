# 开发日志 — 2026-05-08 DevAgent force_pass 死循环修复

## 问题现象

JumpGame 项目「玩家移动与跳跃系统」需求（REQ-20260508-39d511）在所有工单被 force_pass 后，
一直卡住无法合入 develop，持续约 2 小时后用户手动取消。

用户取消时留下的原因注释：
> Pipeline 卡在合并阶段 2 小时无响应，重新创建

---

## 根本原因分析

### 直接原因：DevAgent 覆盖了 force_pass 的结果

`orchestrator.py` 中 DevAgent 完成时的写入逻辑（第 1783 行）：

```python
new_status = TicketStatus.DEVELOPMENT_DONE.value

await db.update("tickets", {
    "status": new_status,   # ← 无条件写入，不检查现在是什么状态
    ...
}, "id = ?", (ticket_id,))
```

DevAgent 是**异步任务**，在它执行期间 Orchestrator 可以修改工单状态（force_pass）。
任务跑完后无条件写入 `development_done`，把已经是 `testing_done` 的状态覆盖掉。

### 完整循环链

```
T1: Orchestrator 触发 DevAgent 异步执行（status = development_in_progress）
T2: ProductAgent 打回 5 次 → Orchestrator force_pass
    status: development_in_progress → testing_done
T3: DevAgent 异步任务执行完毕，写入 development_done
    status: testing_done → development_done  ← 覆盖！
T4: Orchestrator 下次轮询发现 development_done，再次触发 DevAgent
    → 回到 T1，无限循环
```

### 为什么 merge_develop 永远不触发？

merge_develop 的触发条件：**该需求所有工单都是 testing_done**。

由于循环，在 Orchestrator 每 30 秒的轮询时刻，总有 1 个工单刚被 DevAgent 推回 `development_done`，
条件永远不成立，merge_develop 永远触发不了。

### 日志证据

```
[13:38] Orchestrator force_pass: development_done → testing_done  ← 强制完成
[13:38] DevAgent complete:        testing_done     → development_done  ← 覆盖！
[13:38] Orchestrator force_pass: development_done → testing_done  ← 再次强制
...（循环 2 小时）
[15:42] ChatAssistant update_status: in_progress → cancelled
```

---

## 修复方案

在 DevAgent 写入 `development_done` 前，重新从 DB 读取工单最新状态，
如果已是 `testing_done / deployed / cancelled`，跳过写入。

```python
# 写入前重新读一次最新状态，防止 force_pass / 外部修改被覆盖
latest = await db.fetch_one("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
latest_status = (latest or {}).get("status", current_status)
_TERMINAL_STATUSES = {
    TicketStatus.TESTING_DONE.value,
    TicketStatus.DEPLOYED.value,
    "cancelled",
}
if latest_status in _TERMINAL_STATUSES:
    logger.info("⏭ 工单 %s 当前状态 %s 已超过 development_done，跳过写入", ...)
    return
```

**修改文件**：`backend/orchestrator.py`，第 1783 行附近。

**commit**：`5d41b70`

---

## 关联问题

同样的竞态条件可能存在于其他 Agent 的 `complete()` 逻辑中（ReviewAgent、TestAgent 等），
需要后续统一排查：**所有 Agent 在写入新状态前都应该做「乐观锁」检查**。

---

## 延伸：force_pass 机制的设计缺陷

当前 force_pass 只改 DB 状态，不通知/停止正在执行的异步任务。
长期方案：给工单加「已锁定」标志，Agent 开始执行前检查锁，被锁定的工单不再接受状态写入。
