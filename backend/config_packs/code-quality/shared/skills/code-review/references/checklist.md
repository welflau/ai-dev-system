# 代码评审检查清单

> 本清单供 `code-review` skill 和 `/review` 命令使用。
> 按前端 / 后端 / 运行时 / 通用四类组织，每项标注严重级别和处理建议。

---

## 一、前端检查清单（apps/web — Vue 3 + Vite + TailwindCSS + Pinia）

### CRITICAL

| # | 检查项 | 说明 | Fix-First |
|---|--------|------|-----------|
| FE-C01 | 前端不直接调 LLM | 所有 AI 请求必须通过 SSE 通道到 L2 后端 | BLOCK |
| FE-C02 | SSE 错误处理 | `EventSource` 必须处理 `onerror`，实现断线重连 | ASK |
| FE-C03 | XSS 防护 | AI 生成的 HTML/代码不得直接 `v-html` 渲染，需 sanitize | BLOCK |
| FE-C04 | 沙箱通信安全 | `postMessage` 必须校验 `origin`，使用 `sandbox-protocol` 类型 | BLOCK |
| FE-C05 | 敏感信息泄露 | API key、token 不得出现在前端代码或 localStorage | BLOCK |

### INFORMATIONAL

| # | 检查项 | 说明 | Fix-First |
|---|--------|------|-----------|
| FE-I01 | Composition API | 新组件必须使用 `<script setup>` + Composition API | AUTO-FIX |
| FE-I02 | Pinia 状态管理 | 跨组件共享状态使用 Pinia store，不用 provide/inject 传递复杂状态 | ASK |
| FE-I03 | Props 类型定义 | 使用 `defineProps<T>()` 泛型方式，不用运行时 props 声明 | AUTO-FIX |
| FE-I04 | 响应式正确性 | `ref` / `reactive` 使用正确，无 `.value` 遗漏或多余 | AUTO-FIX |
| FE-I05 | TailwindCSS 优先 | 优先使用 Tailwind utility class，避免自定义 CSS（除非复杂动画） | ASK |
| FE-I06 | 路由守卫 | 需要认证的页面有路由守卫保护 | ASK |
| FE-I07 | 组件拆分 | 单组件超过 300 行建议拆分 | ASK |
| FE-I08 | 事件清理 | `onMounted` 注册的事件监听在 `onUnmounted` 清理 | AUTO-FIX |
| FE-I09 | 异步组件 | 路由级组件使用 `defineAsyncComponent` 或动态 import 懒加载 | ASK |
| FE-I10 | i18n 准备 | 用户可见文案不硬编码（如果项目启用了 i18n） | ASK |

### DO NOT flag（误报抑制）

- TailwindCSS 中的 `!important`（Tailwind 的 `!` 前缀是设计用法）
- `<script setup>` 中的顶级 `await`（Vue 3 支持）
- Pinia store 中的 `$patch` 嵌套调用

---

## 二、后端检查清单（apps/server — Express + TypeScript + Orchestrator）

### CRITICAL

| # | 检查项 | 说明 | Fix-First |
|---|--------|------|-----------|
| BE-C01 | Agent 通过 Orchestrator | Agent 间通信必须经过 Orchestrator 调度，不得直接互调 | BLOCK |
| BE-C02 | DB 操作通过 db 层 | 所有数据库读写必须通过 `db/` 模块，不得裸 SQL 或直接 ORM 调用 | BLOCK |
| BE-C03 | AST 校验 AI 代码 | AI 生成的代码在执行前必须经过 AST 校验（esbuild parse 或 acorn） | BLOCK |
| BE-C04 | SSE 响应格式 | SSE 事件必须遵循 `data: JSON\n\n` 格式，含 event type | ASK |
| BE-C05 | 错误边界 | Express 路由必须有 try-catch，未捕获异常不得导致进程退出 | ASK |
| BE-C06 | 输入验证 | 所有 API 入参使用 Zod schema 验证，不信任客户端数据 | BLOCK |

### INFORMATIONAL

| # | 检查项 | 说明 | Fix-First |
|---|--------|------|-----------|
| BE-I01 | Zod schema 边界 | 跨包数据传输边界使用 `packages/shared-types` 中的 Zod schema | ASK |
| BE-I02 | 日志规范 | 使用项目 logger，不用 `console.log`；含 requestId 上下文 | AUTO-FIX |
| BE-I03 | 幂等性 | 写操作 API 设计幂等或有去重机制 | ASK |
| BE-I04 | 超时控制 | LLM 调用和外部 HTTP 请求有超时设置 | ASK |
| BE-I05 | 环境变量 | 配置项通过环境变量注入，不硬编码；有默认值和校验 | AUTO-FIX |
| BE-I06 | 并发安全 | 共享资源（文件、缓存）的读写有适当的锁或序列化机制 | ASK |
| BE-I07 | 依赖注入 | 服务间依赖通过构造函数注入，便于测试 mock | ASK |
| BE-I08 | 中间件顺序 | Express 中间件注册顺序正确（auth → validate → handler → error） | ASK |

