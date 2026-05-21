---
alwaysApply: false
paths:
  - "**/*.ts"
  - "**/*.tsx"
priority: high
description: TypeScript 文件专属规范（类型安全 / 异步 / React）
---

# TypeScript 编码规范

> 仅在编辑 .ts / .tsx 文件时注入。

## 一、类型安全

- **禁止** `any`（除非封装在类型守卫中）；用 `unknown` 替代不确定类型
- 函数返回值类型**必须**显式声明（尤其是公共 API）
- 联合类型需要穷举处理（`switch` 的 `default` 分支抛 `never`）
- 优先用 `interface` 定义对象形状，用 `type` 定义联合/交叉类型

## 二、Null 安全

- 启用 `strictNullChecks`（项目 tsconfig 应已开启）
- 可选链 `?.` 和空值合并 `??` 优先于 `&&` 链式判断
- 对外部数据（API 响应、localStorage）做运行时校验再用

## 三、异步处理

- 统一用 `async/await`，不混用 `.then()` 链
- `async` 函数内的 `await` 必须在 `try/catch` 中，或在调用处处理异常
- `Promise.all` 处理并行任务，避免串行 `await` 降低性能

## 四、React（如适用）

- 组件文件使用 `.tsx`，非 JSX 文件使用 `.ts`
- Props 接口命名：`{ComponentName}Props`
- 避免在 render 中创建新函数/对象（用 `useCallback` / `useMemo`）
- `useEffect` 依赖数组必须完整（eslint exhaustive-deps）

## 五、命名约定

- 接口/类：PascalCase（`UserProfile`）
- 变量/函数：camelCase（`getUserById`）
- 常量：UPPER_SNAKE_CASE（`MAX_RETRY_COUNT`）
- 枚举值：PascalCase（`enum Status { Active, Inactive }`）
- 泛型参数：单大写字母（`T`）或描述性名称（`TData`）

## 六、模块与导入

- 使用 ES Module `import/export`，禁止 `require()`
- 路径别名优先于相对路径（`@/components/Foo` > `../../components/Foo`）
- 每个文件职责单一；导出超过 10 个符号考虑拆分
