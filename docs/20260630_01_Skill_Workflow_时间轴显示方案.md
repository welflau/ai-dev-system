# Skill Workflow 时间轴显示方案

**创建日期**: 2026-06-30  
**状态**: 待实现  
**背景**: 工单在进行中时，Agent 处理会加载 Skill，Skill 的 SKILL.md 中定义了结构化的 workflow 步骤（## Workflow 节），但这些步骤目前不会被记录，也不会在工单属性面板的进展时间轴中体现。

---

## 一、现状分析

### 1.1 两条独立的执行路径

```
工单 Workflow（状态机）
  orchestrator.poll_loop
    → process_ticket
    → transition_rules 匹配
    → agent.execute(action, context)
    → _handle_agent_result
    → 状态转换 → 触发下一 Agent

Skill 注入（知识模块）
  skill_loader.build_index_for_agent()
    → 注入 system prompt 索引
    → Agent LLM 推理时调用 load_skill 工具
    → LoadSkillAction.run() 返回 Skill 全文
    → Agent 根据 Skill 内容指导自身推理
```

两条路径目前在 `agent.execute()` 内部隐式汇合，但 Skill 内容只影响 LLM 推理，**无法向上反馈到日志层**。

### 1.2 现有日志基础

**`ticket_logs` 表 schema**（`database.py:351-364`）：
```sql
CREATE TABLE IF NOT EXISTS ticket_logs (
    id              TEXT PRIMARY KEY,
    ticket_id       TEXT REFERENCES tickets(id),
    subtask_id      TEXT REFERENCES subtasks(id),
    requirement_id  TEXT REFERENCES requirements(id),
    project_id      TEXT NOT NULL REFERENCES projects(id),
    agent_type      TEXT,
    action          TEXT NOT NULL,
    from_status     TEXT,
    to_status       TEXT,
    detail          TEXT,          -- JSON 格式，可自由扩展
    level           TEXT NOT NULL DEFAULT 'info',
    created_at      TEXT NOT NULL
);
```

**目前 `_log` 函数**（`orchestrator.py:3508`）已支持 `detail_data` 扩展字段：
```python
async def _log(self, ..., detail_data: Optional[Dict] = None):
    detail_obj = {"message": message}
    if detail_data:
        detail_obj.update(detail_data)   # 可注入任意字段
```

**目前已记录的事件类型**：
| action | 含义 | detail 字段 |
|--------|------|------------|
| `thought_start` | Agent 开始执行 | agent_name, action |
| `thought_done` | Agent 执行完成 | elapsed_ms, result_summary, files |
| `complete` | Agent 成功 | git_commit, file_count |
| `accept/reject` | 验收通过/不通过 | reason |
| `reflection` | Reflexion 反思 | root_cause, strategy_change, confidence |
| `blocked/error` | 阻塞/异常 | error_summary |
| `update_status` | 状态流转 | from_status, to_status |

**缺失的字段**：`skill_name`、`phase_name`、`phase_index`、`phase_total`。

### 1.3 SKILL.md 中的 Workflow 定义格式

多个 SKILL.md 已定义结构化 workflow，例如 `data-analysis-workflows/SKILL.md`：

```markdown
---
name: data-analysis-workflows
description: Comprehensive data analysis workflows
---

# Data Analysis Workflows

## Workflow 1: Answer Data Questions
### 1. Understand the question
### 2. Identify relevant tables
### 3. Write and validate SQL
### 4. Format the answer

## Workflow 2: Explore and Profile Datasets
### 1. List available tables
### 2. Sample and profile data
...
```

还有 `image-to-ui` 等 Skill 在 `description` frontmatter 中直接声明阶段名（"四阶段流水线"）。

**解析规范**：
- `## Workflow N: <名称>` → 一个 workflow 块
- `### N. <步骤名>` → 该 workflow 内的一个步骤
- frontmatter `phases: [...]` → 可选的结构化阶段声明（未来标准化）

### 1.4 前端时间轴现状

前端已有时间轴组件（`app.js:4381`，`_renderUnifiedTimeline`）：
- 分 `primary` 层（主日志）和 `secondary` 层（细节日志，默认折叠）
- `renderLogItem` 渲染单条日志，已支持展开面板（input/output/cli）
- `thought_start/thought_done` 目前被 `_classify_tier` 归为 `secondary`，用户默认看不到

---

## 二、目标效果

工单在进行中时，进展时间轴应显示：

