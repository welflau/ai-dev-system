# MCP run_command：CLI 工具长命令实时进度方案

**日期**：2026-06-26  
**状态**：设计中 📐  
**背景**：TClaude 执行 UBT 编译等长命令时，前端任务面板只能等命令结束后一次性看到输出，无法实时显示进度。

---

## 一、问题背景

### 当前架构

```
用户 → TClaude(CLI) → Bash 工具
                       ↓
                    子进程运行（UBT 编译 2~5 分钟）
                       ↓
                    完成后 tool_result 一次性返回
                       ↓
                    llm_client 截取 50000 字符推给前端
```

**问题：**

1. **实时进度缺失**：TClaude 的 `stream-json` 协议中，`tool_result` 在命令**完成后**才推送，中间无任何进度事件。UBT 跑两分钟，面板一直显示"等待输出…"。

2. **AI 无感知过程**：TClaude 只拿到最终 stdout，无法在编译中途发现并响应异常（如链接错误出现在第 30 秒但命令在第 2 分钟才退出）。

3. **Bash 工具限制**：TClaude 内置 Bash 工具没有回调接口，无法在执行中途向外推数据。

---

## 二、技术路线选择

### 路径 A：System Prompt 指令 + MCP report_progress（否决）

要求 TClaude 在长命令执行时周期性调 MCP 工具上报进度。

**问题**：TClaude 执行 Bash 时是阻塞的，无法同时调其他工具。此路不通。

### 路径 B：MCP run_command 工具（采用）✅

在 `ads_data_mcp_server.py` 注册 `run_command` MCP 工具，**替代** Bash 执行长命令：

```
TClaude → MCP run_command(cmd, cwd)
              ↓  后端 asyncio.create_subprocess_exec
              ↓  stdout 逐行 → event_manager SSE → 前端实时滚动
              ↓  命令退出
              ↓  返回 {exit_code, stdout_tail(最后200行), duration_s}
TClaude 拿到结构化结果 → 继续推理（知道成功/失败/错误信息）
```

**优势：**
- TClaude 调用是**同步阻塞**的——工具返回时命令已完成，AI 拿到完整结果继续推理
- 前端实时刷新——后端 spawn 逐行推 SSE
- 结构化返回——`exit_code`、`stdout_tail`、`duration_s`，AI 可直接判断成功/失败

---

## 三、详细实现步骤

### Step 1：后端 — ads_data_mcp_server.py 注册 run_command 工具

#### 1.1 工具描述（让 TClaude 在合适场景优先调用）

```python
@mcp.tool()
async def run_command(
    command: str,       # 完整命令行，如 "cmd /c UBT.bat TP_Blank Win64 Development"
    cwd: str = "",      # 工作目录，为空时使用项目 git_repo_path
    timeout_s: int = 600,  # 超时秒数，默认 10 分钟
) -> str:
    """
    执行 shell 命令并实时推送输出到前端任务面板。
    适合耗时超过 5 秒的命令：UBT 编译、打包、批处理脚本等。
    返回结构化结果：{ exit_code, stdout_tail(最后200行), duration_s, success }
    """
```

#### 1.2 实现逻辑

```python
async def run_command(command, cwd="", timeout_s=600):
    task_id = generate_id("CLI")
    # 1. 创建后台任务记录（推 SSE 给前端，让面板显示任务卡片）
    await _publish_cli_task_start(task_id, command[:80])

    start = time.time()
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,  # 合并 stderr，统一推送
        cwd=cwd or None,
    )

    lines = []
    async for raw_line in proc.stdout:
        line = raw_line.decode("utf-8", errors="replace").rstrip()
        lines.append(line)
        # 实时推到前端
        await _publish_cli_task_line(task_id, line)

    await asyncio.wait_for(proc.wait(), timeout=timeout_s)
    duration_s = round(time.time() - start, 1)

    await _publish_cli_task_done(task_id, proc.returncode, duration_s)

    # 返回给 TClaude：最后 200 行 + 退出码 + 耗时
    tail = "\n".join(lines[-200:])
    return json.dumps({
        "exit_code": proc.returncode,
        "success": proc.returncode == 0,
        "duration_s": duration_s,
        "stdout_tail": tail,
    }, ensure_ascii=False)
```

#### 1.3 SSE 推送辅助函数

```python
async def _publish_cli_task_start(task_id, title):
    await event_manager.publish("global", "cli_task_start", {
        "task_id": task_id, "title": title, "status": "running"
    })

async def _publish_cli_task_line(task_id, line):
    await event_manager.publish("global", "cli_task_line", {
        "task_id": task_id, "line": line
    })

async def _publish_cli_task_done(task_id, exit_code, duration_s):
    await event_manager.publish("global", "cli_task_done", {
        "task_id": task_id,
        "status": "success" if exit_code == 0 else "error",
        "exit_code": exit_code,
        "duration_s": duration_s,
    })
```

> **注意**：MCP server 是独立进程，无法直接调 `event_manager`。
> 解决方式：MCP server 通过 HTTP 调 ADS 后端的内部 API `/api/internal/cli-task-event` 推事件，后端再转发 SSE。

---

### Step 2：后端 — 新增内部事件接收 API

在 `backend/api/chat.py` 或新建 `backend/api/internal.py`：

