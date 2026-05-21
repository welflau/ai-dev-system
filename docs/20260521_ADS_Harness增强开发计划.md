# ADS Harness 增强开发计划

> 基于业界成熟 AI 编码基建的实践调研，对 ADS 现有 Harness 层进行系统性补齐。
>
> 目标：将 ADS 从「面向自身项目」的 Harness 演进为「可复制到任意项目」的通用 AI 研发基建。

---

## 一、背景与差距分析

### 1.1 ADS 现状

| 能力域 | 现状 | 成熟度 |
|------|------|--------|
| SkillLoader 三层过滤 | `paths:` / `traits_match` / `alwaysApply` 均已实现 | ✅ 成熟 |
| 全局规则注入 | 单文件 `global.md`（alwaysApply） | ⚠️ 单层 |
| 项目规则（.ads/rules/） | `load_project_rules()` 存在，但仅支持 alwaysApply，不做 glob 文件匹配 | ⚠️ 不完整 |
| AI 代码审查（AICR） | 无 | ❌ 缺失 |
| Hook 触发链 | 无 pre/post 编辑 hook | ❌ 缺失 |
| MCP 规则服务 | 无 | ❌ 缺失 |
| **MCP 配置分层** | **只有全局层（mcp_servers.json），无项目级配置** | **❌ 缺失** |
| 知识库结构 | 平铺，无分层、无 Frontmatter 导航 | ⚠️ 待升级 |
| Plugin 正式化 | marketplace 目录存在，但无标准接口 | ⚠️ 初步 |
| Skill 质量保障 | 无审计 pipeline | ❌ 缺失 |
| Harness 审计机制 | 无 | ❌ 缺失 |

### 1.2 核心痛点

1. **项目级规则没有文件上下文**：`.ads/rules/` 的规则对所有文件一视同仁，写 C++ 文件时 TypeScript 规则也被注入，浪费 token 且降低聚焦度
2. **AI 写完代码无自动复查**：没有在 Agent 完成编辑后触发的代码质量检查环节，问题只能靠人工 CR 发现
3. **知识库检索精度低**：现有知识条目无结构化标签，LLM 只能靠全文检索，相关性差
4. **外部 IDE 无法使用 ADS 规则**：规则存在服务端，开发者在 IDE 中使用其他 AI 工具时无法获取同一套约束
5. **Harness 健康无可见性**：没有机制定期评估规则有效性、skill 覆盖率、hook 触发率

---

## 二、Phase 1：规则体系精细化（P0，预计 1.5 周）

### 目标

将 ADS 规则从「全局一刀切」升级为「按项目 + 按文件 + 按场景」三维精细注入。

### 2.1 项目规则支持 `paths:` 文件匹配

**现状**：`load_project_rules()` 只加载 `alwaysApply=True` 的规则，项目规则缺乏文件上下文。

**改造**：

```python
# backend/skills/loader.py — load_project_rules() 升级
def load_project_rules(self, repo_path: str, current_file: Optional[str] = None) -> str:
    """
    支持 paths: 字段。当 current_file 不为空时，只注入匹配的规则。
    无 paths: 字段的规则视为 alwaysApply（向后兼容）。
    """
    rules_dir = Path(repo_path) / ".ads" / "rules"
    if not rules_dir.exists():
        return ""

    sections = []
    for md_file in sorted(rules_dir.rglob("*.md")):  # rglob 支持子目录
        frontmatter, body = _parse_frontmatter(md_file.read_text())
        paths = frontmatter.get("paths") or []
        always = frontmatter.get("alwaysApply", not bool(paths))  # 无paths则默认常驻
        
        if not always and current_file and paths:
            if not _match_paths(current_file, paths):
                continue
        elif not always and not current_file:
            continue  # 有paths但无当前文件上下文，跳过
            
        if body.strip():
            sections.append(body.strip())
    return "\n\n---\n\n".join(sections)
```

**.ads/rules/ 目录建议结构**：

