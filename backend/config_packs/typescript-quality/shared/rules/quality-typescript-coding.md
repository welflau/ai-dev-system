---
description: TypeScript 编码准则 — 共享逻辑优先、类型安全边界、状态不变性。编写或审查 TypeScript 代码时必读。
title: TypeScript AI Coding Rules
impact: HIGH
impactDescription: 减少重复代码、消除运行时类型错误、保证状态可预测
tags: quality, typescript, type-safety, shared-logic, state-management
alwaysApply: false
globs: ["**/*.ts", "**/*.vue"]
enabled: true
updatedAt: 2026-03-14
---

# TypeScript AI Coding Rules

本项目所有 TypeScript 代码（前端 Vue SFC、后端 Express、运行时 Phaser）统一遵循以下三大核心准则。

---

## 1. 共享逻辑优先 (Shared Invariants)

> **原则**：禁止在业务模块中编写内联的辅助函数，公共逻辑必须沉淀到共享层。

### 规则

- **编写任何逻辑前**，必须先搜索项目中是否已有相同或相似的工具函数：
  - 前端：`apps/web/src/utils/`
  - 后端：`apps/server/src/services/`、`apps/server/src/agents/schemas.ts`
- 如果发现**重复逻辑**（≥2 处相同），必须将其抽象为泛型工具函数，放入对应的 `utils/` 或 `services/` 目录。
- 跨前后端共用的类型定义，集中在 `apps/server/src/agents/schemas.ts`（Zod Schema）或各包的类型文件中。

### 示例

```typescript
// ❌ 不推荐 — 在业务组件中内联辅助函数
const formatDate = (d: Date) => d.toISOString().split('T')[0];

// ✅ 推荐 — 沉淀到共享 utils
// apps/web/src/utils/date.ts
export function formatDate(d: Date): string {
  return d.toISOString().split('T')[0];
}

// 业务组件中
import { formatDate } from '@/utils/date';
```

### 落地检查

- 新增函数时，AI Agent 应先 `search_content` 检索相似逻辑
- Code Review 时关注 `function` / `const.*=>` 在非 `utils/` 目录下的新增

---

## 2. 类型安全边界 (Type-Safe Boundaries)

> **原则**：禁止对外部数据进行"猜测性"访问，所有系统边界必须有运行时校验。

### 规则

- **API 响应、LocalStorage 读取、User Input、postMessage** 等外部数据，必须经过运行时校验后再使用。
- 后端使用 **Zod**（项目已引入 `zod@^3.25`）进行运行时 Schema 校验。
- 前端在接收 SSE 响应或 postMessage 时，同样需要类型守卫或 Zod 校验。
- **禁止 `any`**：业务代码中严禁使用 `any` 类型（测试文件中可酌情放宽）。
- **减少 `as` 断言**：仅在类型系统确实无法推断时允许，且必须附注释说明原因。
- 必须为所有数据结构定义严格的 `interface` 或 `type`。

### 示例

```typescript
// ❌ 不推荐 — 盲信外部数据
const data = await api.get('/user') as any;
console.log(data.profile.name);

// ✅ 推荐 — Zod 边界校验
import { z } from 'zod';

const UserSchema = z.object({
  profile: z.object({ name: z.string() }),
});

type User = z.infer<typeof UserSchema>;

const raw = await api.get('/user');
const data = UserSchema.parse(raw); // 运行时校验 + 类型推断
```

```typescript
// ❌ 不推荐 — postMessage 无校验
window.addEventListener('message', (e) => {
  const { type, payload } = e.data; // 可能是任意数据
});

// ✅ 推荐 — 类型守卫
interface HotUpdateMessage {
  type: 'asset-swap' | 'config-tweak' | 'scene-reload' | 'full-reload';
  payload: Record<string, unknown>;
}

function isHotUpdateMessage(data: unknown): data is HotUpdateMessage {
  return typeof data === 'object' && data !== null && 'type' in data;
}

window.addEventListener('message', (e) => {
  if (!isHotUpdateMessage(e.data)) return;
  // 此处 e.data 已有完整类型推断
});
```

### 落地检查

- 新增 API 调用时，必须同步定义 Schema 或 interface
- CI / Code Review 关注 `as any`、`: any`、无校验的 `.data` 直接访问

---

## 3. 状态管理不变性 (Immutable State)

> **原则**：全局状态变更必须通过受控的 Actions，确保逻辑集中且可追踪。

### 规则

- 前端使用 **Pinia** `defineStore`，状态变更**只能**通过 `actions` 进行，禁止在组件中直接 `store.$patch` 或修改 `store.xxx`。
- 后端的会话状态（`CodeGenState`、`SessionState`）变更必须通过对应的 Service 方法，不能在路由处理函数中直接操作。
- 复杂的状态变更逻辑应当拆分为独立的、可测试的纯函数。
- 避免在 `watch` / `computed` 中产生副作用（如修改其他 state）。

### 示例

```typescript
// ❌ 不推荐 — 组件中直接修改 store 状态
const editorStore = useEditorStore();
editorStore.previewUrl = newUrl; // 绕过了 action

// ✅ 推荐 — 通过 action 修改
// stores/editorStore.ts
export const useEditorStore = defineStore('editor', {
  state: () => ({
    previewUrl: '',
  }),
  actions: {
    setPreviewUrl(url: string) {
      this.previewUrl = url;
    },
  },
});

// 组件中
const editorStore = useEditorStore();
editorStore.setPreviewUrl(newUrl);
```

```typescript
// ❌ 不推荐 — 路由中直接操作内部状态
router.post('/generate', async (req, res) => {
  session.state.artifacts.push(newArtifact); // 绕过 service 层
});

// ✅ 推荐 — 通过 service 方法
router.post('/generate', async (req, res) => {
  await artifactService.addArtifact(sessionId, newArtifact);
});
```

### 落地检查

- 新增 store 属性时，必须同步添加对应的 action
- 禁止在 Vue 组件的 `<script setup>` 中直接赋值 store 响应式属性
- 后端状态操作必须经过 `services/` 层

---

## 速查表

| 场景 | ❌ 禁止 | ✅ 正确做法 |
|------|---------|------------|
| 辅助函数 | 业务文件内 inline 定义 | 沉淀到 `utils/` 或 `services/` |
| API 响应 | `as any` + 直接访问属性 | Zod `parse()` / 类型守卫 |
| 类型声明 | `any`、宽松 `as` 断言 | 严格 `interface` / `type` |
| 前端状态 | 组件中 `store.xxx = val` | 通过 Pinia `actions` |
| 后端状态 | 路由中直接操作内部数据 | 通过 Service 层方法 |
| postMessage | 无校验直接解构 `e.data` | 类型守卫函数过滤 |
