---
description: 初始化项目 .ads/ 目录（rules/ skills/ config.json），根据项目 traits 生成对应规则模板
args_hint: ""
requires_project: true
---

# /ads-init

在当前项目仓库创建 `.ads/` 目录结构，并根据项目类型（traits）自动生成对应规则模板：

```
.ads/
├── rules/
│   ├── project-rules.md      ← 项目通用规范（常驻，无 paths:）
│   ├── cpp-rules.md          ← C++ 专属规范（ue5/c++ 项目自动生成）
│   ├── ts-rules.md           ← TypeScript 专属规范（ts 项目自动生成）
│   └── workflow/
│       └── autoaicr.md       ← 项目级 AutoAICR 补充规则
├── skills/                   ← 项目 Skill 目录
├── mcp_servers.json          ← 项目级 MCP 配置（覆盖全局层）
└── config.json               ← 项目配置（traits / aicr 等）
```

## 规则文件格式

每个规则文件支持以下 frontmatter：

```yaml
---
alwaysApply: true          # true=常驻注入，false=按条件
paths:                     # 文件匹配（有 paths 时按需注入）
  - "**/*.cpp"
  - "**/*.h"
scene: ""                  # 场景过滤（autoaicr / precommit / 空=所有）
priority: medium           # high / medium / low
description: "规则说明"
---
```

## 生成逻辑

执行后，读取项目 `config.json` 中的 `traits` 列表，按以下规则生成模板文件：

- 所有项目 → 生成 `project-rules.md`（alwaysApply: true）
- traits 含 `ue5` / `unreal` → 生成 `cpp-rules.md`（paths: *.cpp/*.h）
- traits 含 `typescript` / `react` → 生成 `ts-rules.md`（paths: *.ts/*.tsx）
- traits 含 `python` → 生成 `python-rules.md`（paths: *.py）
- 所有项目 → 生成 `workflow/autoaicr.md`（scene: autoaicr）
- 所有项目 → 生成 `mcp_servers.json`（项目级 MCP 配置模板，含注释说明）

已存在的文件不会被覆盖（加 `--force` 参数强制覆盖）。

初始化后：
- 编辑 `.ads/rules/` 下的规则文件写入项目编码约定
- 编辑 `.ads/mcp_servers.json` 启用/禁用/添加项目专属 MCP server（或使用 `/mcp-config` 命令管理）
