---
name: done
description: "任务收尾：文档同步 + CHANGELOG + 版本号 + commit"
argument-hint: "[--skip-review]"
---

# /done — 任务收尾

## Step 1: Wave 完整性校验

检查 `CURRENT_PLAN.md` 中是否有未打勾 `[ ]` 的任务。有则拒绝执行，列出未完成任务。

## Step 2: Review Readiness 检查

若未通过 `/review`：
- **轻量变更**（≤1 文件、<50 行、仅文档/注释/格式）：建议但允许跳过
- **其他变更**：询问是否先运行 `/review`

传入 `--skip-review` 时跳过此检查。

## Step 3: 文档审计

获取变更文件：`git diff $BASE_REF --name-only`

逐文件检查是否影响了 `README.md`、`docs/` 等文档：
- **事实性更正**（路径、计数、列表）→ 直接修改
- **叙述性变更**（架构理念、大段重写）→ 询问用户

## Step 4: 踩坑点沉淀

本次开发中遇到非预期行为、调试困难、平台差异？追加到项目文档或 `.agents/memory/` 下对应 skill 的 `gotchas.md`。

## Step 5: CHANGELOG 更新

追加到 `CHANGELOG.md`，格式：

```markdown
### vX.Y.Z: 标题

- 现在可以…
- 现在可以…

### 内部改进

- 实现摘要 1

### 相关文档

- ADR / Acceptance 链接（如有）
```

版本号规则：
- 功能新增 → minor +1
- Bug 修复 / 重构 → patch +1

**措辞检查**：用"现在可以…"开头；内部改进放 `### 内部改进` 子段；不要把 commit message 复制进来。

## Step 6: 清理计划文件

重置 `CURRENT_PLAN.md` 为 IDLE 状态：

```markdown
# CURRENT PLAN

> 状态：⚪ IDLE
> 更新时间：{日期}
> 说明：当前无进行中的计划。请通过 `/plan` 创建下一轮任务。
```

如存在 `DESIGN_BRIEF.md`，同样重置为 IDLE。

## Step 7: Commit & Push（需确认）

检测 detached HEAD（Worktree 环境）：`git branch --show-current` 输出为空则禁止 push，提示 cherry-pick 回主分支。

确认后执行：
```bash
git add -A
git commit -m "$(CHANGELOG 中本次版本标题)"
git push
```

## 完成输出

> "✅ 任务已彻底闭环！代码已提交并推送至远程。"
