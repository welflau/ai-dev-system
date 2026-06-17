---
name: web-dev-rules
description: Web 项目开发规范：组件、API、TypeScript
type: always
---

# {{project_name}} — Web 开发规范

**技术栈**：{{tech_stack}}

## 组件规范

- 文件名 PascalCase，Props 必须有 TypeScript 类型
- 副作用统一在 `useEffect`，依赖数组不遗漏
- 避免渲染函数中创建对象/函数

## API 规范

- 所有请求通过统一 `api/` 模块，不直接 `fetch`
- 网络错误和业务错误（非 2xx）分开处理
- Loading 状态必须反映在 UI

## 禁止

- 禁止 `any`（用 `unknown` + 类型守卫）
- 禁止硬编码 API base URL
