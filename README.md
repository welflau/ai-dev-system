# AI 自动开发系统 (AI Dev System)

[![Version](https://img.shields.io/badge/version-v0.21-blue.svg)](docs/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> 多 Agent 自动化软件开发平台 + 强大的 AI 开发助手
> 从自然语言需求到代码部署的全链路自动化，内置 Skill 市场与联网搜索能力

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│               Web UI（看板 / AI助手 / 工单 / 监控）               │
├───────────────────────────┬─────────────────────────────────────┤
│   ChatAssistant AI 助手   │  Orchestrator 工单编排引擎            │
│   · 流式输出 + 思考面板    │  · SOP YAML 驱动工作流               │
│   · 全屏分屏对话           │  · Agent 调度 (6 个 Role)            │
│   · Skills 市场           │  · Reflexion 反思 + 失败库            │
│   · 联网搜索 / Shell / Git │  · Trait-First 动态技能注入           │
├───────────────────────────┴─────────────────────────────────────┤
│                     Skills 体系                                  │
│  packs/(内置) │ use_skills/(已安装) │ marketplace/(市场)          │
│  项目 .Agent/skills/ │ global_skill_settings │ 三层优先级          │
├─────────────────────────────────────────────────────────────────┤
│  LLM Client (Anthropic/OpenAI/Gemini) │ MCP Client │ SQLite      │
└─────────────────────────────────────────────────────────────────┘
```

![系统截图](Images/README/1778564605286960.png)

---

## 核心功能

### 🤖 AI 开发助手（ChatAssistant）

- **流式输出 + 思考面板**：逐字回答，实时显示工具调用步骤和耗时
- **全屏模式**：一键隐藏其他面板，AI 助手铺满全屏
- **分屏对话**：全屏下最多 3 格并排，各自独立 session
- **历史对话**：多会话管理，今天/本周/更早分组
- **全局 + 项目**：项目列表页和项目内均可使用

### 🛠️ AI 助手工具集（对标 Gemini CLI）

| 工具 | 说明 | 可用范围 |
|------|------|---------|
| `web_search` | 联网搜索（腾讯元宝 / Bing 降级）| 全局+项目 |
| `fetch_url` | 抓取指定 URL 内容 | 全局+项目 |
| `glob` | glob 通配符查找文件 | 项目内 |
| `grep` | 正则搜索文件内容 | 项目内 |
| `list_directory` | 树形列出目录结构 | 项目内 |
| `shell` | 执行 Shell 命令（含安全白名单）| 项目内 |
| `read_files` | 批量读取多个文件 | 全局+项目 |
| `save_memory` | 写入 Agent 记忆（跨会话）| 全局+项目 |
| `search_knowledge` | 搜索项目知识库 | 项目内 |
| `git_*` | Git 操作（查日志/读文件/切分支/合并）| 项目内 |
| `ue_call` | 通过 UCP 控制 UE Editor | UE 项目 |
| `browse_marketplace` | 浏览/安装 Skill 市场 | 全局+项目 |

### 📦 Skills 市场体系

```
marketplace/     ← 浏览目录，复制文件夹即可出现
    ↓ 安装
use_skills/      ← 系统已安装（AI 助手按需加载）
.Agent/skills/   ← 项目已安装（项目内对话可用）
packs/           ← 内置技术规范（随系统发布）
```

- **三层优先级**：skills.json → global_skill_settings → project_skills
- **Trait-First**：按项目类型（engine:ue5 / platform:web 等）自动注入匹配 Skill
- **主动触发**：AI 通过 `load_skill` 按需加载，不全量注入 prompt
- **系统设置 UI**：全局开关 + 项目级覆盖 + 市场面板

### 🔄 自动化工单流水线

- 自然语言 → AI 自动拆解工单（PRD → 架构 → 开发 → 测试 → 验收）
- **SOP 可配置**：YAML 定义流转规则，热重载无需重启
- **Reflexion 反思**：失败后自动诊断根因，策略迭代，跨工单经验积累
- **Trait-First**：项目特征驱动工作流和技能差异化配置
- **操作日志可见**：每个 Agent 执行过程写入 ticket_logs，实时查看

### 🏗️ UE 项目深度集成

- UCP 插件（UnrealClientProtocol）控制运行中的 Editor
- Actor 管理 / 蓝图编辑 / 材质 / Niagara / PIE 控制
- 自动触发 UBT 编译 + Playtest
- UE Editor Viewport 截图（35s 稳定成功）

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
python main.py
```

访问 http://localhost:8000/app

### 基本使用

1. **创建项目**：填入 Git 仓库 URL，系统识别项目类型并自动安装匹配 Skill
2. **提交需求**：自然语言描述，AI 自动拆单并执行完整流水线
3. **AI 助手**：随时对话，可联网搜索、查看代码、执行命令
4. **查看进度**：看板/工单列表/操作日志实时跟踪

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.10+ / FastAPI / Uvicorn |
| 数据库 | SQLite + aiosqlite（WAL 模式，15+ 张表）|
| LLM | Anthropic Claude / OpenAI 兼容 / 多模型路由 |
| 实时通信 | SSE（流式输出 + 思考面板 + 工具调用）|
| MCP | MCP Client（外部工具扩展）|
| 前端 | 原生 HTML/CSS/JS（无框架）|
| Git | 本地 Git CLI + GitHub 远程 |

---

## 项目结构

```
ai-dev-system/
├── backend/
│   ├── main.py               # FastAPI 入口
│   ├── orchestrator.py       # 工单编排引擎
│   ├── llm_client.py         # LLM 集成（多模型）
│   ├── agents/               # Agent 定义（6个 Role + ChatAssistant）
│   ├── actions/              # Action 能力层
│   │   └── chat/             # AI 助手工具（30+ 个 Action）
│   ├── skills/               # Skills 体系
│   │   ├── packs/            # 内置技术规范
│   │   ├── marketplace/      # 市场目录（浏览用）
│   │   ├── use_skills/       # 系统已安装
│   │   └── rules/            # 全局编码规范
│   ├── sop/                  # SOP 工作流配置（YAML）
│   ├── api/                  # REST API（100+ 接口）
│   ├── ue_plugins/           # UE 插件（UCP）
│   └── knowledge_loader.py   # 知识库加载
├── frontend/
│   ├── index.html            # 页面结构
│   ├── app.js                # 应用逻辑（15000+ 行）
│   └── styles.css            # 样式
├── docs/                     # 设计文档 + 技术方案
└── dev-notes/                # 开发日志（含截图）
```

---

## 版本历史（近期）

| 版本 | 主要更新 |
|------|---------|
| v0.21 | AI 助手工具扩展（Shell/Glob/Grep/WebSearch 等 7 个工具）|
| v0.20 | UE MCP Phase 1-5 / Skills 市场双目录 / AI 助手流式统一 |
| v0.19 | UE 自动编译 + Playtest / UE Editor Viewport 截图 |
| v0.17 | Trait-First 动态 Skill 注入 / 多会话管理 |
| v0.16 | ChatAssistant 全面升级 / Skill 主动触发架构 |
| v0.15 | MetaGPT 移植（ActionNode / 状态机 / REACT 模式）|

详细变更见 [dev-notes/](dev-notes/) 目录。

---

## License

MIT
