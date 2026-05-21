---
alwaysApply: false
scene: precommit
priority: high
description: PreCommit 场景规则：提交前的完整 Bug Pattern 扫描
---

# PreCommit 审查准则

> 本规则仅在 PreCommit 场景（/aicr-check 命令或 git commit 前）触发。
> 目标：阻止已知 Bug Pattern 入库。

## Bug Pattern 检查清单

### 空指针与空值
- [ ] 所有指针/引用解引用前是否有 null/nil 检查？
- [ ] 函数返回值为可选类型时，是否检查后再使用？
- [ ] 数组/列表访问是否有越界检查（index < length）？

### 资源管理
- [ ] 打开的文件/连接/锁是否在所有路径（包括异常路径）都有关闭/释放？
- [ ] 是否使用了 RAII / with / defer 等自动释放机制？

### 并发安全
- [ ] 多线程访问的共享变量是否有同步保护？
- [ ] 异步回调中是否有 use-after-free 风险？

### 逻辑错误
- [ ] 是否有整数溢出风险（循环计数、位运算、乘法）？
- [ ] 浮点数比较是否用了 `==`（应用 epsilon 比较）？
- [ ] switch/match 是否处理了所有枚举值（有无 default/exhaustive check）？

### 安全漏洞
- [ ] SQL 查询是否全部参数化（无字符串拼接）？
- [ ] 用户输入是否经过校验和转义再使用？
- [ ] 是否有凭证/密钥硬编码？

### 测试覆盖
- [ ] 新增的公共函数是否有对应测试？
- [ ] Bug 修复是否附有能复现 Bug 的测试用例？

## 输出格式

```
🔍 PreCommit 扫描结果：
  ✅ 通过：X 项
  ❌ 阻断：Y 项
    - [空指针] src/foo.cpp:42 — GetComponent 返回值未检查
    - [SQL注入] api/user.py:18 — 字符串拼接构建查询
  ⚠ 建议：Z 项（不阻断）
```
