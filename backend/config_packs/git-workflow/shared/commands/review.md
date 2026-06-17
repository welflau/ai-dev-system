Review the current staged changes or a specific PR.

```bash
# 查看未提交改动
git diff --staged

# 或查看指定 PR
gh pr diff <pr-number>
```

审查要点：
1. 逻辑正确性：边界条件、错误处理
2. 可读性：命名、注释必要性
3. 安全性：SQL 注入、XSS、敏感信息泄露
4. 性能：N+1 查询、不必要的循环

给出具体的行级建议，格式：`文件:行号 — 问题描述`
