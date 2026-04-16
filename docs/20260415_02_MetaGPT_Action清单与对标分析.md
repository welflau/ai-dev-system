# MetaGPT Action 清单与对标分析

> 日期: 2026-04-15 | 来源: D:\A_Works\MetaGPT\metagpt\actions\

---

## 一、MetaGPT Action 全览

MetaGPT 共 **42 个 Action**，覆盖软件开发全生命周期 + 数据分析 + 研究调研 + 教育等场景。

### 1.1 核心框架层（4 个）

| Action | 文件 | 说明 |
|--------|------|------|
| `Action` | action.py | Action 基类，所有 Action 继承此类 |
| `ActionNode` | action_node.py | 结构化输出节点（我们已移植） |
| `ActionGraph` | action_graph.py | Action 有向图编排 |
| `ActionOutput` | action_output.py | Action 输出包装器 |

### 1.2 需求分析（8 个）

| Action | 文件 | 说明 |
|--------|------|------|
| `UserRequirement` | add_requirement.py | 用户需求输入（无实现，纯标识） |
| `AnalyzeRequirementsRestrictions` | analyze_requirements.py | 需求约束分析与审查 |
| `WritePRD` | write_prd.py | 撰写产品需求文档 |
| `WritePRDReview` | write_prd_review.py | PRD 审查 |
| `WriteTRD` | requirement_analysis/trd/write_trd.py | 撰写技术需求文档 |
| `EvaluateTRD` | requirement_analysis/trd/evaluate_trd.py | 评审技术需求文档 |
| `DetectInteraction` | requirement_analysis/trd/detect_interaction.py | 检测系统交互关系 |
| `Pic2Txt` | requirement_analysis/requirement/pic2txt.py | 图片需求转文本 |

### 1.3 架构设计（4 个）

| Action | 文件 | 说明 |
|--------|------|------|
| `WriteDesign` | design_api.py | API 和系统架构设计 |
| `DesignReview` | design_api_review.py | 架构设计审查 |
| `WriteFramework` | requirement_analysis/framework/write_framework.py | 撰写技术框架方案 |
| `EvaluateFramework` | requirement_analysis/framework/evaluate_framework.py | 评审框架方案 |

### 1.4 项目管理（3 个）

| Action | 文件 | 说明 |
|--------|------|------|
| `WriteTasks` | project_management.py | 任务拆分和分配 |
| `ExecuteTask` | execute_task.py | 执行单个任务 |
| `PrepareDocuments` | prepare_documents.py | 初始化项目文件夹 + 文档准备 |

### 1.5 编码开发（7 个）

| Action | 文件 | 说明 |
|--------|------|------|
| `WriteCode` | write_code.py | 代码编写（核心） |
| `WriteCodeAN` | write_code_an_draft.py | 代码编写（ActionNode 版，结构化输出） |
| `WriteCodePlanAndChange` | write_code_plan_and_change_an.py | 先规划再改代码（增量修改） |
| `WriteCodeReview` | write_code_review.py | 代码审查 |
| `ValidateAndRewriteCode` | write_code_review.py | 验证并重写代码 |
| `SummarizeCode` | summarize_code.py | 代码摘要（提取关键信息） |
| `WriteDocstring` | write_docstring.py | 生成代码文档注释 |

### 1.6 测试调试（4 个）

| Action | 文件 | 说明 |
|--------|------|------|
| `WriteTest` | write_test.py | 生成测试用例 |
| `RunCode` | run_code.py | 运行代码并获取输出 |
| `DebugError` | debug_error.py | 分析错误并生成修复方案 |
| `FixBug` | fix_bug.py | 修复 Bug（标识类，无具体实现） |

### 1.7 代码理解（3 个）

| Action | 文件 | 说明 |
|--------|------|------|
| `RebuildClassView` | rebuild_class_view.py | 从代码重建类图（UML） |
| `RebuildSequenceView` | rebuild_sequence_view.py | 从代码重建时序图 |
| `ExtractReadMe` | extract_readme.py | 从仓库提取/生成 README |

### 1.8 联网研究（4 个）

