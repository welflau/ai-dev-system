# AI自动开发系统后端

## 技术栈
- Python 3.10+
- FastAPI (Web框架)
- LangGraph (Agent编排)
- SQLAlchemy (ORM)
- PostgreSQL (数据库)
- Redis (缓存和任务队列)
- Celery (异步任务处理)

## 安装依赖

```bash
pip install -r requirements.txt
```

## 运行开发服务器

```bash
uvicorn main:app --reload --port 8000
```

## 项目结构

```
backend/
├── orchestrator/      # 协调器
│   ├── decomposer.py  # 任务分解器
│   ├── coordinator.py # 协调引擎
│   └── state_manager.py
├── agents/           # 智能体
│   ├── base.py       # 基类
│   ├── product.py    # 产品代理
│   ├── architect.py  # 架构师代理
│   ├── dev.py        # 开发代理
│   └── test.py      # 测试代理
├── tools/           # 工具集成
│   ├── registry.py   # 工具注册表
│   ├── git_tool.py   # Git工具
│   └── file_tool.py  # 文件工具
├── api/             # API接口
│   └── routes/
├── models/          # 数据模型
├── utils/           # 工具函数
└── tests/           # 测试
```
