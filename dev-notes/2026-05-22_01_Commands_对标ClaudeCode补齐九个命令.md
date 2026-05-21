# Commands — 对标 Claude Code 补齐九个命令

> 日期：2026-05-22
> 提交：`7c070a1`
> 参考文档：`docs/20260522_01_ADS斜杠命令对标ClaudeCode补齐计划.md`

---

## 背景

ADS 原有 16 个斜杠命令，与 Claude Code 标配命令存在较大差距，且部分命令名称不统一（如 `/aicr-check` vs Claude 的 `/review`，`/mcp-config` vs `/mcp`）。本次一次性补齐，命令总数 **16 → 26**。

---

## 新增命令总览

### P0：基础体验

#### `/doctor`
检查 ADS 四项运行状态：

```
## ADS 环境诊断

✅ 数据库：连接正常
✅ LLM：已配置（claude-sonnet-4-6）
✅ MCP：2 运行中 / 1 已禁用
✅ 项目仓库：/path/to/project
   git: ✅  .ads/: ✅  .claude/: ⭕
💰 今日费用：$0.0240
```

**实现**：复用 `db.fetch_one("SELECT 1")`、`llm_client.is_configured`、`mcp_client.get_status()`，无新依赖。

---

#### `/cost`
三种模式：

| 命令 | 内容 |
|------|------|
| `/cost` | 今日 + 本月 + 近 7 天柱状图 |
| `/cost --month` | 本月按日明细 |
| `/cost --session` | 当前 session 费用 |

**数据来源**：`llm_conversations.cost_usd`（已有），SQL 聚合即可。

近 7 天输出示例：
```
今日费用：$0.0240
本月累计：$1.2800

近 7 天：
  2026-05-22  $0.0240  ██
  2026-05-21  $0.3600  ████████████████████
  2026-05-20  $0.1200  ████████
```

---

### P1：效率提升

#### `/diff`
```
/diff              工作区变更（git diff）
/diff --staged     staged 变更（git diff --staged）
/diff src/foo.cpp  指定文件变更
```
超过 200 行自动截断并提示。

---

#### `/config`
Session 配置统一入口，替代分散的 `/think on/off` 等命令：

```
/config                    列出所有配置项
/config thinking_mode on   等同于 /think on
/config compaction off     关闭历史压缩
/config max_turns 20       最大工具调用轮次
```

**实现**：包装 `SetSessionFlagAction` 的 `_SESSION_FLAGS` 字典，与 `/think` 命令共享同一底层存储。

---

### P1：名称统一别名（1 行转发）

| 新命令 | 原命令 | 说明 |
|--------|--------|------|
| `/review` | `/aicr-check` | 与 Claude Code 名称一致 |
| `/mcp` | `/mcp-config` | 与 Claude Code 名称一致 |
| `/init` | `/ads-init` | 与 Claude Code 名称一致 |

---

### P2：进阶功能

#### `/commit`
```
/commit                    LLM 分析 staged diff → 生成 Conventional Commits 格式 message → git commit
/commit "fix: 修复登录"    直接使用指定 message 提交
```

生成 message 使用 `temperature=0.2`，格式：`<type>(<scope>): <subject>`。

---

#### `/context`
```
Context 使用情况

对话历史：约 8,600 tokens（20 条消息）
Token 预算：300,000
使用率：2.9%  [█░░░░░░░░░░░░░░░░░░░░░░░░░░░░░]
上次调用：3,240 tokens（输入+输出）
```

token 数通过字符数估算（÷4），上次调用精确值从 `llm_conversations` 取。

---

## 文件变更

```
backend/api/commands.py          实现 9 个新 handler + 注册别名
backend/skills/commands/
  ├── doctor.md
  ├── cost.md
  ├── diff.md
  ├── config.md
  ├── commit.md
  ├── context.md
  ├── review.md    (别名)
  ├── mcp.md       (别名)
  └── init.md      (别名)
```

---

## 推荐工作流

代码提交标准流程，现在全程 ADS 命令完成：

```
/diff --staged     ← 确认变更内容
/review            ← 代码审查（bug pattern 扫描）
/commit            ← AI 生成 message + 提交
/cost --session    ← 查本次费用
```
