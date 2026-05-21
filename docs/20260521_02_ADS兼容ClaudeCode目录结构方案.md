# ADS 兼容 Claude Code 目录结构方案

> 日期：2026-05-21
> 状态：规划中
> 目标：让 ADS 同时支持 `.ads/` 和 `.claude/` 两套目录，以及 `ADS.md` / `CLAUDE.md` 项目总指令文件，已有 Claude Code 项目无需迁移即可接入 ADS。

---

## 一、背景与动机

### 1.1 现状

ADS 目前使用 `.ads/` 作为项目级配置目录，Claude Code CLI 使用 `.claude/` 作为标准目录。两套工具各自独立，导致：

- 同一个项目需要维护两套规则文件（`.ads/rules/` + `.claude/rules/`）
- 已有 Claude Code 项目接入 ADS 时需要手动迁移配置
- ADS 的规则、命令无法被 Claude Code 读取，反之亦然

### 1.2 目标

**双目录共存**：ADS 同时读取 `.claude/`（Claude Code 标准）和 `.ads/`（ADS 扩展层），`.ads/` 优先级高于 `.claude/`。

```
项目仓库/
├── CLAUDE.md        ← Claude Code 项目总指令（Claude CLI 读取）
├── ADS.md           ← ADS 项目总指令（ADS 读取，优先级高于 CLAUDE.md）
├── .claude/         ← Claude Code 标准目录（Claude CLI 使用）
│   ├── settings.json
│   ├── commands/
│   ├── rules/
│   └── agents/
│
└── .ads/            ← ADS 扩展层（ADS 独有功能）
    ├── rules/            覆盖 .claude/rules/ 同名规则
    ├── wiki/             知识库（.claude 无此概念）
    ├── mcp_servers.json  ADS 格式 MCP 配置
    └── config.json       traits / aicr（ADS 专属）
```

---

## 二、各功能域对比与兼容方案

| 功能 | ADS `.ads/` | Claude Code `.claude/` | 兼容策略 |
|------|------------|----------------------|---------|
| 项目总指令 | `ADS.md`（新增） | `CLAUDE.md` | 合并读取，`ADS.md` 优先；两者均为 alwaysApply |
| 规则注入 | `.ads/rules/*.md` | `.claude/rules/*.md` + `CLAUDE.md` | 合并读取，`.ads/` 优先 |
| 斜杠命令 | 全局 `backend/skills/commands/` | `.claude/commands/*.md`（项目级） | 扫描两路径，合并补全列表 |
| MCP 配置 | `.ads/mcp_servers.json` | `.claude/settings.json` > `mcpServers` | 合并，`.ads/` 优先 |
| 全局配置 | `.ads/config.json`（traits/aicr） | `.claude/settings.json`（model/permissions） | 字段不重叠，各读各的 |
| 子 Agent | 无 | `.claude/agents/*.md` | 新增读取，注册到 ADS agent 池 |
| 项目 Skill | `.ads/skills/` | — | 保留不变 |
| 知识库 Wiki | `.ads/wiki/` | — | 保留不变，`.claude/` 无对应 |

**合并优先级**（高 → 低）：

```
ADS.md（项目根，alwaysApply）
    ↑ 追加
.ads/ 同名条目
    ↑ 覆盖
CLAUDE.md（项目根，alwaysApply）
    ↑ 追加
.claude/ 条目
    ↑ 覆盖
系统全局（backend/skills/rules/ 等）
```

---

## 三、详细实现方案

### Phase A：规则加载兼容（P0，1 天）

**改动文件**：`backend/skills/loader.py`

#### A.1 `ADS.md` — ADS 专属项目总指令文件

对标 `CLAUDE.md`，在项目仓库根目录放置 `ADS.md` 作为 ADS 的项目总指令文件：

| 文件 | 谁读 | 用途 |
|------|------|------|
| `CLAUDE.md` | Claude Code CLI | Claude Code 的项目总指令 |
| `ADS.md` | ADS | ADS 的项目总指令（优先级高于 `CLAUDE.md`） |

