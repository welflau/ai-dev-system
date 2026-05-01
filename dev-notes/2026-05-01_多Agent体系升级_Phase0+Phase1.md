# 开发日志 — 2026-05-01 多 Agent 体系升级（Phase 0 + Phase 1）

## 背景

基于腾讯 KM《如何让AI分工帮我做游戏》三篇的对比分析（详见 `docs/20260430_AI开发系统下一阶段升级设计方案.md`），系统从原有 7 个 Agent 扩展为 **10 个 Agent**，并建立了分层知识库体系和图片生成能力。

---

## Phase 0：基础设施准备（commit `0f0746b`）

### P0-1. SOP YAML 扩展

- `sop/loader.py`：`stage.mode` 字段透传到 `sop_config`，供 Agent prompt 读取行为模式标签
- `actions/write_code.py`：读取 `sop_config.mode`，切换 prompt 前缀（IMPLEMENT / REVIEW / DEBUG）
- **意义**：后续可在 SOP YAML 里给每个阶段指定 `mode`，让 Agent 以不同"心态"执行

### P0-2. Agent 产出物写文件到 Git

- `api/knowledge.py`：`_upsert_knowledge_index()` 新增 `agent_scope` 参数
- 新增 `_FILENAME_SCOPE_MAP`：根据文件名自动推断 `agent_scope`（PRD.md→planner，UX设计.md→ux，架构设计.md→arch 等）
- `orchestrator.py`：docs/ 下 Markdown 文件**保留中文名**（不再强制转英文），其他代码文件仍做 sanitize
- **意义**：PRD.md / UX设计.md / 视觉规范.md 等产出物进入 Git 历史，可追溯，同时自动按 Agent 类型分类入知识库

### P0-3. 数据库变更

```sql
-- knowledge_index 加 agent_scope 字段（向后兼容，NULL = 所有Agent可见）
ALTER TABLE knowledge_index ADD COLUMN agent_scope TEXT DEFAULT NULL;

-- 新增 4 张领域知识表（来自 G_DesignKnowledge/）
CREATE TABLE planning_knowledge (...)    -- 策划领域知识（游戏设计/产品设计）
CREATE TABLE ux_knowledge (...)          -- UX 交互设计知识
CREATE TABLE engineering_knowledge (...) -- 工程实践知识
CREATE TABLE design_knowledge (...)      -- 视觉设计知识
-- 每张表配套 FTS5 全文索引
```

### P0-4. KnowledgeLoader 基础框架

新增 `backend/knowledge_config.yaml`：集中声明每个 Agent 的知识来源（project / domain / spec / insight 四种类型）

新增 `backend/knowledge_loader.py`：
- 按 Agent 类型 + 项目 traits 加载对应知识
- 支持 `path_filter_by_traits`：按项目 traits 自动路由到领域知识子目录（如 RPG 项目查 `planning/games/rpg/`）
- `_build_context()` 改造：接受 `agent_name` 参数，差异化加载三段知识（`project_knowledge` / `domain_knowledge` / `agent_spec`）

新增 `config.py` 配置项：
```
GLOBAL_KNOWLEDGE_LOCAL_PATH=F:\A_Works\G_DesignKnowledge
ART_ASSETS_LOCAL_PATH=F:\A_Works\G_ArtRes
```

---

## Phase 1：新 Agent 体系（commits `0f0746b` ~ `885bdc1`）

### P1-1. 策划 Agent（PlannerAgent）

**新增状态**：`planning_in_progress` / `planning_done`

**新文件**：
- `actions/write_prd.py`（WritePRDAction）
- `agents/planner.py`（PlannerAgent）

**SOP 改造**：`_core.yaml` 在 architecture 前插入 `planning` 阶段：
```
pending → PlannerAgent(write_prd) → planning_done
       → ArchitectAgent → architecture_done → ...
```

**PRD 产出内容**：用户故事 / 功能需求 / 验收标准（必须可量化）/ 边界条件 / 资产需求线索

**资产需求线索（新增 PRD 章节）**：策划 Agent 在 PRD 末尾固定输出非正式的资产清单，供美术 Agent 识别：
```markdown
## 资产需求线索
- 音频：战斗开始/结束音效
- 图片：角色立绘 × 4
```

---

### P1-2. UX Agent

**新增状态**：`ux_design_in_progress` / `ux_design_done`

**新文件**：
- `actions/write_ux_design.py`（WriteUXDesignAction）
- `agents/ux.py`（UXAgent）
- `sop/fragments/ux_design.yaml`（SOP fragment）

**触发条件**（traits）：`platform:web/wechat/mobile/desktop` 或 `category:game`  
**SOP 位置**：`insert_after: planning`，自动插入 Planner 和 Architect 之间

**UX 产出内容**：
- 交互流程图（Mermaid）
- 组件线框说明（布局/层级/清单）
- 交互状态定义（正常/hover/disabled/loading/empty/error）
- 响应式/适配规则
- UI 资产清单初稿 → `asset_manifest.yaml` 初版

**验证**（SOP compose 后）：
```
Web: pending→Planner→UX→Art→Architect→Dev→Review→ProductAgent→Deploy ✅
Server: pending→Planner→Architect→Dev→... (跳过 UX) ✅
```

---

### P1-3. 美术 Agent（ArtAgent）

**新增状态**：`art_design_in_progress` / `art_design_done`

