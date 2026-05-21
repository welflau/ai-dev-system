---
description: AI 辅助生成 commit message 并提交 git staged 变更
args_hint: "[消息]"
requires_project: true
---

# /commit [消息]

对当前 git staged 变更执行提交。

## 用法

```
/commit                      LLM 分析 staged diff，自动生成 commit message，确认后提交
/commit "fix: 修复登录逻辑"  直接使用指定的 commit message 提交
```

## 流程

1. 检查 `git diff --staged` 是否有变更
2. 若无指定消息，调用 LLM 分析 diff 生成符合 Conventional Commits 格式的 message
3. 执行 `git commit -m <message>`

提交前建议先用 `/diff --staged` 确认变更内容。
