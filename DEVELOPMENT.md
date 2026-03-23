# 开发文档

## 项目概述

AI 自动开发系统是一个从自然语言需求到可运行软件的端到端自动化开发平台。用户提交需求描述后，系统自动完成需求分析、架构设计、代码生成、测试验证和部署上线全流程。

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 后端框架 | FastAPI | Python 异步 Web 框架 |
| 前端 | HTML / CSS / JavaScript | 纯原生实现，无框架依赖 |
| 数据存储 | 内存 (v0.2) → SQLite (v0.3) | 轻量级持久化 |
| 测试 | pytest | 51 个测试用例 |
| CI/CD | GitHub Actions | 自动运行 pytest + flake8 |

## 目录结构

```
ai-dev-system/
├── backend/                  # 后端代码
│   ├── agents/               # AI Agent 实现
│   │   ├── __init__.py       # 导出 DevAgent, ArchitectAgent
│   │   ├── base.py           # BaseAgent 抽象基类
│   │   ├── product.py        # ProductAgent (需求分析)
│   │   ├── dev.py            # DevAgent (代码生成, 14种任务)
│   │   └── architect.py      # ArchitectAgent (架构设计, 7种方案)
│   ├── models/               # 数据模型
│   │   ├── enums.py          # 枚举定义 (TaskStatus, AgentType, etc.)
│   │   └── schemas.py        # Pydantic 模型 (Task, Requirement, etc.)
│   ├── orchestrator/         # 协调器
│   │   ├── coordinator.py    # Orchestrator 主调度器
│   │   ├── decomposer.py     # TaskDecomposer 任务分解器
│   │   └── state_manager.py  # StateManager 状态管理器
│   ├── tools/                # 开发工具
│   │   ├── registry.py       # ToolRegistry 工具注册表
│   │   ├── file_tool.py      # 文件读写工具
│   │   └── git_tool.py       # Git 操作工具
│   ├── tests/                # 测试
│   │   ├── test_tools.py     # 工具测试 (8)
│   │   ├── test_orchestrator.py # 协调器测试 (21)
│   │   └── test_agents.py    # Agent + 集成测试 (22)
│   ├── projects/             # Agent 生成的项目文件输出目录
│   ├── main.py               # FastAPI 主应用入口
│   └── requirements.txt      # Python 依赖
├── frontend/                 # 前端代码
│   ├── index.html            # 主页面 (含全部 CSS + HTML)
│   └── app.js                # 应用逻辑 (路由/API调用/渲染)
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
                                    Agent 池
                              ┌────────┼────────┐
                         DevAgent  ArchitectAgent  ...
                              ↓         ↓
                         代码文件    设计文档
```

### 1. Orchestrator (协调器)

`backend/orchestrator/coordinator.py`

核心调度中心，负责：
- `process_request()` - 接收需求，触发任务分解，创建项目
- `execute_task()` - 调用对应 Agent 执行指定任务
- `execute_next_task()` - 按阶段顺序执行下一个 pending 任务
- `get_project_state()` - 获取项目完整状态
- `update_task()` - 更新任务状态

### 2. TaskDecomposer (任务分解器)

`backend/orchestrator/decomposer.py`

基于关键词匹配的规则引擎，将需求描述分解为开发任务：

| 关键词 | 生成的任务 |
|--------|-----------|
| API / 接口 / REST | API 设计、路由开发、接口文档 |
| 数据库 / 数据 / 存储 | Schema 设计、ORM 实现、数据迁移 |
| 前端 / 界面 / UI | UI 设计、组件开发、前端集成 |
| 用户 / 权限 / 角色 | 用户模型、权限系统、角色管理 |
| 登录 / 认证 / 注册 | 认证流程、JWT 实现、注册页面 |

任务按 5 个阶段组织：需求分析 → 架构设计 → 开发实现 → 测试验证 → 部署上线

### 3. StateManager (状态管理器)

`backend/orchestrator/state_manager.py`

管理项目和任务的完整生命周期：
- 项目创建 / 查询 / 列表
- 任务状态流转 (pending → in_progress → completed/failed)
- 阶段自动推进
- 项目日志记录

### 4. Agent 系统

**BaseAgent** (`agents/base.py`) - 抽象基类，定义 Agent 接口

**DevAgent** (`agents/dev.py`) - 代码生成 Agent，14 种任务处理器：
- 项目初始化 (目录结构 + main.py + requirements.txt)
- API CRUD 代码生成
- SQLAlchemy 数据模型
- 认证服务 (注册/登录/Token)
- 权限管理 (RBAC)
- 前端页面 + JS
- 数据库迁移、文档、工具函数等

**ArchitectAgent** (`agents/architect.py`) - 架构设计 Agent，7 种方案：
- 系统架构 (分层 + 模块划分 + 技术选型)
- 数据库 ER 设计
- API 接口设计
- UI 设计方案
- 用户系统设计

### 5. 工具系统

`backend/tools/` - 可扩展的工具注册表

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
| PUT | /api/projects/{id}/tasks/{task_id} | 更新指定任务状态 |
| GET | /tools | 查看已注册的开发工具 |
| GET | /app | 前端主页面 |

完整接口文档访问：http://localhost:8000/docs

## 数据模型

### TaskStatus (任务状态)
```
pending → in_progress → completed
                     → failed
                     → cancelled
```

### ProjectPhase (项目阶段)
```
requirement_analysis → design → development → testing → deployment → completed
```

### AgentType (Agent 类型)
```
product | architect | dev | test | review | deploy
```

## 前端页面

| 页面 | 路由标识 | 功能 |
|------|---------|------|
| 首页 | home | 概览统计 (项目数/完成数/进行中/工具数) |
| 提交需求 | submit | 输入需求描述 + 技术栈 + 项目名 |
| 项目看板 | projects | 项目卡片列表，进度条 |
| 项目详情 | project-detail | 阶段分组任务列表、统计摘要、日志 |
| 工具列表 | tools | 已注册开发工具 |
| 使用指引 | guide | 快速上手 + 功能说明 + FAQ |

## 测试

```bash
# 运行全部测试
cd backend && python -m pytest tests/ -v

# 运行特定测试
python -m pytest tests/test_tools.py -v         # 工具测试 (8)
python -m pytest tests/test_orchestrator.py -v   # 协调器测试 (21)
python -m pytest tests/test_agents.py -v         # Agent + 集成测试 (22)
```

## 扩展指南

### 添加新 Agent

1. 在 `backend/agents/` 创建新文件，继承 `BaseAgent`
2. 实现 `execute(task_name, context)` 方法
3. 在 `backend/agents/__init__.py` 导出
4. 在 `Orchestrator.__init__()` 的 `self.agents` 中注册

### 添加新工具

1. 在 `backend/tools/` 创建新工具类
2. 实现 `execute(**params)` 和 `get_schema()` 方法
3. 在 `main.py` 中 `tool_registry.register()` 注册

### 添加新关键词规则

编辑 `backend/orchestrator/decomposer.py` 的 `keyword_rules` 字典，添加新的关键词和对应任务模板。