### DO NOT flag

- `console.log` 在开发脚本（scripts/）中使用
- 测试文件中的裸 SQL
- `any` 类型在测试 mock 中使用

---

## 三、运行时检查清单（apps/runtime — Phaser.js + Platform Bridge）

### CRITICAL

| # | 检查项 | 说明 | Fix-First |
|---|--------|------|-----------|
| RT-C01 | 沙箱隔离 | 运行时代码不得访问父页面 DOM 或非 postMessage 通道 | BLOCK |
| RT-C02 | Platform Bridge 抽象 | 平台相关代码（微信/QQ/H5）通过 Bridge 抽象，不直接调用平台 API | BLOCK |
| RT-C03 | 资源释放 | Scene 切换时正确销毁旧 Scene 的资源（texture、audio、timer） | ASK |
| RT-C04 | 用户代码沙箱 | AI 生成的游戏代码在隔离上下文执行，不能访问宿主全局 | BLOCK |

### INFORMATIONAL

| # | 检查项 | 说明 | Fix-First |
|---|--------|------|-----------|
| RT-I01 | 帧率控制 | 游戏循环使用 Phaser 内建计时器，不用 `setInterval` | AUTO-FIX |
| RT-I02 | 资源预加载 | 大资源在 Preload Scene 加载，不在游戏循环中动态加载 | ASK |
| RT-I03 | 事件总线 | 使用 Phaser Events 或项目事件系统，不用全局变量通信 | ASK |
| RT-I04 | 屏幕适配 | 使用 Phaser Scale Manager 适配不同分辨率 | ASK |
| RT-I05 | 物理引擎 | 物理体在不需要时及时销毁或禁用 | ASK |
| RT-I06 | 音频管理 | 音频播放有统一管理器，支持静音和音量控制 | ASK |

### DO NOT flag

- Phaser 内部的 `any` 类型（引擎类型定义不完整）
- 游戏 config 中的魔法数字（分辨率、帧率等是游戏设计参数）
- 测试中直接构造 Phaser 对象

---

## 四、通用检查清单（TypeScript + 跨包边界 + Git 规范）

### CRITICAL

| # | 检查项 | 说明 | Fix-First |
|---|--------|------|-----------|
| GN-C01 | 类型安全 | 禁止 `as any` 强制转换（测试文件除外）；禁止 `@ts-ignore`（需说明原因除外） | ASK |
| GN-C02 | 跨包类型 | 包间共享的类型定义在 `packages/shared-types`，不在各包中重复定义 | BLOCK |
| GN-C03 | 密钥泄露 | `.env`、密钥文件、token 不得提交到 Git | BLOCK |

### INFORMATIONAL

| # | 检查项 | 说明 | Fix-First |
|---|--------|------|-----------|
| GN-I01 | Commit 规范 | 遵循 Conventional Commits（`feat:` / `fix:` / `chore:` 等） | ASK |
| GN-I02 | import 路径 | 跨包 import 使用 workspace 包名（`@vibe/shared-types`），不用相对路径 | AUTO-FIX |
| GN-I03 | 枚举完整性 | 新增枚举值时，检查所有 switch/map 是否已处理 | ASK |
| GN-I04 | 错误类型 | 自定义错误类继承 `Error`，含 `code` 和 `message` | AUTO-FIX |
| GN-I05 | 异步错误 | Promise 链有 `.catch()` 或在 async 函数中有 try-catch | AUTO-FIX |
| GN-I06 | 未使用导入 | 移除未使用的 import 语句 | AUTO-FIX |
| GN-I07 | TODO 注释 | 新增的 `TODO` / `FIXME` 注释需关联 issue 或有时间承诺 | ASK |
| GN-I08 | 文件命名 | 组件 PascalCase，工具函数 camelCase，常量 UPPER_SNAKE_CASE | AUTO-FIX |

### DO NOT flag

- `tsconfig.json` 中的 `strict: true` 配置差异（各包可能有不同配置）
- `.d.ts` 文件中的 `declare module`
- 测试文件中的 `@ts-expect-error`（用于测试类型错误场景）

---

## 架构红线速查

以下违规直接 BLOCK，无需讨论：

```
❌ apps/web/ 中 import 了 LLM SDK（openai / anthropic / 等）
❌ apps/server/src/agents/ 中 Agent 直接实例化其他 Agent（应通过 Orchestrator）
❌ apps/server/ 中直接使用 prisma/knex/sql 而非 db 层封装
❌ AI 生成代码未经 AST parse 校验就执行
❌ postMessage 未校验 origin
❌ 跨包类型在非 packages/ 目录定义
```
