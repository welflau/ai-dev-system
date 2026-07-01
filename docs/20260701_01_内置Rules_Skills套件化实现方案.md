# 内置 Rules/Skills 套件化 — 实现方案

> 日期: 2026-07-01 | 关联: [[20260420_01_Skills注入系统实现方案]]、ConfigPack 套件系统

---

## 一、背景

### 1.1 当前痛点

用户在 OG 项目对话时发现：**每一轮 CLI 调用都在 stdin 里塞入一大段前缀**（`<ads_context>`），即使只是问一个简单问题也不例外。排查后定位到前缀的构成与加载机制：

CLI（codebuddy）模式下，system prompt 由 `chat_assistant._build_system_prompt()` 每轮全量重建，包含：

| 块 | 内容 | 来源 |
|---|---|---|
| Rules | `global.md` + 按 traits 命中的 `ue5.md`/`game-dev.md` 等 | `backend/skills/rules/*.md` |
| Skills 索引 | 可用 skill 名称+描述表（不含全文） | `skills.json` + 项目 skill 目录 |
| 工具使用规则 | confirm_requirement / confirm_bug / run_command 等约 100 行 | 硬编码在 prompt 模板 |
| 动态状态 | 需求 / 工单 / 文件树 / 产出物 | 每轮实时 |

### 1.2 根因

内置 rules/skills 是 **进程启动时无条件全量加载** 的：

- `SkillLoader.__init__` → `_load_rules()` 递归扫 `backend/skills/rules/**/*.md`，全部进 `self.rules`
- `_load_config()` 读 `skills.json` 全部进 `self.skills`
- 之后 `get_rules_for_context(traits)` / `get_skills_for_agent(agent, traits)` 只按 **traits / paths / alwaysApply** 过滤，**与"项目是否启用某套件"无关**

结果：只要项目 traits 命中，对应 rule 就注入，用户无法按项目控制"这个项目到底要不要加载 UE 规范 / 游戏开发规范"。

### 1.3 现存的两套并行体系（未打通）

| 体系 | rules 来源 | skills 来源 | 加载时机 |
|---|---|---|---|
| **内置（硬编码）** | `backend/skills/rules/*.md`（8 个） | `skills.json` + `packs/*/prompt.md` | 进程启动全量加载，与套件无关 |
| **ConfigPack 套件** | `config_packs/<pack>/shared/rules/*.md` | `config_packs/<pack>/shared/skills/*/SKILL.md` | 安装时 copy 到项目 `.claude`/`.codebuddy` 目录 |

两者内容还有重复：`config_packs/game-dev/shared/rules/`（11 个）与 `backend/skills/rules/game-dev.md` 并存。

### 1.4 落地目标

1. **内置 rules/skills 下沉套件**：每个内置项标注归属套件（`pack` 字段）
2. **按项目启用才加载**：项目启用了对应套件，其 rules/skills 才注入 prompt；未启用则跳过
3. **global.md 常驻**：语言一致性 / 安全红线等通用基线不受套件控制，任何项目都加载
4. **向后兼容**：未标 `pack` 的项 = 常驻（现有行为不变）；缓存与展示接口同步适配

---

## 二、设计原则

**不物理搬移文件**，而是「标注归属 + 启用门控」。

理由：`skill_loader` 是全局单例，`get_rules_for_context` / `get_skills_for_agent` 等被 15+ 处调用。直接把 8 个 rule 文件搬进各 pack 目录会破坏所有调用点、且需要大规模数据迁移。采用「加 `pack` 字段 + 门控参数」的方式，风险最小、可灰度、可回退。

物理重组（把内置文件真正移入 `config_packs/<pack>/`）作为后续可选步骤，等门控稳定后再做。

---

## 三、实现细节

### 3.1 数据层：标注归属套件

**内置 rules frontmatter 加 `pack` 字段：**

| 文件 | pack | 说明 |
|---|---|---|
| `rules/global.md` | *(不标)* | 核心常驻，任何项目加载 |
| `rules/ue5.md` | `ue5-dev` | |
| `rules/cpp.md` | `code-quality` | |
| `rules/python.md` | `code-quality` | |
| `rules/typescript.md` | `typescript-quality` | |
| `rules/game-dev.md` | `game-dev` | |
| `rules/workflow/autoaicr.md` | `vibe-workflow` | |
| `rules/workflow/precommit.md` | `vibe-workflow` | |

**`skills.json` 每个 skill 加 `"pack": "..."` 字段**（未标者常驻）。

**`loader._load_rules` / `_load_config` 读取并保存 `pack` 字段**：

```python
self.rules[rule_id] = {
    ...,
    "pack": frontmatter.get("pack") or "",   # 空 = 核心常驻
}
```

### 3.2 门控层：`skills/loader.py`

**新增启用套件查询**（查已存在的 `project_packs` 表）：

```python
async def get_enabled_packs(project_id: str) -> set[str]:
    rows = await db.fetch_all(
        "SELECT pack_name FROM project_packs WHERE project_id = ?", (project_id,)
    )
    return {r["pack_name"] for r in rows}
```