```
.ads/rules/
├── project-rules.md          # 无 paths: → 常驻（项目基本约定）
├── cpp-rules.md              # paths: ["**/*.cpp","**/*.h"] → 按需
├── ts-rules.md               # paths: ["**/*.ts","**/*.tsx"] → 按需
├── blueprint-rules.md        # paths: ["**/BP_*","**/*.uasset"] → 按需
└── workflow/
    ├── autoaicr.md           # scene: autoaicr（Phase 2 使用）
    └── precommit.md          # scene: precommit（Phase 2 使用）
```

### 2.2 全局规则从单文件升级为目录分层

**现状**：`backend/skills/rules/global.md` 一个文件包含所有内容。

**改造**：扩展为目录，`_load_rules()` 已支持 `rules/*.md`，只需补充文件：

```
backend/skills/rules/
├── global.md              # alwaysApply: true — 跨技术栈通用准则（保留现有）
├── ue5.md                 # traits_match: {any_of: [ue5]} — UE5 项目专属
├── game-dev.md            # traits_match: {any_of: [game]} — 游戏项目通用
├── cpp.md                 # paths: ["**/*.cpp","**/*.h"] — C++ 文件规则
├── typescript.md          # paths: ["**/*.ts","**/*.tsx"] — TS 文件规则
├── python.md              # paths: ["**/*.py"] — Python 文件规则
└── workflow/
    ├── autoaicr.md        # scene: autoaicr
    └── precommit.md       # scene: precommit
```

### 2.3 `_load_rules()` 支持子目录扫描

```python
# 将 glob("*.md") 改为 rglob("*.md")，支持 workflow/ 等子目录
for md_file in sorted(self.rules_dir.rglob("*.md")):
    ...
```

### 2.4 Scene 字段支持

规则 frontmatter 新增 `scene` 字段，配合 Phase 2 的 AICR：

```yaml
---
scene: autoaicr        # 只在 AutoAICR 场景注入
alwaysApply: false
---
```

`get_rules_for_context()` 新增 `scene` 参数过滤。

---

## 三、Phase 2：AI 代码审查（AICR）子系统（P1，预计 2.5 周）

### 目标

在 Agent 完成代码编辑后，自动触发一轮轻量代码质量审查；在用户执行 commit 前，触发完整 bug pattern 扫描。形成「写完自检 + 提交前把关」双层保障。

### 3.1 两场景设计

| Scene | 触发时机 | 规则集重点 |
|-------|---------|--------|
| **AutoAICR** | Agent 调用 Write/Edit/Bash 编辑文件后 | 行为约束：keep-scope、avoid-over-design、no-todo-left |
| **PreCommit** | 用户执行 `git commit` / 斜杠命令 `/aicr-check` | Bug pattern：空指针、数组越界、资源泄漏、安全漏洞 |

### 3.2 后端实现

**新增模块** `backend/aicr/`：

```
backend/aicr/
├── __init__.py
├── engine.py          # AICREngine：触发、规则加载、调用 LLM 审查
├── scene.py           # Scene 枚举 + 场景上下文
├── reporter.py        # 审查结果格式化（Markdown / JSON）
└── rules/
    ├── autoaicr/      # AutoAICR 规则集（.md 文件）
    │   ├── keep-scope.md
    │   ├── no-todo-left.md
    │   └── avoid-over-design.md
    └── precommit/     # PreCommit 规则集
        ├── null-deref.md
        ├── array-bounds.md
        ├── resource-leak.md
        └── security.md
```

**核心接口**：

```python
class AICREngine:
    async def run_autoaicr(
        self,
        diff: str,           # 本轮编辑的 diff
        file_paths: list[str],
        project_traits: list[str],
    ) -> AICRResult:
        """AutoAICR：diff + 匹配规则 → LLM 轻量审查 → 返回问题列表"""

    async def run_precommit(
        self,
        staged_diff: str,    # git diff --staged
        project_traits: list[str],
    ) -> AICRResult:
        """PreCommit：staged diff + 完整规则集 → LLM 深度审查"""
```

### 3.3 Hook 触发集成

在 `backend/agents/base.py` 的工具调用后钩子中接入 AutoAICR：

