# AI 自动开发系统 (AI Dev System)

[![Version](https://img.shields.io/badge/version-v0.22-blue.svg)](docs/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> 多 Agent 自动化软件开发平台 + 对标 Claude Code 的强大 AI 开发助手  
> 从自然语言需求到代码部署的全链路自动化，内置斜杠命令系统、Extended Thinking、UE 创作流水线

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────────────┐
│               Web UI（看板 / AI助手 / 工单 / 监控）                    │
├────────────────────────────┬─────────────────────────────────────────┤
│   ChatAssistant AI 助手    │  Orchestrator 工单编排引擎               │
│   · Extended Thinking 推理链│  · SOP YAML 驱动工作流                  │
│   · 按轮次分组思考面板       │  · Agent 调度（7 个 Role）               │
│   · 斜杠命令系统（/command）│  · Reflexion 反思 + 失败库               │
│   · @file 引用展开          │  · 并行子任务调度                        │
│   · 全屏 / 分屏对话         │  · Trait-First 动态技能注入              │
│   · 全局工具全量开放         │  · UEEditorAgent BP/关卡生成             │
├────────────────────────────┴─────────────────────────────────────────┤
│                     QueryEngine（核心引擎）                            │
│  Budget 约束 │ Hooks 生命周期 │ Diminishing Returns │ Prompt Cache    │
├──────────────────────────────────────────────────────────────────────┤
│                     Skills 体系                                       │
│  packs/(内置) │ use_skills/(已安装) │ marketplace/(市场)              │
│  skills/commands/(斜杠命令定义) │ 三层优先级 │ Trait-First 注入        │
├──────────────────────────────────────────────────────────────────────┤
│  LLM Client (Anthropic/OpenAI) │ UE Python Bridge │ MCP │ SQLite FTS5│
└──────────────────────────────────────────────────────────────────────┘
```

![系统截图](Images/README/1778564605286960.png)

---

## 核心功能

### 🤖 AI 助手（对标 Claude Code）

- **Extended Thinking 推理链**：每轮推理文字 + 对应工具调用绑定展示，三态模式（adaptive/on/off）
- **斜杠命令系统**：输入 `/` 弹出补全，Tab/↑↓ 键盘导航，可扩展（`skills/commands/*.md`）
- **@file 引用**：消息中 `@/path/to/file` 自动注入文件内容
- **工具结果展开**：每个工具步骤可点击 `›` 展开完整返回内容
- **ultrathink 关键字**：输入 `ultrathink` 自动启用最大推理预算
- **全屏默认打开**：进入系统即全屏 AI 助手，默认获得全量工具

### 🔧 内置斜杠命令

| 命令 | 说明 |
|---|---|
| `/compact` | 手动触发对话历史压缩 |
| `/memory [query]` | 查看或搜索 Agent 记忆 |
| `/think <on\|off\|adaptive>` | 切换 Extended Thinking 模式 |
| `/skills` | 查看当前项目已加载 Skills |
| `/ue-run <code>` | 在 UE Editor 执行 Python 代码 |
| `/ue-bp-gen <描述>` | LLM 生成 Blueprint 并写入 UE Editor |
| `/ue-level <描述>` | LLM 生成关卡布局并写入 UE Editor |

### 🛠️ AI 助手工具集

| 工具 | 说明 | 范围 |
|---|---|---|
| `web_search` | 联网搜索 | 全局+项目 |
| `shell` | 执行 Shell 命令 | 全局+项目 |
| `glob` / `grep` | 文件搜索 / 内容搜索 | 全局+项目 |
| `read_files` | 批量读取文件 | 全局+项目 |
| `save_memory` / `get_memory` | Agent 记忆读写（4 类型）| 全局+项目 |
| `ue_run_python` | UE Python 桥接执行 | UE 项目 |
| `ue_blueprint_gen` | LLM 生成 Blueprint | UE 项目 |
| `ue_level_gen` | LLM 生成关卡布局 | UE 项目 |
| `search_knowledge` | FTS5 全文搜索知识库 | 项目内 |
| `browse_marketplace` | 浏览/安装 Skill 市场 | 全局+项目 |

### 🔄 自动化工单流水线

- 自然语言 → AI 自动拆解工单（PRD → 架构 → 开发 → 测试 → 验收）
- **SOP 可配置**：YAML 定义流转规则，热重载无需重启
- **Reflexion 反思**：失败后自动诊断根因，策略迭代，跨工单经验积累
- **并行子任务**：`/dispatch_parallel_subtasks` 一次创建多个并行子任务
- **UE 内容工单**：`type=ue_content` 触发 UEEditorAgent 生成 BP/关卡

### 🏗️ UE 项目深度集成

| 能力 | 实现方式 |
|---|---|
| 任意 Python 代码执行 | `ue_python_bridge`（UDP 多播 + TCP）|
| Blueprint 创建/修改 | `BlueprintGenAction` LLM 生成 |
| 关卡自动布置 | `LevelGenAction` LLM 生成 |
| UCP 结构化控制 | Actor 管理/蓝图编辑/材质/截图 |
| 自动 UBT 编译 | `UECompileCheckAction` |
| 自动 Playtest | `UEPlaytestAction` |

### 🧠 Memory 系统（4 类型，对标 Claude Code）

| 类型 | 说明 |
|---|---|
| `user_profile` 👤 | 用户角色、偏好、知识背景 |
| `behavior_feedback` 💬 | 行为反馈（正向确认或纠正）|
| `project_context` 📁 | 项目决策、里程碑、技术方案 |
| `external_ref` 🔗 | 外部资源指针（文档链接）|

---

## 快速开始

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
LLM_MODEL=claude-sonnet-4-5
LLM_API_FORMAT=anthropic   # 或 openai
EOF
```

### 启动

```bash
cd backend
DB_PATH=./data/ai_dev_system.db python -m uvicorn main:app --port 8000
```

访问 http://localhost:8000/app

### 基本使用

1. **进入即用**：默认全屏打开 AI 助手，输入 `/` 查看所有可用命令
2. **创建项目**：填入 Git 仓库 URL，系统识别项目类型并自动安装匹配 Skill
3. **提交需求**：自然语言描述，AI 自动拆单并执行完整流水线
4. **深度思考**：消息里加 `ultrathink` 启用最大推理预算

---

## 技术栈

| 层级 | 技术 |
|---|---|
| 后端 | Python 3.10+ / FastAPI / Uvicorn |
| 数据库 | SQLite + aiosqlite（WAL 模式，FTS5 全文搜索）|
| LLM | Anthropic Claude 4.x（Extended Thinking）/ OpenAI 兼容 |
| 实时通信 | SSE（流式输出 + 思考面板 + 工具调用）|
| UE 集成 | Python Remote Execution + UCP 协议 |
| MCP | MCP Client（外部工具扩展）|
| 前端 | 原生 HTML/CSS/JS（无框架）|

---

## 项目结构

```
ai-dev-system/
├── backend/
│   ├── main.py               # FastAPI 入口
│   ├── orchestrator.py       # 工单编排引擎
│   ├── llm_client.py         # LLM（Extended Thinking / Prompt Cache）
│   ├── query_engine/         # 核心引擎（Budget/Hooks/Events）
│   ├── agents/               # Agent 定义（7个 Role）
│   │   └── ue_editor.py      # UEEditorAgent（BP/关卡生成）
│   ├── actions/              # Action 能力层
│   │   ├── chat/             # AI 助手工具（35+ 个）
│   │   ├── ue_blueprint_gen.py
│   │   ├── ue_level_gen.py
│   │   └── ue_run_python.py
│   ├── engines/
│   │   └── ue_python_bridge.py  # UE Python 桥接
│   ├── api/
│   │   └── commands.py       # 斜杠命令路由
│   ├── skills/
│   │   ├── commands/         # 斜杠命令定义（*.md）
│   │   ├── use_skills/       # 已安装 Skills
│   │   └── rules/            # 全局编码规范
│   └── sop/fragments/        # SOP 工作流片段（YAML）
├── frontend/
│   ├── index.html
│   ├── app.js                # 应用逻辑（16000+ 行）
│   └── styles.css
├── docs/                     # 设计文档 + 分析报告
└── dev-notes/                # 开发日志（NextPhase 系列）
```

---

## 版本历史

| 版本 | 主要更新 |
|---|---|
| v0.22 | 斜杠命令系统 / Extended Thinking 三态 / UE Python 桥接 / BP+关卡生成 / Memory 4 类型 / @file 引用 |
| v0.21 | AI 助手工具扩展 / 思考过程分组展示 / 推理链面板 / 全局工具全量开放 |
| v0.20 | UE MCP Phase 1-5 / Skills 市场 / AI 助手流式统一 |
| v0.19 | UE 自动编译 + Playtest / Viewport 截图 |
| v0.17 | Trait-First 动态 Skill 注入 / 多会话管理 |
| v0.16 | ChatAssistant 全面升级 / Skill 主动触发 |

详细变更见 [dev-notes/](dev-notes/) 目录。

---

## License

MIT
