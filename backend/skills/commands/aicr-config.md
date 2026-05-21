---
description: 查看或切换 AICR 开关（autoaicr / precommit / off）
args_hint: "[autoaicr|precommit|all|off]"
requires_project: false
---

# /aicr-config [选项]

查看或切换 AI 代码审查配置。

## 用法

```
/aicr-config             查看当前 AICR 状态
/aicr-config autoaicr    切换 AutoAICR（写文件后自动审查）开关
/aicr-config precommit   切换 PreCommit（提交前深度扫描）开关
/aicr-config all         开启所有审查
/aicr-config off         关闭所有审查
```

## 说明

- **AutoAICR（默认开启）**：Agent 完成文件编辑后自动触发，轻量行为约束检查（keep-scope、no-todo-left 等）
- **PreCommit（默认关闭）**：需手动通过 `/aicr-check` 触发，或在 `.ads/config.json` 中设置 `"precommit": true` 后由 pre-commit hook 自动触发
