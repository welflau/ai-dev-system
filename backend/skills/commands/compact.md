---
description: 手动触发对话历史压缩，减少 context 占用
args_hint: ""
requires_project: false
---

# /compact

手动触发当前 session 的对话历史压缩。

当对话轮次较多时，旧消息会通过 LLM 摘要压缩，释放 context 空间。
