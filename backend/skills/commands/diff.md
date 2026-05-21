---
description: 查看当前项目 git diff（工作区或 staged）
args_hint: "[--staged] [文件路径]"
requires_project: true
---

# /diff [选项]

查看当前项目的 git 变更。

## 用法

```
/diff              查看工作区变更（git diff）
/diff --staged     查看 staged 变更（git diff --staged）
/diff src/foo.cpp  查看指定文件变更
```

结合 `/review` 使用：先 `/diff --staged` 确认变更内容，再 `/review` 做代码审查。