| Action | 文件 | 说明 |
|--------|------|------|
| `CollectLinks` | research.py | 搜索引擎收集链接 |
| `WebBrowseAndSummarize` | research.py | 浏览网页并摘要 |
| `ConductResearch` | research.py | 综合调研（多轮搜索+总结） |
| `SearchEnhancedQA` | search_enhanced_qa.py | 搜索增强问答 |

### 1.9 数据分析 — Data Interpreter（5 个）

| Action | 文件 | 说明 |
|--------|------|------|
| `WritePlan` | di/write_plan.py | 撰写数据分析计划 |
| `WriteAnalysisCode` | di/write_analysis_code.py | 生成分析代码 |
| `ExecuteNbCode` | di/execute_nb_code.py | 执行 Notebook 代码 |
| `RunCommand` | di/run_command.py | 运行命令行 |
| `AskReview` | di/ask_review.py | 请求人工审查 |

### 1.10 其他场景（4 个）

| Action | 文件 | 说明 |
|--------|------|------|
| `TalkAction` | talk_action.py | 对话（聊天机器人） |
| `SkillAction` / `ArgumentsParingAction` | skill_action.py | 技能调用 + 参数解析 |
| `PrepareInterview` | prepare_interview.py | 面试准备 |
| `GenerateQuestions` | generate_questions.py | 生成深度提问 |
| `WriteTeachingPlanPart` | write_teaching_plan.py | 教学计划生成 |
| `WriteDirectory` / `WriteContent` | write_tutorial.py | 教程目录 + 内容生成 |
| `InvoiceOCR` / `GenerateTable` / `ReplyQuestion` | invoice_ocr.py | 发票 OCR + 表格生成 |

---

## 二、与我们的 Action 对标

### 2.1 当前对标

| 我们的 Action | MetaGPT 对标 | 差距 |
|--------------|-------------|------|
| `DesignArchitectureAction` | `WriteDesign` + `DesignReview` | MetaGPT 有独立审查，我们设计和审查混在一起 |
| `WriteCodeAction` | `WriteCode` + `WriteCodeAN` | MetaGPT 有 ActionNode 版和规划版两种模式 |
| `SelfTestAction` | `RunCode` + `WriteTest` | MetaGPT 分开跑代码和写测试，我们合在一起 |
| `AcceptanceReviewAction` | `WritePRDReview` | 类似，但 MetaGPT 的审查更系统化 |

### 2.2 我们缺失的 Action（可参考补充）

| MetaGPT Action | 对应能力 | 价值 | 优先级 |
|----------------|---------|------|--------|
| **`WriteCodePlanAndChange`** | 先规划改动范围再写代码 | 避免大范围无脑重写，精准增量 | P0 |
| **`WriteCodeReview`** | 独立代码审查（非验收） | 当前 ReviewAgent 盲审，需要改 | P0 |
| **`DebugError`** | 错误分析 + 修复方案 | 当前 fix_issues 只是重新开发，不分析原因 | P1 |
| **`CollectLinks` + `ConductResearch`** | 联网调研 | 对应计划中的 ResearchAgent | P1 |
| **`SummarizeCode`** | 代码摘要 | 给后续 Agent 传递精简上下文 | P2 |
| **`RebuildClassView`** | 从代码生成类图 | 导入已有项目时理解架构 | P2 |
| **`WritePRD`** | 正式 PRD 文档 | 当前拆单只有摘要，无正式 PRD | P2 |
| **`WriteTest` (独立)** | 独立测试用例生成 | 当前嵌在 TestAgent 里，不可复用 | P2 |
| **`WritePlan` (DI)** | 数据分析计划 | 对应 Phase 4 Data Interpreter | P3 |
| **`ExecuteNbCode` (DI)** | 执行 Notebook | 数据分析能力 | P3 |

### 2.3 对标覆盖率

```
MetaGPT 42 个 Action
  ├── 我们已有对标:  4 个（10%）
  ├── 计划中:        4 个（10%）— ResearchAgent / Data Interpreter
  ├── 值得补充:      6 个（14%）— CodeReview / Debug / Summarize / ClassView / PRD / Plan
  └── 场景不同:     28 个（66%）— 发票OCR / 教程 / 面试等非核心场景
```

---

## 三、补充路线图

### 短期（配合盲审修复）

| Action | 说明 | 对标 MetaGPT |
|--------|------|-------------|
| `CodeReviewAction` | 独立代码审查，读取实际代码 | `WriteCodeReview` |
| `DecomposeAction` | 需求拆单迁移到 ActionNode | `WriteTasks` |

