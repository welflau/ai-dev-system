---
name: typescript-coding-rules
description: TypeScript 编码准则：共享逻辑优先、类型安全边界、状态不变性
type: always
globs: ["**/*.ts", "**/*.tsx", "**/*.vue"]
---

# TypeScript 编码规范

## 1. 共享逻辑优先

禁止在业务模块中编写内联辅助函数，公共逻辑必须沉淀到共享层（`utils/` 或 `services/`）。

编写任何逻辑前，先搜索项目中是否已有相同或相似的工具函数。发现 ≥2 处重复，必须抽象。

## 2. 类型安全边界

**禁止 `any`**；**减少 `as` 断言**（必须附注释说明原因）。

API 响应、外部消息、用户输入等外部数据，必须经过运行时校验（Zod 或类型守卫）后再使用。

```typescript
// ✅ Zod 校验
const UserSchema = z.object({ name: z.string() });
const data = UserSchema.parse(rawData);

// ✅ 类型守卫
function isMyMessage(data: unknown): data is MyMessage {
  return typeof data === 'object' && data !== null && 'type' in data;
}
```

## 3. 状态不变性

全局状态变更必须通过受控的 action 方法，禁止直接赋值 store 属性或在控制器中直接操作内部状态对象。
