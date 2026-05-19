---
description: 初始化项目 .ads/ 目录（rules/ skills/ config.json），一键创建框架
args_hint: ""
requires_project: true
---

# /ads-init

在当前项目仓库创建 `.ads/` 目录结构：

```
.ads/
├── rules/
│   └── project-rules.md   ← 项目规范模板
├── skills/                ← 项目 Skill 目录
└── config.json            ← 项目配置（traits 等）
```

初始化后编辑 `.ads/rules/project-rules.md` 写入项目专属规范，
所有 Agent 执行时会自动读取并注入。
