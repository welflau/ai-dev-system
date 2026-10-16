# Agent 群聊 PM 驱动循环 Phase 1

2026-10-13

## 背景

黑板群聊从「固定回合制辩论」升级为「PM 驱动动态循环」：OrchestratorAgent 主持，
动态决定 ask（发问/@点名）/ summarize（小结）/ conclude（收敛），直到达成目标或预算耗尽。
解决「一问一答、聊不下去」的问题。

方案文档：`docs/20261013_02_PM驱动群聊循环实现方案.md`

## 改动

### 后端（api/chat.py）

- `GroupBoardRequest` 加 `mode`（pm/legacy）、`max_pm_decisions`（8）、`max_agent_rounds`（4）。
- `_empty_board` 加 `goal` / `summary` 分区（向后兼容，legacy 不用）。
- 新增 `_group_board_pm_generator`：PM 决策循环 + 兜底强制收敛。
- 新增 `_pm_extract_goal`（需求 A 目标提炼）/ `_pm_decide`（PM 决策）/ `_pm_state_view`（决策状态视图）。
- 新 SSE：`pm_goal` / `pm_action` / `pm_summary`。
- `group_board` 端点按 mode 分发。

### 前端

- `_sendGroupBoardStreaming` 消费 `pm_goal`（目标卡）/ `pm_action`（PM 决策过程行）/ `pm_summary`（纪要卡）。
- 请求体加 `mode:'pm'`。
- 新 CSS：`.group-board-goal` / `.group-board-summary` / `.gbs-badge-pm`。
- 版本戳 → `v=20261013d`。

## 关键语义

- **PM 决策循环**：每轮 PM 读「goal + 黑板 + 纪要 + 介入」→ 输出 `{action, targets, question/summary/conclusion, reason}`。
- **需求 A**：首条消息提炼 goal + acceptance_criteria，作为收敛判据；提炼失败降级用消息本身。
- **需求 B**：每条新用户消息作为「介入」注入 PM 决策首步（最高优先级）。
- **纪要 summary**：PM summarize 写入，注入后续决策（最近 5 条）——跨消息「接着聊」的关键。
- **@点名**：`targets` 定向回复（空=全体）。

## 验证

- `py_compile` / `node --check` 通过。
- 端到端 HTTP（mode=pm）：`pm_goal → pm_action×3 → round_begin×2 → agent_thought/agent_message×2 → pm_summary → converge → message_done` 完整；PM 正确 @DevAgent 定向追问。

## 修复的 bug

1. `_pm_extract_goal` / `_pm_decide` 缺 `set_llm_context` 导入 → NameError（模块级函数无 generator 里的局部 import）。
2. goal 提炼 `max_tokens=800` 易截断导致 JSON 解析失败 → 改 1500 + 提示 acceptance_criteria 简短。
3. `max_agent_rounds` 耗尽时 `continue` 死代码（decision 被下一轮覆盖）→ 改 `break` 落到兜底收敛。

## 遗留（Phase 2）

- 需求 B 实时打断（当前靠前端 Abort 重发，非同一流内打断）。
- @点名 `reply_to` 前端引用高亮。
- 目标卡/纪要卡的刷新还原。
