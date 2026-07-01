# 内置 Rules/Skills 套件化门控（enabled_packs）

**日期**：2026-07-01
**状态**：已上线 ✅
**关联方案**：`docs/20260701_01_内置Rules_Skills套件化实现方案.md`

## 背景

每轮 CLI 调用都会把全量内置 rules/skills 注入 system prompt（`<ads_context>`），哪怕项目根本没用到对应技术栈。OG 项目对话时会无条件注入 `ue5.md` / `game-dev.md` / `cpp.md` / workflow rules 等，用户无法按项目控制"到底要不要加载这些规范"。

目标：标注每条 rule/skill 归属哪个套件，项目启用了对应套件才注入，未启用则跳过；`global.md` 等核心规范不受套件控制。

## 改动内容

### 数据层

**`backend/skills/rules/*.md`** — 6 个 rule 加 `pack` frontmatter：

| 文件 | pack |
|---|---|
| `global.md` | *(不标，永远常驻)* |
| `ue5.md` | `ue5-dev` |
| `cpp.md` | `code-quality` |
| `python.md` | `code-quality` |
| `typescript.md` | `typescript-quality` |
| `game-dev.md` | `game-dev` |
| `workflow/autoaicr.md` | `vibe-workflow` |
| `workflow/precommit.md` | `vibe-workflow` |

**`backend/skills/skills.json`** — 各 skill 加 `pack` 字段：

| skill | pack |
|---|---|
| `react-dev` / `fastapi-dev` / `playwright-e2e` | `web-dev` |
| `git-workflow` | `vibe-workflow` |
| `unreal-cpp-dev` / `unreal-editor-control` / `unreal-project` | `ue5-dev` |
| `marketplace-skills`（及 scan_dir 扫出的 market items） | *(不标，常驻)* |

### 门控层（`backend/skills/loader.py`）

- `_load_rules` / `_load_config`：读取并保存 `pack` 字段
- `get_rules_for_context(enabled_packs=None)` — 新增参数：
  - `None` → 旧行为（不门控）
  - `set()` → 只加载 pack 为空的核心规则
  - `{"ue5-dev", ...}` → 核心 + 已启用套件
- `get_skills_for_agent(enabled_packs=None)` — 同上逻辑
- `build_prompt_for_agent` / `build_index_for_agent` — 透传 `enabled_packs`；缓存 key 加入 `packs_key = tuple(sorted(enabled_packs))`（不同项目不再串台）
- 新增模块级异步函数 `get_enabled_packs(project_id)` — 查 `project_packs` 表，返回 `set[str]`

### 调用层（`backend/agents/chat_assistant.py`）

- 项目聊天：解析 `project_traits` 后，调 `get_enabled_packs(project_id)` 取 `_enabled_packs`，传入 rules + skills 注入
- 全局聊天（无项目）：传 `set()`，只注入 `global.md` 等核心

### 展示层（`backend/api/commands.py`）

- `/skills` 命令：取项目 `enabled_packs` 后传入 `get_skills_for_agent` / `get_rules_for_context`，保证面板显示 = 实际注入

## 验证

```python
from skills.loader import SkillLoader
sl = SkillLoader()

# 全局聊天：只有 global
sl.get_rules_for_context(traits=['ue5'], enabled_packs=set())
# → ['global']

# 启用 ue5-dev + game-dev 套件
sl.get_rules_for_context(traits=['ue5', 'game-ue'], enabled_packs={'ue5-dev', 'game-dev'})
# → ['global', 'ue5', 'game-dev']

# 未启用任何套件：UE 项目对话不注入 ue5/game-dev rules
sl.get_rules_for_context(traits=['ue5', 'game-ue'], enabled_packs=set())
# → ['global']
```

## 当前状态

`project_packs` 表暂无数据 → 所有项目等价于 `enabled_packs=set()`，只注入 `global.md`。

**下一步**：在项目设置页添加套件启用/停用 UI，写 `project_packs` 表后，门控才真正按项目生效。

手动测试方法（临时验证）：
```sql
INSERT INTO project_packs (project_id, pack_name) VALUES ('PRJ-xxx', 'ue5-dev');
```
重启后端，对应项目对话时 `ue5.md` + UE 系 skills 将重新注入。

## 改动文件

- `backend/skills/rules/ue5.md` / `cpp.md` / `python.md` / `typescript.md` / `game-dev.md` / `workflow/autoaicr.md` / `workflow/precommit.md`
- `backend/skills/skills.json`
- `backend/skills/loader.py`
- `backend/agents/chat_assistant.py`
- `backend/api/commands.py`
