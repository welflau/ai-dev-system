# {{project_name}}

## Web 项目规范

**技术栈**：{{tech_stack}}
**仓库**：{{git_remote}}

### 组件开发规范

- 组件文件名使用 PascalCase，样式文件与组件同名
- Props 必须声明 TypeScript 类型
- 副作用统一放在 `useEffect`，依赖数组不得遗漏
- 避免在渲染函数中创建对象/函数（memo/callback）

### API 调用规范

- 所有请求通过统一的 `api/` 模块发起，不直接 fetch
- 错误处理：网络错误、业务错误（非 2xx）分开处理
- Loading 状态必须反映在 UI 上，不得让用户面对空白

### 禁止事项

- 禁止在组件里直接操作 DOM（用 ref）
- 禁止 `any` 类型（用 `unknown` + 类型守卫代替）
- 禁止硬编码 API base URL（用环境变量）
