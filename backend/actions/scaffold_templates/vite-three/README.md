# {{PROJECT_TITLE}}

Vite + TypeScript + Three.js 项目骨架，由 AI 自动开发系统确定性生成（不经 LLM）。

## 目录结构

```
index.html            入口页面
vite.config.ts        Vite 构建配置
tsconfig.json         TypeScript 严格模式配置
src/main.ts           渲染循环与场景入口
src/types/scene.ts    共享类型定义层
src/utils/math.ts     共享数学工具层
```

后续业务模块请复用 `src/types/scene.ts` 的 `SceneContext`，不要各自创建渲染器。

## 本地开发

```bash
npm install
npm run dev
```

## 校验

```bash
npm run typecheck   # tsc --noEmit
npm run build       # tsc && vite build
```
