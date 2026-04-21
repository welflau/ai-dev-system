# React / HTML 开发最佳实践

> 本项目前端倾向单文件部署（`index.html` 内联 `<script>`），不走 webpack / 构建链路。

## 单文件优先原则

- **默认把所有前端代码写到单个 `index.html`**：`<style>` + `<script>`（React via CDN / 纯 JS）直接内联，用户打开文件即可运行
- 只有在需求明确要求"多页面"或"单独模块复用"时，才拆分独立的 `.js` / `.css`
- 不要产生 `package.json` / `webpack.config.js` / `vite.config.ts` 等构建配置文件（除非需求要求）

## React Hooks 规范（如果用 React）

| 规则 | 说明 |
|------|------|
| 只在函数组件顶层调 Hooks | 不在 if/for/嵌套函数里调，否则渲染顺序错乱 |
| 自定义 Hook 必须以 `use` 开头 | `useAuth`、`useLocalStorage` |
| `useEffect` 依赖数组要完整 | 漏写依赖会产生闭包陷阱 |
| `useState` 初始值用函数惰性计算 | `useState(() => expensiveInit())` |

```jsx
// 好 — 依赖完整，惰性初始化
function Counter() {
  const [count, setCount] = useState(() => parseInt(localStorage.visits || "0"));
  useEffect(() => {
    localStorage.visits = count;
  }, [count]);
  return <div>{count}</div>;
}
```

## 命名约定

| 类型 | 约定 | 示例 |
|------|------|------|
| 组件名 | PascalCase | `UserCard`, `LoginForm` |
| Hook | `use` + camelCase | `useFetch`, `useLocalStorage` |
| 事件处理 | `handle` + 动作 | `handleSubmit`, `handleClick` |
| 布尔 props | `is` / `has` / `can` 前缀 | `isLoading`, `hasError` |
| 常量 | SCREAMING_SNAKE_CASE | `MAX_RETRIES`, `API_BASE` |

## 可见 DOM 是产品验收的硬门槛

本系统有个反复踩过的坑：DevAgent 写了后端逻辑声称"访问计数功能完成"，但页面上根本没有可见的计数器元素，被 ProductAgent 打回。

**硬规则**：

1. 凡是用户提到的"功能"，页面上**必须有可见的 DOM 元素**来呈现它。不能只有 JS 变量 / localStorage 读写
2. 位置明确时（"右下角"、"顶部导航"）用 `position: fixed` 等 CSS 固定到该位置
3. 初始化 JS 在 `</body>` 前，或用 `DOMContentLoaded` 保证元素已挂载
4. 自测时必须打开页面肉眼（或用 Playwright 截图）确认元素可见，不能只跑后端单测

```html
<!-- 访问计数器示例 -->
<body>
  <div id="visit-counter"
       style="position:fixed;bottom:10px;right:10px;padding:6px 12px;background:#333;color:#fff;border-radius:4px;font-family:sans-serif;">
    访问次数: <span id="visit-count">0</span>
  </div>
  <script>
    const count = parseInt(localStorage.visits || "0") + 1;
    localStorage.visits = count;
    document.getElementById("visit-count").textContent = count;
  </script>
</body>
```

## 样式规范

- 优先用**原生 CSS**（写到 `<style>` 标签里），避免引入 TailwindCSS / styled-components 等依赖
- 用 CSS 变量做主题色：`--primary: #1a1a2e`
- 响应式用 `@media (max-width: 768px)`，不要用 JS 计算窗口大小
- 保留 `box-sizing: border-box` 重置：`*{box-sizing:border-box;margin:0;padding:0}`

## 安全要点

- 渲染用户输入时用 `textContent` 而不是 `innerHTML`，防 XSS
- fetch 本地 API 时加 try/catch，网络失败不要让整个页面挂
- 存 localStorage 前 `JSON.stringify`，读时 try/catch 一下
