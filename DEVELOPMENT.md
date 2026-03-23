# 开发文档

## 项目概述

AI 自动开发系统是一个从自然语言需求到可运行软件的端到端自动化开发平台。用户提交需求描述后，系统自动完成需求分析、架构设计、代码生成、测试验证和部署上线全流程。

**当前版本：v0.5.0**

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 后端框架 | FastAPI | Python 异步 Web 框架 |
| 前端 | HTML / CSS / JavaScript | 纯原生实现，无框架依赖 |
| 数据存储 | SQLite | DbStateManager 持久化 |
| LLM | OpenAI 兼容 API | 支持 CodeBuddy/DeepSeek/Moonshot 等 |
| 实时推送 | SSE (sse-starlette) | 替代轮询的实时事件流 |
| 代码高亮 | highlight.js | CDN 加载，自动语言检测 |
| 测试 | pytest | 68 个测试用例 |
| CI/CD | GitHub Actions | 自动运行 pytest + flake8 |

## 目录结构

```
ai-dev-system/
├── backend/                  # 后端代码
│   ├── agents/               # AI Agent 实现
│   │   ├── __init__.py       # 导出 DevAgent, ArchitectAgent, TestAgent
│   │   ├── base.py           # BaseAgent 抽象基类
│   │   ├── product.py        # 原始 ProductAgent (async, 未直接使用)
│   │   ├── dev.py            # DevAgent (代码生成, 14种任务 + LLM)
│   │   ├── architect.py      # ArchitectAgent (架构设计, 7种方案 + LLM)
│   │   └── test_agent.py     # TestAgent (测试生成, LLM + 模板)
│   ├── models/               # 数据模型
│   │   ├── enums.py          # 枚举定义 (TaskStatus, AgentType, etc.)
│   │   └── schemas.py        # Pydantic 模型 (Task, Requirement, etc.)
│   ├── orchestrator/         # 协调器
│   │   ├── coordinator.py    # Orchestrator + ProductAgentAdapter
│   │   ├── decomposer.py     # TaskDecomposer (LLM + 规则引擎)
│   │   ├── state_manager.py  # StateManager 内存版
│   │   └── db_state_manager.py # DbStateManager SQLite 版
│   ├── llm/                  # LLM 客户端
│   │   ├── __init__.py       # 导出 LLMClient
│   │   └── client.py         # LLMClient (OpenAI 兼容)
│   ├── tools/                # 开发工具
│   │   ├── registry.py       # ToolRegistry 工具注册表
│   │   ├── file_tool.py      # 文件读写工具
│   │   └── git_tool.py       # Git 操作工具
│   ├── tests/                # 测试
│   │   ├── test_tools.py     # 工具测试 (8)
│   │   ├── test_orchestrator.py # 协调器测试 (21)
│   │   └── test_agents.py    # Agent + 集成测试 (22+)
│   ├── projects/             # Agent 生成的项目文件输出目录
│   ├── config.py             # 集中化配置 (Settings)
│   ├── main.py               # FastAPI 主应用入口
│   ├── .env.example          # 环境变量模板
│   └── requirements.txt      # Python 依赖
├── frontend/                 # 前端代码
│   ├── index.html            # 主页面 (含全部 CSS + HTML)
│   └── app.js                # 应用逻辑 (路由/API/SSE/高亮)
├── .github/workflows/ci.yml  # CI 配置
├── ROADMAP.md                # 开发路线图
└── DEVELOPMENT.md            # 本文档
```

## 快速开始

### 环境要求
- Python 3.8+
- pip

### 安装依赖
```bash
cd backend
pip install -r requirements-mvp.txt
```

### 配置 LLM (可选)
```bash
cd backend
cp .env.example .env
# 编辑 .env 填入你的 API Key
```

### 启动后端
```bash
cd backend
python main.py
# 或
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 访问系统
- 前端界面：http://localhost:8000/app
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

### 运行测试
```bash
cd backend
python -m pytest tests/ -v
```

## 核心架构

### 请求处理流程

```
用户需求 → FastAPI → Orchestrator → TaskDecomposer → StateManager
                                        ↓
                                    Agent 池 (上下文传递)
                    ┌──────────┬──────────┬──────────┐
               ProductAgent  ArchitectAgent  DevAgent  TestAgent
                    ↓              ↓           ↓          ↓
                 PRD 文档       设计文档     代码文件    测试文件
                                                          ↓
                              SSE EventBus → 前端实时更新
```

### Agent 间上下文传递 (v0.5.0)

```
ProductAgent → 需求分析/PRD
                ↓ (design_outputs)
ArchitectAgent → 架构设计文档
                ↓ (design_outputs + existing_files)
DevAgent → 代码文件（参考架构设计，避免重复生成）
                ↓ (dev_outputs + existing_files)