```
▶ DevAgent                                    15:32:01
  ● 加载 Skill: unreal-modeling-create
    ├─ [1/4] 理解需求：分析用户描述和现有代码...  ✓
    ├─ [2/4] 创建 Actor 类：生成 .h/.cpp 文件... ✓  (当前)
    ├─ [3/4] 注册组件和属性...
    └─ [4/4] 编写测试代码...

  状态变更: 开发中 → 审核中               15:34:22
```

关键特性：
1. **Skill 名称可见** — 哪个 Skill 在驱动当前执行
2. **阶段进度** — `phase_index / phase_total`，如 `2/4`
3. **当前步骤高亮** — 正在执行的阶段实时更新
4. **步骤折叠** — 同一 Skill 的多步骤折叠为可展开块
5. **primary 层可见** — Skill 阶段日志归为 primary，默认展示

---

## 三、实现方案

### 3.1 后端：解析 SKILL.md Workflow 定义

**新建工具函数** `backend/skills/workflow_parser.py`：

```python
import re
from pathlib import Path
from typing import List, Dict, Optional

def parse_skill_workflow(skill_md_path: str) -> Optional[Dict]:
    """
    解析 SKILL.md 中的 ## Workflow 节，返回阶段列表。
    
    返回结构：
    {
        "skill_name": "unreal-modeling-create",
        "workflows": [
            {
                "name": "Create Static Mesh Actor",
                "phases": ["理解需求", "创建类文件", "注册组件", "编写测试"]
            }
        ]
    }
    """
    try:
        content = Path(skill_md_path).read_text(encoding="utf-8")
    except Exception:
        return None

    # 提取 frontmatter 中的 name
    skill_name = Path(skill_md_path).parent.name
    fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if fm_match:
        name_m = re.search(r'^name\s*:\s*(.+)$', fm_match.group(1), re.MULTILINE)
        if name_m:
            skill_name = name_m.group(1).strip().strip('"\'')

    # 提取所有 ## Workflow 节
    workflows = []
    workflow_blocks = re.split(r'^## Workflow', content, flags=re.MULTILINE)
    for block in workflow_blocks[1:]:
        # 提取 workflow 名称（## Workflow N: <名称> 或 ## Workflow: <名称>）
        title_m = re.match(r'[^:]*:\s*(.+)', block.split('\n')[0])
        wf_name = title_m.group(1).strip() if title_m else "执行流程"
        # 提取步骤（### N. <步骤名>）
        phases = re.findall(r'^###\s+\d+\.\s+(.+)$', block, re.MULTILINE)
        if not phases:
            # 退化匹配：- 步骤N: xxx 或 **步骤N**
            phases = re.findall(r'^[-*]\s+\*?\*?步骤\d+\*?\*?[：:]\s*(.+)$', block, re.MULTILINE)
        if phases:
            workflows.append({"name": wf_name, "phases": phases})

    return {"skill_name": skill_name, "workflows": workflows} if workflows else None
```

### 3.2 后端：skill_loader 缓存 Workflow 定义

在 `backend/skills/loader.py` 的 `SkillLoader` 类中添加：

```python
# 在 __init__ 中
self._workflow_cache: Dict[str, Optional[Dict]] = {}

def get_skill_workflow(self, skill_id: str) -> Optional[Dict]:
    """获取 skill 的 workflow 定义（带缓存）"""
    if skill_id not in self._workflow_cache:
        cfg = self.skills.get(skill_id, {})
        file_path = cfg.get("file_path") or cfg.get("prompt_file")
        if file_path:
            from skills.workflow_parser import parse_skill_workflow
            self._workflow_cache[skill_id] = parse_skill_workflow(str(file_path))
        else:
            self._workflow_cache[skill_id] = None
    return self._workflow_cache[skill_id]

def invalidate_workflow_cache(self):
    self._workflow_cache.clear()
```

在 `reload()` 中调用 `invalidate_workflow_cache()`。

### 3.3 后端：orchestrator 记录 Skill 阶段日志

在 `orchestrator.py` 的 `_log_agent_thought` 或 `process_ticket` 中，Agent 执行前解析当前 skill：

**位置**：`process_ticket`（`orchestrator.py:1430` 附近），在 `agent.execute()` 调用前后：

