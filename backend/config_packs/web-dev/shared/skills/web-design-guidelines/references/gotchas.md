# Gotchas（踩坑记录）

> 本项目（Vibe Game Creator）前端设计常见踩坑点。执行 `build`、`review`、`resilience` 模式时建议先浏览本文件。

---

## G-001: TailwindCSS 深色模式下的对比度不足

**症状**：深色模式下文字或图标与背景对比度不够，难以辨识；WCAG AA 检查不通过。

**原因**：直接在 `dark:` 变体中使用浅灰色文字（如 `dark:text-gray-400`），未验证与深色背景的对比度比值是否 ≥ 4.5:1。

**✅ 正确做法**：
```html
<!-- 使用对比度足够的颜色组合，确保 >= 4.5:1 -->
<p class="text-gray-700 dark:text-gray-200">正文内容</p>
<span class="text-gray-500 dark:text-gray-300">次要文字</span>
```

**❌ 错误做法**：
```html
<!-- gray-400 在 dark 背景上对比度仅 ~3:1，不达标 -->
<p class="text-gray-700 dark:text-gray-400">正文内容</p>
<span class="text-gray-500 dark:text-gray-500">次要文字</span>
```

**触发条件**：任何涉及深色模式适配的 UI 开发或审查。特别注意次要文字、placeholder、disabled 状态等低对比度场景。

---

## G-002: 沙箱 iframe 内的样式隔离

**症状**：游戏预览沙箱中的样式"泄漏"到宿主页面，或宿主页面的 TailwindCSS 全局样式影响沙箱内游戏渲染。

**原因**：iframe 的 `srcdoc` 模式或同源 iframe 会继承部分宿主样式；宿主的 CSS reset（Tailwind Preflight）可能通过同源 iframe 渗透。

**✅ 正确做法**：
```typescript
// 使用 sandbox 属性隔离，通过 blob URL 加载以实现跨域隔离
const blob = new Blob([htmlContent], { type: 'text/html' });
const url = URL.createObjectURL(blob);
iframe.src = url;
iframe.sandbox = 'allow-scripts';

// 沙箱内的游戏 HTML 应包含独立的样式重置
// <style>* { margin: 0; padding: 0; box-sizing: border-box; }</style>
```

**❌ 错误做法**：
```typescript
// srcdoc 同源模式，宿主样式可能渗透
iframe.srcdoc = htmlContent;
// 且未设置 sandbox 属性
```

**触发条件**：预览沙箱开发、游戏预览样式异常排查、iframe 通信相关功能。

---

## G-003: 分屏编辑器中的响应式布局适配

**症状**：工作台左侧面板（对话区）和右侧面板（预览/编辑器）在窄屏或分屏拖拽时布局错乱——溢出、重叠、滚动条异常。

**原因**：使用媒体查询（`@media`）断点做响应式，但分屏场景下容器宽度与视口宽度不一致；面板宽度由拖拽决定，不受视口断点控制。

**✅ 正确做法**：
```html
<!-- 使用 CSS Container Queries 基于面板实际宽度响应 -->
<div class="@container">
  <div class="@lg:grid-cols-2 @sm:grid-cols-1 grid gap-4">
    <!-- 内容根据容器宽度自适应 -->
  </div>
</div>
```
```css
/* 或使用 min-width / clamp 确保最小可用宽度 */
.panel {
  min-width: 320px;
  width: clamp(320px, 50%, 100%);
  overflow: auto;
}
```

**❌ 错误做法**：
```html
<!-- 仅依赖视口断点，分屏时无法正确响应 -->
<div class="lg:grid-cols-2 sm:grid-cols-1 grid gap-4">
  <!-- 当面板被拖到 400px 宽时，视口可能仍是 1920px，断点不触发 -->
</div>
```

**触发条件**：工作台分屏布局开发、面板拖拽调整、窄屏设备适配。

---

## G-004: 动效性能与 GPU 加速

**症状**：动画卡顿、掉帧，尤其在对话消息流式输出、预览加载过渡、面板切换等高频场景。

**原因**：对 `width`、`height`、`top`、`left` 等触发 Layout 的属性做动画，导致每帧都触发重排（reflow）；未利用 GPU 合成层加速。

