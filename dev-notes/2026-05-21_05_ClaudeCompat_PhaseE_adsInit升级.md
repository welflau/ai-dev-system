# ClaudeCompat Phase E — ads-init 升级

> 日期：2026-05-21
> 提交：`de5ab6c`
> 系列：ClaudeCompat（ADS 兼容 Claude Code 目录结构）

---

## 目标

`/ads-init` 命令智能检测 `.claude/` 是否已存在，避免重复创建规则文件；新增 `--claude` 参数一键生成标准 `.claude/` 骨架；所有情况下生成 `ADS.md` 模板。

---

## 三种执行模式

| 场景 | 命令 | 行为 |
|------|------|------|
| 全新项目，无 `.claude/` | `/ads-init` | 完整生成 `.ads/` + `ADS.md` |
| 已有 `.claude/` 的项目 | `/ads-init` | 扩展模式：只生成 ADS 专属文件，提示读取策略 |
| 新项目，需要同时生成两套 | `/ads-init --claude` | 生成 `.ads/` + `.claude/` 骨架 + `CLAUDE.md` + `ADS.md` |

---

## 扩展模式提示文案

```
✅ `.ads/` 目录已初始化（traits: ue5, game）
  ✅ config.json
  ✅ mcp_servers.json
  ✅ ADS.md

📌 扩展模式：检测到 `.claude/` 已存在。
ADS 将自动读取 `.claude/rules/`、`CLAUDE.md` 和 `.claude/commands/`。
`.ads/` 作为扩展层，仅需填写 ADS 专属配置（mcp_servers.json / wiki / config.json）。
如需覆盖 `.claude/rules/` 中的规则，在 `.ads/rules/` 创建同名文件即可。
```

---

## `ADS.md` 模板

```markdown
# ADS 项目指令

<!-- 此文件仅被 ADS 读取，优先级高于 CLAUDE.md -->

## Agent 行为约定
<!-- 在这里写 ADS 专属指令 -->
```

所有 `/ads-init` 执行时均生成此文件（`--force` 可覆盖）。
