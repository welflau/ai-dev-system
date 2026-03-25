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

## 阶段五: 质量 + 部署 (v0.6.0) ✅

### 5.1 ReviewAgent 实现 ✅
- [x] 代码审查 Agent（代码规范检查、安全漏洞扫描）
- [x] LLM + 规则引擎双模式
- [x] 10 种审查规则（SEC-001~003、PY-001~005、STYLE-001、DOC-001）
- [x] Markdown 审查报告生成（评分 A~F）

### 5.2 DeployAgent 实现 ✅
- [x] 部署 Agent（Dockerfile + docker-compose 生成）
- [x] CI/CD 配置生成（GitHub Actions）
- [x] Nginx 反向代理配置（自动检测前端）
- [x] 部署文档自动生成
- [x] 项目结构智能分析（技术栈、数据库、前端检测）

### 5.3 项目打包下载 ✅
- [x] ZIP 打包项目文件
- [x] 一键下载按钮（前端）
- [x] API 端点 GET /api/projects/{id}/download

### 5.4 更多测试 ✅
- [x] TestAgent 单元测试（4 个）
- [x] ReviewAgent 单元测试（7 个）
- [x] DeployAgent 单元测试（7 个）
- [x] ProductAgentAdapter 单元测试（6 个）
- [x] 共计 92 个测试全部通过

---

## 阶段六: 工单管理系统 (v0.7.0) ✅

### 6.1 类 TAPD 工单管理系统 ✅
- [x] 从 Pipeline 模式升级为三级工单模型：需求单 → 任务单 → 子任务
- [x] 工单状态机（13 种工单状态 + 6 种需求状态）
- [x] Agent 接单/流转/日志追溯
- [x] 5 列看板视图（待办→进行中→待审查→待测试→已完成）

### 6.2 后端架构重写 ✅
- [x] 单文件模块架构（models.py, orchestrator.py, llm_client.py, database.py, events.py, utils.py）
- [x] 6 张数据表：projects, requirements, tickets, subtasks, ticket_logs, artifacts
- [x] 旧 v0.6.0 遗留文件全部清理（26 文件，6477 行删除）

### 6.3 前端 SPA 重写 ✅
- [x] 完整 SPA 前端（app.js ~600 行）：项目管理、需求提交、看板、工单详情抽屉
- [x] SSE 实时推送集成

---

## v0.7.1: LLM 会话日志 + 产出文件展示 ✅

- [x] 新增 llm_conversations 表（7 张表总计）
- [x] llm_client.py: chat() 自动记录会话（prompt/response/tokens/耗时）
- [x] set_llm_context() / clear_llm_context() 关联工单/需求
- [x] 新增 API: GET /tickets/{id}/llm-logs, /requirements/{id}/llm-logs, /tickets/{id}/artifacts, /requirements/{id}/artifacts
- [x] Pipeline Job 面板 3 个 Tab: 📋日志 / 🤖AI对话 / 📦产出文件
- [x] AI 对话 Tab: 展示完整 prompt/response + tokens/耗时/model/状态
- [x] 产出文件 Tab: 文件类型 icon/名称/文件列表展开
- [x] 工单详情抽屉: 产物增加文件列表 + 类型标签

---

## 阶段七: Git 仓库集成 (v0.8.0) ✅

### 7.1 Git 操作管理器 ✅
- [x] 新增 git_manager.py: 异步 Git 操作（init/write/commit/push/log/tree/diff）
- [x] 通过 asyncio.create_subprocess_exec 调用 git CLI（不依赖 GitPython）
- [x] 项目仓库路径: backend/projects/<project_id>/
- [x] 标准目录结构: src/api/, src/models/, src/services/, src/utils/, tests/, docs/, config/, build/

### 7.2 Agent 文件输出改造 ✅
- [x] 6 个 Agent 全部改造返回 files 字典：包含真实文件内容（代码/文档/配置）
- [x] Orchestrator 集成 GitManager：Agent 执行后自动写文件 + commit + push

### 7.3 命令记录 + 前端增强 ✅
- [x] 新增 ticket_commands 表（8 张表总计），记录每步执行命令
- [x] projects 表新增 git_repo_path / git_remote_url 字段
- [x] 创建项目时自动初始化 Git 仓库
- [x] 新增 10 个 API 端点：git/tree, git/log, git/file, git/diff, git/remote, commands
- [x] 前端 Job 抽屉新增第 4 个 Tab: ⚙️配置（执行命令列表，类蓝盾 CI 配置视图）
- [x] 前端侧栏新增 📂仓库文件浏览（文件树 + 文件内容查看 + Git 日志）

