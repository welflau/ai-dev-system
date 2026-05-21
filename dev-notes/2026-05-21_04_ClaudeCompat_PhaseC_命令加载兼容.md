# ClaudeCompat Phase C — 命令加载兼容

> 日期：2026-05-21
> 提交：`a331382`
> 系列：ClaudeCompat（ADS 兼容 Claude Code 目录结构）

---

## 目标

前端斜杠命令补全列表同时包含系统命令和项目级命令（`.claude/commands/` + `.ads/commands/`），项目切换时自动刷新。

---

## 改动

**`backend/api/commands.py`**：
- `_parse_command_md()` — 提取解析逻辑，复用于系统命令和项目命令
- `_load_project_commands(repo_path)` — 新函数，扫描 `.claude/commands/` 和 `.ads/commands/`，`.ads/` 同名覆盖
- `get_all_commands(repo_path)` — 新增 `repo_path` 参数，合并系统 + 项目级命令
- `GET /api/commands?project_id=` — 传入 `project_id` 时合并项目命令，响应中附加 `source` 字段

**`frontend/app.js`**：
- `_loadSlashCommands()` — 带 `project_id` 查询参数，项目切换时清缓存
- `showProjectDetail()` — 切换项目时重置命令缓存

---

## 合并优先级（低 → 高）

```
内置命令（_BUILTIN_COMMANDS）
    ↓
系统磁盘命令（backend/skills/commands/*.md）
    ↓
.claude/commands/*.md（项目级，source=claude）
    ↓
.ads/commands/*.md（项目级，source=ads，同名覆盖 .claude/）
```

---

## 响应格式新增 source 字段

```json
{
  "commands": [
    { "name": "compact",  "source": "system", "description": "..." },
    { "name": "deploy",   "source": "ads",    "description": "ADS 部署..." },
    { "name": "hotfix",   "source": "claude", "description": "..." }
  ]
}
```

---

## 测试结果

| 场景 | 验证点 | 结果 |
|------|--------|------|
| `.ads/commands/deploy.md` 覆盖 `.claude/commands/deploy.md` | source=ads，desc 为 ADS 版本 | ✅ |
| `.ads/commands/hotfix.md` 新增 | source=ads，出现在补全列表 | ✅ |
| 系统命令 `/compact` 仍存在 | source=system | ✅ |
| 项目切换后重新请求命令列表 | 缓存清除，重新加载 | ✅ |
