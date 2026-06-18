---
description: 保持注释简洁，避免显而易见的注释。注释应该解释"为什么"而不是"是什么" - 代码本身应该足够清晰来说明它做了什么。仅在业务决策、权宜之计、性能优化、安全考虑或故障排查等无法从代码直接看出的情况下添加注释。
alwaysApply: false
enabled: true
updatedAt: 2026-03-08T14:03:32.176Z
provider: 
---

# 代码注释规范

## 基本原则

保持注释简洁，避免显而易见的注释。注释应该解释"为什么"而不是"是什么" - 代码本身应该足够清晰来说明它做了什么。

## 何时需要注释

- 从代码中无法直接看出的业务决策或领域逻辑
- 权宜之计或临时方案，需要解释为什么需要这样做
- 不明显的性能优化
- 重要的安全考虑
- 故障排查上下文（例如，在遇到问题后为什么选择某种特定方法）

如果以上情况都不适用，就完全不要写注释。函数名、参数和返回类型应该能够自我说明。

## 何时不需要注释

```typescript
// ❌ 不好 - 显而易见的注释
// 获取用户
const user = await getUser(userId);

// ❌ 不好 - 重复代码的意思
// 循环遍历预订
for (const booking of bookings) {
  // 处理预订
  processBooking(booking);
}
```

## 好的例子

```typescript
// ✅ 好 - 解释为什么，而不是做什么
// 我们需要在获取时间段之前先获取可用性，因为时区转换
// 依赖于用户配置的可用性规则
const availability = await getAvailability(userId);
const slots = convertToSlots(availability, timezone);

// ✅ 好 - 记录不明显的约束
// Google Calendar API 每次同步请求有 2500 个事件的限制
const BATCH_SIZE = 2500;
```