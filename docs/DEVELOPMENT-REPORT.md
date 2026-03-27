# 📋 AI Dev System — 项目开发报告

> 生成时间：2026-03-27 | 版本：v0.10.0+

---

## 1. 项目概述

| 项目 | 内容 |
|------|------|
| **名称** | AI Dev System（AI 自动开发系统） |
| **仓库** | https://github.com/welflau/ai-dev-system |
| **本地路径** | D:\A_Works\ai-dev-system\ |
| **运行地址** | http://localhost:8000/app |
| **开发周期** | 2026-03-22 ~ 2026-03-27（6天） |
| **定位** | 工单驱动的 AI 多 Agent 自动开发管理平台 |

### 核心能力

- 📋 需求管理（提交→AI 拆单→工单→自动流转→完成报告）
- 🤖 6 Agent 协作（产品→架构→开发→审查→测试→部署）
- 🎫 工单看板 + 列表 + 关系图（依赖拓扑）
- 💬 AI 聊天面板（全局/工单对话，指令式操作）
- 📂 Git 仓库集成（自动 init/branch/commit/push）
- 🗺️ Roadmap 甘特图 + 里程碑管理
- 📊 Agent 实时监控面板
- 📋 需求完成自动生成汇总报告

---

## 2. 技术栈

| 层级 | 技术 |
|------|------|
| **后端** | Python 3.14 + FastAPI + aiosqlite + SSE (sse-starlette) |
| **前端** | 纯原生 HTML/CSS/JS SPA（无框架依赖） |
| **数据库** | SQLite（WAL 模式） |
| **LLM** | Anthropic Messages API（腾讯 SkyNet 代理），支持 OpenAI 兼容格式 |
| **Git** | 异步 subprocess 调用 git CLI |
| **部署** | uvicorn（--reload 热加载） |

---

## 3. 版本迭代历程

| 版本 | 日期 | 里程碑 |
|------|------|--------|
| v0.1~v0.2 | 03-22~03-23 | 基础框架搭建 |
| v0.3.0 | 03-23 | SQLite 持久化 + 体验升级 |
| v0.4.0 | 03-23 | LLM 智能引擎接入 |
| v0.5.0 | 03-24 | Agent 协作 + SSE 实时推送 |
| v0.6.0 | 03-24 | 质量保障 + 部署配置 |
| v0.7.0 | 03-24 | 工单管理系统（类 TAPD，三级模型，13 种状态） |
| v0.7.1 | 03-24 | LLM 会话日志 + 产出文件展示 |
| v0.8.0 | 03-24 | Git 仓库集成（6 Agent 全部改造返回 files） |
| v0.9.0 | 03-25 | AI 聊天面板（全局/工单对话） |
| v0.9.1 | 03-25 | 需求列表可折叠工单 + 工单列表页 |
| v0.9.2 | 03-25 | AI 助手需求状态管理（暂停/恢复/关闭） |
| v0.9.3 | 03-25 | 工单依赖关系 + 关系图视图（SVG 拓扑） |
| v0.9.4 | 03-26 | AI 助手全局可用 + 对话创建项目 |
| v0.9.5 | 03-26 | Roadmap 甘特图 + 列表视图 |
| v0.10.0 | 03-26 | 里程碑系统（AI 自动生成+关联+进度追踪） |
| v0.10.1 | 03-26~27 | 工单状态编辑 + 轮询调度 + Agent 监控 + 分支管理 + 完成报告 |

---

## 4. 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (SPA)                         │
│  index.html + app.js (~6000行) + styles.css (~3000行)    │
│  看板 / 列表 / 关系图 / Pipeline / Roadmap / Agent监控    │
│  聊天面板 / 仓库浏览 / 统计面板                            │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP + SSE
┌──────────────────────▼──────────────────────────────────┐
│                  FastAPI Backend                          │
│  ┌──────────┐  ┌───────────┐  ┌──────────────────────┐  │
│  │ API 路由  │  │ SSE 推送   │  │   LLM Client         │  │
│  │ 8个模块   │  │ EventMgr  │  │ Anthropic/OpenAI     │  │
│  └────┬─────┘  └───────────┘  └──────────────────────┘  │
│       │                                                   │
│  ┌────▼─────────────────────────────────────────────┐    │
│  │           Orchestrator (调度引擎)                  │    │
│  │  轮询调度 → 状态机 → Agent 分派 → 结果处理         │    │
│  │  依赖检查 → 僵尸检测 → 分支管理 → 报告生成         │    │
│  └────┬─────────────────────────────────────────────┘    │
│       │                                                   │
│  ┌────▼─────────────────────────────────────────────┐    │
│  │              Agent Pool (6 Agents)                │    │
│  │  📋 Product  🏗️ Architect  💻 Dev                 │    │
│  │  🧪 Test     🔍 Review     🚀 Deploy              │    │
│  └──────────────────────────────────────────────────┘    │
│                                                           │
│  ┌──────────────┐  ┌──────────────────────────────────┐  │
│  │ SQLite (10表) │  │ Git Manager (分支/提交/推送)      │  │
│  └──────────────┘  └──────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## 5. 代码量统计

