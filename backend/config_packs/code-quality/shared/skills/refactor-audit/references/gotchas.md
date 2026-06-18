# Gotchas（踩坑记录）

## G-001: 误判测试代码为重复代码

**症状**：审计报告将测试文件中的 setup/teardown 代码标记为"重复逻辑未提取"。

**原因**：测试文件中的相似 setup 代码是刻意为之——每个测试用例应保持独立性，共享 setup 反而增加耦合。

**✅ 正确做法**：
```typescript
// 测试中的重复 setup 是允许的，跳过 duplication 维度
// 只有业务代码（apps/、packages/src/）中的重复需要标记
```

**❌ 错误做法**：
```typescript
// 将所有 test setup 提取为共享 helper → 测试间产生隐式依赖
```

**触发条件**：扫描范围包含 `__tests__/`、`*.spec.ts`、`*.test.ts` 文件时。

---

## G-002: 忽略 Vue SFC 特殊语法

**症状**：审计工具对 `.vue` 文件中的 `<script setup>` 语法报出误判，如"顶层变量未导出"或"函数定义不符合模块化规范"。

**原因**：Vue SFC 的 `<script setup>` 中的顶层绑定会自动暴露给模板，不需要显式 export。`defineProps`、`defineEmits` 等编译器宏也不需要 import。

**✅ 正确做法**：
```vue
<script setup lang="ts">
// defineProps 是编译器宏，无需 import
const props = defineProps<{ title: string }>()

// 顶层变量自动暴露给 template，无需 export
const count = ref(0)
</script>
```

**❌ 错误做法**：
```
// 将 <script setup> 中缺少 export 标记为"未导出变量"
// 将 defineProps/defineEmits 标记为"未导入的函数调用"
```

**触发条件**：扫描 `apps/web/` 中的 `.vue` 文件时。

---

## G-003: 跨包 type-only import 误判为耦合

**症状**：审计报告将 `import type { Foo } from '@vgc/shared-types'` 标记为跨包耦合问题。

**原因**：`type-only import` 在编译后会被完全擦除，不产生运行时依赖。`shared-types` 包的设计目的就是被所有包引用。

**✅ 正确做法**：
```typescript
// type-only import 不算耦合——编译后完全擦除
import type { UnifiedMessage } from '@vgc/shared-types'

// 这些共享包是被设计为跨包引用的：
// - @vgc/shared-types
// - @vgc/sse-protocol
// - @vgc/sandbox-protocol
```

**❌ 错误做法**：
```typescript
// 将 type-only import 标记为 coupling 维度的问题
// 建议将共享类型内联到每个包中
```

**触发条件**：扫描到从 `packages/` 导入类型的语句时。

---

## G-004: 误判 Pinia Store 的 `$patch` 为绕过 action

**症状**：审计报告将 Pinia 的 `$patch()` 调用标记为"绕过 actions 直接修改 state"。

**原因**：`$patch()` 是 Pinia 提供的官方批量更新 API，本身就是一种 action。真正需要标记的是直接赋值 `store.someState = value`。

**✅ 正确做法**：
```typescript
// $patch 是 Pinia 官方 API，允许使用
store.$patch({ loading: true, error: null })

// 需要标记的是组件中直接赋值
// store.loading = true  ← 这才是绕过 action
```

**❌ 错误做法**：
```
// 将 $patch() 调用标记为 state 维度的问题
```

**触发条件**：扫描 `apps/web/src/stores/` 或组件中的 store 调用时。

---

## G-005: 忽略 monorepo 内部包的路径别名

**症状**：审计报告将 `@vgc/xxx` 标记为外部依赖，建议锁定版本。

**原因**：`@vgc/` 前缀是 monorepo 内部包的 scope，通过 pnpm workspace 协议引用，不是 npm 外部包。

**✅ 正确做法**：
```jsonc
// package.json 中 workspace: 协议 = 内部包
"dependencies": {
  "@vgc/shared-types": "workspace:*"
}
```

**❌ 错误做法**：
```
// 将 @vgc/ 开头的 import 视为外部依赖
// 建议为内部包锁定具体版本号
```

**触发条件**：审计 `package.json` 或 import 语句时遇到 `@vgc/` 前缀。

---

## G-006: ESM 函数声明的循环 import 在运行时是安全的

**症状**：把一个大模块拆成两个伴生文件时，发现双方要互相调用对方的函数，误以为必须把共享函数抽到第三个"common"模块才能破循环。

**原因**：ESM 对**函数声明**有 hoisting 语义。`module A` 与 `module B` 相互 `import` 时，加载器会先把双方的 module record 建好，再按拓扑顺序执行顶层代码。只要：

1. 两边互引的都是 `function` 声明（非 `const = () =>`）
2. 调用点在**另一个函数的函数体内部**（不在模块顶层初始化期执行）

那么当实际调用发生时，双方的函数引用都已就绪，运行时安全。

**✅ 正确做法**：
```ts
// verifyFixer.ts
export function computeScore(checks) { ... }
import { attachRubricPreviewAndBenchmark } from './hybridEvidenceRubric.js';
export function verifyGeneratedCode(state) {
  attachRubricPreviewAndBenchmark(report);
}

// hybridEvidenceRubric.ts
import { computeScore } from './verifyFixer.js';
export function attachRubricPreviewAndBenchmark(report) {
  let score = report.score ?? computeScore(report.checks);
}
```

**❌ 错误做法（过度抽象）**：
```ts
// 为破循环硬拉出 computeScore.ts
// 然后两边都从那里 import
// 结果是把一个清晰的双文件结构变成三文件，且 computeScore 失去语义归属
```

**触发条件**：重构/拆分一个大模块为两个伴生文件时，双方需要共享 1-2 个工具函数。

**反例**：**共享 type**（`type` / `interface`）仍然应该抽到独立的 `types.ts`。虽然 TS 会把 type-only import 擦除，不会有运行时循环，但独立的 types 文件能避免 `export type` 路径耦合，也让消费者 import 更干净。本次 `verifyFixerTypes.ts` 就是这样处理的。

**关联决策**：`docs/arch/codegen-architecture.md §12.1`（verifyFixer/fixLoop/hybridEvidenceRubric 三模块拆分）
