---
name: review-extra-rules
description: review 模式额外强制规则，负责拉取外部 Web 指南并按统一格式输出问题。
---

# Review 模式额外规则（强制）

执行 `review` 时，必须先拉取并应用外部 Web 指南，再输出检查结论。

## 指南来源

```
https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md
```

## 执行流程

1. 使用 `WebFetch` 拉取最新规则
2. 读取目标文件或文件模式
3. 按规则检查并输出问题（`file:line`）
4. 按严重级别排序（高 -> 中 -> 低）
5. 给出最小可行修复建议
