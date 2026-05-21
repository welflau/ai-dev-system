---
description: 列出当前 AICR 场景的适用规则
args_hint: "[autoaicr|precommit]"
requires_project: false
---

# /aicr-rules [场景]

列出指定场景（autoaicr / precommit）的规则内容。

## 用法

```
/aicr-rules              列出所有 AICR 规则（两个场景）
/aicr-rules autoaicr     只列出 AutoAICR 规则
/aicr-rules precommit    只列出 PreCommit 规则
```

规则来源（按优先级合并）：
1. `backend/skills/rules/workflow/autoaicr.md` / `precommit.md`（系统规则）
2. `.ads/rules/workflow/autoaicr.md` / `precommit.md`（项目规则，若存在）
