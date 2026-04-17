# AI Dev System — 待办清单

> 最后更新: 2026-04-17

---

## Action 池扩充（参考 MetaGPT 42 个 Action，当前 4 个）

### 短期 P0（配合盲审修复）

| Action | 说明 | 对标 MetaGPT | 状态 |
|--------|------|-------------|------|
| `CodeReviewAction` | 独立代码审查，读取实际代码内容 | `WriteCodeReview` | 待开发 |
| `DecomposeAction` | 需求拆单迁移到 ActionNode | `WriteTasks` | 待开发 |

### 中期 P1（配合 Phase 3）

| Action | 说明 | 对标 MetaGPT | 状态 |
|--------|------|-------------|------|
| `PlanCodeChangeAction` | 先规划改哪些文件再逐个修改（解决全文件重写） | `WriteCodePlanAndChange` | 待开发 |
| `DebugErrorAction` | 分析错误日志，定位根因，生成修复方案 | `DebugError` | 待开发 |
| `ResearchAction` | 联网搜索 + 竞品调研 | `CollectLinks` + `ConductResearch` | 待开发 |
| `SummarizeCodeAction` | 代码摘要（给下游 Agent 传精简上下文） | `SummarizeCode` | 待开发 |

### 长期 P2（配合 Phase 4）

| Action | 说明 | 对标 MetaGPT | 状态 |
|--------|------|-------------|------|
| `WritePRDAction` | 正式 PRD 文档生成 | `WritePRD` | 待开发 |
| `RebuildClassViewAction` | 从代码生成类图（导入项目用） | `RebuildClassView` | 待开发 |
| `WritePlanAction` | 数据分析计划 | `WritePlan` (DI) | 待开发 |
| `ExecuteCodeAction` | 执行代码并获取输出 | `RunCode` + `ExecuteNbCode` | 待开发 |
| `WriteTestAction` | 独立测试用例生成（从 TestAgent 抽离） | `WriteTest` | 待开发 |
| `DesignReviewAction` | 架构设计审查 | `DesignReview` | 待开发 |

---

## ActionNode 迁移（MetaGPT 移植未完成）

| 优先级 | Agent | 当前状态 | 待办 |
|--------|-------|---------|------|
| ✅ | ArchitectAgent | ActionNode + Watch | 已完成 |
| ✅ | DevAgent | ActionNode + BY_ORDER + Watch | 已完成 |
| ✅ | ProductAgent 验收 | ActionNode + Watch + SOP config | 已完成 |
| P1 | **ProductAgent 拆单** | legacy，手动 json.loads | 迁移到 ActionNode + DecomposeOutput Schema |
| P1 | **TestAgent** | legacy，无 ActionNode | 迁移核心逻辑到 Action + ActionNode |
| P2 | **ReviewAgent** | legacy，完全盲审 | 迁移到 ActionNode + 读取实际代码 |
| P2 | **DeployAgent** | legacy | 迁移到 ActionNode |
| P2 | **REACT 模式** | 预留接口，等同 BY_ORDER | 实现 LLM 动态选择下一步 Action |

## 盲审修复

| 优先级 | Agent | 问题 | 修复内容 |
|--------|-------|------|---------|
| P0 | ProductAgent 拆单 | 不看已有代码就拆单 | 注入 existing_files/code，拆单时参考已有架构 |
| P0 | ReviewAgent | 完全盲审，不读代码 | 读取实际代码内容 + ActionNode + SOP 配置 |
| P1 | DevAgent SelfTest | 不读 Git 仓库实际文件 | 检查仓库中文件而非只看内存 files |
| P2 | DeployAgent | 不读代码，部署配置通用化 | 读取项目类型生成针对性部署配置 |
| P2 | ArchitectAgent | 缺 SOP 配置读取 | 使用 sop_config 中的参数 |

## 架构改进

