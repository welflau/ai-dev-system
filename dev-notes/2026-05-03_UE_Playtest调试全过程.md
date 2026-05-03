# 开发日志 — 2026-05-03 UE Playtest 调试全过程

## 背景

v0.19 ② UE run_playtest 功能代码早已完成，但一直未真机验收。
今天系统性排查，发现并修复了 4 个叠加问题，最终验收通过。

---

## 问题一：asyncio.create_subprocess_exec 抛空异常

**现象**：点"跑 Automation"，日志显示：
```
[playtest] cmd: UnrealEditor-Cmd.exe ...
[error] 启动 Editor-Cmd 异常:
✗ playtest 失败
```
异常消息完全为空，耗时 0s。

**根因**：Python 3.14 + Windows `ProactorEventLoop` 与 UE 子进程创建不兼容。
`asyncio.create_subprocess_exec` 抛出 `NotImplementedError()`，该异常 `str(e) == ""`。
老代码用 `f"异常: {e}"` 格式化，就显示成空字符串。

`ue_compile_check.py` 早已遇到同样问题并修复（注释里有记录），
但 `ue_playtest.py` 和 `ue_package.py` 没有同步这个修复。

**修复**：改用 `subprocess.Popen + asyncio.Queue + daemon 线程读取`：
```python
proc = subprocess.Popen(cmd, stdout=PIPE, stderr=STDOUT, encoding="utf-8")
loop = asyncio.get_event_loop()
queue = asyncio.Queue()

def _reader_thread():
    for line in proc.stdout:
        loop.call_soon_threadsafe(queue.put_nowait, line.rstrip())
    loop.call_soon_threadsafe(queue.put_nowait, _sentinel)

threading.Thread(target=_reader_thread, daemon=True).start()
```

---

## 问题二：Python .pyc 字节码缓存导致修复不生效

**现象**：改了代码、重启服务器，日志还是老行为（无 `-stdout`，无 DLL 检查）。

**根因（复合）**：

1. **多进程叠加**：每次"重启"只杀了部分进程，`SO_REUSEADDR` 允许多个进程同时监听 8000 端口，最老的进程（跑最老代码）优先响应。最多时有 8 个进程同时在线。

2. **stale .pyc**：`ue_playtest.cpython-314.pyc` 修改时间为 12:22，比 `.py` 文件(20:59)旧，但 uvicorn 热重载的 worker 进程在某些情况下读到旧 bytecode。

3. **reload_includes 不递归**：`reload_includes=["*.py"]`（单星）只匹配 `backend/` 根目录，不匹配子目录（如 `actions/ue_playtest.py`）。换成 `**/*.py` 后子目录改动才能触发热重载。

**修复**：
- `main.py` 改为 `reload_includes=["**/*.py"]`
- 每次重启前必须用 `Get-Process python | Stop-Process -Force` 杀死**所有** Python 进程
- 调试期间可删除 `__pycache__/*.pyc` 确保加载最新代码

**教训**：uvicorn 热重载 + Windows 在多次重启后容易形成"僵尸进程"堆积。
出现"改了代码没效果"时，首先怀疑有旧进程在运行。

---

## 问题三：DLL 检查路径错误

**现象**：UBT 编译成功（1m 31s）后，Automation 测试立刻报：
```
游戏模块未编译：找不到 F:\Projects\TestTPS\Binaries\Win64\MyFPS.dll
```

**根因**：UE5 Editor 编译产出的 DLL 命名规则是 `UnrealEditor-{ProjectName}.dll`，
代码里检查的是 `{ProjectName}.dll`（UE4 风格）。

实际文件：`F:\Projects\TestTPS\Binaries\Win64\UnrealEditor-MyFPS.dll`

**修复**：按优先级依次查找：
```python
dll_candidates = [
    binaries_dir / f"UnrealEditor-{proj_name}.dll",  # UE5 Editor
    binaries_dir / f"{proj_name}.dll",                 # UE4 Game
    binaries_dir / f"{proj_name}Editor.dll",           # UE4 Editor
]
```

---

## 问题四：UE 无测试用例时 exit=1 被误判为失败

**现象**：Playtest 跑了 18s，输出 1171 行，`0/0 failed`，但显示失败。

**根因**：UE Automation Framework 找不到匹配 `Project.` filter 的测试用例时，
以 exit code 1 退出。这对于新建 C++ 项目（无 `IMPLEMENT_SIMPLE_AUTOMATION_TEST`）是正常行为。

旧判断：`exit_code == 0 and failed == 0` → success，否则 playtest_failed。

**修复**：
```python
no_tests = total == 0 and failed == 0
if (exit_code == 0 or no_tests) and failed == 0:
    status = "success"
```

---

## 其他修复

**UE 无 stdout 输出**：加 `-stdout -FullStdOutLogOutput` 参数，
强制 UE 把日志写入管道（否则只写 `.log` 文件，subprocess 读不到任何输出）。

**日志末行截断**：`raw_output_tail` 按 8192 字节硬切会截断最后一行（"LogExit: Exi"）。
修复：找到 8192 字节内的第一个换行符，从该换行后开始取内容。

---

## 最终验收结果

```
UBT 编译  → 成功（1m 31s）→ 生成 UnrealEditor-MyFPS.dll
Playtest  → 成功（18s）  → 0/0 tests，no failures
```

---

## 变更文件

| 文件 | 变更 |
|---|---|
| `backend/actions/ue_playtest.py` | Popen 替换；-stdout；DLL 检查（UE5/4）；0-test 判断 |
| `backend/actions/ue_package.py` | Popen 替换（预防） |
| `backend/ci/strategies/ue.py` | error_message 回填；日志行边界截断 |
| `backend/main.py` | `reload_includes=["**/*.py"]` |

commit: `06969c2`, `3047783`
