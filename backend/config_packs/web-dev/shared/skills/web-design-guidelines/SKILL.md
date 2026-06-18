---
name: web-design-guidelines
description: >-
  网站设计统一技能入口。当用户请求设计页面、创建组件、审查 UI、检查可访问性、
  优化用户体验、改善文案、优化动效、打磨视觉细节、处理边界场景、或输入
  "设计"、"UI"、"UX"、"样式"、"布局"、"动画"、"响应式"等关键词时触发。
user-invokable: true
args:
  - name: mode
    description: 工作模式（build/review/ux/copy/motion/polish/system/resilience/style）
    required: false
  - name: target
    description: 目标页面、组件、路由或文件模式（可选）
    required: false
argument-hint: <mode> <target>
metadata:
  pattern: "composite[pipeline + reviewer]"
  version: "3.0.0"
  author: vibe-game-creator
  tags: [design, ui, ux, frontend]
---

# Web Design Guidelines

网站设计相关任务统一走本技能，按 `mode` 路由到模块执行。

## 执行规则

1. 若未提供 `mode`，根据用户意图自动判断最匹配模式。
2. 执行前先补齐必要上下文；信息不足时先提问，不猜测。
3. 先读取对应模块，再产出结果。
4. 执行 `build`、`review`、`resilience` 模式时，先加载 `references/gotchas.md` 了解常见踩坑点。
5. **Diff-aware 自动检测**：在 feature branch 时 `review` 模式自动进入 diff-aware 模式。
6. **设计规范校准**：`review` 模式输出前校准 DESIGN.md / ui-visual-design.md。

---

## Diff-aware 模式（review 模式增强）

当处于 feature branch 时，`review` 模式自动启用 diff-aware：

### 检测条件

```bash
_BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
_DEFAULT=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || echo "master")
```

若 `_BRANCH` 不等于 `_DEFAULT` 且不等于 `unknown`，进入 diff-aware 模式。

### Diff-aware 流程

1. **获取变更文件列表**：
   ```bash
   git diff origin/<default>...HEAD --name-only -- 'apps/web/'
   ```

2. **过滤前端文件**：只审查 `apps/web/` 下变更的 `.vue`、`.ts`、`.tsx`、`.css` 文件。

3. **映射受影响页面**：从变更文件推导受影响的路由/页面。

4. **仅审查受影响范围**：不审查未变更的文件，避免噪音。

5. **输出差异对照**：对每个发现标注是"新引入"还是"已有问题"。

**若无前端文件变更**：跳过设计评审，输出"无前端变更，跳过设计评审"。

---

## DESIGN.md / ui-visual-design.md 校准

`review` 模式在输出最终报告前，执行设计规范校准：

1. **查找设计规范文件**：按优先级查找 `DESIGN.md` → `docs/ui-visual-design.md` → `design-system.md`。

2. **校准规则**：
   - 设计规范中明确允许的模式 → 不标记为问题
   - 设计规范中明确禁止的模式 → 提升为 HIGH 级别
   - 与设计规范不一致但未明确禁止 → 标记为 MEDIUM 并注明偏差

3. **无设计规范时**：使用通用设计原则，报告中注明"未找到项目设计规范，使用通用标准"。

---

## Fix-First + Atomic Commit 模式（review 模式增强）

`review` 模式发现问题后，进入 Fix-First 流程：

### 前置检查

```bash
git status --porcelain
```

若工作区不干净，提示用户先提交或暂存变更。

### 分类与处理

| 级别 | 条件 | 处理 |
|------|------|------|
| **AUTO-FIX** | 机械性 CSS 修复（`outline: none`、`!important`、`font-size < 16px`） | 直接修复 + atomic commit |
| **ASK** | 需要设计判断的问题 | 批量提问后修复 |
| **DEFER** | 需要设计师确认或涉及第三方组件 | 记录到报告，不修复 |

### Atomic Commit 规则

每个修复一个独立提交：

```bash
git add <only-changed-files>
git commit -m "style(design): FINDING-NNN — 简短描述"
```

- **一个提交一个修复**，不捆绑
- 提交信息格式：`style(design): FINDING-NNN — 描述`
- CSS-only 修复优先（更安全、更可逆）
- 不得顺便重构或"改善"不相关代码

### 修复后验证

每个修复后验证：
1. 确认修复效果
2. 确认无回归（相关组件仍然正常）
3. 若修复导致回归 → `git revert HEAD` → 标记为 DEFER

