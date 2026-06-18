---
name: refactor-audit
description: >-
  对指定范围的代码进行结构化审计并输出重构建议书。当用户请求代码审计、质量检查、重构建议、或输入'审计'、'review'、'代码质量'等关键词时触发。
user-invokable: true
metadata:
  pattern: reviewer
  version: "1.1.0"
  author: vibe-game-creator
  tags: [code-quality, audit, refactor]
---

# 代码重构审计

对指定范围的代码库进行系统化审计，输出结构化的「代码重构建议书」，并支持逐条应用修复。

## 使用方式

用户可通过以下方式触发：

| 输入示例 | 行为 |
|---------|------|
| `审计 apps/web/src/stores` | 聚焦扫描指定目录 |
| `全局审计` | 扫描 `apps/` + `packages/` 下所有包 |
| `审计 --dimension coupling` | 按维度筛选（见下方维度表） |
| `修复 [ID]` | 对建议书中的某一项生成修复代码 |

## 执行流程

### 第 1 步：确定扫描范围

如果用户未指定范围，主动询问：

> 请告诉我要审计的范围：
> 1. **全局** — 扫描 `apps/` + `packages/` 下所有包
> 2. **指定目录** — 例如 `apps/web/src/stores`、`apps/server/src/services`、`packages/shared-types/src`
> 3. **指定维度** — 例如「只看耦合问题」「只看类型安全」

### 第 2 步：读取项目规则

在开始审计前，**必须**读取以下规则文件作为审计基准：

- `.agents/rules/monorepo_guide.md` — 跨包边界、依赖方向、共享类型
- `.agents/rules/quality-typescript-coding.md` — TypeScript 编码准则
- `.agents/rules/quality-simplicity.md` — 简洁性原则
- `AGENTS.md` 中的 Architecture Constraints — 四层架构红线

### 第 3 步：执行审计

⚠️ 首次审计前，先加载 `references/gotchas.md` 了解常见误判场景（如测试代码、Vue SFC、type-only import 等），避免产出无效建议。

逐文件扫描目标范围，按以下 **6 个审计维度** 检查问题。加载 `modules/dimensions.md` 获取各维度的详细检查规则。

| 维度 | 代号 | 检查要点 |
|------|------|---------|
| 跨包耦合 | `coupling` | 违反依赖方向、私有路径引用、前端直接 import 后端 |
| 类型安全 | `type-safety` | any 逃逸、缺少 Zod 校验、共享类型未同步 |
| 状态管理 | `state` | 绕过 Pinia actions 直接修改 state、缺少 Service 层 |
| 代码重复 | `duplication` | ≥2 处重复逻辑未提取、工具函数内联在业务模块 |
| 复杂度 | `complexity` | 函数过长、嵌套过深、职责不单一 |
| 架构红线 | `redline` | 违反四层架构约束（前端调 LLM、绕过 Orchestrator 等） |

### 第 4 步：输出建议书并写入 CURRENT_PLAN.md

审计完成后需要完成**两件事**，加载 `modules/output-format.md` 获取完整模板和写入规范：

#### 4a. 在对话中输出完整建议书

按 `modules/output-format.md` 中的「对话输出模板」格式，在对话中展示完整的审计摘要、问题分布和详细任务单。

#### 4b. 将待办事项写入 CURRENT_PLAN.md

将审计发现的每条问题转化为 `CURRENT_PLAN.md` 中的待办事项，作为新的里程碑追加到文件中：

- 使用 `replace_in_file` 在 `CURRENT_PLAN.md` 的 `## ⚠️ 遗留待办` 之前插入新的里程碑章节
- 更新文件顶部的「当前状态」为活跃开发状态
- 待办格式严格使用 `- [ ]` checkbox 格式，方便后续逐条打勾
- 按 P0 → P1 → P2 优先级排序
- 每条待办包含 ID、模块路径、问题摘要和重构方向
- 详见 `modules/output-format.md` 中的「CURRENT_PLAN.md 写入模板」

### 第 5 步：应用修复（按需）

当用户输入 `修复 R-XXX` 时，**本步骤属于 `/execute` 开发执行阶段**，必须读取并遵循 `.agents/commands/execute.md` 中的完整流程（含单元测试维护、E2E 检查、验收文档同步）。

在 `/execute` 框架下，本 skill 负责以下代码修改步骤：
1. 定位对应任务的源文件
2. 按建议书中的重构方向生成代码变更
3. 使用 replace_in_file 精准修改，不重写整个文件
4. 修改完成后重新检查该文件，确保无新增 lint 错误

> 兼容别名：`apply fix for task R-XXX`、`fix R-XXX` 等英文指令同样生效。

## 严重程度定义

| 等级 | 含义 | 处理要求 |
|------|------|---------|
| **P0** | 违反架构红线或导致运行时故障 | 必须立即修复 |
| **P1** | 违反编码准则或影响可维护性 | 当前迭代内修复 |
| **P2** | 代码异味或优化建议 | 择机处理 |