**✅ 正确做法**：
```css
/* 只对 transform 和 opacity 做动画——仅触发 Composite，GPU 加速 */
.panel-enter-active {
  transition: transform 300ms ease-out, opacity 300ms ease-out;
}
.panel-enter-from {
  transform: translateX(-100%);
  opacity: 0;
}
.panel-enter-to {
  transform: translateX(0);
  opacity: 1;
}

/* 对需要动画的元素提前提升为合成层 */
.will-animate {
  will-change: transform, opacity;
}
```

**❌ 错误做法**：
```css
/* 对触发 Layout 的属性做动画，每帧重排 */
.panel-enter-active {
  transition: left 300ms ease-out, width 300ms ease-out;
}
.panel-enter-from {
  left: -100%;
  width: 0;
}
```

**触发条件**：任何涉及过渡动画、微交互、加载动效的开发。特别注意流式消息渲染（频繁 DOM 更新 + 滚动）场景下的性能。

---

## G-005: `overflow-hidden` 裁切绝对定位动作浮层

**症状**：卡片右上角的操作按钮、状态浮层或徽标在窄卡片宽度下显示不全，看起来像“明明渲染了，但下半截/右半截被吃掉了”。

**原因**：把 `overflow-hidden` 放在了外层卡片容器上，同时又让动作区使用 `position: absolute` 向外扩展。按钮从单行变成多行或浮层高度增长时，会被父容器直接裁切。

**✅ 正确做法**：
```html
<!-- 外层允许动作浮层溢出，真正需要裁切的图片区域单独包一层 -->
<div class="rounded-xl overflow-visible">
  <div class="relative overflow-hidden rounded-t-xl">
    <!-- 图片、失败态覆盖层、处理中覆盖层 -->
    <div class="absolute top-2 right-2">
      <!-- 动作浮层 -->
    </div>
  </div>
</div>
```

**❌ 错误做法**：
```html
<!-- 外层一旦 overflow-hidden，绝对定位动作区向外扩展时就会被裁切 -->
<div class="rounded-xl overflow-hidden">
  <div class="relative">
    <div class="absolute top-2 right-2">
      <!-- 多行动作按钮 -->
    </div>
  </div>
</div>
```

**触发条件**：素材卡片、图片卡片、带 hover 操作区的缩略图卡片，尤其是动作按钮数量增加或改为多行布局时。

---

## 维护指南

- 遇到新的设计踩坑点时，按 `G-XXX` 编号追加到本文件末尾
- 按频率排序：最常见的放最前面
- 每条 gotcha 必须包含"正确做法"和"错误做法"的对比
- 触发条件要具体，便于 Agent 在相关场景自动参考

---

## G-006: `tailwindcss-animate` 未安装时 `animate-in` / `fade-in` 类为 no-op

**症状**：使用 `animate-in fade-in duration-300` 等类名后，DOM 元素出现时无任何入场动画——元素直接呈现，无淡入效果。

**原因**：`animate-in`、`fade-in`、`zoom-in` 等工具类由 `tailwindcss-animate` 插件提供；若 `tailwind.config.js` 的 `plugins` 数组中未包含该插件（或该插件根本未安装），这些类名在构建产物中不存在，Tailwind 会静默忽略它们。

**✅ 正确做法**：

方案一：改用原生 Tailwind CSS 过渡工具类（推荐，无额外依赖）：
```html
<!-- 配合 v-if/v-show 的 Vue transition 或直接用 transition 类 -->
<div class="transition-opacity duration-300 opacity-0 group-hover:opacity-100">...</div>
```

方案二：安装并注册插件后再使用：
```bash
pnpm add tailwindcss-animate --filter @vibe-game-creator/web
```
```js
// tailwind.config.js
plugins: [require('tailwindcss-animate')],
```

**❌ 错误做法**：
```html
<!-- 未安装/注册插件时，animate-in fade-in 是无效类，无任何效果 -->
<div class="animate-in fade-in duration-300">...</div>
```

**触发条件**：新接手项目时引用其他项目/文档中的动画示例，或使用 shadcn-vue / radix-vue 组件库示例代码（它们默认依赖 `tailwindcss-animate`）。每次引入新的 CSS 动画工具类前，先确认 `tailwind.config.js` 中对应插件已注册。