**新文件**：
- `actions/write_art_design.py`（WriteArtDesignAction）
- `agents/art.py`（ArtAgent）
- `sop/fragments/art_design.yaml`（SOP fragment，`insert_after: ux_design`）

**美术 Agent 产出（三类文件）**：

| 文件 | 内容 |
|---|---|
| `视觉规范.md` | 整体风格说明 + 组件视觉规格（Markdown）|
| `asset_manifest.yaml` | 完整资产清单（覆盖 UX 初稿，含类型/来源/状态）|
| `design_tokens.json` | Design Token：颜色/字体/间距/圆角 |

**资产路由标注**（asset_manifest 里每项）：
```yaml
- id: icon_home
  type: icon
  source_hint: iconify
  status: pending
- id: hero_banner
  type: illustration
  source_hint: ai_generate
  status: pending
```

---

### P1-4. 图片处理 Agent + LightAI 配置

**新文件**：
- `image_processor.py`：后台处理器（LightAI API 集成）
- `api/image_gen.py`：REST API（请求队列管理 + 配置测试）

**新增 DB 表**：`image_requests`（id/prompt/engine/status/lightai_task_id/callback_doc/callback_tag/result_path）

**LightAI API 集成**（参考 lightai_public_skills）：

```
POST /api/lightai/create_async_task → task_id
GET  /api/lightai/get_task_status/{task_id} → status(2=成功)
```

**支持引擎**：

| 引擎 | 说明 | 模型 |
|---|---|---|
| `gemini` | nano-banana pro（推荐）| gemini-3-pro-image-preview |
| `gemini2` | nano-banana2（更快）| gemini-3.1-flash-image-preview |
| `jimeng` | 即梦 | doubao-seedream-5-0-260128 |
| `midjourney` | Midjourney v6 | v6 |

**工作流程**：
```
Agent 请求生图 → 立即返回 [IMG_PENDING:xxx]（继续工作）
                          ↓（后台 10s 轮询）
         image_processor → LightAI API → 下载图片 → G_ArtRes
                          → 替换文档占位符 → 推送 SSE
         API Key 未配置 → LLM 生成 ASCII 艺术兜底
```

**LightAI 配置面板**：LLM 配置弹窗下方新增 LightAI 配置区，支持：
- API Base URL / API Key 配置
- 引擎选择（4 种）
- 独立"测试 LightAI"按钮
- 保存时写入 `.env` 并更新 runtime settings

---

## Agent 体系演进对比

| | 升级前 | 升级后 |
|---|---|---|
| Agent 数量 | 7 个 | **10 个** |
| SOP 阶段数（Web项目）| 6 个 | **9 个** |
| Agent 知识库 | 所有 Agent 共用 | **按 Agent 类型差异化加载** |
| 产出物文件 | 代码写 Git，中间产出只在 DB | **所有产出物（PRD/UX/视觉规范）同步写 Git** |
| 图片生成 | 无 | **LightAI 异步生图，占位符机制** |

### 完整 SOP 流水线（Web 项目）

```
pending
  → PlannerAgent (write_prd)     → planning_done
  → UXAgent (write_ux_design)    → ux_design_done
  → ArtAgent (write_art_design)  → art_design_done
  → ArchitectAgent               → architecture_done
  → DevAgent                     → development_done
  → ReviewAgent                  → review_passed
  → ProductAgent (acceptance)    → acceptance_passed
  → DeployAgent                  → deployed
```

---

## 变更文件清单

| 文件 | 变更 |
|---|---|
| `backend/models.py` | 新增 6 个 TicketStatus 值（planning/ux_design/art_design 各两个）|
| `backend/database.py` | 新增 4 张领域知识表 + image_requests 表 + agent_scope 迁移 |
| `backend/config.py` | 新增 G_ArtRes / G_DesignKnowledge / LightAI 配置项 |
| `backend/knowledge_config.yaml` | 新增，各 Agent 的知识来源声明 |
| `backend/knowledge_loader.py` | 新增，KnowledgeLoader 三层知识加载 |
| `backend/image_processor.py` | 新增，LightAI 图片生成后台处理器 |
| `backend/agents/planner.py` | 新增，PlannerAgent |
| `backend/agents/ux.py` | 新增，UXAgent |
| `backend/agents/art.py` | 新增，ArtAgent |
| `backend/actions/write_prd.py` | 新增，WritePRDAction |
| `backend/actions/write_ux_design.py` | 新增，WriteUXDesignAction |
| `backend/actions/write_art_design.py` | 新增，WriteArtDesignAction |
| `backend/actions/write_code.py` | 加 mode 标签支持 |
| `backend/api/image_gen.py` | 新增，图片生成 REST API |
| `backend/api/knowledge.py` | agent_scope 支持 |
| `backend/sop/_core.yaml` | 插入 planning 阶段 |
| `backend/sop/loader.py` | mode 字段透传 |
| `backend/sop/fragments/ux_design.yaml` | 新增 fragment |
| `backend/sop/fragments/art_design.yaml` | 新增 fragment |
| `backend/agent_registry.py` | 注册 3 个新 Agent |
| `backend/orchestrator.py` | 新状态处理 + 产物保存 + KnowledgeLoader 接入 |
| `backend/main.py` | 图片调度器启动 + 路由注册 |
| `frontend/index.html` | LLM 配置弹窗加 LightAI 配置区 |
| `frontend/app.js` | LightAI 加载/保存/测试逻辑 |
