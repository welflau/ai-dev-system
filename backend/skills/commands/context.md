---
description: 查看当前 session context token 使用分布
args_hint: ""
requires_project: false
---

# /context

可视化当前 session 的 context 使用情况。

## 输出示例

```
Context 使用情况

对话历史：约 8,600 tokens（20 条消息）
Token 预算：300,000
使用率：2.9%  [█░░░░░░░░░░░░░░░░░░░░░░░░░░░░░]
上次调用：3,240 tokens（输入+输出）

/config budget_tokens <N> 调整 token 上限
```

上下文接近上限时可使用 `/compact` 压缩历史，或 `/config budget_tokens` 调整预算。
