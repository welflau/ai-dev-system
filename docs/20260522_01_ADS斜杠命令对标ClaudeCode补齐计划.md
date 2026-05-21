# ADS 斜杠命令对标 Claude Code 补齐计划

> 日期：2026-05-22
> 状态：规划中
> 原则：命令名称与 Claude Code 保持一致，降低学习成本

---

## 一、现有命令对比

### 已实现（与 Claude Code 对齐或等价）

| ADS 命令 | Claude Code 对应 | 状态 | 备注 |
|---------|----------------|------|------|
| `/compact` | `/compact` | ✅ 名称一致 | 对话历史压缩 |
| `/memory` | `/memory` | ✅ 名称一致 | 记忆查询 |
| `/skills` | `/skills` | ✅ 名称一致 | Skills + Rules 查看 |
| `/think` | `ultrathink` 关键词 | ✅ ADS 扩展 | Extended Thinking 切换 |
| `/mcp-config` | `/mcp` | ⚠️ 名称不同 | MCP 管理 |
| `/aicr-check` | `/review` | ⚠️ 名称不同 | 代码审查 |
| `/ads-init` | `/init` | ⚠️ 名称不同 | 项目初始化 |
| `/memory-export` / `/memory-import` | 无对应 | 🔵 ADS 独有 | 记忆导入导出 |
| `/harness-audit` | 无对应 | 🔵 ADS 独有 | Harness 健康审计 |
| `/aicr-config` / `/aicr-rules` | 无对应 | 🔵 ADS 独有 | AICR 配置 |
| `/save-to-knowledge` / `/search-knowledge` | 无对应 | 🔵 ADS 独有 | 知识库 |

---

## 二、待补齐命令（按优先级）

### P0 — 高频，基础体验

#### `/doctor`
**Claude Code 功能**：检查开发环境健康状态（认证、网络、工具可用性）

**ADS 实现方案**：
```
/doctor
```
检查 ADS 运行状态，输出：
- 后端服务（DB 连接、API 响应）
- LLM 连通性（Anthropic API 可达、model 可用）
- MCP server 状态（各 server 是否 running）
- 项目仓库可访问性（git_repo_path 是否存在）
- `.ads/` / `.claude/` 目录检测

**实现成本**：低（复用现有 `mcp_client.get_status()`、DB ping、API test）

---

#### `/cost`
**Claude Code 功能**：显示当前 session 及历史使用成本

**ADS 实现方案**：
```
/cost              今日费用 + 本月累计
/cost --today      今日明细（按 session）
/cost --month      本月明细（按日）
/cost --session    当前 session 费用
```

**数据来源**：`llm_conversations.cost_usd`（已有，`main.py` 已统计）

**实现成本**：低（已有数据，写 SQL + 格式化即可）

---

### P1 — 常用，提升效率

#### `/config`
**Claude Code 功能**：查看和修改 session 配置（model、theme 等）

**ADS 实现方案**：
```
/config                        查看当前所有 session 配置
/config model claude-opus-4-7  切换模型
/config think on               等价于 /think on
/config compaction off         关闭历史压缩
/config max_turns 20           设置最大工具调用轮次
```

**实现成本**：低（`SetSessionFlagAction` 已有，包装成 `/config` 入口）

---

#### `/diff`
**Claude Code 功能**：查看当前工作区的 git diff

**ADS 实现方案**：
```
/diff              查看 git diff（unstaged）
/diff --staged     查看 staged diff（等同于 git diff --staged）
/diff <文件路径>   查看指定文件的变更
```

**数据来源**：`git_manager._run_git()` 已封装 git 命令

**实现成本**：低（直接调 git diff，格式化输出）

---

#### `/review`（作为 `/aicr-check` 的别名）
**Claude Code 功能**：代码审查

**ADS 实现方案**：
```
/review            等价于 /aicr-check（staged diff PreCommit 扫描）
/review <文件>     针对指定文件做审查
```