```python
# BaseAgent._after_tool_call() — 新增
async def _after_tool_call(self, tool_name: str, tool_result: dict):
    if tool_name in ("write_file", "edit_file") and self._aicr_enabled:
        changed_files = tool_result.get("changed_files", [])
        diff = tool_result.get("diff", "")
        if diff:
            result = await aicr_engine.run_autoaicr(diff, changed_files, self.traits)
            if result.has_issues:
                # 以 tool_feedback 事件注入到当前对话流
                yield AICRFeedbackEvent(result)
```

**AutoAICR 结果展示**：以折叠的黄色提示框显示在思考面板内（不阻断流程，只提示）。

### 3.4 新增命令

```
/aicr-check              手动触发 PreCommit 审查（针对 git staged 差异）
/aicr-config             查看/切换 AICR 开关（autoaicr / precommit / off）
/aicr-rules [scene]      列出当前场景的审查规则
```

**命令文件**：在 `backend/skills/commands/` 下添加 `aicr-check.md`、`aicr-config.md`、`aicr-rules.md`。

### 3.5 前端展示

AutoAICR 结果以新事件类型 `aicr_feedback` 推送，在思考面板最后一个 step 后追加：

```
✦ AutoAICR ⚠ 2 项提示
  › [keep-scope] 修改超出任务范围，新增了 UserService 中的额外方法
  › [no-todo-left] 发现 TODO 注释未处理: "// TODO: handle edge case"
```

---

## 四、Phase 3：知识库三层架构升级（P1，预计 3 周）

### 目标

将 ADS 知识库从平铺 KV 存储升级为具备结构化索引、多轴导航、自动 MOC 的三层知识体系，大幅提升 LLM 检索精度。

### 4.1 三层架构

```
knowledge/
├── raw/           # 原始资料（会议纪要、调研记录、外部文档）—— 不直接用于检索
├── wiki/          # 知识合成层（AI/人可读）—— 主要检索源
│   ├── Features/  # 按功能域分组
│   ├── Workflow/  # 工作流类
│   └── CrossCutting/  # 跨领域
└── _schema/       # 组织规则（标签定义、索引生成脚本）
    ├── tags.yaml  # 三轴标签定义
    └── scripts/   # wiki_index 生成脚本
```

### 4.2 Wiki 条目 Frontmatter 规范

```yaml
---
title: "Mass NPC 三层 LOD 同步方案"
feature: mass-npc          # 功能域（从 tags.yaml 枚举）
role: [programmer]         # 目标职能（programmer / designer / artist / pm）
type: technical-design     # 文档类型（technical-design / feature-spec / bugfix / howto）
status: active             # active / archived / deprecated
tags: [network-sync, LOD, performance]
code_refs:                 # 追踪关联代码文件（防文档漂移）
  - "Source/IGMASS/MassNPCSync.cpp"
  - "Source/IGMASS/MassLODManager.h"
created: 2026-01-15
updated: 2026-05-20
---
```

### 4.3 wiki_index 自动生成

新增脚本 `backend/scripts/gen_wiki_index.py`，扫描 `wiki/` 目录生成两级树状索引：

```markdown
## wiki_index（LLM 专用，按功能域导航）

### mass-npc
- **Mass NPC 三层 LOD 同步方案** [technical-design] — LOD0/1/2 同步机制，网络带宽优化，速度预测方案
- **Mass NPC 闪现消除复盘** [bugfix] — 5 路径根因分析，渐进纠正方案

### network-sync
- **DS 同构网络编程指南** [technical-design] — RPC vs 属性复制决策树，Iris Push Model
```

**接入点**：`BaseAgent.get_memory_prompt()` 在注入记忆时同步注入 wiki_index 头部（500 token 限额）。

### 4.4 新增命令

```
/save-to-knowledge <描述>   将当前对话内容归档为 wiki 条目（LLM 生成 frontmatter）
/search-knowledge <关键词>  搜索知识库（FTS5 + 标签过滤）
/knowledge-audit            检查知识条目的 code_refs 是否仍有效
```

### 4.5 Ingest 工作流

`/save-to-knowledge` 触发时：
1. LLM 从对话中提取结构化摘要
2. 自动填充 frontmatter（feature/role/type 三轴从 tags.yaml 枚举选择）
3. 检查是否有同 feature+type 的已有条目（补充 or 新建）
4. 写入 `wiki/{Feature}/` 目录
5. 更新 wiki_index