### 中期（配合 Phase 3）

| Action | 说明 | 对标 MetaGPT |
|--------|------|-------------|
| `PlanCodeChangeAction` | 先规划再改代码（增量精准） | `WriteCodePlanAndChange` |
| `DebugErrorAction` | 分析错误日志，定位根因 | `DebugError` |
| `ResearchAction` | 联网搜索 + 竞品调研 | `CollectLinks` + `ConductResearch` |
| `SummarizeCodeAction` | 代码摘要（给下游 Agent 用） | `SummarizeCode` |

### 长期（配合 Phase 4）

| Action | 说明 | 对标 MetaGPT |
|--------|------|-------------|
| `WritePlanAction` | 数据分析计划 | `WritePlan` (DI) |
| `ExecuteCodeAction` | 执行代码并获取输出 | `RunCode` + `ExecuteNbCode` |
| `RebuildClassViewAction` | 从代码生成类图 | `RebuildClassView` |

---

## 四、MetaGPT Action 设计模式总结

### 模式 1: 标准 Action（调 LLM）
```python
class WriteCode(Action):
    async def run(self, *args):
        prompt = self._build_prompt(context)
        return await self._aask(prompt)
```
**特点**：简单直接，适合单次 LLM 调用。
**我们的对标**：Legacy 模式。

### 模式 2: ActionNode Action（结构化输出）
```python
class WriteCodeAN(Action):
    def __init__(self):
        self.node = ActionNode(key="code", expected_type=CodeOutput, ...)
    async def run(self, *args):
        return await self.node.fill(req=context, llm=self.llm)
```
**特点**：输出自动解析为 Pydantic 模型。
**我们的对标**：ActionNode 模式（已移植）。

### 模式 3: PlanAndChange（规划+执行）
```python
class WriteCodePlanAndChange(Action):
    async def run(self, *args):
        plan = await self._plan(context)       # 先规划改动
        for file in plan.files_to_change:
            await self._change_file(file)       # 逐文件修改
```
**特点**：不是一次性生成所有代码，而是先规划改哪些文件，再逐个修改。
**我们的差距**：当前 WriteCodeAction 一次性生成所有文件，无规划。

### 模式 4: Review（审查+重写循环）
```python
class WriteCodeReview(Action):
    async def run(self, *args):
        review = await self._review(code)       # 审查
        if review.has_issues:
            fixed = await self._rewrite(code, review)  # 重写
            return fixed
        return code
```
**特点**：审查和修复在同一个 Action 内循环，直到通过。
**我们的差距**：审查和修复分在不同 Agent，跨越多个 SOP 阶段。

### 模式 5: 联网研究（多步骤）
```python
class ConductResearch(Action):
    async def run(self, topic):
        links = await CollectLinks().run(topic)           # 收集链接
        summaries = await WebBrowseAndSummarize().run(links)  # 浏览摘要
        report = await self._synthesize(summaries)         # 综合报告
```
**特点**：Action 内部组合调用其他 Action。
**我们的差距**：Action 之间不互相调用，只通过 SOP 串联。

---

## 五、核心启示

### MetaGPT 做得好的
1. **Action 粒度细**：代码编写、审查、重写、摘要各自独立，可灵活组合
2. **PlanAndChange**：先规划再改，精准增量，不会全文件重写
3. **Review 循环**：审查+修复在 Action 内闭环，不用跑完整 SOP 流程
4. **Action 组合**：ConductResearch 内部调用 CollectLinks + Summarize

### 我们的优势
1. **SOP 编排**：Action 通过 YAML 配置串联，MetaGPT 硬编码在 Role 里
2. **持久化**：每个 Action 的输入输出都存数据库，可追溯
3. **质量门禁**：多层验收+测试+重试限制，MetaGPT 无此机制
4. **Git 集成**：Action 产出自动提交 Git，MetaGPT 写本地文件

### 最值得学的一件事
**`WriteCodePlanAndChange`** — 先规划改哪些文件、每个文件改什么，再逐个精准修改。解决我们"每次全文件重写"的根本问题。

---

*文档由 AI Dev System + Claude Code 基于 MetaGPT 源码分析生成*