直接将 `/review` 路由到现有 `_cmd_aicr_check()` 逻辑。

**实现成本**：极低（1 行 handler 转发）

---

#### `/mcp`（作为 `/mcp-config` 的简短别名）
**Claude Code 功能**：MCP server 管理

**ADS 实现方案**：
```
/mcp               等价于 /mcp-config list
/mcp enable git    等价于 /mcp-config enable git
```

直接将 `/mcp` 路由到 `_cmd_mcp_config()`。

**实现成本**：极低（1 行 handler 转发）

---

### P2 — 锦上添花

#### `/commit`
**Claude Code 功能**：AI 辅助生成 commit message 并提交

**ADS 实现方案**：
```
/commit                LLM 分析 staged diff，生成 commit message，确认后提交
/commit "手动消息"     直接用指定 message 提交
```

**数据来源**：`git_manager.commit()` 已有提交方法

**实现成本**：中（需要 LLM 生成 message + 交互确认流程）

---

#### `/context`
**Claude Code 功能**：可视化当前 context token 使用量

**ADS 实现方案**：
```
/context           显示当前 session 的 token 分布
```
输出：
```
Context 使用情况
  系统提示：    2,400 tokens（规则 1,200 + Skills 800 + 记忆 400）
  对话历史：    8,600 tokens（20 条消息）
  本轮输入：    340 tokens
  ─────────────────────────────
  合计：        11,340 / 200,000 tokens（5.7%）
```

**实现成本**：中（需要在 LLM 调用时记录各段 token 数）

---

#### `/init`（作为 `/ads-init` 的别名）
**Claude Code 功能**：初始化项目 CLAUDE.md

**ADS 实现方案**：
```
/init              等价于 /ads-init
/init --claude     等价于 /ads-init --claude
```

**实现成本**：极低（1 行 handler 转发）

---

## 三、命名统一建议

以下命令建议新增与 Claude Code 一致的别名（原命令保留）：

| 原 ADS 命令 | 新增别名（与 Claude Code 一致） |
|------------|-------------------------------|
| `/ads-init` | `/init` |
| `/aicr-check` | `/review` |
| `/mcp-config` | `/mcp` |

---

## 四、实施路线图

```
Day 1   P0：/doctor + /cost
        ├─ /doctor：DB + API + MCP + git 健康检查
        └─ /cost：今日/本月/session 费用查询

Day 2   P1（简单部分）：/review + /mcp + /init 别名
        ├─ 3 个 1 行转发 handler
        └─ 对应 .md 命令文件

Day 3   P1：/diff + /config
        ├─ /diff：git diff / staged / 指定文件
        └─ /config：session 配置统一入口

Day 4   P2：/commit
        ├─ LLM 生成 commit message
        └─ 交互确认后调 git_manager.commit()

Day 5   P2：/context（token 分布可视化）
```

---

## 五、优先级汇总

| 命令 | 优先级 | 工期 | 实现成本 | 核心价值 |
|------|--------|------|---------|---------|
| `/doctor` | **P0** | 0.5 天 | 低 | 环境诊断，排查问题 |
| `/cost` | **P0** | 0.5 天 | 低 | 费用可见，已有数据 |
| `/review`（别名） | **P1** | 极低 | 极低 | 名称统一 |
| `/mcp`（别名） | **P1** | 极低 | 极低 | 名称统一 |
| `/init`（别名） | **P1** | 极低 | 极低 | 名称统一 |
| `/diff` | **P1** | 0.5 天 | 低 | 配合代码审查 |
| `/config` | **P1** | 0.5 天 | 低 | session 配置统一入口 |
| `/commit` | **P2** | 1 天 | 中 | AI 辅助提交 |
| `/context` | **P2** | 1 天 | 中 | token 可视化 |

---

*文档创建：2026-05-22 | 项目：ai-dev-system | 版本：v1.0*
