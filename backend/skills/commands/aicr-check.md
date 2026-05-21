---
description: 对当前 git staged diff 做 PreCommit 代码审查（bug pattern 扫描）
args_hint: ""
requires_project: true
---

# /aicr-check

对当前项目仓库的 `git diff --staged` 执行完整 PreCommit 代码审查。

检查内容（来自 `backend/skills/rules/workflow/precommit.md` + `.ads/rules/workflow/precommit.md`）：
- 空指针与空值解引用
- 数组/容器越界访问
- 资源泄漏（文件、连接、锁未释放）
- 并发安全问题
- SQL 注入 / XSS / 命令注入
- 整数溢出 / 浮点比较
- 测试覆盖缺失

**输出**：
- 错误项（error）：阻断型，强烈建议修复后再提交
- 建议项（suggestion）：非阻断，可选修复
