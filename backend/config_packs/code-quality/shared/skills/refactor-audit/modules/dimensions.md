# 审计维度详细检查规则

## 1. 跨包耦合 (coupling)

检查项：
- `apps/web/` 中是否存在对 `apps/server/` 或 `apps/runtime/` 的直接 import
- 跨包引用是否绕过 `package.json` exports，直接引用 `src/` 内部路径
- 依赖方向是否违反 `web ──(HTTP/SSE)──▶ server ──▶ runtime` 的单向约束
- `web` 与 `runtime` 之间是否存在非 postMessage 的直接通信

判定标准：
- 任何违反依赖方向的 import → **P0**
- 引用未通过 exports 声明的内部路径 → **P1**
- 类型定义跨包复制而非共享 → **P1**

## 2. 类型安全 (type-safety)

检查项：
- 是否存在 `any` 类型（包括隐式 any）
- API 响应数据是否经过 Zod schema 或类型守卫校验
- postMessage 事件数据是否有类型校验
- 用户输入是否做了类型断言而非运行时校验
- 前后端共享类型是否存在定义不一致

判定标准：
- 外部数据未校验直接使用 → **P0**
- 显式 `as any` 或 `@ts-ignore` → **P1**
- 共享类型定义不同步 → **P1**
- 可收窄但未收窄的联合类型 → **P2**

## 3. 状态管理 (state)

检查项：
- 是否存在绕过 Pinia actions 直接修改 store state 的代码（如 `store.$state.xxx = ...`）
- 组件内是否包含本应在 store 中管理的业务状态
- 后端状态操作是否全部经过 Service 层
- 是否存在跨组件通过 props drilling 传递超过 3 层的状态

判定标准：
- 绕过 Pinia actions 直接修改 state → **P1**
- 后端逻辑绕过 Service 层直接操作数据 → **P1**
- 业务状态散落在组件内而非 store → **P2**

## 4. 代码重复 (duplication)

检查项：
- 相同或高度相似的逻辑是否在 ≥2 个文件中出现
- 工具函数是否内联在业务模块中，而非沉淀到 `utils/` 或 `services/`
- 相似的 API 调用模式是否可以抽取为通用 composable / service

判定标准：
- 相同逻辑出现在 ≥3 处 → **P1**
- 相同逻辑出现在 2 处 → **P2**
- 工具函数内联在业务代码中 → **P2**

## 5. 复杂度 (complexity)

检查项：
- 单个函数是否超过 50 行
- 嵌套层级是否超过 3 层（if/for/try 嵌套）
- 单个文件是否超过 300 行
- 函数参数是否超过 4 个
- 单个组件是否承担了多个不相关的职责

判定标准：
- 函数超 100 行或嵌套超 4 层 → **P1**
- 函数超 50 行或嵌套超 3 层 → **P2**
- 文件超 500 行 → **P1**
- 文件超 300 行 → **P2**

## 6. 架构红线 (redline)

检查项（对应 AGENTS.md 中的 5 条红线）：
- `apps/web/` 是否直接调用 LLM API（而非通过后端代理）
- AI 生成的代码是否未经 AST 安全校验就注入沙箱
- Agent 间通信是否绕过 Orchestrator
- 数据库操作是否绕过 `apps/server/src/db/` 层
- 数据存储是否未遵循 UnifiedMessage 格式

判定标准：
- 任何违反红线的代码 → **P0**
