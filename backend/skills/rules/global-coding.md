---
alwaysApply: false
priority: medium
description: 编码细则（命名 / 文档 / commit / 错误处理 / 测试）；写代码或 CodeReview 时按需加载，不每轮常驻
scene: coding
---

# 全局编码细则

> 本文件 **不** alwaysApply。闲聊 / 查状态不注入；写代码、改仓库、CodeReview 时再加载。

## 命名约定

- **常量**：全大写 + 下划线（`MAX_RETRIES`、`DEFAULT_TIMEOUT`）
- **布尔变量**：`is_` / `has_` / `should_` 前缀（python），或 `b` 前缀（C++/UE 生态）
- **私有成员**：单下划线前缀 `_internal_state`（或语言对应约定）
- **避免**：单字符变量（除了 `i/j/k` 循环索引 + `x/y/z` 坐标）、拼音命名、无意义缩写

## 文档注释

- **所有 public API** 必须有文档注释，至少包含 `@param` 和 `@return`（或语言对应的 docstring 格式）
- 复杂算法的核心逻辑段必须有 `why` 级别的注释（不解释 `what`，解释为什么这么做）
- 代码写不清楚的地方才写注释；**清楚的代码不要画蛇添足**

## Commit Message

- 第一行 ≤ 70 字符；推荐 Conventional Commits：`<type>(<scope>): <subject>`
  - type: `feat / fix / docs / refactor / test / chore / perf / ci / build / style`
- 正文跟主题空一行，可用中文详细说明
- 不要在 commit message 里放 secret / log dump / 超长 stack trace

## 错误处理

- **不吞异常**：`except: pass` 在大多数情况是 bug，要么记 log 要么向上抛
- 能明确预期的异常才 catch，不要 `except Exception` 扫一切
- log 级别分清：`debug / info / warning / error` —— 生产环境默认 info 及以上

## 测试

- 新增逻辑要有对应测试（单测 / 集成测试）
- Bug 修复必须附**能复现 bug 的测试用例**，防止退化
- 测试文件命名：`_test_*.py` / `*_test.py` / `*.test.ts` 按项目风格

## 文件修改边界

- 不要顺手重构无关代码；想重构发独立 commit
- 删文件前**先确认没有其它地方引用**
- 删除大段代码前先看提交历史，确认不是别人刚加的
