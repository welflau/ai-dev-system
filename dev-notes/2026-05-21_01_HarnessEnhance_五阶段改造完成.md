# Harness 增强开发 — 五阶段改造完成

> 日期：2026-05-21
> 提交：`b6aeea7` → `2d670a0`（共 5 个提交）
> 参考文档：`docs/20260521_ADS_Harness增强开发计划.md`

---

## 背景

通过对业界成熟 AI 编码基建的实践调研，发现 ADS 在 Harness 层存在以下差距：

| 问题 | 影响 |
|------|------|
| 项目规则（`.ads/rules/`）不做文件上下文匹配 | 写 C++ 时 TypeScript 规则也注入，token 浪费 |
| 无 AI 代码审查机制 | 写完代码无自动检查，只能靠人工 CR |
| 全局规则单文件 `global.md` | 无法按技术栈差异化分类 |
| 外部 IDE 无法使用 ADS 规则 | 规则孤岛，跨工具无法复用 |
| 知识库无结构化索引 | LLM 检索精度低，无法积累知识 |
| Harness 健康无可见性 | 规则覆盖率、Skill 使用率不可知 |

---

## Phase 1：规则精细化注入

**提交**：`b6aeea7`

### 核心改造

**`skills/loader.py`** 三处升级：

1. `_load_rules()` — `glob("*.md")` → `rglob("*.md")`，支持子目录（`workflow/`）
2. `get_rules_for_context()` — 新增 `scene` 参数，按触发场景过滤
3. `load_project_rules()` — 新增 `current_file` / `scene` 参数，项目规则支持 `paths:` 文件匹配
4. `_match_paths()` — 修复 `**/*.ext` 对无目录前缀文件名的匹配（`A.cpp` 可被 `**/*.cpp` 命中）

**新增全局规则文件**：

```
backend/skills/rules/
├── global.md           (已有，alwaysApply)
├── ue5.md              (traits: ue5/unreal — UE5 专属规范)
├── cpp.md              (paths: **/*.cpp /**/*.h — C++ 规范)
├── typescript.md       (paths: **/*.ts/**/*.tsx — TS 规范)
├── python.md           (paths: **/*.py — Python 规范)
├── game-dev.md         (traits: game — 游戏开发通用)
└── workflow/
    ├── autoaicr.md     (scene: autoaicr — 编辑后自检规则)
    └── precommit.md    (scene: precommit — 提交前扫描规则)
```

**`ads-init` 升级**：根据项目 `traits` 自动生成对应规则模板（ue5 → `cpp-rules.md`，ts → `ts-rules.md` 等）

### 过滤逻辑验证（11 个测试全通过）

```
cpp file     → [global, cpp]
py file      → [global, python]
ts file      → [global, typescript]
no file      → [global]
ue5 traits   → [global, ue5]
game traits  → [global, game-dev]
autoaicr     → [global, workflow/autoaicr]
precommit    → [global, workflow/precommit]
ue5 + cpp    → [global, ue5, cpp]
```

---

## Phase 2：AI 代码审查（AICR）子系统

**提交**：`1b41acd`

### 架构

```
backend/aicr/
├── __init__.py       aicr_engine 单例
├── engine.py         AICREngine（AutoAICR + PreCommit 两场景）
└── scene.py          AICRScene / AICRResult / AICRIssue
```

### 两场景设计

| Scene | 触发时机 | 规则集 |
|-------|---------|--------|
| AutoAICR | Agent write/edit 工具完成后自动触发 | 行为约束（keep-scope、no-todo-left、avoid-over-design） |
| PreCommit | `/aicr-check` 命令手动触发 | Bug pattern（空指针、越界、资源泄漏、SQL 注入） |

### Hook 链路

```
chat_assistant.py → ToolDoneEvent（write_file / edit_file）
    → _maybe_autoaicr()
    → aicr_engine.run_autoaicr(diff, file_paths, traits)
    → yield {"type": "aicr_feedback", ...}
```

### 前端展示

`aicr_feedback` SSE 事件在思考面板末尾追加可折叠黄色提示块：

```
⚠ AutoAICR ⚠ 2 项提示 ›
  [keep-scope] 修改超出任务范围，新增了额外方法
  [no-todo-left] 发现 TODO 注释未处理
```

点击 `›` 展开/折叠详情。

### 新增命令

