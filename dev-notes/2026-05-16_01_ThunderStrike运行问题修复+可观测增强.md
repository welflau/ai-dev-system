# ThunderStrike 运行问题修复 + 可观测性增强

> 日期：2026-05-15~16  
> 提交范围：`c5ae407` → `2459649`（9 个提交）

---

## 一、ThunderStrike 工单卡住问题排查记录

### 问题现象
- 工单看板 35 张工单，处理中持续为 0
- DeployAgent 对同 3 张工单无限循环（b84c6c / c0ae70 / 381b8b）
- 日志大量 `database is locked` 错误

### 根本原因链

```
1. SOP 组合问题（deployed → deploy 死循环）
   _relink_stage_transitions 将 core SOP 的 deploy 阶段重新链接到
   deploy_web fragment 的 success_status=deployed，产生：
   [deployed] → DeployAgent.deploy → success_status=deployed → 无限循环

2. 缓存未清除
   _project_rules_cache 缓存了错误规则，热重载不清空，
   需要完整重启服务器才能重置

3. database is locked
   35 张工单并发 × 3 槽位，SQLite WAL 模式下写锁竞争超时（30s 不够）
   导致 Orchestrator 拾取工单后立即失败，看起来"不动"
```

### 修复

| 修复 | 方案 |
|------|------|
| SOP 死循环 | `_TERMINAL_STATUSES = frozenset({'deployed', 'cancelled'})`，`_get_all_actionable_statuses()` 硬排除，无论 SOP 配置如何 |
| 并发冲突 | `_MAX_CONCURRENT_PER_PROJECT` 3→2 |
| DB 超时 | `busy_timeout` 30s→60s，`cache_size=-32000`（32MB），`wal_autocheckpoint=1000` |
| DeployAgent KeyError | `del _preview_servers[key]` → `_preview_servers.pop(key, None)` 并发安全 |
| 循环工单恢复 | 手动 DB 重置 deployed → testing_done，重启服务清空 cache |

---

## 二、功能增强

### ActionNode LLM 调用加超时

**背景**：Orchestrator Agent（ArchitectAgent/DevAgent 等）通过 ActionNode
直接调 `llm.chat_json()`，没有任何超时，昨天出现工单运行 70 分钟不停的情况。

**修复**：`asyncio.wait_for(timeout=AGENT_MAX_SECONDS)`，
- 超时 → emit `TOOL_ERROR` Hook → AI 聊天面板报警
- 成功 → emit `SESSION_END` Hook → tool_audit_log 记录耗时

---

### Agent 关键错误推送到 AI 聊天面板

**路径**：git push 失败 / ticket blocked → emit `TOOL_ERROR` Hook
→ `chat_alert_hook`（新内置 Hook）→ `agent_alert` SSE
→ 聊天面板插入红色通知气泡

```
⚠️ Git Push 失败
代码已提交但未推送到远端仓库。
原因：Repository not found...
工单 ID: xxxxxxxx，可发送「查看工单状态」了解详情。
```

**架构意义**：所有关键错误统一走 HookRegistry，不散落在各处手动 publish。

---

### 日志面板工单 ID 可点击

`_linkifyTicketIds()` 函数：把日志消息中的工单 ID 变成可点击蓝色链接，
点击直接打开工单抽屉。支持：
- `工单 381b8b`（6-8 位十六进制后缀）
- `TK-20260514-xxxxxx`（完整工单 ID）

`renderLogItem` 和 `addLog` 两处均已应用。

---

### Orchestrator 调度状态面板

**位置**：Agent 监控页顶部，5 秒刷新

**新增 API**：`GET /api/agents/orchestrator`
- 并发槽位使用率（█████░ 2/2）
- 正在执行的 Agent 列表（agent + action + ticket_id + 已运行时间）
- 超过 5 分钟显示黄色警告
- 待处理队列按状态聚合（development_done×3 / acceptance_rejected×1 ...）
- 前 5 条队列预览（工单 ID 可点击）

---

## 三、其他修复

| 提交 | 内容 |
|------|------|
| `b7be7ee` | CI lint：补充 Path import + 排除第三方 skill 脚本 |
| `f4596d8` | 工单抽屉 deploy_config 产物去重，只显示最新一条（历史循环遗留 3+ 张）|

---

## 四、实战教训

### SOP 配置错误导致无限循环

ThunderStrike 的 `_relink_stage_transitions` 把 `deploy` 阶段的 trigger 重链到上一个 stage 的 success_status（`deployed`），产生 `deployed → DeployAgent.deploy` 的死规则。

**预防措施**：Orchestrator 层硬编码 `_TERMINAL_STATUSES`，
`deployed / cancelled` 永远不能成为 actionable 状态。

### 服务重启 ≠ 缓存清除

uvicorn `--reload` 是文件变更重载，`_project_rules_cache` 在内存里。
如果重载触发前就已经缓存了错误规则，规则依然生效。

**最佳实践**：改完 SOP 逻辑后务必完整重启进程（pkill + restart）。

### database is locked 的根本解法

SQLite WAL 模式仍有单写者限制。当并发工单数 > 3 时，
写锁竞争超过 `busy_timeout` 会导致级联失败（每个失败再写日志也失败）。

**现行缓解**：并发 2 + timeout 60s + 32MB cache。  
**长期方案**：考虑 PostgreSQL 或工单处理结果批量写入。
