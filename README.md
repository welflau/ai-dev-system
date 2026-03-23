# AI 驱动的全自动软件开发系统

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-92%20passed-brightgreen.svg)](backend/tests/)
[![Version](https://img.shields.io/badge/version-v0.6.0-orange.svg)](ROADMAP.md)

> 用 AI 智能体协作，从自然语言需求到可运行软件的端到端自动化开发系统

## 🎯 项目愿景

**"一个大脑，多个智能体，全链自动执行"**

本系统旨在实现软件开发的全流程自动化：
- **输入**: 自然语言描述的需求
- **输出**: 可运行的软件 + 完整文档 + 测试用例 + 部署配置

## ✨ 核心特性

### 🧠 AI Orchestrator (协调器)
- 智能任务分解（LLM + 规则引擎双模式）
- 多 Agent 协同工作流编排
- Agent 间上下文自动传递
- SQLite 持久化状态管理

### 🤖 6 大智能体

| Agent | 能力 | 模式 |
|-------|------|------|
| **ProductAgent** | 需求分析、PRD 生成 | LLM + 模板降级 |
| **ArchitectAgent** | 系统架构设计（7 种方案） | LLM + 模板降级 |
| **DevAgent** | 代码生成（14 种任务处理器） | LLM + 模板降级 |
| **TestAgent** | pytest 测试用例生成 | LLM + 模板降级 |
| **ReviewAgent** | 代码审查（10 种规则 + 评分 A~F） | LLM + 规则引擎 |
| **DeployAgent** | Docker + CI/CD + Nginx 部署配置 | LLM + 模板降级 |

### 📊 可视化看板
- Pipeline 看板视图（需求→架构→开发→测试→部署）
- SSE 实时推送（替代轮询）
- 代码语法高亮预览（highlight.js）
- 项目文件浏览器
- 实时处理日志面板

### 🛠️ 工具集成层
- **Git**: 初始化、添加、提交、推送、分支管理
- **文件**: 读写、目录浏览
- **打包**: 项目 ZIP 一键下载

## 🏗️ 系统架构

```
用户自然语言需求
        ↓
[Orchestrator 协调器] — 任务分解 → 状态管理 → Agent 调度
        ↓
   Agent 池（上下文自动传递）
   ┌──────────┬──────────┬──────────┬──────────┬──────────┐
ProductAgent  ArchitectAgent  DevAgent  TestAgent  ReviewAgent  DeployAgent
   ↓              ↓           ↓          ↓          ↓           ↓
 PRD 文档      设计文档     代码文件    测试文件    审查报告    部署配置
                                                    ↓
                         SSE EventBus → 前端实时更新（Pipeline 看板）
```

## 🚀 快速开始

### 前置要求
- Python 3.8+
- pip

### 安装与启动

```bash
# 克隆仓库
git clone https://github.com/welflau/ai-dev-system.git
cd ai-dev-system

# 安装后端依赖
cd backend
pip install -r requirements.txt

# (可选) 配置 LLM
cp .env.example .env
# 编辑 .env 填入你的 API Key

# 启动服务
python main.py
```

### 访问系统

| 页面 | 地址 |
|------|------|
| 前端界面 | http://localhost:8000/app |
| API 文档 | http://localhost:8000/docs |
| 健康检查 | http://localhost:8000/health |

### 使用流程

1. 打开 http://localhost:8000/app
2. 点击 **"提交需求"** → 输入自然语言描述
3. 系统自动分解任务 → 在项目看板查看
4. 点击 **"一键执行"** → 系统自动完成需求分析、架构设计、代码生成、测试、审查、部署配置
5. 在 Pipeline 看板实时查看各阶段进度
6. 下载项目 ZIP 文件

### 运行测试

```bash
cd backend
python -m pytest tests/ -v   # 92 个测试全部通过
```

## 📁 项目结构

```
ai-dev-system/
├── backend/                      # 后端代码
│   ├── agents/                   # AI Agent 实现
│   │   ├── base.py               # BaseAgent 抽象基类
│   │   ├── product.py            # ProductAgent (需求分析)
│   │   ├── architect.py          # ArchitectAgent (架构设计)
│   │   ├── dev.py                # DevAgent (代码生成)
│   │   ├── test_agent.py         # TestAgent (测试生成)
│   │   ├── review_agent.py       # ReviewAgent (代码审查)
│   │   └── deploy_agent.py       # DeployAgent (部署配置)
│   ├── orchestrator/             # 协调器
│   │   ├── coordinator.py        # Orchestrator + ProductAgentAdapter
│   │   ├── decomposer.py         # TaskDecomposer (LLM + 规则引擎)
│   │   ├── state_manager.py      # StateManager 内存版
│   │   └── db_state_manager.py   # DbStateManager SQLite 版
│   ├── llm/                      # LLM 客户端
│   │   └── client.py             # LLMClient (OpenAI 兼容)
│   ├── models/                   # 数据模型
│   ├── tools/                    # 开发工具 (Git + 文件)
│   ├── tests/                    # 测试 (92 个用例)
│   ├── projects/                 # Agent 生成的项目输出
│   ├── config.py                 # 集中化配置 (Settings)
│   └── main.py                   # FastAPI 主应用入口
├── frontend/                     # 前端代码
│   ├── index.html                # 主页面 (含全部 CSS + HTML)
│   └── app.js                    # 应用逻辑 (路由/API/SSE/高亮)
├── .github/workflows/ci.yml      # GitHub Actions CI
├── ROADMAP.md                    # 开发路线图
└── DEVELOPMENT.md                # 详细开发文档
```

## 🛠️ 技术栈

### 后端
| 技术 | 说明 |
|------|------|
| FastAPI | Python 异步 Web 框架 |
| SQLite | DbStateManager 持久化 |
| OpenAI 兼容 API | LLM 引擎（支持 CodeBuddy/DeepSeek/Moonshot 等） |
| SSE (sse-starlette) | 实时事件推送 |
| pytest | 92 个测试用例 |

### 前端
| 技术 | 说明 |
|------|------|
| HTML5 / CSS3 / JavaScript | 纯原生实现，零依赖 |
| highlight.js (CDN) | 代码语法高亮 |
| EventSource | SSE 实时更新 |

## 📊 开发路线图

### ✅ 已完成

| 阶段 | 版本 | 主要功能 |
|------|------|---------|
| 基础框架搭建 | v0.1~v0.2 | ProductAgent + DevAgent + ArchitectAgent + 前端看板 |
| SQLite 持久化 | v0.3.0 | 数据持久化 + 一键执行 + 文件浏览器 |
| LLM 智能引擎 | v0.4.0 | 智能任务分解 + 智能代码生成 + 智能架构设计 |
| Agent 协作 | v0.5.0 | 上下文传递 + TestAgent + SSE 实时推送 + 语法高亮 |
| 质量 + 部署 | v0.6.0 | ReviewAgent + DeployAgent + ZIP 打包 + Pipeline 看板 |

### 🔜 开发中

| 阶段 | 版本 | 计划功能 |
|------|------|---------|
| 进阶功能 | v0.7.0 | 多 LLM 支持、项目模板系统、实时协作、Agent 自我进化 |

详细路线图见 [ROADMAP.md](ROADMAP.md)

## 🤝 贡献指南

我们欢迎任何形式的贡献！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'feat: add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

## 📄 开源协议

本项目采用 MIT 协议开源 - 查看 [LICENSE](LICENSE) 文件了解详情

## 📧 联系方式

- 作者: welflau
- GitHub: [@welflau](https://github.com/welflau)

## 🙏 致谢

- [FastAPI](https://fastapi.tiangolo.com/) - 现代化 Web 框架
- [highlight.js](https://highlightjs.org/) - 代码语法高亮
- [sse-starlette](https://github.com/sysid/sse-starlette) - SSE 实时推送