---

## 五、Phase 4：MCP 规则服务（P2，预计 1.5 周）

### 目标

为外部 IDE（VSCode、Rider、Cursor 等）中使用其他 AI 工具的开发者提供 ADS 规则查询接口，实现「规则单一真源，多工具共享」。

### 5.1 rules-bridge-mcp 服务

新建 `backend/mcps/rules-bridge-mcp/`：

```
mcps/rules-bridge-mcp/
├── server.py            # FastMCP server，暴露 get_coding_rules 工具
├── requirements.txt
└── README.md
```

**核心工具**：

```python
@mcp.tool()
def get_coding_rules(
    file_path: str,         # 当前编辑文件路径（用于 glob 匹配）
    project_path: str = "", # 项目仓库路径（加载 .ads/rules/）
    traits: list[str] = [], # 项目 trait 列表
) -> str:
    """返回适用于当前文件的所有规则文本，供 AI IDE 插件注入上下文"""
    loader = SkillLoader()
    global_rules = loader.get_rules_for_context(traits, file_path)
    project_rules = loader.load_project_rules(project_path, file_path) if project_path else ""
    return format_rules(global_rules, project_rules)
```

**运行方式**：

```bash
# 本地启动（IDE 通过 stdio 或 HTTP 调用）
python -m mcps.rules-bridge-mcp.server --port 3100
```

**IDE 配置**（以 Claude Code MCP 为例）：

```json
{
  "mcpServers": {
    "ads-rules": {
      "command": "python",
      "args": ["-m", "mcps.rules-bridge-mcp.server"],
      "cwd": "/path/to/ai-dev-system"
    }
  }
}
```

---

## 六、Phase 5：工程质量体系（P2，预计 2 周）

### 6.1 Skill 质量五层闭环

| 层 | 名称 | 触发点 | 说明 |
|---|------|--------|------|
| L1 | self-check | Skill 执行后 | LLM 自评：是否完成任务、有无遗漏 |
| L2 | gate | Skill 执行后 | 结构化校验：输出格式、必填字段 |
| L3 | skill-audit | 每周定时 | 统计 Skill 命中率、用户满意度 |
| L4 | skill-creator eval | 新 Skill 合入时 | PR 时自动评测 Skill 质量分 |
| L5 | 外部审计 | 季度 | 对照业界标准人工评审 |

**实现路径**：
- L1/L2：在 `BaseAgent._react_with_think_inner()` 结束时，对命中的 Skill 追加一轮 self-check 提示
- L3：新增 `backend/scripts/skill_audit.py`，每周生成审计报告写入 `backend/audits/`
- L4：GitHub Actions 工作流，新增 Skill 时自动运行 `skill_audit.py --scope <skill_id>`

### 6.2 Harness Audit 机制

新增 `backend/skills/commands/harness-audit.md`（`/harness-audit` 命令）：

触发时生成 Harness 健康报告，包含：

```markdown
## Harness 审计报告 — 2026-05-21

### Rules 覆盖
- 全局规则：5 条（alwaysApply 1，paths 匹配 4）
- 项目规则（.ads/rules/）：3 条
- 命中率：最近 7 天规则平均命中 12 次/天

### Skills 状态
- 启用 Skills：28 个
- 近 7 天被调用：14 个（50%）
- 未被调用 Skills：14 个（列表...）

### AICR 统计
- AutoAICR 触发：47 次
- 发现问题：23 条（49%）
- 问题修复率：87%

### 建议
- [ ] 清理 14 个未被调用的 Skills（或标记为 deprecated）
- [ ] precommit 场景覆盖率低，建议补充 Python 专项规则
```

### 6.3 `ads-init` 升级

现有 `/ads-init` 命令创建 `.ads/` 目录结构，升级为：
- 根据项目 traits 自动生成对应的规则模板（UE5 项目生成 `cpp-rules.md`，TypeScript 项目生成 `ts-rules.md`）
- 写入 `.ads/rules/` 子目录结构
- 生成 `.ads/config.json` 的 AICR 默认配置

