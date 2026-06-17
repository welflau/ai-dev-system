---
name: plan
description: "基于设计简报生成 Wave 执行计划，输出 CURRENT_PLAN.md（严禁写代码）"
argument-hint: "[需求描述（无 DESIGN_BRIEF 时必填）]"
---

读取 `DESIGN_BRIEF.md`（优先）或直接使用用户描述，生成 Wave 执行计划写入 `CURRENT_PLAN.md`。

Wave 结构：串行前置 Wave → 并行核心 Wave（各 Agent 目录无交集）→ 串行集成 Wave。
所有任务项必须使用 `- [ ]` checkbox 格式，每个并行 Agent 必须标注目录范围。
