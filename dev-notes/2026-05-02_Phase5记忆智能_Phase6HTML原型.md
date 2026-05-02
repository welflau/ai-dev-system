# 开发日志 — 2026-05-02 Phase 5 记忆与智能 + Phase 6 HTML 原型

---

## Phase 5：记忆与智能（commit `5513d89`）

### P5-1. Memory 持久化系统

**问题**：Orchestrator 传递上下文靠函数参数，重启后丢失；ChatAssistant 无法回答「当初为什么这样设计」。

#### 数据库变更

新增 `agent_memory` 表：
```sql
CREATE TABLE agent_memory (
    id, project_id, type,         -- decision/handoff/project_status/insight
    agent_type, title, content,   -- JSON 详情
    tags,                         -- JSON 数组，用于检索
    requirement_id, ticket_id, created_at
)
```

#### GetMemoryAction（ChatAssistant 新工具）

`backend/actions/chat/get_memory.py`：

当用户问「当初为什么这样设计」「这个功能踩过什么坑」时，AI 调用此工具检索 `agent_memory` 表，返回相关历史决策和经验。

#### Orchestrator 写入时机

1. **ArchitectAgent 完成时**：写入架构决策摘要（type=`decision`）
2. **需求完成时**：写入项目状态记录（type=`project_status`）

---

### P5-2. Insight 置信度 + 使用次数

**问题**：知识库里所有条目等权，高质量经验和普通笔记混在一起，DevAgent 无法分辨轻重。

#### 数据库变更

`knowledge_index` 新增两列（通过 `_auto_migrate` 无感迁移）：
```sql
ALTER TABLE knowledge_index ADD COLUMN confidence TEXT DEFAULT NULL;   -- high/medium/low
ALTER TABLE knowledge_index ADD COLUMN used_count INTEGER DEFAULT 0;
```

#### _fetch_prior_insights 升级

- 查询时获取 `confidence` 字段
- 高置信度条目排在前面，并标注 `⭐ [高置信，建议直接应用]`
- 每次引用后 `used_count+1`，形成使用频率数据

---

### P5-3. 需求级内省（三级内省 Level 1）

需求完成后（`_generate_requirement_report` 末尾）自动写入复盘摘要到 `knowledge_index`：

```
需求「XXX」完成复盘：
- 工单数: N，产物数: M
- 返工次数: K，Blocked 次数: J
- LLM 总耗时: Xs
- 注意: 有较多返工，说明需求描述或架构设计需要改进
```

文件名：`insight__req_{req_short}_retrospective.md`，`agent_scope=dev`，供后续同类需求的 Insight 检索命中。

---

### P5-4. 研发效率统计 API

新增 `backend/api/efficiency.py`，端点 `GET /api/projects/{id}/efficiency`：

| 统计维度 | 说明 |
|---|---|
| 需求交付周期 | 创建→完成的天数，计算均值 |
| Agent 耗时占比 | 按 agent_type 统计 LLM 调用时长 |
| Reflexion 重试排行 | 返工最多的工单 Top 10 |
| Smart Probe 均分 | 已处理需求的清晰度评分均值 |
| 工单状态分布 | 各状态工单数量 |

---

## Phase 6：HTML 原型验证管线（commit `b4f23f8`）

### 背景

游戏项目开发最大的浪费不是写错代码，而是做错了方向——在引擎里开发一个玩法循环不通的功能，损失 1-2 周。

解决方案：**进引擎前先用 HTML 验证核心循环**，1-2 天暴露问题，验证通过再进引擎。

### 实现

#### 新增 TicketStatus

```python
HTML_PROTOTYPE_IN_PROGRESS = "html_prototype_in_progress"
HTML_PROTOTYPE_DONE = "html_prototype_done"
HTML_PROTOTYPE_FAILED = "html_prototype_failed"
```

#### WriteHtmlPrototypeAction（`backend/actions/write_html_prototype.py`）

DevAgent 用 `write_html_prototype` 动作生成 HTML 原型：
- 产出 `prototype.html`（单文件，<!DOCTYPE html> 开头，可直接双击打开）
- 产出 `prototype-notes.md`（核心机制说明 + 引擎实现要点）
- 约束：不超过 300 行，只实现核心循环，不做 UI 美化

#### SOP Fragment（`backend/sop/fragments/html_prototype.yaml`）

```yaml
id: html_prototype
insert_after: planning
priority: 92                 # 在 UX 设计之前
required_traits:
  any_of:
    - category:game
    - prototype:html         # 非游戏但需要原型验证的项目可手动加此 trait
stage:
  agent: DevAgent
  action: write_html_prototype
  trigger_on: planning_done
  success_status: html_prototype_done
  reject_goto: html_prototype_fix
```

#### 游戏项目完整流水线

```
pending
  → PlannerAgent (write_prd)
  → DevAgent (write_html_prototype)   ← 新增，验证核心循环
  → UXAgent (write_ux_design)
  → ArtAgent (write_art_design)
  → ArchitectAgent
  → DevAgent (develop)
  → ReviewAgent
  → ProductAgent (acceptance)
  → DeployAgent
```

验证通过 → 流转到 UX 设计继续正常流水线
验证失败 → `html_prototype_failed` → fix_issues 修 HTML → 重新验证

---

## 变更文件汇总

| 文件 | 变更 |
|---|---|
| `backend/database.py` | agent_memory 表；knowledge_index 加 confidence/used_count |
| `backend/models.py` | 3 个 HTML 原型状态；STATUS_LABELS 补全 |
| `backend/actions/chat/get_memory.py` | 新增，GetMemoryAction |
| `backend/actions/write_html_prototype.py` | 新增，WriteHtmlPrototypeAction |
| `backend/agents/chat_assistant.py` | 注册 GetMemoryAction |
| `backend/orchestrator.py` | _write_memory 方法；需求级内省；HTML原型产物保存；Insight置信度排序 |
| `backend/api/efficiency.py` | 新增，研发效率统计 API |
| `backend/sop/fragments/html_prototype.yaml` | 新增 |
| `backend/main.py` | 注册 efficiency_router |
| `frontend/app.js` | html_prototype/report 产物图标 |

---

## 系统现状（Phase 0-6 完成后）

```
Agent 体系：10 个（含策划/UX/美术/图片处理）
SOP 流水线：
  普通 server 项目：6 阶段
  Web 项目：9 阶段（含策划/UX/美术）
  游戏项目：10 阶段（含 HTML 原型验证）

知识与记忆：
  美术资产库：33,263 条（图标/游戏资源/材质等）
  策划知识库：5,747 篇（游戏设计/产品设计）
  Agent Memory：跨会话持久化，可查历史决策
  Insight 置信度：高置信经验自动排前

流程优化：
  对抗性代码审查（三级分类）
  Smart Probe（5维度清晰度评分）
  规模自适应（XS直接开发/S跳策划/M+完整流水线）
  需求级内省（完成后自动写复盘到知识库）
```
