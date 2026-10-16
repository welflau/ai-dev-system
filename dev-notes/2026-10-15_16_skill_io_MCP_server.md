# skill_io MCP server（2026-10-15）

2026-10-15

方案文档：`docs/20261015_01_能力自描述与动态组装框架方案.md`
前置：`2026-10-15_15_CLI模式工具缺陷查清.md`

## 一、做了什么

补上 CLI 模式下 skill builtin 工具的唯一可行通道。

```
backend/skills/skill_io_mcp_server.py            新增（4 个 MCP 工具）
backend/llm_client.py                            +20 行（skill_io contextvar + 条件注入）
backend/skills/runner.py                         +40 行（进出上下文）
backend/skills/executable_skills/demo-*/SKILL.md body 补 MCP 工具名
backend/tests/skills/test_skill_io_mcp_server.py 28 用例
backend/tests/skills/test_cli_mode_tool_gap.py   重写为 22 用例
```

## 二、缺陷本身没修，也不打算在那层修

`QueryEngine.run` 的 CLI 分支仍然不传 tools——CLI 的工具循环由 CLI 自己控制，ADS 没法把 Python 侧的 callable 塞进去。

**绕过去的方式是 MCP**：CLI 能命名调用 `mcp__<server>__<tool>`。`openspec_mcp_server.py` 已经证明这条路可行，本轮照抄它的套路。

三条证据测试保留了下来（放在 `test_cli_mode_tool_gap.py`），作用从「记录缺陷」变成「MCP 方案存在的前提」——哪天 CLI 支持工具透传，`test_cli_stream_still_has_no_tools_param` 会红，提醒 skill_io 可以退役。

## 三、核心设计：LLM 不碰路径

```python
_OUTPUT_ROOT = os.environ.get("SKILL_OUTPUT_ROOT", "")

async def write_output(filename: str, content: str) -> str:
    # 签名里没有 path / dir / root
```

产出目录通过环境变量传给 MCP server 进程，LLM 只给文件名。

这正是原生 Write 出问题的地方——它的相对路径基于 cwd(=仓库根)，而产出目录在 `artifacts/{req}/{ticket}/{kind}/`。让 LLM 传路径等于把「产出落在哪」的决定权交出去。

写了测试直接检查 `write_output` 的签名里不含 `path`/`dir`/`root`。

## 四、四个工具

| 工具 | 替代 | 关键点 |
|---|---|---|
| `write_output(filename, content)` | write_file | 自动去 ``` 围栏、扩展名白名单、拒绝路径穿越 |
| `read_repo_file(path)` | read_file | 仓库内越界校验、**二进制明确报错**、60k 字符截断 |
| `gen_image(prompt, filename, ...)` | gen_image | **委托 GenImageAction**，不重写校验 |
| `list_outputs()` | — | 让 LLM 确认自己写了什么，避免重复产出 |

`read_repo_file` 对二进制**明确报错**而非返回乱码——返回乱码的话 LLM 会以为读到了内容，然后基于垃圾数据往下做。

`gen_image` 在函数内部按 `SKILL_BACKEND_DIR` 延迟 import `GenImageAction`。模块级不能 import backend（MCP server 是独立进程，启动时 sys.path 里没有 backend），但也不想把参数校验和零字节检测写第二份——两份实现迟早漂。写了测试断言模块级没有 backend import。

## 五、contextvar 的进出

```python
# SkillRunner.execute
self._enter_skill_io_context(out_root, context)
try:
    async for ev in engine.run(...): ...
finally:
    self._exit_skill_io_context()   # 必须清