---

## 七、实施路线图

```
Week 1-2   Phase 1：规则体系精细化           ✅ 已完成
Week 3-5   Phase 2：AICR 子系统             ✅ 已完成
Week 6-8   Phase 3：知识库三层架构           ✅ 已完成
Week 9-10  Phase 4：rules-bridge-mcp        ✅ 已完成
Week 11-12 Phase 5：工程质量体系             ✅ 已完成

Week 13-14 Phase 6：MCP 配置分层（项目级）
           ├─ Day 1-2：mcp_client.py 支持合并加载 .ads/mcp_servers.json
           ├─ Day 3-4：/ads-init 生成 .ads/mcp_servers.json 模板
           ├─ Day 5-7：/mcp-config 命令（查看/启用/禁用项目 MCP）
           ├─ Day 8-9：前端 MCP 状态面板显示当前项目生效的 server
           └─ Day 10：DevNote
```

---

## 八、优先级汇总

| Phase | 内容 | 优先级 | 工期 | 状态 | 核心价值 |
|-------|------|--------|------|------|--------|
| 1 | 规则精细化（paths + 分层 + scene） | **P0** | 1.5 周 | ✅ 完成 | 减少无关规则注入，提高规则精度 |
| 2 | AICR 自动代码审查 | **P1** | 2.5 周 | ✅ 完成 | 写完即审，提前发现问题 |
| 3 | 知识库三层架构 | **P1** | 3 周 | ✅ 完成 | 提高知识检索精度，实现知识积累闭环 |
| 4 | rules-bridge-mcp | **P2** | 1.5 周 | ✅ 完成 | 规则单一真源，多工具共享 |
| 5 | 工程质量体系 | **P2** | 2 周 | ✅ 完成 | Harness 健康可见，持续运营保障 |
| **6** | **MCP 配置分层（项目级）** | **P1** | **1.5 周** | **待开发** | **项目独立控制 MCP server，支持私有 MCP** |

---

## 六-补、Phase 6：MCP 配置分层（项目级）（P1，预计 1.5 周）

### 背景与问题

目前 ADS 的 MCP 配置**只有全局一层**：

```
backend/mcp_servers.json   ← 所有项目共用，服务器启动时统一加载
```

对比 Claude Code 的两层结构：

```
~/.claude/settings.json         用户全局 MCP（所有 session 可用）
{project}/.claude/settings.json 项目级 MCP（仅该项目 session 可用）
```

ADS 缺少项目层，导致：
- 不能给「UE5 项目」单独启用 UE Editor MCP，其他项目不受影响
- 不能给特定项目配置私有 MCP server（如项目专属的数据库 MCP、内部 API MCP）
- 全局 enabled/disabled 修改会影响所有项目

### 6.1 目标架构

```
全局层   backend/mcp_servers.json          所有项目默认可用（管理员维护）
项目层   {repo}/.ads/mcp_servers.json      项目独立启用/禁用/添加 MCP server
```

**合并规则**（项目层优先）：
- 项目层 `enabled: true` → 覆盖全局层 `enabled: false`（项目单独开启）
- 项目层 `enabled: false` → 覆盖全局层 `enabled: true`（项目单独关闭）
- 项目层新增条目 → 仅该项目可用的私有 MCP server

### 6.2 `.ads/mcp_servers.json` 格式

与全局层格式完全一致，支持所有字段：

```json
{
  "filesystem": {
    "enabled": true,
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/project"],
    "_comment": "覆盖全局 enabled:false，为本项目单独开启"
  },
  "project-db": {
    "type": "stdio",
    "command": "python",
    "args": ["-m", "my_project_mcp.server"],
    "enabled": true,
    "description": "项目专属数据库 MCP（仅此项目可用）"
  }
}
```

### 6.3 后端实现

**`mcp_client.py` 新增 `get_tools_for_project(project_id)` 方法**：