### 自我监控

每 5 个修复后评估风险：

```
DESIGN-FIX 风险:
  起始 0%
  每次 revert:                     +15%
  每个 CSS-only 修改:              +0%  (安全)
  每个 Vue/TS 组件修改:            +5%  per file
  修复超过 10 个后:                +1%  per fix
  触及不相关文件:                  +20%
```

**风险 > 20%**：STOP，展示已完成的修复，询问是否继续。
**硬上限：30 个修复**。

---

## mode 说明

- `build`：页面或组件设计与实现
- `review`：审查 UI、UX、可访问性与规范一致性（含 diff-aware + fix-first）
- `ux`：信息架构、引导流程、空态与可用性优化
- `copy`：文案、提示语与错误信息优化
- `motion`：动效与微交互增强
- `polish`：细节打磨与视觉一致性优化
- `system`：组件与模式抽取复用
- `resilience`：边界场景、异常处理、性能与跨端适配
- `style`：视觉风格增强或收敛

## mode 对应模块

### `build` -> `modules/frontend-design.md`

#### 🚧 Gate: 设计方向确认

> 在开始实现之前，必须满足以下条件：
> - [ ] 已明确设计方向（风格、目标页面/组件、交互意图）
> - [ ] 已输出实现计划并获得用户确认
>
> **未满足时**：先与用户对齐设计方向，输出分步计划等用户确认后再开始编码实现，不得跳过。

### `review` -> `modules/audit.md` + `modules/critique.md` + `modules/review-rules.md`

#### 🚧 Gate: 问题列表确认

> 在输出修复建议之前，必须满足以下条件：
> - [ ] 已按严重级别输出完整问题列表
> - [ ] 已对照 DESIGN.md / ui-visual-design.md 校准（如存在）
> - [ ] 用户已确认需要修复的问题范围
>
> **未满足时**：先输出问题清单等用户确认修复范围，不得直接给出修复代码。

#### 🚧 Gate: Fix-First 完成确认

> 修复完成后，必须满足以下条件：
> - [ ] 所有 AUTO-FIX 已执行并 atomic commit
> - [ ] 所有 ASK 项已获用户确认并处理
> - [ ] 无回归（已 revert 的修复标记为 DEFER）
>
> **未满足时**：继续处理未完成的修复项。

### `ux` -> `modules/onboard.md` + `modules/critique.md`

### `copy` -> `modules/clarify.md`

### `motion` -> `modules/animate.md` + `modules/delight.md`

### `polish` -> `modules/polish.md` + `modules/normalize.md` + `modules/distill.md` + `modules/quieter.md`

### `system` -> `modules/extract.md`

### `resilience` -> `modules/harden.md` + `modules/optimize.md` + `modules/adapt.md`

#### 🚧 Gate: 边界场景范围确认

> 在开始处理之前，必须满足以下条件：
> - [ ] 已输出边界场景清单（异常状态、极端输入、跨端差异、性能瓶颈）
> - [ ] 用户已确认需要处理的场景范围
>
> **未满足时**：先输出边界场景清单等用户确认范围，不得直接开始加固实现。

### `style` -> `modules/bolder.md` + `modules/colorize.md` + `modules/quieter.md`

## 输出要求

- 设计/改造：给出计划 -> 实施 -> 验证
- 审查：按严重级别列问题，并给最小修复建议；含 Fix-First 处理结果
- 优化：说明可验证改进点（指标或观察项）

### review 模式报告格式

```markdown
## 🎨 设计评审报告

**分支**：feature/xxx → master
**模式**：[Full / Diff-aware]
**设计规范**：[DESIGN.md / ui-visual-design.md / 通用标准]

### 评审摘要
设计评审: N issues (X high, Y medium, Z polish)

### 发现列表
| # | 级别 | 分类 | 描述 | 处理 | 状态 |
|---|------|------|------|------|------|
| 1 | HIGH | Typography | ... | AUTO-FIX | ✅ committed |
| 2 | MEDIUM | Spacing | ... | ASK | ⏳ pending |
| 3 | POLISH | Motion | ... | DEFER | 📋 deferred |

### Fix-First 结果
- AUTO-FIX: N items (N commits)
- ASK: N items (N approved, N skipped)
- DEFER: N items

### 设计规范偏差
[与 DESIGN.md 不一致的发现列表，如有]
```