**`ADS.md` 与 `CLAUDE.md` 的区别**：
- `CLAUDE.md` 面向 Claude Code CLI 的通用编码约定
- `ADS.md` 可包含 ADS 专属指令（Agent 行为调整、工单处理规范、项目特殊约定等）
- 两者都作为 `alwaysApply` 规则注入，无 `paths:` 文件过滤
- 同时存在时，`ADS.md` 内容**追加**在 `CLAUDE.md` 之后（不覆盖，两者均注入）

**示例 `ADS.md`**：

```markdown
# 项目 AI 工作规范

## Agent 行为约定
- 修改 Source/ 下的文件前必须先查阅 OGDocs 对应模块文档
- 所有网络同步相关代码修改后需运行 /aicr-check

## 工单处理规范
- P0 Bug 工单优先于所有功能开发
- 技术方案超过 200 行代码时先拆分子任务

## 禁止事项
- 禁止直接修改 ThirdParty/ 目录下的代码
- 禁止使用 LogTemp，必须用模块专属 log 类别
```

#### A.2 规则加载优先级与合并逻辑

**读取顺序（低→高优先级）**：

```
1. .claude/rules/**/*.md    Claude Code 标准规则
2. CLAUDE.md                Claude 项目总指令（alwaysApply，整体注入）
3. .ads/rules/**/*.md       ADS 专属规则（同名覆盖 .claude/rules/）
4. ADS.md                   ADS 项目总指令（alwaysApply，追加在 CLAUDE.md 之后）
```

```python
def load_project_rules(repo_path, current_file=None, scene=None):
    repo = Path(repo_path)
    all_rules: dict[str, str] = {}  # rule_id → content（后写覆盖前写）

    # 1. 读 .claude/rules/
    claude_rules_dir = repo / ".claude" / "rules"
    if claude_rules_dir.exists():
        for md_file in sorted(claude_rules_dir.rglob("*.md")):
            _load_rule_file(md_file, claude_rules_dir, all_rules, current_file, scene)

    # 2. 读 CLAUDE.md（alwaysApply，无 paths: 过滤，限制 3000 字符）
    claude_md = repo / "CLAUDE.md"
    if claude_md.exists():
        content = claude_md.read_text(encoding="utf-8").strip()[:3000]
        if content:
            all_rules["__CLAUDE_MD__"] = f"<!-- CLAUDE.md -->\n{content}"

    # 3. 读 .ads/rules/（同名 key 覆盖步骤 1）
    ads_rules_dir = repo / ".ads" / "rules"
    if ads_rules_dir.exists():
        for md_file in sorted(ads_rules_dir.rglob("*.md")):
            _load_rule_file(md_file, ads_rules_dir, all_rules, current_file, scene)

    # 4. 读 ADS.md（alwaysApply，追加在最后，优先级最高）
    ads_md = repo / "ADS.md"
    if ads_md.exists():
        content = ads_md.read_text(encoding="utf-8").strip()[:3000]
        if content:
            all_rules["__ADS_MD__"] = f"<!-- ADS.md -->\n{content}"

    return "\n\n---\n\n".join(all_rules.values())
```

**完成标准**：
- 项目根有 `CLAUDE.md`，ADS 聊天时自动注入其内容（限 3000 字符）
- 项目根有 `ADS.md`，注入在 `CLAUDE.md` 之后，优先级最高
- `.claude/rules/cpp.md` 被 ADS 自动读取注入
- `.ads/rules/cpp.md` 存在时覆盖 `.claude/rules/cpp.md`
- `ADS.md` 不存在时静默跳过，不影响现有流程

---

### Phase B：MCP 配置兼容（P0，1 天）

**改动文件**：`backend/mcp_client.py`

**目标**：`_load_project_mcp_config()` 同时读取 `.claude/settings.json["mcpServers"]` 和 `.ads/mcp_servers.json`，合并后返回。

**格式转换**：Claude Code 的 `settings.json` 中 MCP 配置格式为：

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]
    }
  }
}
```

ADS `mcp_servers.json` 格式多了 `enabled` 字段。转换规则：**Claude Code 格式中出现的 server 视为 `enabled: true`**。

```python
def _load_project_mcp_config(repo_path: str) -> dict:
    result = {}

    # 1. 读 .claude/settings.json["mcpServers"]
    claude_settings = Path(repo_path) / ".claude" / "settings.json"
    if claude_settings.exists():
        try:
            data = json.loads(claude_settings.read_text(encoding="utf-8"))
            for name, cfg in (data.get("mcpServers") or {}).items():
                result[name] = {**cfg, "enabled": True}  # claude 格式默认 enabled
        except Exception:
            pass

    # 2. 读 .ads/mcp_servers.json（覆盖 .claude/ 同名条目）
    ads_mcp = Path(repo_path) / ".ads" / "mcp_servers.json"
    if ads_mcp.exists():
        try:
            raw = json.loads(ads_mcp.read_text(encoding="utf-8"))
            for k, v in raw.items():
                if not k.startswith("_"):
                    result[k] = {**result.get(k, {}), **v}  # .ads/ 优先
        except Exception:
            pass

    return result