```python
@internal_router.post("/cli-task-event")
async def cli_task_event(req: CliTaskEventRequest):
    """MCP server 调此接口推 CLI 任务事件，后端转发 SSE"""
    etype = req.event_type  # cli_task_start / cli_task_line / cli_task_done
    data  = req.data

    if etype == "cli_task_start":
        _cli_task_add(data["task_id"], data["title"], "run_command")
    elif etype == "cli_task_line":
        t = _CLI_TASKS.get(data["task_id"])
        if t:
            t["output_lines"].append(data["line"])
            t["output_lines"] = t["output_lines"][-2000:]  # 最多保留 2000 行
    elif etype == "cli_task_done":
        _cli_task_finish(data["task_id"], ..., data["duration_s"] * 1000,
                         data["exit_code"] == 0)

    # 推 SSE 到前端
    project_id = data.get("project_id", "")
    if project_id:
        await event_manager.publish_to_project(project_id, etype, data)
    else:
        await event_manager.publish("global", etype, data)
    return {"ok": True}
```

---

### Step 3：前端 — 监听新 SSE 事件

在 `frontend/app.js` 的 SSE eventSource 监听器里加三个新事件：

```javascript
// CLI 任务启动（MCP run_command 调用时）
eventSource.addEventListener('cli_task_start', e => {
    const d = JSON.parse(e.data);
    _cliTaskRegister(d.task_id, d.title, 'run_command', 'running');
    _openTasksPanel();
});

// 实时输出行
eventSource.addEventListener('cli_task_line', e => {
    const d = JSON.parse(e.data);
    const t = _CLI_TASKS_MEM[d.task_id];
    if (t) {
        t.output = (t.output || '') + d.line + '\n';
        // 若该任务当前被选中，刷新右侧
        const outputEl = document.getElementById('tasksPanelOutput');
        if (outputEl?.dataset.activeTaskId === d.task_id) {
            _renderCliTaskOutput(d.task_id, outputEl);
        }
    }
});

// 完成
eventSource.addEventListener('cli_task_done', e => {
    const d = JSON.parse(e.data);
    const t = _CLI_TASKS_MEM[d.task_id];
    _cliTaskUpdate(d.task_id, d.status, t?.output || '', d.duration_s * 1000);
});
```

---

### Step 4：System Prompt 指令（让 TClaude 优先用 run_command）

在 `ChatAssistant` 的 system prompt 里加一段：

```
## 长命令执行规范
对于预期耗时超过 5 秒的命令（UBT 编译、打包、大量文件操作等），
优先使用 MCP 工具 `run_command` 而非 Bash，原因：
- run_command 会将输出实时推送到用户的任务面板
- 返回结构化结果（exit_code / stdout_tail / duration_s），便于你判断成功/失败
- 不会因为 Bash 超时截断而丢失错误信息
```

---

## 四、数据流全景

```
用户："帮我编译 TestFPS"
    │
    ▼
TClaude 推理 → 决定调 MCP run_command
    │
    ▼
ads_data_mcp_server.run_command(cmd="UBT ...", cwd="F:/ADS_Projects/TestFPS")
    │
    ├─→ POST /api/internal/cli-task-event {cli_task_start}
    │       ↓ SSE → 前端 → 面板弹出，左侧出现 "🔄 UBT 编译"
    │
    ├─→ spawn UBT 子进程
    │   ├─→ 每输出一行: POST /api/internal/cli-task-event {cli_task_line}
    │   │       ↓ SSE → 前端 → 右侧输出区实时滚动
    │   ├─→ ...
    │   └─→ 进程退出
    │
    ├─→ POST /api/internal/cli-task-event {cli_task_done, exit_code=0}
    │       ↓ SSE → 前端 → 左侧图标变 ✅
    │
    └─→ 返回给 TClaude: {"exit_code":0, "success":true, "duration_s":47.3, "stdout_tail":"...Build succeeded..."}
            │
            ▼
        TClaude 继续推理："编译成功，现在可以启动编辑器验证了"
```

---

## 五、关键设计决策

| 问题 | 决策 | 原因 |
|------|------|------|
| MCP server 如何推 SSE | HTTP 回调到后端内部 API | MCP server 是独立进程，不共享 event_manager |
| stderr 如何处理 | 合并到 stdout（`STDOUT`） | 编译错误通常在 stderr，合并后 AI 能看到 |
| TClaude 如何知道结果 | 返回 JSON 字符串 | MCP tool 返回值就是 TClaude 的 tool_result |
| 超长输出截断 | 保留最后 200 行给 AI，全量存内存给前端 | AI 只需要知道结果，前端展示全量 |
| 现有 Bash 工具 | 保留，不废弃 | 短命令仍走 Bash，无需强制改变 TClaude 行为 |

---

## 六、文件改动清单

| 文件 | 改动 |
|------|------|
| `backend/ads_data_mcp_server.py` | 新增 `run_command` 工具，调内部 API 推事件 |
| `backend/api/chat.py` 或新文件 | 新增 `/api/internal/cli-task-event` 接收接口 |
| `backend/main.py` | 注册 internal router |
| `frontend/app.js` | 监听 `cli_task_start/line/done` SSE 事件 |
| `backend/agents/chat_assistant.py` | System Prompt 补充 run_command 使用规范 |

---

## 七、后续扩展

- **kill 支持**：`/tasks` 面板加"终止"按钮，调 `/api/internal/cli-task-kill/{task_id}`
- **持久化**：任务记录写 DB，重启后仍可查历史输出
- **项目隔离**：SSE 推到 `project:{project_id}` 频道而非 `global`
