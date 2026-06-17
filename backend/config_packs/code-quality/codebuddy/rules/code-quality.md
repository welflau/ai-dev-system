---
name: code-quality-rules
description: 代码简洁性 + 注释规范 + Git 提交约定
type: always
---

# 代码质量规范

## 清晰优于巧妙

目标是易于快速阅读和理解，不追求优雅的复杂性。

**问自己**：我是否真正解决了手头的问题？我是否过度考虑了可能的未来用例？

## 注释规范

注释解释"为什么"而不是"是什么"。

**写注释的时机**：业务决策、权宜之计、不明显的性能优化、安全考虑。
**不写注释的时机**：代码本身已能说明意图时。

```
// ❌ 不好 — 显而易见
const user = await getUser(userId); // 获取用户

// ✅ 好 — 解释原因
// 需要先获取可用性，因为时区转换依赖于用户配置的规则
const availability = await getAvailability(userId);
```

## Git 提交规范

格式：`<type>(<scope>): <描述>`

| 前缀 | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `refactor` | 重构 |
| `docs` | 文档 |
| `test` | 测试 |
| `chore` | 构建/依赖 |
