---
description: 初始化项目 .ads/ 目录（/ads-init 别名）
args_hint: "[--claude] [--force]"
requires_project: true
---

# /init [选项]

等同于 `/ads-init`，初始化项目的 AI 工作流配置目录。

## 用法

```
/init              初始化 .ads/ 目录（若检测到 .claude/ 则进入扩展模式）
/init --claude     同时生成 .claude/ 骨架 + CLAUDE.md + ADS.md
/init --force      强制覆盖已存在的文件
```
