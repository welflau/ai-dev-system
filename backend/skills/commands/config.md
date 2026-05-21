---
description: 查看或修改当前 session 配置（model / thinking_mode / compaction 等）
args_hint: "[key] [value]"
requires_project: false
---

# /config [key] [value]

查看或修改当前 session 的行为配置。

## 用法

```
/config                          列出所有配置项和当前值
/config thinking_mode on         开启推理链（等同于 /think on）
/config thinking_mode adaptive   自适应推理（默认）
/config compaction off           关闭历史压缩
/config max_turns 20             设置最大工具调用轮次
/config budget_tokens 500000     设置 token 上限
```

## 配置项说明

| key | 默认值 | 说明 |
|-----|--------|------|
| `thinking_mode` | adaptive | 推理模式：adaptive/on/off |
| `thinking_budget` | 8000 | 推理 token 预算 |
| `compaction` | true | 历史压缩开关 |
| `max_turns` | 50 | 最大工具调用轮次 |
| `budget_tokens` | 300000 | 总 token 上限 |
| `nudge` | true | 回复后未完成需求提示 |
| `verbose` | false | 详细输出模式 |