```python
async def get_tools_for_project(self, project_id: str) -> list[dict]:
    """合并全局 + 项目层 MCP 配置，返回该项目可用的工具列表。"""
    # 1. 加载项目 .ads/mcp_servers.json
    repo_path = await _get_repo_path(project_id)
    project_cfg = _load_project_mcp_config(repo_path)
    
    # 2. 合并：项目层覆盖全局层
    merged = _merge_mcp_configs(self._global_config, project_cfg)
    
    # 3. 启动项目独有的 server（尚未运行的）
    # 4. 返回合并后的工具列表
```

**合并逻辑**：

```python
def _merge_mcp_configs(global_cfg: dict, project_cfg: dict) -> dict:
    result = {**global_cfg}
    for name, proj_server in project_cfg.items():
        if name in result:
            # 项目层覆盖：只覆盖显式声明的字段（enabled / args / env）
            result[name] = {**result[name], **proj_server}
        else:
            # 项目新增 server
            result[name] = proj_server
    return result
```

**`chat_assistant.py` 调用点**：

```python
# 现有：
tools = mcp_client.get_tools(traits=traits)

# 改为：
tools = await mcp_client.get_tools_for_project(project_id, traits=traits)
```

### 6.4 `/ads-init` 升级

生成 `.ads/mcp_servers.json` 模板（空配置 + 注释说明）：

```json
{
  "_comment": "项目级 MCP 配置。覆盖全局 mcp_servers.json 中同名 server 的字段。",
  "_example_enable_filesystem": {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
    "enabled": true
  }
}
```

### 6.5 新增命令 `/mcp-config`

```
/mcp-config                    列出当前项目生效的所有 MCP server（全局 + 项目层合并结果）
/mcp-config enable filesystem  在项目层启用 filesystem MCP
/mcp-config disable git        在项目层禁用 git MCP
/mcp-config add <name> <cmd>   向项目层添加自定义 MCP server
```

### 6.6 前端 MCP 状态显示

在 `/mcp-config` 命令输出中展示三列：

```
MCP Server     来源      状态
filesystem     项目层    启用 ✅
fetch          全局      禁用 ⭕
git            全局      启用 ✅（traits 过滤）
project-db     项目层    启用 ✅（仅本项目）
```

### 6.7 完成标准（DoD）

- `.ads/mcp_servers.json` 中 `enabled: true` 的 server 被纳入该项目的工具列表，全局层同名 server 若 `enabled: false` 也能正常工作
- 项目层新增的私有 server 只对该项目的 chat_stream 可见
- `/mcp-config` 命令输出正确区分「全局层」和「项目层」来源
- `/ads-init` 生成带注释的 `.ads/mcp_servers.json` 模板

---

## 九、完成标准（DoD）

**Phase 1**：
- `.ads/rules/` 中带 `paths:` 的规则仅在匹配文件时注入，验证：编辑 `.py` 文件不触发 `cpp-rules.md`
- `backend/skills/rules/` 下有 UE5/C++/TypeScript/Python 分类规则各至少一份

**Phase 2**：
- Agent 编辑文件后，思考面板出现 AutoAICR 折叠提示（有问题时展示）
- `/aicr-check` 命令在 staged diff 上触发完整审查并输出 Markdown 报告

**Phase 3**：
- 知识库首页有 wiki_index，支持 feature 和 type 两级导航
- `/save-to-knowledge` 能从对话中自动生成带 frontmatter 的 wiki 条目
- BaseAgent 在 memory_prompt 中包含 wiki_index 摘要

**Phase 4**：
- MCP server 本地启动后，外部 Claude Code session 调用 `get_coding_rules` 能返回正确规则

**Phase 5**：
- `/harness-audit` 输出包含 Rules 覆盖、Skills 使用、AICR 命中三项统计
- skill_audit.py 生成审计报告写入 `backend/audits/`

**Phase 6**：
- `.ads/mcp_servers.json` 中 `enabled: true` 的 server 被纳入项目工具列表（全局层 disabled 也能工作）
- 项目层新增私有 server 只对该项目可见
- `/mcp-config` 命令输出区分「全局层」和「项目层」来源
- `/ads-init` 生成带注释的 `.ads/mcp_servers.json` 模板

---

*文档创建：2026-05-21 | 项目：ai-dev-system | 版本：v1.1（2026-05-21 新增 Phase 6）*
