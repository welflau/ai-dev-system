---
alwaysApply: false
pack: code-quality
paths:
  - "**/*.py"
priority: high
description: Python 文件专属规范（类型注解 / 异常处理 / 异步 / 安全）
---

# Python 编码规范

> 仅在编辑 .py 文件时注入。

## 一、类型注解

- 所有 public 函数**必须**有参数和返回值类型注解
- 使用 `Optional[T]` 表示可为 None，Python 3.10+ 可用 `T | None`
- 集合类型用泛型：`list[str]`、`dict[str, int]`、`tuple[int, ...]`
- 复杂类型用 `TypeAlias` 或 `TypedDict` 命名

## 二、异常处理

- 禁止裸 `except:` 和 `except Exception: pass`（吞异常）
- 捕获具体异常类型（`except FileNotFoundError`）
- 必须记录或重新抛出：`logger.warning(...); raise` 或 `raise NewException(...) from e`
- 资源操作用 `with` 语句（文件、锁、数据库连接）

## 三、异步（asyncio）

- async 函数只在 async 上下文中 `await`
- CPU 密集操作放 `loop.run_in_executor`，不阻塞事件循环
- `asyncio.gather` 处理并行任务
- 数据库/网络 I/O 统一用异步库（`aiohttp`、`aiosqlite` 等）

## 四、安全

- 用户输入进 SQL 必须参数化（`?` 占位符），**绝不**字符串拼接
- `subprocess` 调用必须用列表形式（`subprocess.run(["cmd", "arg"])`），**禁止** `shell=True`
- 文件路径来自外部时必须用 `pathlib.Path.resolve()` 规范化，防止路径穿越
- 不要把密钥/token 硬编码；从 `os.getenv()` 或配置服务读取

## 五、代码风格（PEP 8）

- 缩进 4 空格
- 行长 ≤ 120 字符（项目设定）
- 模块导入顺序：标准库 → 第三方 → 本地（isort 约定）
- 命名：`snake_case` 变量/函数，`PascalCase` 类，`UPPER_SNAKE` 常量
- 私有成员前缀 `_`，强私有 `__`（触发 name mangling）

## 六、测试

- 测试文件命名 `_test_*.py` 或 `*_test.py`
- 每个 public 函数至少一个正常路径测试
- 用 `pytest.mark.parametrize` 覆盖边界值，不要复制粘贴测试
