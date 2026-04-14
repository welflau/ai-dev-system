# AI 自动开发系统 (AI Dev System)

[![Version](https://img.shields.io/badge/version-v0.14.7-blue.svg)](docs/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> 基于 Harness 架构思想的多 Agent 自动化软件开发平台
> 从自然语言需求到代码部署的全链路自动化，7 层工程约束确保 AI 产出可靠

## 核心理念：Harness 模式

**AI 不可靠，但工程可以驾驭它。**

```
用户需求 → [Prompt约束] → [上下文注入] → [Agent状态机] → [质量门禁]
         → [Git分支隔离] → [CI/CD流水线] → [环境隔离] → 安全上线
```

7 层 Harness 将 AI 的不确定性转化为工程的确定性。每一层都有约束、验证和兜底机制。

## 系统架构

```
┌──────────────────────────────────────────────────────┐
│                    Web UI (看板/聊天/监控)              │
├──────────────────────────────────────────────────────┤
│  SOP 配置引擎 (YAML)  │  事件总线 + 轮询兜底           │
├──────────────────────────────────────────────────────┤
│             Orchestrator 编排器                        │
│  状态机 · 依赖检查 · 僵尸检测 · Agent 调度             │
├──────────────────────────────────────────────────────┤
│  Agent (Role + Action 组合，移植 MetaGPT 模式)         │
│                                                       │
│  ProductAgent → AcceptanceReviewAction (ActionNode)   │
│  ArchitectAgent → DesignArchitectureAction (ActionNode)│
│  DevAgent → WriteCodeAction + SelfTestAction (BY_ORDER)│
│  TestAgent → 5层测试 (静态/审查/功能/用例/执行)          │
│  ReviewAgent → 10条静态规则 + LLM 审查                  │
│  DeployAgent → dev/test/prod 三环境部署                 │
├──────────────────────────────────────────────────────┤
│  ActionNode (结构化输出)  │  Agent Memory (cause_by索引) │
├──────────────────────────────────────────────────────┤
│  LLM Client (Anthropic/OpenAI) │ Git Manager │ SQLite │
└──────────────────────────────────────────────────────┘
```

## 功能列表

### 需求管理
- 自然语言提交需求，AI 自动拆解为工单
- 需求优先级、里程碑关联
- 需求可暂停/恢复/关闭/重新执行

### 6 个 AI Agent

| Agent | 职责 | 模式 | Actions |
|-------|------|------|---------|
| **ProductAgent** | 需求拆单 + 产品验收 | SINGLE | `acceptance_review` (ActionNode) |
| **ArchitectAgent** | 增量架构设计 | SINGLE | `design_architecture` (ActionNode) |
| **DevAgent** | 代码开发 + 自测 | BY_ORDER | `write_code` → `self_test` |
| **TestAgent** | 5层测试 + 报告 + 截图 | SINGLE | 静态/审查/功能/用例/执行 |
| **ReviewAgent** | 代码审查 | SINGLE | 10条规则 + LLM |
| **DeployAgent** | 环境部署 | SINGLE | dev/test/prod 隔离 |

### SOP 可配置工作流
- YAML 定义工单流转规则（`sop/default_sop.yaml`）
- 修改 YAML 即改流程，无需改代码
- 前端 SVG 流程图可视化
- 热重载 API

### Git 原生集成
- 每个需求自动创建 `feat/` 分支
- 有意义的 commit message（含工单标题和文件名）
- feat → develop → main 逐级合并
- 仓库文件浏览器 + 分支选择器

### CI/CD + 三环境隔离

| 环境 | 分支 | 端口 | 触发 |
|------|------|------|------|
| dev | feat/* | base+0 | Agent 提交代码后 |
| test | develop | base+100 | develop 构建通过后 |
| prod | main | base+200 | master 构建通过后 |

### AI 聊天面板
- 全局对话：自然语言操控项目（创建需求/Git 操作/生成文档）
- 工单对话：查看所有工单的 Agent 对话记录
- Git 能力：切换分支/查看日志/读文件/合并

### 全链路可追溯
- 7 张表审计链：从部署代码倒推到用户原始对话
- 每次 LLM 调用的完整 prompt + response 记录
- 操作日志 + 产物归档 + Git commit 关联

## 快速开始

### 前置要求
- Python 3.10+
- Git

### 安装

```bash
git clone https://github.com/welflau/ai-dev-system.git
cd ai-dev-system/backend
pip install -r requirements.txt
```

### 配置 LLM

```bash
# 创建 .env 文件
cat > .env << EOF
LLM_BASE_URL=https://api.anthropic.com
LLM_API_KEY=your-api-key
LLM_MODEL=claude-sonnet-4-20250514
LLM_API_FORMAT=anthropic
EOF
```

### 启动

```bash
cd backend
python main.py
```

访问 http://localhost:8000/app

### 使用

1. 创建项目（填 Git 远程仓库 URL）
2. 点击"+ 提交需求"，输入需求描述
3. 系统自动：拆单 → 架构 → 开发 → 验收 → 测试 → 部署
4. 在看板实时查看进度，在 AI 聊天面板对话

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.10+ / FastAPI / Uvicorn |
| 数据库 | SQLite + aiosqlite (WAL 模式, 13 张表) |
| LLM | Claude Sonnet 4 (Anthropic API) / OpenAI 兼容 |
| 实时通信 | SSE (Server-Sent Events) |
| 前端 | 原生 HTML/CSS/JS (无框架, ~15000 行) |
| Git | 本地 Git CLI + GitHub 远程 |
| 截图 | Playwright (可选) |

## 项目结构

```
ai-dev-system/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── orchestrator.py      # 编排引擎 (2000+ 行)
│   ├── llm_client.py        # LLM 集成 (Anthropic/OpenAI)
│   ├── database.py          # SQLite (13 张表)
│   ├── event_bus.py         # 内部事件总线
│   ├── memory.py            # Agent Memory (cause_by 索引)
│   ├── agent_registry.py    # Agent 注册中心
│   ├── ci_pipeline.py       # CI/CD 流水线
│   ├── git_manager.py       # Git 操作
│   ├── sop/                 # SOP 工作流配置
│   │   ├── default_sop.yaml # 默认开发流程
│   │   └── loader.py        # YAML 解析引擎
│   ├── actions/             # Action 能力层 (移植 MetaGPT)
│   │   ├── action_node.py   # ActionNode 结构化输出
│   │   ├── schemas.py       # Pydantic 输出 Schema
│   │   ├── write_code.py    # 代码开发 Action
│   │   ├── design_architecture.py
│   │   ├── self_test.py
│   │   └── acceptance_review.py
│   ├── agents/              # Agent (Role) 定义
│   │   ├── base.py          # BaseAgent + ReactMode + Watch
│   │   ├── product.py       # ProductAgent
│   │   ├── architect.py     # ArchitectAgent
│   │   ├── dev.py           # DevAgent (BY_ORDER)
│   │   ├── test.py          # TestAgent (5 层测试)
│   │   ├── review.py        # ReviewAgent
│   │   ├── deploy.py        # DeployAgent (三环境)
│   │   └── custom/          # 自定义 Agent (自动加载)
│   └── api/                 # API 端点 (68+ 接口)
├── frontend/
│   ├── index.html           # 页面结构
│   ├── app.js               # 应用逻辑 (~7800 行)
│   └── styles.css           # 样式 (~6600 行)
├── docs/                    # 项目文档
├── dev-notes/               # 开发日志
└── scripts/
    └── daily-summary.py     # 每日日报自动生成
```

## API (68+ 接口)

- 项目管理: CRUD + Git + 环境
- 需求管理: 创建/拆单/暂停/恢复/重新执行
- 工单管理: 看板/状态/日志/依赖图
- AI 聊天: 全局对话/工单对话/群聊/Git 操作
- Agent: 状态监控/Actions/配置
- CI/CD: 构建/部署/环境管理
- SOP: 查询/热重载
- 里程碑/Roadmap/Bug 追踪/知识库

完整接口见 http://localhost:8000/docs

## 开发路线

```
✅ v0.13   SOP 配置化 + 事件驱动 + 流程查看器
✅ v0.14   Agent 能力层重构 (Action/Memory/Registry)
✅ v0.14.5 MetaGPT 移植 (ActionNode/状态机/Watch)
⬜ v0.15   多 LLM 支持 / 并发调度 / 竞品分析
⬜ v0.16   插件市场 / 多项目协作 / Data Interpreter
```

详细计划见 [docs/20260413_03_改进开发计划.md](docs/20260413_03_改进开发计划.md)

## 文档

- [系统技术架构](docs/20260413_01_系统技术架构文档.md) — 完整架构 + Harness 7 层 + 工作流回溯
- [MetaGPT 对比分析](docs/20260413_02_MetaGPT对比分析与改进方向.md) — 7 维度对比
- [改进开发计划](docs/20260413_03_改进开发计划.md) — v0.13~v0.16 路线图
- [MetaGPT 移植方案](docs/20260414_01_MetaGPT移植方案与开发计划调整.md) — ActionNode/状态机/Watch

## License

MIT
