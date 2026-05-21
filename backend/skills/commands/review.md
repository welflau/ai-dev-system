---
description: 对 git staged diff 做 PreCommit 代码审查（/aicr-check 别名）
args_hint: ""
requires_project: true
---

# /review

等同于 `/aicr-check`，对当前项目的 `git diff --staged` 做完整 PreCommit 代码审查。

检查内容：空指针、数组越界、资源泄漏、SQL 注入、安全漏洞、测试覆盖等。

**推荐流程**：
1. `git add` 要提交的文件
2. `/diff --staged` 确认变更
3. `/review` 做代码审查
4. `/commit` 提交