---

## 阶段八: AI 聊天面板 (v0.9.0) ✅

### 8.1 聊天面板 UI ✅
- [x] 右侧聊天面板（可折叠/展开，grid 三栏布局）
- [x] 模式切换栏（全局对话 / 工单对话）
- [x] 聊天消息支持简单 Markdown 格式化（代码块/行内代码/加粗）

### 8.2 全局对话模式 ✅
- [x] 用户与 AI 自由对话，LLM 带项目上下文（需求状态 + 工单概况）
- [x] 指令解析: AI 回复中提取 [ACTION:CREATE_REQUIREMENT] 自动创建需求

### 8.3 工单对话模式 ✅
- [x] 选中工单加载该工单的 AI 对话历史（来自 llm_conversations 表）
- [x] 工单抽屉新增 '💬 AI 对话' 按钮，联动聊天面板

### 8.4 后端支持 ✅
- [x] 新增 api/chat.py: 3 个端点（POST chat, GET history, GET ticket conversations）
- [x] 新增 chat_messages 表（9 张表总计）

---

## 阶段九: 沙箱执行 + 真实验证 (v1.0.0) 🔜

> **核心目标**：让整条流水线从"纯 LLM 文本审查"升级为"真实代码执行验证"。
> 当前 v0.9.0 的所有 Agent（ProductAgent 验收、TestAgent 测试）都是纯 LLM prompt 文本审查，
> 没有实际编译/构建/运行代码。v1.0 要解决这个根本性问题。

### 9.1 沙箱执行环境 🔜
- [ ] Docker 沙箱容器：为每个项目创建隔离的执行环境
- [ ] 支持多语言运行时（Python / Node.js / Go）
- [ ] 安全隔离：网络限制、资源限额、超时控制
- [ ] 沙箱生命周期管理（创建 → 执行 → 清理）

### 9.2 构建验证 🔜
- [ ] DevAgent 代码提交后自动触发构建验证
- [ ] Python 项目：pip install + import 检查 + 语法校验
- [ ] 前端项目：npm install + 构建检查
- [ ] 构建失败自动打回 DevAgent 返工（附带错误日志）

### 9.3 ProductAgent 验收升级 🔜
- [ ] **真实验收**替代纯文本审查：在沙箱中启动服务 → 调用 API → 验证响应
- [ ] 前端功能：截图对比 / Playwright 自动化验证
- [ ] 验收报告附带实际运行证据（HTTP 响应、截图、日志）
- [ ] 保留 LLM 辅助审查作为补充（审查代码质量、文档完整性）

### 9.4 TestAgent 测试升级 🔜
- [ ] **真实执行 pytest**：在沙箱中实际运行 DevAgent 生成的测试用例
- [ ] 冒烟测试：启动服务 → 发送 HTTP 请求 → 验证状态码和响应
- [ ] 单元测试：subprocess 执行 `python -m pytest` 并解析结果
- [ ] 测试覆盖率报告（coverage.py 集成）
- [ ] 替换当前硬编码桩实现（_smoke_test / _unit_test 永远返回 True）

### 9.5 返工循环控制 🔜
- [ ] 验收/测试打回增加最大重试次数（默认 3 次）
- [ ] 超过重试次数自动升级为人工介入（状态 → needs_human_review）
- [ ] 每轮返工附带上一轮的完整错误上下文（而非仅文字描述）

### 9.6 执行日志增强 🔜
- [ ] 沙箱执行的 stdout/stderr 实时推送到前端
- [ ] 构建/测试过程的进度条展示
- [ ] 执行命令的完整时间线视图

---

## 阶段十: 进阶功能 (v1.1.0+) 📋

### 10.1 多 LLM 支持
- [ ] 不同 Agent 可配置不同 LLM
- [ ] 模型性能对比（成本/质量/速度）

### 10.2 项目模板系统
- [ ] 预置项目模板（Web API、全栈应用、CLI 工具等）
- [ ] 自定义模板创建

### 10.3 实时协作
- [ ] WebSocket 双向通信
- [ ] 多用户同时操作

### 10.4 Agent 自我进化
- [ ] 执行历史分析
- [ ] 自适应提示词优化
- [ ] 成功/失败模式学习

### 10.5 CI/CD 集成
- [ ] 对接 GitHub Actions / GitLab CI
- [ ] 自动触发外部 CI 流水线
- [ ] 部署状态回写到工单