### 后端 (Python)

| 模块 | 文件 | 行数 |
|------|------|------|
| **核心** | orchestrator.py | ~1,439 |
| **LLM 客户端** | llm_client.py | 443 |
| **Git 管理** | git_manager.py | 416 |
| **数据模型** | models.py | 352 |
| **数据库** | database.py | 336 |
| **入口** | main.py | 296 |
| **事件推送** | events.py | 74 |
| **配置** | config.py | 39 |
| **工具** | utils.py | 28 |
| **API — chat** | api/chat.py | 959 |
| **API — tickets** | api/tickets.py | 682 |
| **API — requirements** | api/requirements.py | 659 |
| **API — milestones** | api/milestones.py | 491 |
| **API — projects** | api/projects.py | 396 |
| **API — agents** | api/agents.py | 334 |
| **API — roadmap** | api/roadmap.py | 295 |
| **API — verification** | api/verification.py | 220 |
| **Agents (6个)** | agents/*.py | ~1,071 |
| | **合计** | **~7,700+** |

### 前端 (HTML/CSS/JS)

| 文件 | 大小 | 估算行数 |
|------|------|----------|
| app.js | 223 KB | ~6,000 |
| styles.css | 100 KB | ~3,000 |
| index.html | 51 KB | ~1,400 |
| | **合计** | **~10,400** |

### 项目总计

**约 18,000+ 行代码**（后端 ~7,700 + 前端 ~10,400）

---

## 6. 数据库设计 (10 张表)

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `projects` | 项目 | name, git_repo_path, git_remote_url |
| `requirements` | 需求单 | title, status(7种), branch_name, milestone_id |
| `tickets` | 工单 | status(13种), dependencies, assigned_agent, verification_* |
| `subtasks` | 子任务 | ticket_id, status |
| `ticket_logs` | 操作日志 | agent_type, action, from/to_status, detail |
| `artifacts` | 产出文件 | type, name, content, metadata |
| `llm_conversations` | LLM 会话 | messages, response, tokens, duration |
| `ticket_commands` | 执行命令 | command_type, command, status |
| `chat_messages` | 聊天消息 | role, content, action_type |
| `milestones` | 里程碑 | title, status(5种), target_date, progress |

---

## 7. Agent 池

| Agent | 职责 | 输出 |
|-------|------|------|
| 📋 **ProductAgent** | 需求分析 + PRD + 拆单 + 验收 | docs/PRD.md, acceptance-review.md |
| 🏗️ **ArchitectAgent** | 架构设计 | docs/architecture.md |
| 💻 **DevAgent** | 代码生成（LLM 驱动） | src/**/*.py, *.js |
| 🧪 **TestAgent** | 代码审查 + 冒烟 + 单元测试 | tests/test_*.py, docs/test-report.md |
| 🔍 **ReviewAgent** | 代码审查报告 | docs/code-review.md |
| 🚀 **DeployAgent** | 部署配置生成 | Dockerfile, docker-compose.yml, CI/CD |

### 工单流转状态机

```
pending → architecture_in_progress → architecture_done
       → development_in_progress → development_done
       → acceptance_passed (或 acceptance_rejected → 打回开发)
       → testing_in_progress → testing_done (→ 激活后续依赖)
       → deploying → deployed
```

---

## 8. API 端点清单

### 项目管理 (api/projects.py)
- `GET /api/projects` — 项目列表
- `POST /api/projects` — 创建项目（自动 git init + push）
- `GET /api/projects/{id}` — 项目详情
- `PUT /api/projects/{id}` — 更新项目
- `DELETE /api/projects/{id}` — 删除项目
- `GET /api/projects/{id}/git/*` — Git 操作（tree/log/file/diff/remote）

### 需求管理 (api/requirements.py)
- `GET /api/projects/{id}/requirements` — 需求列表
- `POST /api/projects/{id}/requirements` — 创建需求（自动触发拆单）
- `GET /api/projects/{id}/requirements/{rid}` — 需求详情（含工单）
- `PUT /api/projects/{id}/requirements/{rid}` — 更新需求
- `DELETE /api/projects/{id}/requirements/{rid}` — 取消需求
- `DELETE /api/projects/{id}/requirements/{rid}/permanent` — 永久删除
- `POST /api/projects/{id}/requirements/{rid}/decompose` — AI 拆单
- `GET /api/projects/{id}/requirements/{rid}/pipeline` — Pipeline 视图