```python
# 在 agent.execute 调用前（thought_start 日志之后）
from skills import skill_loader

# 获取当前 Agent 使用的 Skill 列表
active_skills = skill_loader.get_skills_for_agent(
    agent_name,
    traits=context.get("traits"),
)

# 对每个 skill，如果有 workflow 定义，记录 skill_start 事件
for skill_id in active_skills:
    wf = skill_loader.get_skill_workflow(skill_id)
    if not wf:
        continue
    for wf_def in wf.get("workflows", []):
        phases = wf_def.get("phases", [])
        if not phases:
            continue
        await self._log(
            project_id, ticket.get("requirement_id"), ticket_id,
            agent_type=agent_name,
            action="skill_workflow_start",
            from_status=None, to_status=None,
            message=f"加载 Skill: {wf['skill_name']} — {wf_def['name']}",
            level="info",
            detail_data={
                "skill_name": wf["skill_name"],
                "skill_id": skill_id,
                "workflow_name": wf_def["name"],
                "phases": phases,
                "phase_total": len(phases),
                "phase_index": 0,       # 0 = 未开始
            }
        )
```

**注意**：`phase_index` 的递增依赖 Agent 主动上报（见 3.4），初始方案可以只记录 `skill_workflow_start`（包含全部阶段列表），前端据此渲染完整步骤列表但不追踪当前进度。

### 3.4 后端（可选，Phase 2）：Agent 主动上报步骤进度

为 `SkillExecutor`（`agents/skills.py`）新增 `report_phase` 工具：

```python
async def _handle_report_phase(self, params: dict) -> dict:
    """Agent 上报当前执行到 skill workflow 的第几步"""
    skill_id    = params.get("skill_id", "")
    phase_index = int(params.get("phase_index", 0))
    phase_name  = params.get("phase_name", "")
    # 写入 ticket_logs
    await self._log_phase_progress(
        skill_id=skill_id,
        phase_index=phase_index,
        phase_name=phase_name,
    )
    return {"ok": True, "phase_index": phase_index}
```

**tool_schema**：
```json
{
  "name": "report_phase",
  "description": "上报当前 Skill Workflow 执行进度（第几阶段）",
  "input_schema": {
    "type": "object",
    "properties": {
      "skill_id":    { "type": "string", "description": "Skill ID" },
      "phase_index": { "type": "integer", "description": "当前阶段序号（1-based）" },
      "phase_name":  { "type": "string", "description": "当前阶段名称" }
    },
    "required": ["skill_id", "phase_index", "phase_name"]
  }
}
```

**说明**：Phase 2 实现，不阻塞 Phase 1。

### 3.5 后端：`_classify_tier` 调整

在 `orchestrator.py` 或前端的 tier 分类逻辑中，将 `skill_workflow_start` 归为 `primary`：

```python
PRIMARY_ACTIONS = {
    "update_status", "complete", "accept", "reject",
    "blocked", "error", "reflection",
    "skill_workflow_start",   # 新增
}
```

### 3.6 前端：`renderLogItem` 扩展

在 `app.js` 的 `renderLogItem` 函数中，新增 `skill_workflow_start` 的专用渲染分支：

```javascript
function renderLogItem(log) {
    // 解析 detail JSON
    let detail = {};
    try { detail = JSON.parse(log.detail || '{}'); } catch {}

    // ── Skill Workflow 步骤块 ────────────────────────────────
    if (log.action === 'skill_workflow_start' && detail.phases) {
        return _renderSkillWorkflowBlock(log, detail);
    }
    if (log.action === 'skill_phase_update' && detail.phase_index) {
        // Phase 2：更新已有 workflow 块的进度（通过 DOM 操作）
        _updateSkillWorkflowProgress(detail);
        return '';  // 不渲染新节点，只更新
    }

    // 原有渲染逻辑...
}

function _renderSkillWorkflowBlock(log, detail) {
    const { skill_name, workflow_name, phases, phase_total, phase_index = 0 } = detail;
    const blockId = `skill-wf-${log.id}`;

    const phaseItems = phases.map((name, i) => {
        const idx = i + 1;
        const isDone    = idx < phase_index;
        const isCurrent = idx === phase_index;
        const icon = isDone ? '✓' : isCurrent ? '●' : '○';
        const cls  = isDone ? 'phase-done' : isCurrent ? 'phase-current' : 'phase-pending';
        return `<div class="skill-phase-item ${cls}">
            <span class="skill-phase-icon">${icon}</span>
            <span class="skill-phase-label">[${idx}/${phase_total}] ${escHtml(name)}</span>
        </div>`;
    }).join('');

    return `
        <div class="log-item info skill-workflow-block" id="${blockId}" data-skill-id="${escHtml(detail.skill_id||'')}">
            <div class="log-header">
                <span class="log-agent">🎯 ${escHtml(log.agent_type || 'Agent')}</span>
                <span class="log-action skill-tag">Skill: ${escHtml(skill_name)}</span>
                <span class="skill-workflow-name">${escHtml(workflow_name || '')}</span>
                <span class="log-time">${formatTime(log.created_at)}</span>
            </div>
            <div class="skill-phases-container" id="${blockId}-phases">
                ${phaseItems}
            </div>
        </div>`;
}

function _updateSkillWorkflowProgress(detail) {
    // Phase 2：SSE 实时更新步骤进度
    const block = document.querySelector(`[data-skill-id="${detail.skill_id}"]`);
    if (!block) return;
    const container = block.querySelector('.skill-phases-container');
    if (!container) return;
    // 重新渲染 phases（保持已完成状态）
    // ...
}
```

