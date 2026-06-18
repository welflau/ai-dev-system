---
name: verify
description: "端到端验证（三层级 + diff-aware 模式）"
argument-hint: "[--quick | --exhaustive] [--scope <all|api|preview|TC-XX>] [--priority <P0|P1|P2>]"
---

# 执行指令 (Instructions)

当用户执行此命令时，按以下步骤执行：

## Step 0: 模式检测与参数解析

1. **解析验证层级**：

   | 层级 | 参数 | 覆盖范围 | 适用场景 |
   |------|------|----------|---------|
   | **Quick** | `--quick` | 仅 P0 + P1 | 快速冒烟测试；**合并前自动化门控**请另按 CI 分层顺序跑 typecheck + 三分包 `test`（见下文） |
   | **Standard** | （默认） | P0 + P1 + P2 | 常规验证 |
   | **Exhaustive** | `--exhaustive` | 全部 + 边界/细节 | 发布前全量检查 |

2. **解析其他参数**：
   - `--scope`：验证范围，可选值 `all`（全量）、`api`（仅 API 验证）、`preview`（仅预览沙箱）、`TC-XX`（指定测试用例）
   - `--priority`：按优先级过滤，可选值 `P0`、`P1`、`P2`

3. **Diff-aware 自动模式检测**：
   - 检查当前分支：`git branch --show-current`
   - 识别远端默认主干基线（`BASE_REF`）：优先 `origin/HEAD`，失败时先读取 `git remote show origin` 的 `HEAD branch`，再兜底首个非 `HEAD` 分支
   - **如果在 feature branch（非远端默认主干）且用户未指定 `--scope`**：
     - 自动进入 **diff-aware 模式**
     - 运行 `git diff ${BASE_REF} --name-only` 获取变更文件列表
     - 根据变更文件推断需要测试的范围：
       - `apps/web/` 变更 → 前端 UI 测试
       - `apps/server/` 变更 → API 接口测试
       - `apps/runtime/` 变更 → 预览沙箱测试
       - `packages/` 变更 → 跨模块集成测试
     - 输出："🎯 Diff-aware 模式：检测到变更涉及 [目录列表]，仅测试相关用例。"
   - **如果在默认主干分支或用户指定了 `--scope`**：使用指定范围。

---

## Step 1: 加载 e2e-verification skill

- 读取 `.agents/skills/e2e-verification/SKILL.md`，按其中定义的 Pipeline 流程执行。

---

## Step 2: 用例筛选

根据层级和模式筛选用例：

### Quick 模式
- 只运行 P0（核心流程不可用）和 P1（关键功能异常）级用例
- 跳过 P2 及以下
- 超时阈值较短

### Standard 模式（默认）
- 运行 P0 + P1 + P2（一般功能问题）
- 标准超时阈值

### Exhaustive 模式
- 运行所有级别用例
- 增加边界条件测试：
  - 空输入、超长输入、特殊字符
  - 并发操作、快速连续点击
  - 网络断连恢复
  - 浏览器后退/前进
- 增加视觉回归检查（如 diff-aware 模式触及前端）
- 超时阈值较长

### Diff-aware 过滤
如果处于 diff-aware 模式，在层级筛选后进一步过滤：
- 只保留与变更文件相关的测试用例
- 加上直接依赖变更模块的用例（级联影响）
- 输出过滤结果："从 N 个用例中筛选出 M 个与本次变更相关的用例。"

---

## Step 3: 执行验证 Pipeline

- 按 e2e-verification skill 的 Pipeline 步骤依次执行
- 在 Gate 检查点暂停，呈现结果并等待用户确认
- 对于 diff-aware 模式，在每个 Gate 检查点额外说明："本次仅验证变更相关用例。全量验证请运行 `/verify --scope all`。"

---

## Step 4: 输出结果

根据层级输出不同格式的报告：

### Quick 报告
```
⚡ Quick 验证完成
通过: N/M (P0: X/Y, P1: A/B)
[失败列表（如有）]
```

### Standard 报告
```
✅ Standard 验证完成
通过: N/M (P0: X/Y, P1: A/B, P2: C/D)
[失败列表（如有）]
[Diff-aware 说明（如适用）]
```

### Exhaustive 报告
```
🔬 Exhaustive 验证完成
通过: N/M (P0: X/Y, P1: A/B, P2: C/D, 边界: E/F)
[失败列表（如有）]
[边界条件测试详情]
[视觉回归检查结果（如适用）]
```

### 最终判定
- 验证全部通过：`"✅ E2E 验证全部通过！共 N 个用例，通过 N 个。"`
- 存在失败：`"❌ E2E 验证有 N 个失败。详见上方报告，建议修复后重新运行 /verify。"`
- Diff-aware 模式通过但建议全量：`"✅ 变更相关用例全部通过。发布前建议运行 /verify --scope all --exhaustive 做全量检查。"`

---

## 使用示例

```
/verify                           # Standard，auto diff-aware（feature branch）
/verify --quick                   # Quick，仅 P0/P1
/verify --exhaustive              # Exhaustive，全量 + 边界
/verify --scope all               # 全量验证（覆盖 diff-aware）
/verify --scope api               # 仅验证 API 接口
/verify --scope preview           # 仅验证预览沙箱
/verify --scope TC-01             # 仅运行指定用例
/verify --quick --scope api       # Quick + 仅 API
/verify --exhaustive --scope all  # 发布前推荐：全量 + 边界
```

### 自动化测试：CI 分层门禁（与 MR 流水线对齐）

`/verify` 以 E2E / 用例清单为主；**合并前或发布前自检**时，命令顺序以 `.ci/test-gate.yaml` / `.ci/templates/test-gate.yml` 为权威（与 MR 硬门禁一致，**包脚本优先**）。如需**完整对齐 MR 硬门禁**，按下列顺序执行；人类可读摘要见 `README.md`「常用脚本」：

1. `pnpm install --frozen-lockfile`
2. `pnpm --filter @vibe-game-creator/runtime build`
3. `pnpm typecheck`
4. `pnpm --filter @vibe-game-creator/web test`
5. `pnpm --filter @vibe-game-creator/backend test`
6. `pnpm --filter @vibe-game-creator/runtime test`
7. `pnpm --filter @vibe-game-creator/shared-types test`
8. `pnpm --filter @vibe-game-creator/sandbox-protocol test`
9. `pnpm test`（全仓回归抽检；建议在 1–8 全绿后再跑）

**L1 定向单测**（仅跑某一 spec 时）：`pnpm --filter @vibe-game-creator/web exec vitest run <spec...>`（`<spec...>` 路径相对 `apps/web`）。

**L1 参数透传**（跑 web 包全部单测时）：`pnpm --filter @vibe-game-creator/web test -- <vitest 参数>`（例：`pnpm --filter @vibe-game-creator/web test -- --reporter=verbose`）

**覆盖率**：优先 `pnpm --filter @vibe-game-creator/web run test:coverage`（与 `apps/web/package.json` 一致）
