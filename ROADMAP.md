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

### 1.4 Agent实现(基础版)
- [x] ProductAgent - 需求分析（框架已实现，需接入LLM）
- [ ] DevAgent - 代码生成
- [ ] ArchitectAgent - 架构设计

### 1.5 工具集成 ✅
- [x] Git工具 (init, add, commit, push, create_branch)
- [x] 文件读写工具 (writer, reader, directory_lister)

### 1.6 测试和文档
- [x] 工具单元测试 (8个用例)
- [x] 协调器单元测试 (21个用例)
- [ ] API集成测试
- [x] API文档 (FastAPI自动生成)
- [ ] 开发文档

---

## 当前进度: 1.3 核心模块实现 ✅

### 里程碑总结
- **29个测试全部通过**
- **后端 v0.2.0**: Orchestrator + TaskDecomposer + StateManager 完整实现
- **前端 v0.2**: 项目详情页、阶段进度、任务分解展示
- **任务分解**: 支持 API/数据库/前端/用户/登录 5大关键词匹配
- **状态管理**: 项目生命周期、任务状态流转、阶段自动推进

### 下一步: 1.4 Agent实现
