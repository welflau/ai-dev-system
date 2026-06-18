---
name: code-review
description: >-
  代码评审技能，提供架构红线检查、AST 安全校验、SSE 通信规范、Zod schema 验证等评审维度。
  当 `/review` 命令需要加载评审清单、执行 Fix-First 三级处理、或输出分级报告时触发。
user-invokable: false
metadata:
  pattern: "composite[reviewer + pipeline]"
  version: "1.0.0"
  author: vibe-game-creator
  tags: [review, code-quality, architecture, checklist]
---

# Code Review — 代码评审技能

> 本 skill 为 `/review` 命令提供评审清单和 Fix-First 处理流程。不直接面向用户调用，
> 由 `/review` 命令在 Step 2 加载。

---

## Iron Law

**NO REVIEW WITHOUT EVIDENCE.** 不说"probably tested"或"likely handled"——要么引用
具体代码行证明安全，要么标记为 unverified。

---

## Pipeline: 评审流程

### Step 1: 加载评审清单

加载 `references/checklist.md`，获取四大维度的检查项。

**如果文件不存在，STOP 并报告错误。** 不得无清单评审。

### Step 2: Two-Pass 评审

对 diff 执行两轮检查：

**Pass 1 — CRITICAL（阻塞级）**：

| 维度 | 检查焦点 |
|------|---------|
| L1~L4 边界 | 前端是否直接调用 LLM？Agent 是否绕过 Orchestrator？DB 操作是否绕过 db 层？ |
| AST 安全校验 | AI 生成代码是否经过 AST 校验？是否有 eval/Function 构造器？ |
| SSE 通信规范 | SSE 事件格式是否正确？错误处理是否完整？断线重连是否实现？ |
| 竞态条件 | 共享状态是否有竞态？异步操作是否有序？ |
| 数据安全 | 用户输入是否经过验证？Zod schema 是否覆盖边界？ |

**Pass 2 — INFORMATIONAL（建议级）**：

| 维度 | 检查焦点 |
|------|---------|
| Zod Schema | 跨包类型是否使用 Zod 定义？parse 是否在边界处调用？ |
| Vue 组件规范 | 是否使用 Composition API？是否遵循 Pinia 状态管理？ |
| 魔法数字 / 硬编码 | 是否有未提取的常量或硬编码字符串？ |
| 死代码 | diff 中是否引入了未使用的导入、函数或变量？ |
| 测试缺口 | 新功能是否缺少对应测试？修复是否缺少回归测试？ |
| 文档陈旧 | 代码变更是否导致文档（`docs/arch/`、`README.md` 项目结构、`AGENTS.md` 架构表述等）过期？ |

**Enum 完整性检查（需读取 diff 之外的代码）**：当 diff 引入新的枚举值、状态常量或类型
时，使用搜索工具查找所有引用同类值的文件，确认新值是否被处理。

### 🚧 Gate: 评审完成

> 在进入 Fix-First 流程之前，必须满足以下条件：
> - [ ] Pass 1 和 Pass 2 均已完成
> - [ ] 每个发现都有证据（代码行引用或日志）
> - [ ] 不存在"probably"/"likely"等未验证断言
>
> **未满足时**：回去补充证据，不得跳过。

---

### Step 3: Fix-First 三级处理

每个发现必须获得处理——不只是报告。

#### 分类规则

| 级别 | 条件 | 处理方式 |
|------|------|---------|
| **AUTO-FIX** | 机械性修复、无歧义、不影响逻辑 | 直接修复，输出一行摘要 |
| **ASK** | 需要判断或有多种修复路径 | 批量提问让用户选择 |
| **BLOCK** | 严重架构违规、安全漏洞 | 阻塞，必须修复后才能继续 |

#### AUTO-FIX 输出格式

```
[AUTO-FIXED] [文件:行号] 问题 → 修复内容
```

#### ASK 批量提问格式

```
已自动修复 N 项，M 项需要确认：

1. [CRITICAL] apps/server/src/xxx.ts:42 — 问题描述
   修复建议：具体方案
   → A) 修复  B) 跳过

2. [INFORMATIONAL] apps/web/src/xxx.vue:88 — 问题描述
   修复建议：具体方案
   → A) 修复  B) 跳过

建议：修复全部——原因说明。
```

#### BLOCK 格式

```
🚫 [BLOCK] apps/web/src/xxx.ts:15 — 前端直接调用 LLM API
   架构红线：前端不得直接调用 LLM，必须通过 L2 SSE 通道。
   此问题必须修复后才能合入。
```

---

### Step 4: Verification of Claims（断言验证）

在输出最终评审报告前，逐项验证：

- 声称"此模式是安全的" → 引用具体代码行证明
- 声称"其他地方已处理" → 读取并引用处理代码
- 声称"测试已覆盖" → 指出测试文件名和方法名
- **决不允许**"likely handled"或"probably tested" → 验证或标记为 unknown

**反合理化**："This looks fine" 不是有效结论。要么引用证据证明确实 fine，要么标记为未验证。

---

### Step 5: 输出评审报告

```markdown
## 📋 代码评审报告

**分支**：feature/xxx → master
**范围**：N 个文件变更，+X/-Y 行

### Scope Check
[CLEAN / DRIFT DETECTED / REQUIREMENTS MISSING]
意图：[CURRENT_PLAN.md 中的计划]
实际交付：[diff 实际内容]

### 评审摘要
Pre-Landing Review: N issues (X critical, Y informational)

### CRITICAL 发现
| # | 文件:行号 | 问题 | 处理 | 状态 |
|---|----------|------|------|------|
| 1 | ... | ... | AUTO-FIX / ASK / BLOCK | ✅ / ⏳ / 🚫 |

### INFORMATIONAL 发现
| # | 文件:行号 | 问题 | 处理 | 状态 |
|---|----------|------|------|------|
| 1 | ... | ... | AUTO-FIX / ASK | ✅ / ⏳ |

### 文档陈旧检查
[如有代码变更导致文档过期，列出并建议运行 `/done` 同步]

### 评审就绪状态
- Code Review: ✅ PASS / ❌ FAIL (N blocking issues)
- Design Review: ✅ PASS / ⏭️ SKIPPED (无前端变更) / ❌ FAIL
```

---

## 条件性设计评审

仅当 diff 触及 `apps/web/` 目录时启动：

1. 检查 diff 是否包含 `apps/web/` 下的文件变更
2. 若有，加载 `web-design-guidelines` skill 的 `review` 模式
3. 设计评审发现合并到主评审报告的 Fix-First 流程

**若无前端变更**：跳过设计评审，不输出任何信息。

---

## 相关资源

- **评审清单**：`references/checklist.md` — 四大维度详细检查项
- **设计评审**：`web-design-guidelines` skill — 前端设计规范检查
- **排查手册**：`debug-runbook` skill — 评审中发现的问题可参考排查