> 注意：`SkillLoader` 现为同步类，`get_enabled_packs` 涉及 DB 异步查询，放在调用方（async 上下文）解析后作为参数传入，loader 内部方法保持同步。

**`get_rules_for_context` / `get_skills_for_agent` 增加 `enabled_packs` 参数：**

```python
def get_rules_for_context(self, traits=None, current_file=None,
                          scene=None, enabled_packs=None):
    ...
    for rule_id, cfg in self.rules.items():
        pack = cfg.get("pack") or ""
        # 门控：标了 pack 且未启用 → 跳过；未标 pack（核心）→ 放行
        if pack and enabled_packs is not None and pack not in enabled_packs:
            continue
        ...  # 原有 scene / alwaysApply / traits / paths 过滤不变
```

- `enabled_packs=None` → 不做套件门控（保持旧行为，全局/无项目场景）
- `enabled_packs=set()` → 只加载核心（无套件项目）
- `enabled_packs={"ue5-dev", ...}` → 核心 + 已启用套件

**`build_prompt_for_agent` / `build_index_for_agent` 透传 `enabled_packs`，并把它纳入缓存 key：**

```python
cache_key = (agent_type, traits_tuple, current_file or "", scene or "",
             tuple(sorted(enabled_packs)) if enabled_packs is not None else None)
```

> ⚠️ 关键：`_agent_prompt_cache` 原 key 不含项目维度，加 `enabled_packs` 后不同项目才不会串台。

### 3.3 调用层：传入项目启用套件

改造点（先取 `enabled_packs` 再传入）：

| 文件:行 | 场景 | 处理 |
|---|---|---|
| `chat_assistant.py:1318` | 项目聊天 rules | 取 `get_enabled_packs(project_id)` 传入 |
| `chat_assistant.py:1347` | 项目聊天 skills 索引 | 同上 |
| `chat_assistant.py:1608/1622` | 全局聊天 | 传 `set()`（无项目，只核心） |
| `api/projects.py:1454/1468` | rules/skills 列表展示接口 | 传项目 enabled_packs，保持「面板显示 = 实际注入」 |
| `api/commands.py:478/490` | `/skills`、`/rules` 命令 | 同上 |
| `agents/base.py:114` | 其他 Agent 注入 | 按需传入（有 project 上下文时） |

无项目上下文的调用点传 `None` 或 `set()`，行为明确。

---

## 四、效果

以 OG 项目为例：

- **未启用任何套件**：prompt 只含 `global.md`（语言/安全基线）+ 工具使用规则 + 动态状态
- **启用 `ue5-dev`**：额外加载 `ue5.md`
- **启用 `game-dev`**：额外加载 `game-dev.md` 及该套件 skills

前缀随套件按需伸缩，用户可在项目级精确控制加载哪些规范。

---

## 五、风险与兼容

| 项 | 说明 |
|---|---|
| **向后兼容** | 未标 `pack` 的 rule/skill = 常驻；已装套件项目行为不变；`enabled_packs=None` 完全走旧逻辑 |
| **缓存串台** | 必须给 `_agent_prompt_cache` key 加 `enabled_packs` 指纹，否则多项目共享缓存出错 |
| **展示一致性** | 面板列 rules/skills 的接口也要过门控，避免「面板显示了但实际没注入」或反之 |
| **global 兜底** | `global.md` 不标 pack，保证未启用任何套件时 AI 仍有语言/安全基线约束 |
| **codebuddy 双加载** | codebuddy CLI 自身还会扫 `.codebuddy/rules/`（IG3C 全套，与内置不重复），本方案不影响该行为 |

---

## 六、后续可选步骤

1. **物理重组**：门控稳定后，把 `backend/skills/rules/ue5.md` 等真正移入 `config_packs/ue5-dev/shared/rules/`，消除内容重复，内置只保留 `global.md` 核心集。
2. **套件管理 UI**：项目设置页提供套件启用/停用开关，写 `project_packs` 表，实时影响 prompt 组装。
3. **默认套件推荐**：新建项目时按 traits 自动推荐启用套件（复用 `_TRAIT_PACK_MAP`）。

---

## 七、改动文件清单

- `backend/skills/rules/*.md` — 6 个 rule 加 `pack` frontmatter（global 除外）
- `backend/skills/skills.json` — 各 skill 加 `pack` 字段
- `backend/skills/loader.py` — `_load_rules`/`_load_config` 读 pack；`get_enabled_packs`；`get_rules_for_context`/`get_skills_for_agent`/`build_prompt_for_agent`/`build_index_for_agent` 加 `enabled_packs` + 缓存 key
- `backend/agents/chat_assistant.py` — 注入前取 enabled_packs 传入（4 处）
- `backend/api/projects.py`、`backend/api/commands.py` — 展示接口过门控
- `backend/agents/base.py` — 其他 Agent 注入按需传入