```

不清的后果：contextvar 不会自动还原，后续的普通聊天调用会带着上一个 skill 的产出目录，LLM 调 `write_output` 会把文件写进别的工单的产物目录。

只在 skill 声明了 `outputs.root` 时进入——只读 skill（openspec-validate）不需要 write_output。

## 六、第 11 次假绿：`asyncio.run` 把污染隔离了

注入「去掉 finally 清理」→ 测试全绿。

原因：

```python
asyncio.run(runner.execute(...))      # 新建 Context
assert _llm_ctx.skill_io is None      # 主线程读的是旧 Context
```

`asyncio.run` 为协程建独立 Context，退出后主线程读 contextvar 读到的永远是旧值——**哪怕 execute 真的泄漏了**。

实测确认：

```
循环内: polluted
asyncio.run 之后: None  ← 污染没传出来
```

真实场景里 SkillRunner.execute 和后续 LLM 调用在同一个循环里，污染是会传播的。改成**在 async 函数内部断言**（把 `_llm_ctx.skill_io` 当返回值带出来），再注入立刻红。顺带补了成功路径的同款测试。

### 假绿形态累计 11 种

| # | 形态 |
|---|---|
| 1 | 场景在当前实现下不可能发生 |
| 2 | 两种实现产出相同结果 |
| 3 | 输入恰好触发了兜底路径 |
| 4 | 调用次数不够 |
| 5 | 代码路径无任何断言覆盖 |
| 6 | 返回值相同，差异只在副作用 |
| 7 | 测试绕过集成点，只测内部函数 |
| 8 | 通过靠的是别处的过滤，不是被测逻辑 |
| 9 | 输入被更早的分支接走 |
| 10 | 验了结果但没验「结果是怎么来的」 |
| 11 | **测试的执行环境把被测的污染隔离了** |

11 和 7 同源但更隐蔽：7 是「没走真实路径」，11 是「走了真实路径但观察点在错误的上下文里」。

**补充判断**：测 contextvar / 线程局部 / 进程环境这类「隐式上下文」时，观察点必须和被测代码在**同一个上下文实例**里。

## 七、skill body 补 MCP 工具名

LLM 看不到 ADS 的内部实现，只看 body。CLI 模式下它手里只有 `mcp__skill_io__*`，body 里只提 `write_file` 会让它找不到工具而改用原生 Write。

照 openspec-propose 的写法——两种命名都列出来：

```markdown
2. 写入 `outline.md` —— 用 `write_file`，或 MCP 形式的
   `mcp__skill_io__write_output`（CLI 模式下只有后者可用）。
   **不要用原生 Write/Bash**：产出目录由框架决定，原生工具的相对路径
   基于仓库根，写出去的文件回收不到。
```

写了参数化测试断言三个 demo skill 都有对应的 MCP 名 + 原生工具警告。

## 八、变异测试（5 注入，4 抓 1 补）

| 注入 | 结果 |
|---|---|
| A. 不注入 skill_io server | 3 红 ✓ |
| B. execute 不清上下文 | **全绿 → 改观察点后 2 红** |
| C. write_output 加 path 参数 | 1 红 ✓ |
| D. 文件名不做白名单 | 5 红 ✓ |
| E. 读二进制返乱码 | 1 红 ✓ |

## 九、验证

```bash
cd backend && python -m pytest tests/ -q    # 364 passed in 119s
python -c "import main"
```

测试总数 322 → 364（新增 42：MCP server 28 + CLI gap 重写净增 14）。

另外真跑了 MCP 的四个工具函数（不启 stdio 协议，直接调 async）：

```
write: {'ok': True, 'filename': 'outline.md', 'bytes': 8} | 落盘: '# 大纲'  (围栏已去)
  拒绝 '../x.md' / 'a/b.md' / 'x.exe' / '': True
read: True | # 上游内容
  越界: True
  二进制: True | upstream/bin.png 不是 UTF-8 文本...
list: {'ok': True, 'files': [{'path': 'outline.md', 'bytes': 8}]}
```

## 十、仍未做的真机验证

**没有在真实 CLI 进程里跑通一次。** 已验证的是：
- MCP server 的工具逻辑（直接调函数）
- `--settings` 里确实注入了 skill_io 及其 env
- contextvar 的进出与清理

未验证的是 **CLI 是否真的会调用 `mcp__skill_io__write_output`**。这取决于 CLI 对 MCP 工具的识别与选择，属于外部行为。openspec 的同款方案在生产里跑通过，所以路径是可信的，但 skill_io 自己没跑过。

需要一个能跑通的 LLM 环境来验（上一轮 500s 超时未返回）。

## 十一、遗留（更新）

1. **真实 CLI 跑通一次 skill** —— 验证 CLI 会选用 MCP 工具
2. LightAI key 401 —— 修复后补真实出图
3. 3 处 trait 漂移（i18n / multiplayer:true / prototype:html）
4. 11 项 DB trait 漂移 —— detector 侧需要词表约束
5. 阶段间并行度 —— `dispatch_subtask`