| 优先级 | 项目 | 说明 |
|--------|------|------|
| P1 | 前端 SOP 拖拽编辑器 | 可视化编辑流程，不用手改 YAML |
| P1 | **需求 Pipeline 可视化由 SOP 驱动** | 当前 Pipeline UI 的 5 阶段在 `api/requirements.py:283` 硬编码 `STAGE_DEFS`，与 `sop/default_sop.yaml` 的 6 阶段不挂钩。改 SOP 不会自动更新 UI。需新增"Pipeline 聚合规则"配置（哪些 SOP 阶段合并成哪个 UI 分组、首尾补哪些非 SOP 阶段如"需求分析"/"合入 Develop"），让 STAGE_DEFS 动态从 SOP+规则生成 |
| P2 | Memory 持久化索引 | cause_by 索引目前在内存，重启丢失 |
| P2 | 前端 Agent 配置页 | 可切换 ReactMode、启用/禁用 Action |
| P2 | **ChatAssistantAgent 默认化** | P2 已引入（`CHAT_USE_AGENT` flag 双轨），P3/P4 阶段将其切为默认并清理旧 `[ACTION:XXX]` 文本协议（详见 `docs/20260417_01_ChatAssistant_Agent化迁移方案.md`） |

## Phase 3: v0.15 — 智能增强

| 优先级 | 版本 | 内容 | 状态 |
|--------|------|------|------|
| P0 | v0.15.0 | 多 LLM 支持（Ollama + 降级链） | 待开发 |
| P1 | v0.15.1 | 并发调度（多工单并行） | 待开发 |
| P1 | v0.15.2 | ResearchAgent 竞品分析 | 待开发 |
| P2 | v0.15.3 | 前端 SOP 拖拽编辑器 | 待开发 |

## Phase 4: v0.16 — 平台化

| 优先级 | 版本 | 内容 | 状态 |
|--------|------|------|------|
| P1 | v0.16.0 | 插件市场 | 待开发 |
| P2 | v0.16.1 | 多项目协作 | 待开发 |
| P2 | v0.16.2 | Data Interpreter | 待开发 |

## Bug 修复记录（已完成 14 个）

| 日期 | 问题 | 根因 | 修复 |
|------|------|------|------|
| 04-15 | 工单卡在 success 状态 | ActionResult.to_dict() 覆盖 data 中的 status | 不覆盖已有 status |
| 04-15 | 验收死循环 53 次 | BY_ORDER files 覆盖 + 盲审 | 修 files 合并 + 加 max_retries 5 |
| 04-15 | 产出文件在仓库找不到 | BY_ORDER 后续 Action 覆盖前面的 files | pop files 后再 update |
| 04-15 | 验收说缺 index.html 但实际存在 | 验收只看 dev_result 不看仓库 | 传入 existing_files + code |
| 04-15 | 需求创建卡片不显示 | JSON 中文引号/未转义双引号解析失败 | _try_fix_json 三策略修复 |
| 04-15 | 截图路径错误 | MD 中用完整路径而非相对路径 | 改为 screenshots/xxx.png |
| 04-15 | 截图不生成 | Playwright 浏览器未安装 + 文件未落盘 | Chrome headless 兜底 + flush_files |
| 04-15 | MD 预览不显示图片 | 仓库文件浏览器不支持图片渲染 | file-raw API + 相对路径自动转换 |
| 04-14 | 分支没创建 | subtasks 字符串/dict 格式不兼容 | 兼容两种格式 |
| 04-14 | LLM 返回截断 | max_tokens=4096 不够 | 提升到 16000 + 精简 prompt |
| 04-14 | CI lint 失败 | orchestrator 缺 pathlib.Path import | 添加 import |
| 03-30 | 删除项目失败 | ci_builds 未级联删除 + DB locked | 加 ci_builds 删除 + busy_timeout |
| 03-30 | llm_conversations ticket_id 为 NULL | 全局单例 context 并发覆盖 | 改用 contextvars |
| 03-30 | 代码生成废模板 | fallback 生成中文类名空壳 | 改为可运行的 index.html |

## 新功能想法

- ReportAgent：每日自动汇总项目进展生成日报
- 安全扫描 Agent：检查代码安全漏洞
- 性能测试 Agent：页面加载速度、API 响应时间
- 数据库迁移路径更新工具：换机器时批量更新 git_repo_path

---

*待办清单由 AI Dev System 团队维护*
