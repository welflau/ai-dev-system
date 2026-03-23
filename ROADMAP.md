# 开发计划

## 阶段一: 基础框架搭建 (MVP)

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

## 阶段二: 高级功能 (v0.3.0)

### 2.1 数据持久化
- [ ] SQLite 数据库替代内存存储
- [ ] 项目数据重启后不丢失
- [ ] 数据库迁移支持

### 2.2 执行体验升级
- [ ] 一键全量执行（自动依次执行所有任务直到完成）
- [ ] 任务执行结果展示（在前端展示 Agent 生成的代码内容）
- [ ] 执行日志实时滚动

### 2.3 项目文件管理
- [ ] 项目文件浏览器（查看 Agent 生成的文件树）
- [ ] 代码预览（语法高亮）
- [ ] 项目打包下载（ZIP）

### 2.4 前端体验优化
- [ ] 版本升级到 v0.3.0
- [ ] 深色模式 / 主题切换
- [ ] 任务执行动画效果

---

## 当前进度: 阶段二开发中

### 阶段一总结 ✅
- **51个测试全部通过** (8 工具 + 21 协调器 + 22 Agent/集成)
- **DevAgent**: 基于模板的代码生成，支持 14 种任务
- **ArchitectAgent**: 基于模板的架构设计，支持 7 种方案
- **Orchestrator**: 集成 Agent 池，execute_task 调用真正的 Agent 执行
- **前端**: 6 个页面 (首页/提交/看板/详情/工具/指引)