| 命令 | 功能 |
|------|------|
| `/aicr-check` | 对 `git diff --staged` 执行完整 PreCommit 扫描 |
| `/aicr-config` | 查看/切换 AutoAICR / PreCommit 开关 |
| `/aicr-rules [scene]` | 列出 AICR 规则（系统 + 项目） |

---

## Phase 3：知识库三层架构升级

**提交**：`781c189`

### 三层结构

```
.ads/wiki/
├── _wiki_index.md          ← 自动生成的两级索引（LLM 注入用）
├── {feature}/
│   └── YYYYMMDD_标题.md    ← 知识条目（有 frontmatter）
└── ...
```

### Wiki Frontmatter 三轴规范

```yaml
---
title: "Mass NPC LOD 切换闪现修复"
feature: mass-npc          # 功能域
role: [programmer]         # 目标职能
type: bugfix               # 文档类型
status: active
tags: [LOD, network-sync, visual-glitch]
summary: "渐进纠正替代瞬移硬纠正，消除 LOD 切换闪现"
---
```

### `gen_wiki_index.py`

扫描 `wiki/**/*.md` → 按 feature 分组 → 生成两级树状索引（token 预算可控）：

```markdown
## Wiki 知识索引

### mass-npc
- **Mass NPC LOD 切换闪现修复** [bugfix] — 渐进纠正替代瞬移硬纠正...
- **Mass NPC 三层同步方案** [technical-design] — LOD0/1/2 同步机制...
```

### `get_memory_prompt()` 升级

原来只注入数据库记忆，现在额外追加 `.ads/wiki/_wiki_index.md`（500 token 限额），让 LLM 了解项目知识全貌。

### 新增命令

| 命令 | 功能 |
|------|------|
| `/save-to-knowledge [标题]` | LLM 从对话提取知识，生成带 frontmatter 的 wiki 条目，自动更新索引 |
| `/search-knowledge <词> [feature:x] [type:x]` | 关键词 + 过滤器搜索 wiki 条目 |

---

## Phase 4：rules-bridge-mcp

**提交**：`fb93c63`

### 架构

```
backend/mcps/rules-bridge-mcp/
├── server.py    JSON-RPC MCP 服务（stdio + HTTP 双模式）
├── __init__.py
└── README.md
```

### MCP 工具

- **`get_coding_rules`**：按 `file_path` / `traits` / `scene` 过滤，返回规则全文
- **`list_rules`**：列出所有规则元信息

### Claude Code 接入

```json
{
  "mcpServers": {
    "ads-rules": {
      "command": "python",
      "args": ["-m", "mcps.rules-bridge-mcp.server"],
      "cwd": "/path/to/ai-dev-system/backend"
    }
  }
}
```

配置后，所有外部 IDE（Claude Code、Cursor、CodeBuddy）可通过 `get_coding_rules` 获取与 ADS 相同的规则，实现**规则单一真源、多工具共享**。

---

## Phase 5：工程质量体系

**提交**：`2d670a0`

### `skill_audit.py`

```
python scripts/skill_audit.py [--days 7] [--scope <skill_id>]
```

生成包含以下内容的 Markdown 审计报告：
- Rules 覆盖（alwaysApply/paths/scene/traits 分类统计）
- Skills 使用率（启用 / 被调用 / 未被调用 + 列表）
- AICR 统计
- 改进建议 Checklist

### `/harness-audit` 命令

在 AI 助手内直接运行，报告实时返回 + 自动存档到 `backend/audits/harness-YYYY-MM-DD.md`。

---

## 新增命令总览

| 命令 | Phase | 功能 |
|------|-------|------|
| `/aicr-check` | P2 | PreCommit 代码审查（staged diff） |
| `/aicr-config` | P2 | 切换 AutoAICR / PreCommit 开关 |
| `/aicr-rules` | P2 | 列出 AICR 规则 |
| `/save-to-knowledge` | P3 | 归档对话为 wiki 知识条目 |
| `/search-knowledge` | P3 | 搜索项目 wiki 知识库 |
| `/harness-audit` | P5 | 生成 Harness 健康审计报告 |

命令总数：10 → **16**

---

## 测试说明

### Phase 1 — 规则精细化

**自动化测试（已通过）**：

```bash
cd backend
python -c "
from skills.loader import SkillLoader
loader = SkillLoader()
# 验证 11 个场景的规则过滤结果
..."
```

