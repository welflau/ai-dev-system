---
alwaysApply: true
priority: high
description: 全项目通用规范（语言一致性 / 命名 / 文档 / 安全），跟技术栈正交
---

# 全局编码准则

> 本准则对所有 Agent、所有项目、所有文件生效，无条件注入。
> 跟技术栈正交：不关心是 Python / Godot / UE / 小程序，以下条目都适用。

## 一、语言一致性（最高优先级）

**代码本体必须用英文**：
- 变量名 / 函数名 / 类名 / 方法名 → 英文
- 枚举值 / 常量 / 配置 key → 英文
- 文件名 / 目录名 → 英文
- Git 分支名 → 英文（feat/xxx、fix/yyy）
- **Commit message 第一行** → 英文

**允许用中文的地方**：
- 行内注释（`// 这里做 xxx`）
- 文档字符串 / docstring（若团队习惯中文）
- 提交消息正文（第二段以后可中文详细说明）
- 日志消息字符串 / 错误提示字符串（面向用户的）
- Markdown 文档 / 设计文档 / dev-note

**禁止**：
- 中文标识符（`变量名 = 1`）
- 中英混写的名称（`getUserBy编号()`）
- 中文全角标点出现在代码里（`，。；：""''`）

## 二、命名约定

- **常量**：全大写 + 下划线（`MAX_RETRIES`、`DEFAULT_TIMEOUT`）
- **布尔变量**：`is_` / `has_` / `should_` 前缀（python），或 `b` 前缀（C++/UE 生态）
- **私有成员**：单下划线前缀 `_internal_state`（或语言对应约定）
- **避免**：单字符变量（除了 `i/j/k` 循环索引 + `x/y/z` 坐标）、拼音命名、无意义缩写

## 三、文档注释

- **所有 public API** 必须有文档注释，至少包含 `@param` 和 `@return`（或语言对应的 docstring 格式）
- 复杂算法的核心逻辑段必须有 `why` 级别的注释（不解释 `what`，解释为什么这么做）
- 代码写不清楚的地方才写注释；**清楚的代码不要画蛇添足**

## 四、安全红线（硬禁止）

**绝不生成或写入**：
- API Key / Secret / Token / 私钥等凭证
- 数据库连接串（含密码）
- 硬编码的用户密码 / 管理员凭证
- 内网 IP / 生产数据库地址

**凭证相关必须**：
- 从环境变量读（`os.getenv("API_KEY")`）
- 或从专门的凭证管理服务读
- `.env` 文件**必须**加进 `.gitignore`

**不要碰的文件**（这些对 AI 是禁区）：
- `.env` / `.env.*`
- `credentials.*` / `secrets.*` / `*.pem` / `*.key` / `id_rsa*`
- `.git/` 目录内容（metadata 由 git CLI 操作）
- 任何含 `password` / `secret` / `token` 命名的配置文件

## 五、Commit Message 约定

- 第一行 ≤ 70 字符，用英文或简短中文
- 推荐 Conventional Commits 格式：`<type>(<scope>): <subject>`
  - type: `feat / fix / docs / refactor / test / chore / perf / ci / build / style`
  - 例：`feat(v0.17): add trait-first skill loader`
- 正文跟主题空一行，可用中文详细说明
- 不要在 commit message 里放 secret / log dump / 超长 stack trace

## 六、错误处理

- **不吞异常**：`except: pass` 在大多数情况是 bug，要么记 log 要么向上抛
- 能明确预期的异常才 catch（`except FileNotFoundError`），不要 `except Exception` 扫一切
- log 级别分清：`debug / info / warning / error` —— 生产环境默认 info 及以上

## 七、测试

- 新增逻辑要有对应测试（单测 / 集成测试）
- Bug 修复必须附**能复现 bug 的测试用例**，防止退化
- 测试文件命名：`_test_*.py` / `*_test.py` / `*.test.ts` 按项目风格

## 八、文件修改边界

- 不要顺手重构无关代码（"路过"式的改动）；想重构发独立 commit
- 删文件前**先确认没有其它地方引用**（`grep -r 文件名 .`）
- 删除大段代码前先 `git log --follow` 看提交历史，确认不是别人刚加的

---

以上规则**必须遵守**。违反任一条的产出会被 CodeReview 打回。
