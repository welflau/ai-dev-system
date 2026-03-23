# 开发计划

## 阶段一: 基础框架搭建 (MVP) ✅

### 1.1 后端基础架构 ✅
- [x] 创建项目目录结构
- [x] 配置Python依赖(requirements.txt, requirements-mvp.txt)
- [x] 实现基础数据模型(schemas.py, enums.py)
- [x] 实现工具注册表(registry.py)
- [x] 实现文件操作工具(file_tool.py)
- [x] 实现Git操作工具(git_tool.py)
- [x] 实现Agent基类(base.py)
- [x] 实现ProductAgent(product.py)
- [x] 创建FastAPI主应用(main.py)
- [x] 添加测试用例(test_tools.py)

### 1.2 前端基础架构 ✅
- [x] 创建前端项目(纯 HTML/CSS/JavaScript)
- [x] 实现基础布局组件(侧边栏、主内容区)
- [x] 实现需求提交页面
- [x] 实现项目看板页面
- [x] 实现工具列表页面
- [x] 集成后端 API

### 1.3 核心模块实现 ✅
- [x] Task Decomposer (任务分解器) - 基于关键词匹配的规则引擎
- [x] State Manager (状态管理器) - 内存版项目/任务状态管理
- [x] Orchestrator (协调器) - 串联分解、状态管理、任务执行
- [x] 前端升级 - 项目详情页、阶段进度条、任务列表展示
- [x] 协调器单元测试 (test_orchestrator.py) - 21个测试用例
- [x] 后端 API 升级至 v0.2.0 - 完整的项目管理接口

### 1.4 Agent实现(基础版) ✅
- [x] ProductAgent - 需求分析（框架已实现，需接入LLM）
- [x] DevAgent - 代码生成（基于模板引擎，14 种任务处理器）
- [x] ArchitectAgent - 架构设计（基于模板引擎，7 种设计方案）
- [x] Orchestrator 集成 Agent 执行（execute_task / execute_next_task）

### 1.5 工具集成 ✅
- [x] Git工具 (init, add, commit, push, create_branch)
- [x] 文件读写工具 (writer, reader, directory_lister)

### 1.6 测试和文档 ✅
- [x] 工具单元测试 (8个用例)
- [x] 协调器单元测试 (21个用例)
- [x] Agent 单元测试 (17个用例: DevAgent 10 + ArchitectAgent 7)
- [x] 集成测试 (5个用例: Orchestrator + Agent 端到端)
- [x] API文档 (FastAPI自动生成)
- [x] 开发文档 (DEVELOPMENT.md)

---

## 阶段二: SQLite 持久化 + 体验升级 (v0.3.0) ✅

### 2.1 SQLite 持久化 ✅
- [x] DbStateManager - SQLite 数据库替代内存存储
- [x] 项目/任务/日志数据重启后不丢失
- [x] 与内存版 StateManager 相同接口，无缝切换
- [x] 17 个专属测试全部通过

### 2.2 执行体验升级 ✅
- [x] 一键全量执行 (/api/projects/{id}/execute-all)
- [x] 自动依次执行所有 pending 任务直到完成
- [x] 前端增加 ⚡ 一键全量执行按钮

### 2.3 项目文件管理 ✅
- [x] 项目文件浏览器 (API: 列出文件树 + 读取文件内容)
- [x] 代码预览（深色主题）
- [x] 路径安全检查（防目录穿越）

### 2.4 前端体验优化 ✅
- [x] 版本升级到 v0.3.0
- [x] 使用指引页面（快速上手 + FAQ + API 一览）

---

## 阶段三: LLM 智能引擎 (v0.4.0) ✅

### 3.1 LLM 客户端层 ✅
- [x] LLMClient 类 (backend/llm/client.py)
- [x] 同步: generate(), chat(), chat_with_tools(), stream()
- [x] 异步: agenerate(), achat(), astream()
- [x] OpenAI 兼容 API 格式（支持 CodeBuddy/DeepSeek/Moonshot 等）
- [x] 自动降级: LLM 不可用时返回 [LLM_UNAVAILABLE]

### 3.2 集中化配置管理 ✅
- [x] Settings 类 (backend/config.py)
- [x] 环境变量: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
- [x] .env 文件支持（.gitignore 已忽略）

### 3.3 智能任务分解 ✅
- [x] LLM 模式: 自然语言需求 → JSON 任务列表
- [x] 规则引擎降级方案（原关键词匹配逻辑保留）

### 3.4 智能架构设计 ✅
- [x] 每个设计方法支持 LLM 生成 + 模板降级双模式

### 3.5 智能代码生成 ✅
- [x] 无匹配 handler 时自动尝试 LLM 生成多文件代码

### 3.6 前端 LLM 配置面板 ✅
- [x] API 端点: GET /api/llm/status, POST /api/llm/test, POST /api/llm/config
- [x] 前端配置页面 + 连接测试

---

## 阶段四: Agent 协作 + 实时推送 (v0.5.0) ✅

### 4.1 Agent 间上下文传递 ✅
- [x] Orchestrator 维护 _project_context 缓存
- [x] ArchitectAgent 输出 → DevAgent 上下文（设计文档驱动代码生成）
- [x] DevAgent 输出 → TestAgent 上下文（已有代码驱动测试生成）
- [x] 自动收集已生成文件列表（避免重复生成）

### 4.2 TestAgent 实现 ✅
- [x] LLM 模式：根据已有代码智能生成 pytest 测试
- [x] 模板降级：conftest.py + 模块测试 + pytest.ini
- [x] 读取项目代码文件供 LLM 参考

### 4.3 ProductAgent 接入 ✅
- [x] ProductAgentAdapter 同步适配器（桥接原 async 接口）
- [x] LLM 模式：智能需求分析 + PRD 生成
- [x] 模板降级：关键词提取 + 基础 PRD 文档

### 4.4 DevAgent 增强 ✅
- [x] _llm_generate_code 注入架构设计上下文
- [x] 注入已有文件列表（避免重复生成）

### 4.5 SSE 实时推送 ✅
- [x] EventBus 事件总线（支持多客户端订阅）
- [x] /api/projects/{id}/events SSE 端点
- [x] 前端 EventSource 订阅（替代 8 秒轮询）
- [x] 心跳保活 + 自动重连
- [x] Toast 通知系统

### 4.6 代码语法高亮 ✅
- [x] highlight.js 集成（CDN 加载）
- [x] 自动语言检测（Python/JS/HTML/CSS/JSON 等）
- [x] 文件类型标签显示

---

## 阶段五: 质量 + 部署 (v0.6.0) 🔜

### 5.1 ReviewAgent 实现
- [ ] 代码审查 Agent（代码规范检查、安全漏洞扫描）
- [ ] LLM + 规则引擎双模式

### 5.2 DeployAgent 实现
- [ ] 部署 Agent（Dockerfile + docker-compose 生成）
- [ ] CI/CD 配置生成

### 5.3 项目打包下载
- [ ] ZIP 打包项目文件
- [ ] 一键下载按钮

### 5.4 多 LLM 支持
- [ ] 不同 Agent 可配置不同 LLM
- [ ] 模型性能对比

### 5.5 更多测试
- [ ] TestAgent 单元测试
- [ ] ProductAgentAdapter 单元测试
- [ ] SSE 端点集成测试
- [ ] 端到端测试 (E2E)