### 3.7 前端：CSS 样式

在 `frontend/styles.css` 中新增：

```css
/* Skill Workflow 步骤块 */
.skill-workflow-block {
    border-left: 3px solid var(--primary);
    background: rgba(var(--primary-rgb), 0.04);
}

.skill-tag {
    background: rgba(99, 102, 241, 0.12);
    color: #6366f1;
    border-radius: 3px;
    padding: 1px 6px;
    font-size: 11px;
}

.skill-workflow-name {
    font-size: 11px;
    color: var(--text-muted);
    margin-left: 4px;
}

.skill-phases-container {
    padding: 6px 0 2px 16px;
    display: flex;
    flex-direction: column;
    gap: 3px;
}

.skill-phase-item {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--text-secondary);
    padding: 2px 0;
}

.skill-phase-item.phase-done    { color: var(--success); }
.skill-phase-item.phase-current { color: var(--primary); font-weight: 600; }
.skill-phase-item.phase-pending { opacity: 0.5; }

.skill-phase-icon {
    width: 14px;
    text-align: center;
    font-size: 11px;
    flex-shrink: 0;
}
```

---

## 四、实现优先级和阶段

### Phase 1（核心，先做）

| 步骤 | 文件 | 改动量 |
|------|------|--------|
| 新建 `workflow_parser.py` | `backend/skills/workflow_parser.py` | 新建，~60行 |
| `SkillLoader.get_skill_workflow()` | `backend/skills/loader.py` | +20行 |
| orchestrator 在 thought_start 前写 `skill_workflow_start` 日志 | `backend/orchestrator.py` | +15行 |
| `_classify_tier` 加 `skill_workflow_start` 为 primary | `backend/orchestrator.py` | +1行 |
| `renderLogItem` 加 skill workflow 分支 | `frontend/app.js` | +50行 |
| CSS 样式 | `frontend/styles.css` | +40行 |

**效果**：工单时间轴显示 Skill 名称和完整步骤列表（静态，无实时进度）。

### Phase 2（实时进度，后做）

| 步骤 | 文件 | 改动量 |
|------|------|--------|
| `SkillExecutor` 新增 `report_phase` 工具 | `backend/agents/skills.py` | +30行 |
| `_log_phase_progress` 写 phase_update 日志 | `backend/orchestrator.py` | +20行 |
| SSE 推送 phase_update 事件到前端 | `backend/orchestrator.py` | +5行 |
| 前端 `_updateSkillWorkflowProgress` 实时更新 DOM | `frontend/app.js` | +30行 |

**效果**：步骤进度实时更新（`[2/4] 当前执行 ●`）。

---

## 五、API 端点影响

现有端点无需改动，只是 `ticket_logs` 的 `detail` JSON 里新增字段：

```json
{
  "message": "加载 Skill: unreal-modeling-create — 创建 Actor 流程",
  "skill_name": "unreal-modeling-create",
  "skill_id": "unreal-modeling-create",
  "workflow_name": "创建 Static Mesh Actor",
  "phases": ["理解需求", "创建类文件", "注册组件", "编写测试"],
  "phase_total": 4,
  "phase_index": 0
}
```

`GET /api/tickets/{ticket_id}/timeline` 会自然包含这些日志，前端通过 `log.action === 'skill_workflow_start'` 识别并走专用渲染。

---

## 六、相关文件索引

| 文件 | 行号 | 说明 |
|------|------|------|
| `backend/database.py` | 351-364 | ticket_logs 表 schema |
| `backend/orchestrator.py` | 1430-1470 | process_ticket agent.execute 前后 |
| `backend/orchestrator.py` | 3508-3560 | `_log` 函数定义 |
| `backend/skills/loader.py` | 106-141 | `get_skills_for_agent` 三层过滤 |
| `frontend/app.js` | 7575+ | `renderLogItem` |
| `frontend/app.js` | 4381-4417 | `_renderUnifiedTimeline` |
| `backend/skills/marketplace/.../data-analysis-workflows/SKILL.md` | 全文 | Workflow 定义示例 |
