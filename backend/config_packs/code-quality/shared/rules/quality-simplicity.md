---
description: 编写易于阅读和理解的代码，而不是追求优雅的复杂性。简单的系统可以降低认知负担，提高可维护性。
title: 清晰优于巧妙
impact: HIGH
impactDescription: 降低认知负担，提高可维护性
tags: quality, simplicity, readability
alwaysApply: false
enabled: true
---

## 清晰优于巧妙

**影响：高**

目标是编写易于快速阅读和理解的代码，而不是优雅的复杂性。简单的系统可以降低每个工程师的认知负担。

**问自己的问题：**
- 我是否真正解决了手头的问题？
- 我是否过度考虑了可能的未来用例？
- 我是否至少考虑了 1 个其他解决方案？它们相比如何？

**不正确（巧妙但难以理解）：**

```typescript
// 难以理解的巧妙单行代码
const result = data.reduce((a, b) => ({...a, [b.id]: (a[b.id] || []).concat(b)}), {});
```

**正确（清晰且易读）：**

```typescript
// 清晰的分步方法
const groupedById: Record<string, Item[]> = {};

for (const item of data) {
  if (!groupedById[item.id]) {
    groupedById[item.id] = [];
  }
  groupedById[item.id].push(item);
}
```

**重要提示：**
简单并不意味着缺少功能。虽然我们的目标是创建简单的系统，但这并不意味着它们应该显得贫瘠和缺乏明显的功能。