TestAgent → 测试代码（参考已有代码生成针对性测试）
```

### 1. Orchestrator (协调器)

`backend/orchestrator/coordinator.py`

核心调度中心，负责：
- `process_request()` - 接收需求，触发任务分解，创建项目
- `execute_task()` - 调用对应 Agent 执行指定任务（含上下文传递）
- `execute_next_task()` - 按阶段顺序执行下一个 pending 任务
- `_collect_completed_outputs()` - 收集已完成任务输出（供后续 Agent 使用）
- `_save_task_output()` - 保存 Agent 执行结果到上下文缓存

### 2. Agent 系统 (4 个已实现)

| Agent | 文件 | 功能 | LLM 模式 | 模板降级 |
|-------|------|------|----------|----------|
| ProductAgent | coordinator.py (Adapter) | 需求分析 + PRD 生成 | ✅ | ✅ |
| ArchitectAgent | agents/architect.py | 7 种架构设计方案 | ✅ | ✅ |
| DevAgent | agents/dev.py | 14 种代码生成任务 | ✅ | ✅ |
| TestAgent | agents/test_agent.py | pytest 测试生成 | ✅ | ✅ |

所有 Agent 统一接口：`execute(task_name: str, context: dict) -> dict`

### 3. SSE 实时推送 (v0.5.0)

`backend/main.py` - EventBus

- 前端通过 `EventSource` 订阅 `/api/projects/{id}/events`
- 事件类型：`init`, `task_update`, `task_progress`, `execute_all_done`, `heartbeat`
- 30 秒心跳保活，自动重连
- 完全替代原 8 秒轮询（降级为 30 秒轮询仅在不支持 EventSource 的浏览器）

### 4. LLM 客户端

`backend/llm/client.py`

- OpenAI 兼容 API 格式
- 同步: generate(), chat(), chat_with_tools(), stream()
- 异步: agenerate(), achat(), astream()
- 降级标记: `[LLM_UNAVAILABLE]`
- 配置: 环境变量或运行时更新

### 5. 工具系统

已注册工具 (8个)：
- FileWriterTool / FileReaderTool / DirectoryListerTool
- GitInitTool / GitAddTool / GitCommitTool / GitPushTool / GitCreateBranchTool

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /health | 健康检查 + 系统状态 |
| POST | /api/process | 提交需求，触发任务分解 |
| GET | /api/projects | 获取所有项目列表 |
| GET | /api/projects/{id}/state | 获取项目详情 + 任务列表 |
| POST | /api/projects/{id}/execute | 执行项目的下一个任务 |
| POST | /api/projects/{id}/execute-all | 一键全量执行所有任务 |
| GET | /api/projects/{id}/events | **SSE 实时推送**（替代轮询）|
| GET | /api/projects/{id}/files | 列出项目文件 |
| GET | /api/projects/{id}/files/{path} | 读取项目文件内容 |
| PUT | /api/projects/{id}/tasks/{task_id} | 更新指定任务状态 |
| GET | /api/llm/status | LLM 配置状态 |
| POST | /api/llm/test | 测试 LLM 连接 |
| POST | /api/llm/config | 运行时更新 LLM 配置 |
| GET | /tools | 查看已注册的开发工具 |
| GET | /app | 前端主页面 |

完整接口文档访问：http://localhost:8000/docs

## 前端页面

| 页面 | 路由标识 | 功能 |
|------|---------|------|
| 首页 | home | 概览统计 + LLM 状态徽章 |
| 提交需求 | submit | 输入需求描述 + 技术栈 + 项目名 |
| 项目看板 | projects | 项目卡片列表，进度条 |
| 项目详情 | project-detail | 阶段分组任务列表、统计摘要、文件浏览、代码高亮预览、SSE 实时更新 |
| 工具列表 | tools | 已注册开发工具 |
| LLM 配置 | llm-config | API 配置 + 连接测试 |
| 使用指引 | guide | 快速上手 + 功能说明 + FAQ |

## 测试

```bash
# 运行全部测试
cd backend && python -m pytest tests/ -v

# 运行特定测试
python -m pytest tests/test_tools.py -v         # 工具测试 (8)
python -m pytest tests/test_orchestrator.py -v   # 协调器测试 (21)
python -m pytest tests/test_agents.py -v         # Agent + 集成测试 (22+)
```

## 版本历史

| 版本 | 日期 | 主要功能 |
|------|------|---------|
| v0.1.0 | - | 基础框架 + 工具系统 |
| v0.2.0 | - | DevAgent + ArchitectAgent + 前端 |
| v0.3.0 | - | SQLite 持久化 + 一键执行 + 文件浏览 |
| v0.4.0 | 2026-03-23 | LLM 智能引擎（任务分解 + 代码生成 + 架构设计）|
| **v0.5.0** | 2026-03-23 | Agent 上下文传递 + TestAgent + ProductAgent + SSE + 语法高亮 |

## 扩展指南

### 添加新 Agent

1. 在 `backend/agents/` 创建新文件
2. 实现统一接口 `execute(task_name: str, context: dict) -> dict`
3. 在 `backend/agents/__init__.py` 导出
4. 在 `Orchestrator.__init__()` 的 `self.agents` 中注册
5. context 中可获取 `design_outputs`, `dev_outputs`, `test_outputs`, `existing_files`

### 添加新工具

1. 在 `backend/tools/` 创建新工具类
2. 实现 `execute(**params)` 和 `get_schema()` 方法
3. 在 `main.py` 中 `tool_registry.register()` 注册