```

**完成标准**：
- 项目 `.claude/settings.json` 中的 `mcpServers` 自动被 ADS 加载
- `.ads/mcp_servers.json` 同名条目覆盖 `.claude/settings.json` 的值

---

### Phase C：命令加载兼容（P1，0.5 天）

**改动文件**：`backend/api/commands.py` 中的命令元数据扫描逻辑

**目标**：前端输入 `/` 时，补全列表同时包含 `.claude/commands/` 和 `backend/skills/commands/` 中的命令。

**读取顺序**（低→高优先级）：
1. `backend/skills/commands/`（系统全局命令）
2. `.claude/commands/`（项目级命令，Claude Code 标准路径）
3. `.ads/commands/`（项目级命令，ADS 扩展路径，若有）

同名命令后者覆盖前者。

**API 新增**：`GET /api/projects/{id}/commands` 返回合并后的命令列表（供前端补全）。

**完成标准**：
- 项目 `.claude/commands/my-cmd.md` 出现在 ADS 前端的 `/` 补全列表中
- 执行时若 `commands.py` 无对应 handler，走「LLM 执行」路径（让 AI 读 SKILL.md 内容执行）

---

### Phase D：`.claude/agents/` 支持（P2，0.5 天）

**改动文件**：`backend/agents/` 注册逻辑

**目标**：扫描 `.claude/agents/*.md`，将其中定义的 Agent 注册为可用子 Agent。

**Agent 定义格式**（Claude Code 标准）：

```markdown
---
name: my-agent
description: 负责 xxx 的 Agent
---

你是一个专门负责...
```

注册后，Orchestrator 可以调度这些项目自定义 Agent 处理特定类型的工单。

**完成标准**：
- `.claude/agents/deploy-agent.md` 定义的 Agent 出现在 ADS 子任务派发列表中

---

### Phase E：`/ads-init` 升级（P1，0.5 天）

**改动文件**：`backend/api/commands.py` `_cmd_ads_init()`

**目标**：检测项目是否已有 `.claude/`，若有则只生成 ADS 扩展文件，不重复创建规则文件。

```
/ads-init 执行逻辑：

检测到 .claude/ 已存在？
    ├─ 是 → 只生成 ADS 专属文件（wiki/ config.json mcp_servers.json）
    │        提示："检测到 .claude/，规则将从 .claude/rules/ 读取，.ads/ 作为扩展层"
    └─ 否 → 完整生成 .ads/（现有逻辑），同时可选生成 .claude/ 骨架
```

新增 `--claude` 参数：`/ads-init --claude` 强制生成标准 `.claude/` 结构（适合新项目）。

**完成标准**：
- 已有 `.claude/` 的项目执行 `/ads-init` 不会重复创建规则文件
- `--claude` 参数生成标准 `.claude/` 骨架 + ADS 扩展文件

---

## 四、目录结构对齐（`.ads/` 重组方案）

当前 `.ads/` 结构与 `.claude/` 对比后，**建议不重命名现有目录**，只做以下调整：

| 现状 | 是否需要改动 | 原因 |
|------|------------|------|
| `.ads/rules/` | 不改 | 与 `.claude/rules/` 格式完全一致，逻辑上是同类 |
| `.ads/skills/` | 可选改为 `.ads/commands/` | 与 `.claude/commands/` 对齐，但有向后兼容成本 |
| `.ads/wiki/` | 不改 | ADS 独有，`.claude/` 无对应 |
| `.ads/mcp_servers.json` | 不改 | 格式与 `.claude/settings.json` 不同，保持独立 |
| `.ads/config.json` | 不改 | traits/aicr 是 ADS 专属字段，与 `.claude/settings.json` 无重叠 |

**结论**：`.ads/` 目录结构本身不需要重组，只在读取层做兼容即可。

---

## 五、实施路线图

```
Day 1     Phase A：规则加载兼容
          ├─ loader.py load_project_rules() 双路径合并
          ├─ CLAUDE.md 作为 alwaysApply 规则读取
          └─ 单元测试：.claude/rules/ 与 .ads/rules/ 合并优先级验证

Day 2     Phase B：MCP 配置兼容
          ├─ _load_project_mcp_config() 读 .claude/settings.json mcpServers
          ├─ 格式转换（Claude 格式 → ADS 格式，enabled 默认 true）
          └─ 合并测试

Day 3     Phase C + E：命令加载 + ads-init 升级
          ├─ 命令元数据 API 合并 .claude/commands/
          ├─ ads-init 检测 .claude/ 存在逻辑
          └─ --claude 参数支持

Day 4     Phase D + 集成测试
          ├─ .claude/agents/ 注册逻辑
          ├─ 端到端：Claude Code 项目接入 ADS 全流程验证
          └─ DevNote
```

---

## 六、优先级汇总

| Phase | 内容 | 优先级 | 工期 | 核心价值 |
|-------|------|--------|------|---------|
| A | 规则加载兼容 `.claude/rules/` + `CLAUDE.md` | **P0** | 1 天 | 最高频使用，影响所有规则注入 |
| B | MCP 配置兼容 `.claude/settings.json` | **P0** | 1 天 | MCP 统一管理入口 |
| C | 命令加载兼容 `.claude/commands/` | **P1** | 0.5 天 | 项目级命令扩展 |
| E | `ads-init` 升级（检测 + `--claude`） | **P1** | 0.5 天 | 新项目接入体验 |
| D | `.claude/agents/` 支持 | **P2** | 0.5 天 | 子 Agent 扩展 |
| **合计** | | | **3.5 天** | |

---

## 七、完成标准（DoD）

**Phase A**：
- 项目根有 `CLAUDE.md`，ADS 聊天时自动注入其内容（限 3000 字符）
- 项目根有 `ADS.md`，注入在 `CLAUDE.md` 之后，优先级最高
- `.claude/rules/cpp.md` 存在，编辑 `.cpp` 文件时被 ADS 自动读取
- `.ads/rules/cpp.md` 存在时覆盖 `.claude/rules/cpp.md`
- 两个文件均不存在时静默跳过，不影响现有流程

**Phase B**：
- `.claude/settings.json` 中配置的 `mcpServers` 出现在 `/mcp-config` 列表中，来源标注为「.claude」
- `.ads/mcp_servers.json` 同名条目覆盖 `.claude` 配置

**Phase C**：
- 项目 `.claude/commands/deploy.md` 出现在 ADS 前端 `/` 补全列表中

**Phase D**：
- `.claude/agents/deploy-agent.md` 定义的 Agent 可被 Orchestrator 调度

**Phase E**：
- 已有 `.claude/` 的项目执行 `/ads-init` 输出「检测到 .claude/，以扩展模式初始化」
- `/ads-init --claude` 生成标准 `.claude/` 骨架

---

## 八、风险与注意事项

| 风险 | 说明 | 缓解措施 |
|------|------|---------|
| 规则重复注入 | `.claude/rules/` 和 `.ads/rules/` 有同名文件时重复 | 用 `rule_id` 去重，后者覆盖前者 |
| CLAUDE.md / ADS.md 过大 | 项目总指令文件可能几千 token，全量注入消耗上下文 | 各限制最大 3000 字符，超出截断并在思考面板提示 |
| ADS.md 与 CLAUDE.md 内容冲突 | 两个文件对同一规则有不同描述 | ADS.md 排在后面，LLM 自然以后出现的为准；文档建议用户保持互补而非重复 |
| `.claude/settings.json` 格式变更 | Claude Code 版本升级可能调整格式 | 用 `try/except` 容错，解析失败静默跳过 |
| 命令名冲突 | `.claude/commands/compact.md` 与系统命令冲突 | 项目级命令加命名空间前缀，或以项目层覆盖系统层（可配置） |

---

*文档创建：2026-05-21 | 项目：ai-dev-system | 版本：v1.0*
