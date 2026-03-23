# AI驱动的全自动软件开发系统

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![React 18](https://img.shields.io/badge/react-18-61DAFB.svg)](https://reactjs.org/)

> 用AI智能体协作,从自然语言需求到可运行软件的端到端自动化开发系统

## 🎯 项目愿景

**"一个大脑,多个智能体,全链自动执行"**

本系统旨在实现软件开发的全流程自动化:
- 输入: 自然语言描述的需求
- 输出: 可运行的软件 + 完整文档 + 测试用例

## ✨ 核心特性

### 🧠 AI Orchestrator (协调器)
- 智能任务分解与依赖管理
- 多Agent协同工作流编排
- 状态管理和上下文共享
- 错误自愈与人工审批

### 🤖 多智能体体系

| Agent | 能力 |
|-------|------|
| **ProductAgent** | 需求分析、PRD生成、用户故事创建 |
| **ArchitectAgent** | 系统架构设计、技术栈选型、数据库/API设计 |
| **DevAgent** | 代码生成、重构、测试编写、Git操作 |
| **TestAgent** | 测试用例生成、执行、Bug分析、覆盖率分析 |
| **ReviewAgent** | 代码审查、安全扫描、性能优化 |
| **DeployAgent** | CI/CD配置、部署自动化 |

### 🛠️ 工具集成层
- **Git**: 自动创建仓库、分支管理、PR创建
- **CI/CD**: Jenkins、GitHub Actions集成
- **项目管理**: Jira、TAPD等工具对接
- **测试框架**: 自动化测试执行与报告

### 📊 可视化看板
- 实时项目进度追踪
- Agent工作日志展示
- Git提交统计与分析
- 构建状态与告警

## 🏗️ 系统架构

```
用户自然语言指令
        ↓
[AI 项目经理 & 协调员] — 任务分解、规划、调用工具、监控状态
        |
        |——— 调度与协调 ————
        |        |              |
        |        |              |
    [产品/需求代理]   [开发工程师代理]   [测试工程师代理] ...
        |        |              |
        |        |              |
[Git]  [云平台]  [项目管理工具]  [CI/CD]  [监控]  ← 工具集成层
        |
        ↓
    项目看板（全流程状态可视化）
```

## 🚀 快速开始

### 前置要求
- Python 3.10+
- Node.js 18+
- PostgreSQL 14+
- Redis 6+

### 安装

```bash
# 克隆仓库
git clone https://github.com/welflau/ai-dev-system.git
cd ai-dev-system

# 安装后端依赖
cd backend
pip install -r requirements.txt

# 安装前端依赖
cd ../frontend
npm install

# 启动服务
cd ../backend
python -m uvicorn main:app --reload

# 在另一个终端启动前端
cd frontend
npm start
```

### 使用示例

```python
# 1. 输入需求
user_input = """
我想开发一个个人博客系统,需要支持:
- Markdown文章编辑和预览
- 评论功能
- 标签分类
- 响应式设计
"""

# 2. AI自动处理
from orchestrator import Orchestrator

orchestrator = Orchestrator()
project_plan = await orchestrator.process_request(user_input)

# 3. 自动执行
await orchestrator.execute_plan(project_plan)

# 4. 查看结果
# - 完整的项目代码
# - 单元测试
# - API文档
# - 部署配置
```

## 📁 项目结构

```
ai-dev-system/
├── backend/                 # 后端服务
│   ├── orchestrator/        # 协调器
│   │   ├── decomposer.py    # 任务分解器
│   │   ├── coordinator.py   # 协调引擎
│   │   └── state_manager.py # 状态管理
│   ├── agents/              # 智能体
│   │   ├── base.py          # Agent基类
│   │   ├── product.py       # 产品代理
│   │   ├── architect.py     # 架构师代理
│   │   ├── dev.py           # 开发代理
│   │   └── test.py          # 测试代理
│   ├── tools/               # 工具集成
│   │   ├── registry.py      # 工具注册表
│   │   ├── git_tool.py      # Git工具
│   │   └── ci_cd_tool.py    # CI/CD工具
│   ├── api/                 # API接口
│   └── models/              # 数据模型
├── frontend/                # 前端应用
│   ├── src/
│   │   ├── components/      # 组件
│   │   ├── pages/           # 页面
│   │   └── services/        # API调用
│   └── package.json
├── docs/                    # 文档
│   ├── architecture.md      # 架构文档
│   ├── api.md               # API文档
│   └── development.md       # 开发指南
└── tests/                   # 测试
    ├── unit/
    ├── integration/
    └── e2e/
```

## 🛠️ 技术栈

### 后端
- **框架**: FastAPI
- **LLM**: DeepSeek-Coder / GPT-4
- **Orchestrator**: LangGraph
- **任务队列**: Celery + Redis
- **数据库**: PostgreSQL + SQLAlchemy
- **向量数据库**: Pinecone

### 前端
- **框架**: React 18
- **UI库**: Ant Design Pro
- **状态管理**: Zustand
- **HTTP客户端**: Axios
- **实时通信**: Socket.io

## 📊 开发路线图

### Phase 1: 基础框架 (1-2个月)
- [x] 项目初始化
- [ ] AI Orchestrator基础架构
- [ ] ProductAgent实现
- [ ] 简单Web界面

### Phase 2: 多Agent协同 (2-3个月)
- [ ] ArchitectAgent实现
- [ ] DevAgent实现
- [ ] TestAgent实现
- [ ] Git工具集成
- [ ] 完整看板系统

### Phase 3: 端到端自动化 (3-6个月)
- [ ] CI/CD集成
- [ ] ReviewAgent实现
- [ ] DeployAgent实现
- [ ] 错误自愈机制
- [ ] 生产环境部署

## 🤝 贡献指南

我们欢迎任何形式的贡献!

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

- [LangGraph](https://github.com/langchain-ai/langgraph) - Agent工作流编排
- [Ant Design Pro](https://pro.ant.design/) - 企业级前端解决方案
- [FastAPI](https://fastapi.tiangolo.com/) - 现代化Web框架

---

**注意**: 本项目目前处于早期开发阶段,API和架构可能会有较大变化。欢迎关注或参与贡献!
