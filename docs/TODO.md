# AI Dev System — 待办清单

> 最后更新: 2026-04-24

---

## ✅ v0.18 UE 深耕（已完成 2026-04-24）

7/8 Phase 完成 + 24/24 smoke 测试通过，详见 `dev-notes/2026-04-24_v0.18_完结总结.md`。
核心交付：UE 引擎检测 / 模板实例化 / UBT 编译 + 错误解析 / Reflexion 自动修复 /
Skill Packs / 项目 UE 配置持久化 / 对话式 UE 框架生成。

**下一主线待定**：候选方向见 `2026-04-24_v0.18_完结总结.md §9`：
- v0.19 `run_playtest` (headless UE + Automation Framework)
- v0.19 `generate_assets` + ArtistAgent
- v0.19 全局聊天串联"建项目 + 生成骨架"一键流
- v0.19+ action state 持久化消除所有确认卡片刷新后重复点击问题
- 跨平台 UE 引擎检测 (Mac/Linux)

---

## 🎯 上一主线：Trait-First 多项目类型支持（v0.17，已完成）

支持网页 / 客户端 / 游戏 / UE / Godot / Unity / 微信小程序等多种项目类型。从 flat enum 升级到**trait + preset 混合架构**，skill/SOP/agent/mcp 按 traits 动态组装。详见：

- `docs/20260423_01_项目类型分类体系与对话式识别方案.md`（trait 体系 + 对话式识别）
- `docs/20260423_02_TraitFirst动态组装方案.md`（SOP fragments 组合 + Preview API，**最终方案**）

**~14.5 天 roadmap，分 7 个 Phase**（A-F + C'）：

| Phase | 内容 | 估时 |
|---|---|---|
| A | DB 迁移 + trait_taxonomy + presets.yaml + confirm_project traits 必填 + 对话历史压缩 + preset 关键词推荐 | 2.5 天 |
| B | SkillLoader 三层过滤（inject_to + traits_match + paths）+ rules/global.md + 现有 4 个 skill 重构（加 vcs:git trait）+ Skill 分组特化压制 | 4.5 天 |
| C | SOP base+fragments 组合器 + Action/Agent 加 available_for_traits + ticket_type 维度 | 3.5 天 |
| C' | POST /api/projects/preview-assembly 只读端点 | 1 天 |
| D | ProjectTypeDetectorAction（导入链路自动探测）| 1.5 天 |
| E | 前端「项目特征」子 Tab（编辑 traits + 生效配置展示）| 1 天 |
| F | MCP 加 enabled_for_traits | 0.5 天 |

**推荐节奏**：A+B+C+C'（~11.5 天）一批跑通核心垂直切片，D+E+F（~3 天）二批补全。

**阻塞 / 并吞的 TODO 项**：
- 本栏目下方"ChatAssistantAgent 默认化"P2 → trait-first 里的 ChatAssistant 反问规则会一起实现
- 本栏目下方"前端 SOP 拖拽编辑器"P2 → trait-first 的 fragments 组合器是它的前置 + 替代
- 本栏目下方"DeployAgent 读项目类型"P2 → trait-first 落地后直接靠 traits 读取
- 本栏目下方"ArchitectAgent 缺 SOP 配置读取"P2 → fragments 组合器覆盖

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

| 优先级 | Agent | 问题 | 修复内容 | 状态 |
|--------|-------|------|---------|------|
| ✅ | ProductAgent 拆单 | 不看已有代码就拆单 | orchestrator 触发前注入 existing_files/code；AgentMemory.get_code_context() 复用 | **完成 2026-04-21** |
| ✅ | ReviewAgent | 完全盲审/从未被调用 | 抽成独立 SOP 阶段（dev → code_review → acceptance）+ CodeReviewAction 读实际代码 + ActionNode + SOP 配置；详见 `docs/20260421_03_盲审修复P0实现方案.md` | **完成 2026-04-21** |
| ✅ | DevAgent SelfTest | 不读 Git 仓库实际文件 | run() 开头预落盘 + check 6 磁盘落地验证；SOP `verify_disk_files` 开关；详见 `docs/20260422_02_SelfTest读Git实际文件.md` | **完成 2026-04-22** |
| P2 | DeployAgent | 不读代码，部署配置通用化 | 读取项目类型生成针对性部署配置 |
| P2 | ArchitectAgent | 缺 SOP 配置读取 | 使用 sop_config 中的参数 |

## 架构改进

| 优先级 | 项目 | 说明 |
|--------|------|------|
| P1 | 前端 SOP 拖拽编辑器 | 可视化编辑流程，不用手改 YAML |
| ✅ | **需求 Pipeline 可视化由 SOP 驱动** | **已完成 2026-04-17**：新增 `pipeline_view` 配置节 + `sop/loader.py:build_pipeline_stages()` 派生函数；消除 3 处硬编码（`api/requirements.py:283` 的 STAGE_DEFS/PAST/PRE + 观测 Action 的二次硬编码）。现在改流程只要改 yaml 一处，UI 和观测 Action 同步更新 |
| P2 | Memory 持久化索引 | cause_by 索引目前在内存，重启丢失 |
| P2 | 前端 Agent 配置页 | 可切换 ReactMode、启用/禁用 Action |
| P2 | **仓库文件显示 / diff 展示优化** | 文件浏览器：大文件截断策略 / 语法高亮对齐 / 二进制文件占位符；diff 视图：左右分栏 / 行级高亮 / 折叠未变化的大段 / 跳转相关文件 |
| P2 | **仓库分支管理页显示树形关系** | 当前分支列表是扁平平铺；改成展示 `feat/* → develop → main` 的父子树形 + 每分支的 ahead/behind 数 + 最近一次 commit，一眼看清分支结构 |
| 🔄 | **ChatAssistantAgent 默认化** | 已推进大半：v0.16.5 全局聊天也迁到 Agent + tool_use（详见 `docs/20260422_03_全局AI助手新建项目链路分析与Agent化方案.md`）。剩余：观察期后清理 `_global_chat_legacy` + `_parse_global_action` + `[ACTION:CREATE_PROJECT]` prompt 文本协议（~100 行代码） |
| ✅ | **ChatAssistant 观测能力** | **已完成 2026-04-17**：新增 `GetRequirementPipelineAction` / `GetTicketStatusAction` / `GetRequirementLogsAction` 三个 Action。AI 现在能回答"XX 卡在哪""最近发生了什么"，直接给出根因（例："被打回 5 次 → 强制通过"）而非猜测 |

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

## Bug 修复记录（已完成 16 个）

| 日期 | 问题 | 根因 | 修复 |
|------|------|------|------|
| 04-22 | 工单 AI 对话 `content.replace is not a function` | v0.15.2 后 tool_use 消息的 content 是 list of blocks 不是字符串 | 后端加 `_content_to_display_text` 展平 + 前端 `formatChatContent` 加类型兜底 (v0.16.4) |
| 04-22 | 属性面板点「AI 对话」关闭面板 | onclick 里有 closeDrawer() | 去掉 closeDrawer() 调用 (v0.16.4) |
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