**手动验证**：

1. 在有 UE5 项目的 AI 助手中发送：`你现在有哪些规则？`
   - 预期思考面板显示加载了 `global` + `ue5`（若项目 traits 含 ue5）
2. 执行 `/ads-init`，检查 `.ads/rules/` 目录是否按 traits 生成了对应文件
3. 编辑一个 `.cpp` 文件后提问，观察是否加载了 `cpp` 规则

---

### Phase 2 — AICR

**验证 AutoAICR**：

1. 在 AI 助手中让 Agent 写一个文件，故意包含超出范围的改动
2. Agent 完成编辑后，思考面板末尾应出现黄色折叠提示块
3. 点击展开，查看 `[keep-scope]` 或其他规则的提示

**验证 `/aicr-check`**：

```bash
# 在项目仓库内 stage 一些改动
git add src/some_file.cpp

# 在 AI 助手中执行
/aicr-check
```

预期输出：
```
✅ 通过 / ❌ 发现阻断项

PreCommit 扫描结果：
- [null-deref] src/foo.cpp:42 — ...
```

**验证 `/aicr-config`**：

```
/aicr-config            → 显示当前开关状态
/aicr-config autoaicr   → 切换 AutoAICR 开关（再次执行恢复）
/aicr-config off        → 关闭所有
```

---

### Phase 3 — 知识库

**验证 `/save-to-knowledge`**：

1. 和 AI 进行一次技术讨论（如讨论某个 Bug 的修复方案）
2. 执行 `/save-to-knowledge Bug修复方案`
3. 检查 `.ads/wiki/{feature}/` 目录是否新增了 `.md` 文件
4. 检查 `.ads/wiki/_wiki_index.md` 是否已更新

**验证 wiki_index 注入**：

1. 保存几条 wiki 条目后，重新开始一轮对话
2. 在思考面板的「注入记忆」区域，应能看到 wiki_index 摘要（如 `## Wiki 知识索引`）

**验证 `/search-knowledge`**：

```
/search-knowledge LOD
/search-knowledge 网络 feature:mass-npc
/search-knowledge 崩溃 type:bugfix
```

---

### Phase 4 — MCP

**验证 MCP server 启动**：

```bash
cd backend
python -m mcps.rules-bridge-mcp.server --http 3100 &

# 测试 get_coding_rules
curl -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_coding_rules",
      "arguments": {
        "file_path": "Source/IGMASS/MassNPCSync.cpp",
        "traits": ["ue5", "game"]
      }
    }
  }'
```

预期响应包含 `global` + `ue5` + `cpp` 三个规则的合并文本。

**验证 Claude Code 接入**：

1. 在 `.claude/settings.json` 中配置 MCP server（参见 README）
2. 在 Claude Code session 中调用：`/mcp ads-rules get_coding_rules file_path=foo.cpp`
3. 确认返回内容包含规则文本

---

### Phase 5 — 审计

**验证 `/harness-audit`**：

```
/harness-audit
/harness-audit --days 30
```

预期输出包含：
- Rules 覆盖：alwaysApply 1 条，paths 3 条，scene 2 条
- Skills 状态：启用数量、未被调用列表
- 改进建议 Checklist

**验证 CLI 脚本**：

```bash
cd backend
python scripts/skill_audit.py
python scripts/skill_audit.py --days 30
python scripts/skill_audit.py --scope fastapi-dev
```

**验证审计存档**：

执行 `/harness-audit` 后，检查 `backend/audits/` 目录是否生成了 `harness-YYYY-MM-DD.md`。

---

## 可观测性指标

| 功能 | 可观测点 |
|------|---------|
| Phase 1 规则注入 | 思考面板「注入规则」行显示正确规则 ID |
| Phase 2 AutoAICR | 思考面板末尾出现黄色折叠提示块 |
| Phase 2 PreCommit | `/aicr-check` 返回结构化 Markdown 报告 |
| Phase 3 wiki 保存 | `.ads/wiki/` 新增文件 + `_wiki_index.md` 更新 |
| Phase 3 wiki 注入 | memory_prompt 中包含 `## Wiki 知识索引` |
| Phase 4 MCP | curl 返回规则文本（含 `<!-- Rule: xxx -->`） |
| Phase 5 审计 | `/harness-audit` 输出三段报告 + `backend/audits/` 存档 |
