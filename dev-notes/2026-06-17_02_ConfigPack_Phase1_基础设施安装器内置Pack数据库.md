# ConfigPack 库 — Phase 1：基础设施

**日期**：2026-06-17  
**阶段**：Phase 1 完成

---

## 实现内容

### 新增文件

| 文件 | 说明 |
|---|---|
| `backend/pack_installer.py` | Pack 安装器核心逻辑 |
| `backend/config_packs/ue5-dev/` | UE5 开发套件 Pack |
| `backend/config_packs/git-workflow/` | Git 工作流 Pack |
| `backend/config_packs/web-dev/` | Web 前端开发 Pack |

### 修改文件

| 文件 | 变更 |
|---|---|
| `backend/database.py` | 新增 `project_packs` 表 + `projects.installed_packs` 列迁移 |

---

## 关键设计决策

### 三种安装操作

```
copy   → rules / agents / commands / skills（独立文件，直接覆盖写入）
append → CLAUDE.md（追加 ## Pack: <name> section，幂等）
merge  → settings.json / mcp.json（只加新 key，不覆盖已有）
```

### 模板变量白名单替换

只替换 `{{project_name}}` `{{repo_path}}` `{{tech_stack}}` `{{git_remote}}` 四个占位符。  
Codebuddy 的 `{{.CurrentDate}}` 等系统变量不在白名单内，原样保留。  
实现：`str.replace()`，无模板引擎依赖。

### CLI 自动检测

安装时检测项目目录中是否存在 `.claude/` 或 `.codebuddy/`，决定装哪套配置。  
两个都不存在时按 `pack.json` 的 `targets` 字段声明创建目录。

### pack.json 结构

```json
{
  "name": "ue5-dev",
  "display_name": "UE5 开发套件",
  "description": "...",
  "version": "1.0.0",
  "tags": ["ue5", "gamedev"],
  "auto_traits": ["engine:ue5"],
  "contains": ["rules", "agents", "commands"],
  "targets": ["claude", "codebuddy"]
}
```

### Pack 目录布局

```
config_packs/<pack-name>/
├── pack.json
├── claude/
│   ├── CLAUDE.md
│   └── commands/*.md
└── codebuddy/
    ├── rules/*.md
    ├── agents/*.md
    └── commands/*.md
```

### DB 变更

- 新表 `project_packs`：记录每个项目安装了哪些 Pack + 时间 + 目标 CLI
- `projects` 表新增 `installed_packs` TEXT 列（JSON 数组，冗余字段，便于快速读取）

---

## 内置 Pack 内容

### ue5-dev
- Claude: `CLAUDE.md`（UE5 编码规范 + 通信方式）、`/build`、`/playtest` 命令
- Codebuddy: `ue5_build.md` rule、`ue5_advisor` agent（opus 模型）、`/build` 命令

### git-workflow
- Claude: `/pr`（自动创建 PR）、`/review`（代码审查）命令
- Codebuddy: `/pr`、`/review` 命令

### web-dev
- Claude: `CLAUDE.md`（组件/API 规范）、`/debug-api` 命令
- Codebuddy: `web_dev.md` rule

---

## Phase 2 待办

- `create_project.py`：新增 `_auto_install_packs()` 异步任务
- `confirm_project.py`：返回推荐 Pack 列表供前端展示
- `api/projects.py`：新增 `selected_packs` 字段
- 前端确认卡片：Pack 选择 UI（勾选/取消勾选）
