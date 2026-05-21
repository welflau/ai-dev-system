---
description: 生成 Harness 健康审计报告（Rules 覆盖、Skills 使用、AICR 统计）
args_hint: "[--days <N>]"
requires_project: false
---

# /harness-audit [--days N]

生成当前 ADS Harness 的健康审计报告。

**报告内容**：

1. **Rules 覆盖**
   - 全局规则（alwaysApply）数量
   - 文件类型按需规则（paths:）数量
   - 场景规则（scene:）数量
   - 近期规则命中 Top 5

2. **Skills 状态**
   - 启用 / 被调用 / 未被调用 Skills 统计
   - 未被调用 Skills 列表（建议检查或删除）

3. **AICR 统计**
   - AutoAICR 触发次数
   - 发现问题数量

4. **改进建议**
   - 自动生成的 Checklist

**用法**：
```
/harness-audit           生成最近 7 天的报告
/harness-audit --days 30 生成最近 30 天的报告
```
