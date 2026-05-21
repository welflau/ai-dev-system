---
description: 检查 ADS 运行环境健康状态（DB / LLM / MCP / Git）
args_hint: ""
requires_project: false
---

# /doctor

诊断 ADS 各组件运行状态，输出示例：

```
## ADS 环境诊断

✅ 数据库：连接正常
✅ LLM：已配置（claude-sonnet-4-6）
✅ MCP：2 运行中 / 1 已禁用
✅ 项目仓库：/path/to/project
   git: ✅  .ads/: ✅  .claude/: ⭕
💰 今日费用：$0.0240
```
