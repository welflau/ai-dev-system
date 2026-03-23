# AI 自动开发系统后端

## 技术栈
- Python 3.8+
- FastAPI (Web 框架)
- SQLite (数据持久化)
- OpenAI 兼容 API (LLM 引擎)
- SSE / sse-starlette (实时推送)
- pytest (92 个测试用例)

## 安装依赖

```bash
pip install -r requirements.txt
```

## 配置 LLM (可选)

```bash
cp .env.example .env
# 编辑 .env 填入 LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
```

## 运行开发服务器

```bash
python main.py
# 或
uvicorn main:app --reload --port 8000
```

## 访问地址

| 页面 | 地址 |
|------|------|
| 前端界面 | http://localhost:8000/app |
| API 文档 | http://localhost:8000/docs |
| 健康检查 | http://localhost:8000/health |

## 项目结构

```
backend/
├── agents/               # 6 个 AI Agent
│   ├── base.py           # BaseAgent 基类
│   ├── product.py        # ProductAgent (需求分析)
│   ├── architect.py      # ArchitectAgent (架构设计)
│   ├── dev.py            # DevAgent (代码生成)
│   ├── test_agent.py     # TestAgent (测试生成)
│   ├── review_agent.py   # ReviewAgent (代码审查)
│   └── deploy_agent.py   # DeployAgent (部署配置)
├── orchestrator/         # 协调器
│   ├── coordinator.py    # Orchestrator + ProductAgentAdapter
│   ├── decomposer.py     # TaskDecomposer (LLM + 规则引擎)
│   ├── state_manager.py  # StateManager 内存版
│   └── db_state_manager.py # DbStateManager SQLite 版
├── llm/                  # LLM 客户端 (OpenAI 兼容)
├── tools/                # 工具集成 (Git + 文件)
├── models/               # 数据模型 (Pydantic)
├── tests/                # 测试 (92 个用例)
├── projects/             # Agent 生成的项目输出
├── config.py             # 集中化配置
└── main.py               # FastAPI 主应用
```

## 运行测试

```bash
python -m pytest tests/ -v
```
