---
name: review
description: "代码评审门控（Scope Drift + Two-Pass Review + Fix-First）"
---

# /review — 代码评审

## Step 1: 获取 diff 基线

```bash
git fetch origin --quiet
BASE_REF=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || echo "origin/main")
git diff "$BASE_REF" --stat
```

若在默认主干分支上，输出"没有可评审的内容"并停止。

## Step 2: 范围偏移检测

读取 `CURRENT_PLAN.md`（如存在），对比 `git diff $BASE_REF --stat`：

```
范围检查: CLEAN / 检测到偏移 / 需求缺失
预期: <计划要做什么>
实际: <diff 实际做了什么>
```

这是信息性的，不阻塞评审。

## Step 3: Two-Pass 评审

获取完整 diff：`git diff "$BASE_REF"`

**Pass 1 (CRITICAL)**：
- 安全边界：敏感操作是否有权限校验
- 外部数据：API 入参/响应是否有 schema 校验
- 竞态与并发：异步操作的竞态条件
- SQL/注入防护：参数化查询

**Pass 2 (INFORMATIONAL)**：
- 条件副作用：if/else 分支副作用是否配对
- 魔法数字/字符串耦合：硬编码值应提取为常量
- 死代码：未使用的 import、冗余逻辑
- 测试覆盖缺口：新代码路径缺少对应测试

**声明验证原则**：
- 声称"已处理" → 引用处理代码的具体行
- 声称"有测试覆盖" → 给出测试文件和方法名
- 不说"可能已处理"或"大概有测试"

## Step 4: Fix-First

分类每个发现：
- **AUTO-FIX**：机械性修复（格式、typo、缺少 import）→ 直接应用
- **ASK**：需要判断（架构决策、行为变更）→ 批量询问用户
- **BLOCK**：必须修复才能合并 → 立即修复，无跳过选项

对 ASK 项批量呈现：
```
已自动修复 N 个问题。M 个需要确认：
1. [CRITICAL] file:line — 问题描述
   修复建议: ...  → A)修复  B)跳过
```

## Step 5: 文档陈旧检查

检查 diff 中的代码变更是否影响了 `README.md`、架构文档描述的功能，标记为 INFORMATIONAL。

## Step 6: Review Readiness Dashboard

```
+================================================+
|          REVIEW READINESS DASHBOARD            |
+================================================+
| 范围一致性      | CLEAN    | 与计划对齐        |
| 代码评审 CRITICAL| CLEAR   | 0 个关键问题      |
| 代码评审 INFO   | 2 FIXED  | 2 个自动修复      |
+------------------------------------------------+
| 判定: CLEARED — 可运行 /done                   |
+================================================+
```

判定：无 BLOCK 项 + 所有 CRITICAL ASK 已处理 → **CLEARED**

## 衔接

> "评审通过：运行 `/done` 进行收尾。有修复项：修复后重新运行 `/review`。"