### 工单管理 (api/tickets.py)
- `GET /api/projects/{id}/tickets` — 工单列表（支持筛选）
- `GET /api/projects/{id}/tickets/{tid}` — 工单详情
- `PUT /api/projects/{id}/tickets/{tid}` — 更新工单
- `PATCH /api/projects/{id}/tickets/{tid}/status` — 手动改状态（触发自动流转）
- `POST /api/projects/{id}/tickets/{tid}/start` — 启动工单
- `POST /api/projects/{id}/tickets/{tid}/reject` — 打回工单
- `GET /api/projects/{id}/board` — 看板数据
- `GET /api/projects/{id}/ticket-graph` — 工单关系图

### 聊天 (api/chat.py)
- `POST /api/chat` — 全局聊天
- `POST /api/projects/{id}/chat` — 项目聊天（支持指令：创建/暂停/恢复/关闭需求）
- `GET /api/projects/{id}/chat/history` — 聊天历史

### 里程碑 (api/milestones.py)
- CRUD + AI 生成 + 自动关联 + 进度刷新

### Roadmap (api/roadmap.py)
- `GET /api/projects/{id}/roadmap` — 甘特图数据

### Agent (api/agents.py)
- `GET /api/agents` — Agent 配置列表
- `GET /api/agents/status` — Agent 实时状态

### 系统
- `GET /api/health` — 健康检查
- `GET/POST /api/llm/status|config|test` — LLM 配置管理

---

## 9. 前端页面清单

| 页面/Tab | 功能 |
|----------|------|
| 📋 **需求列表** | TAPD 风格表格 + 可折叠工单 + 分支名标签 |
| 🎫 **工单看板** | 5 列看板（待启动/架构/开发/测试/部署） |
| 📝 **工单列表** | 表格视图 + 看板视图切换，状态可下拉编辑 |
| 🔗 **工单关系图** | SVG 拓扑图（依赖线 + 父子关系） |
| 🔧 **Pipeline** | 蓝盾风格流水线（阶段/Job/子任务/日志/AI对话/命令/产物） |
| 🗺️ **Roadmap** | 甘特图 + 列表视图 + 里程碑分组 |
| 📂 **仓库文件** | 文件树浏览 + 文件内容查看 + Git 日志 |
| 📊 **统计面板** | 工单/需求/模块/Agent 统计 |
| 🤖 **Agent 监控** | 6 Agent 实时状态卡片 + 工作量统计 |
| 📝 **操作日志** | 全项目日志流 |
| ⚙️ **设置** | 项目配置 + 仓库设置 + Agent 管理 |
| 💬 **AI 助手** | 右侧聊天面板（全局/工单对话） |

---

## 10. 2026-03-26~27 最新改动

| 功能 | 说明 |
|------|------|
| 工单状态可编辑 | 列表/看板的状态列改为下拉选择框，手动修改触发自动流转 |
| 轮询调度器 | orchestrator 每 10 秒扫描可流转工单 + 僵尸检测（60s 超时自动重置） |
| Agent 监控面板 | 侧栏新 Tab，6 Agent 实时状态/工作量/当前任务 |
| Git 分支管理 | 拆单后自动创建分支 `feat/{日期}-req-{短码}`，Agent 在分支上开发 |
| 文件路径隔离 | `docs/{需求短码}/{工单短码}/` 避免不同工单文档互相覆盖 |
| 需求完成报告 | 需求完成时自动生成汇总 Markdown 报告到 Git 仓库 |
| 验收/测试默认通过 | ProductAgent/TestAgent 始终通过，LLM 反馈仅作参考 |
| SSE 防抖 | 800ms 防抖合并多次状态变更刷新 |
| Git 编码修复 | `encoding=utf-8` 解决 Windows GBK 报错 |
| 文件名英文规范 | 分支名、代码文件名、测试文件名禁止中文 |

---

## 11. 开发规范

- **分支命名**：`feat/{YYYYMMDD}-req-{需求短码}`（纯英文数字）
- **文件命名**：代码文件、测试文件必须英文（如 `block-system.js`）
- **文档路径**：`docs/{需求短码}/{工单短码}/` 按需求+工单隔离
- **Git 提交**：`[AgentName] action: N files` 格式
- **状态机**：测试通过即激活后续依赖工单，部署为最后一步
- **LLM**：Anthropic Messages API，支持 OpenAI 兼容格式切换

---

*报告由 AI Dev System + WorkBuddy 自动生成 — 2026-03-27*
