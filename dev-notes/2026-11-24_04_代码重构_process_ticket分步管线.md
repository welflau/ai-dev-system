# `process_ticket` 改成分步管线（2026-11-24）

> 关联方案：`docs/20261124_01_代码重构方案.md`（R0 第 3 步、R2 第 2 步）
> 前一篇：`dev-notes/2026-11-24_03_代码重构_拆分结果处理器.md`
> 提交基线：`7b9e7f0`；本篇的代码和文档都在工作区，**尚未提交**。

## 背景

上一步拆完 `_handle_agent_result` 之后，全仓最长的函数是 `TicketOrchestrator.process_ticket`：
682 行，圈复杂度 113，全量测试下的行覆盖率是 0%。它是每张工单每一轮流转的入口，出口有十几个。
方案要求先补特征测试再动结构，本轮照这个顺序做：先在原代码上把每个出口钉住，再把函数体搬成分步管线。
外部行为不变。

## 做了什么

### 1. 特征测试（R0 第 3 步的 `process_ticket` 部分）

新增 `backend/tests/agents/test_orchestrator_process_ticket.py`，1,213 行，73 条用例。
其中 59 条是拆分前写的行为用例，14 条是拆分后补的管线约定用例。

- 夹具：真实 SQLite 加 `init_tables()`，`TicketOrchestrator.__new__` 造实例，三个假 Agent
  （`DevAgent`、`UXAgent`、`SkillAgent`）。
- 真跑的部分：占用和释放处理权、两种止损计数、`_log`、Agent 忙闲标记、`current_action` 读写、
  `_execute_assigned_agent`、非代码工单和无界面工单的判断。断言直接查库里的工单、`ticket_logs` 和 SSE 记录。
- 打桩的部分：规则表、SOP 阶段、上下文构建、结果处理、心跳、阶段回退、诊断、Git、检查点、
  `tickets_fts`、Failure Library、`asyncio.sleep`。
- 59 条行为用例分十一组：
  1. 入口门闩：已被占用、上一轮 CLI 还在跑、工单不存在、6 个硬终态、需求暂停或取消；
  2. 全局止损：累计打回 5 次、同因连续失败 3 次、验收打回不计入同因、解除阻塞后计数清零；
  3. 前置依赖：未完成时等待、`testing_done` 和 `deployed` 算完成、自引用和坏 JSON 被忽略、只对 pending 生效；
  4. 规则匹配：无规则、状态修复后再匹配、阶段级 `max_retries` 止损、缺 `next_status` 时的兜底；
  5. 跳过阶段：非代码工单跳过编译类阶段、无界面工单跳过 UX 和美术设计、三种不跳过的情况；
  6. Agent 未注册；
  7. 正常派单：状态和日志、SSE 顺序、LLM 上下文、心跳、检查点、续跑事件、SOP 配置和人工评论注入、skill 阶段；
  8. 切分支：成功、已在目标分支、失败且停在主分支、失败但不在主分支、Git 抛异常；
  9. 反思记录：三处写入，以及任何一处失败都不影响后续；
  10. 排队中的阶段回退：应用、工单已终态时放弃、会前跳时放弃；
  11. 异常和取消：Agent 抛异常、选出 Agent 前后出错的区别、异常后回退仍生效、取消原样抛出。
- 每条用例都检查处理权有没有释放。

59 条在未改动的 `process_ticket` 上首次运行就全部通过。写之前列了七处可能和现状对不上的地方
（状态列的约束、同一秒内多条日志的排序、contextvar 的行为等），实际都没有出现。
首次全绿也可能是断言太松，所以另外做了改坏检查，见「验证」一节。

拆分前这 59 条单独跑时，`process_ticket` 的行覆盖率是 94.1%（273 条语句漏 16 条），
分支 90 条走到 82 条。漏掉的 16 行都是延迟导入失败、日志写入失败这类 `except` 兜底。

### 2. 拆分（R2 第 2 步）

新增 `backend/orchestration/ticket_pipeline.py`，914 行：

- `TicketRun`：一次 `process_ticket` 调用里各步骤共享的状态，字段和原来的局部变量同名
  （`ticket`、`current_status`、`rule`、`agent_name`、`action`、`next_status`、`context`、`result`），
  另有 `agent_chosen`、`stopped_at`、`stop_reason`。
- 17 个步骤函数，签名都是 `async def step(run) -> Optional[str]`。返回 `CONTINUE`（即 `None`）进入下一步，
  返回原因字符串表示本轮到此为止。
- `STEPS` 元组登记执行顺序，`run_pipeline(run)` 按顺序执行。

| 顺序 | 步骤 | 行数 | 可能的停止原因 |
|---|---|---|---|
| 1 | `load_ticket` | 35 | `live_cli`、`ticket_not_found` |
| 2 | `check_entry_gates` | 33 | `hard_terminal`、`requirement_inactive` |
| 3 | `check_global_circuit_breaker` | 73 | `global_circuit_breaker` |
| 4 | `check_dependencies` | 41 | `waiting_dependencies` |
| 5 | `match_rule` | 25 | `no_rule` |
| 6 | `check_stage_retry_limit` | 54 | `stage_retry_limit` |
| 7 | `select_agent` | 21 | 无 |
| 8 | `skip_inapplicable_stage` | 74 | `stage_skipped` |
| 9 | `ensure_agent_registered` | 39 | `agent_not_registered` |
| 10 | `assign_ticket` | 43 | 无 |
| 11 | `switch_to_feature_branch` | 28 | `branch_switch_failed_on_main` |
| 12 | `build_agent_context` | 44 | 无 |
| 13 | `run_agent` | 76 | 无 |
| 14 | `record_reflection` | 10 | 无 |
| 15 | `handle_result` | 24 | 无 |
| 16 | `apply_pending_restart` | 37 | `status_rewound` |
| 17 | `publish_next_stage` | 18 | 无 |

`record_reflection` 下面还有三个小函数：`_log_reflection`（42 行）、`_index_reflection`（24 行）、
`_record_failure_case`（25 行）。

`process_ticket` 留在 `orchestrator.py`，剩 77 行，只做外层骨架：

1. `_try_claim_ticket`，失败就返回；
2. 登记 `_running_tasks`；
3. 构造 `TicketRun`，`await ticket_pipeline.run_pipeline(run)`；
4. `except CancelledError`：记 warning 后原样抛出；
5. `except Exception`：`run.agent_chosen` 为真时给 Agent 记一次失败，写 `error` 日志，发 `ticket_error`；
6. `finally`：释放处理权，兜底应用排队的阶段回退，清检查点上下文。

步骤体是用脚本从原函数按行号区间搬出来的，改动有六处：

1. 缩进减 8 格（反思的三个小函数减 12 格）；
2. `self.` 换成 `orch.`；
3. 跨步骤的局部变量在步骤开头从 `run` 取，写入它的步骤在末尾存回 `run`；
4. 裸 `return` 换成带原因的 `return "..."`，步骤末尾加 `return CONTINUE`；
5. `load_ticket` 里去掉一个没用到的 `clear_checkpoint_context` 导入；
6. `run_pipeline` 在有步骤停止时多打一条 debug 级日志，内容是停在哪一步和原因。

第 6 处是本轮唯一新增的可观察行为，只在 debug 级别可见。

### 3. 配套改动

- `backend/tests/agents/test_dispatch_gate.py`：`test_poll_once_skips_held_tickets_before_zombie` 原来断言
  `process_ticket` 的源码里有 `_ticket_heartbeat`，改成断言 `ticket_pipeline.run_agent` 的源码，
  并确认 `run_agent` 登记在 `STEPS` 里。
- `backend/tests/agents/test_orchestrator_skill_branch.py`：`test_process_ticket_calls_execute_assigned_agent`
  原来在 `orchestrator.py` 文本里找 `await self._execute_assigned_agent(`，改成在 `ticket_pipeline.py` 里找
  `await orch._execute_assigned_agent(`；「不许出现 `agent.execute(action, context)`」这条对两个文件都查。
- `desktop.spec`：`hiddenimports` 增加 `orchestration.ticket_pipeline`。
- `backend/layers.toml` 不用改，`orchestration` 前缀上一步已经归入 L1。

## 设计决定

- **步骤是模块级函数，接收 `run`。** 方案写的是「每步一个方法」。放在类上会让 `TicketOrchestrator`
  再多 20 个方法，和 R2 第 3 步按职责拆类的方向相反，所以放进 `orchestration/`，和结果处理器的做法一致。
- **`db` 经 `run.db` 传入。** 和上一步同理：测试用 `monkeypatch.setattr(orchestrator, "db", test_db)` 换库，
  步骤里自己导入 `db` 会让这个桩失效。`event_manager`、`git_manager` 是按对象属性打桩的，
  新模块导入的是同一个对象，桩照常生效。
- **`'agent_name' in dir()` 换成 `run.agent_chosen`。** 原来的异常处理靠「局部变量 `agent_name` 有没有被赋值」
  判断要不要给 Agent 记一次失败。函数体搬走后这个局部变量不存在了。`select_agent` 取到 `rule["agent"]`
  的下一行就把 `run.agent_chosen` 置真，置真的时机和原来变量被赋值的时机相同。有两条用例钉着这个边界：
  选出 Agent 之前出错不动任何 Agent 的计数，选出之后出错就记一次。
- **`run.ticket` 取到就登记。** 外层的 `except` 和 `finally` 要读工单的 `requirement_id` 和 `type`。
  原来靠函数开头的 `ticket = None` 兜底，现在是 `TicketRun.ticket` 的默认值 `None`。
- **`run.ticket` 不刷新。** 派单后数据库里的状态已经改成进行中，`run.ticket` 仍是派单前读到的那一行。
  `trigger_status` 和结果处理都依赖这一点，原代码也是这样。
- **步骤在同一个协程里直接 `await`。** 检查点上下文和 LLM 上下文都是 contextvar。
  步骤如果另起任务执行，前面步骤设的上下文对后面的步骤就不可见了。
- **延迟导入原样保留。** `llm_client`、`checkpoint`、`capability_check`、`api.knowledge`、`failure_library`
  仍在函数内导入。测试的桩打在这些源模块上，位置不变桩就不用动。
- **停止原因是字符串。** 目前只有两个用途：debug 日志，以及测试里核对「停在了预期的那一步」。
  没有做成枚举，等有调用方真正按原因分支时再收紧。

## 和方案的偏差

1. 方案列了 8 步（加载、熔断检查、返工与重试判定、规则匹配、选 Agent、构建上下文、执行、反思），
   实际是 17 步。多出来的是原函数里本来就有、方案没单列的段落：入口门闩、前置依赖、跳过阶段、
   Agent 未注册、派单、切分支、结果处理、排队回退、续跑。
2. 方案要求每步不超过 80 行，这一条满足：最长的 `run_agent` 是 76 行。
3. 步骤是函数，没有做成方法，理由见上。
4. 步骤仍然通过 `orch._log`、`orch._set_agent_busy` 这样的私有成员干活，一共用到 24 个私有方法和 3 个属性。
   这层耦合要到 R2 第 3 步拆出协作者之后才能解开。
5. 步骤内部的逻辑没有整理。`check_global_circuit_breaker` 和 `check_stage_retry_limit` 里
   「改 blocked、写日志、发事件、起诊断」是两份相似的代码，本轮没有合并，合并会改变搬移的可核对性。

## 验证

环境：Windows，Python 3.14.3；flake8 用的是另一个 Python 3.12.13 环境（flake8 7.5.0）。

| 检查 | 结果 |
|---|---|
| 59 条行为用例，拆分前 | 全部通过 |
| 59 条行为用例，拆分后 | 全部通过，测试代码没有改 |
| 14 条管线约定用例 | 全部通过（步骤顺序 1 条、停止原因 12 条、走完全程 1 条） |
| 改坏检查 | 15 处故意改错，全部被测试发现 |
| 搬移核对脚本 | 7 项全部通过 |
| 相关用例（结果分支、skill 分支、派单门闩、demo 链路） | 通过；两条源码断言按上面的说明改过 |
| 全量 pytest | 998 条通过（原 925 加新增 73），退出码 0 |
| `python scripts/check_layers.py` | 退出码 0；模块 487；方向违规 92 条，相对基线新增 0 |
| `flake8 --select=E9,F63,F7,F82` | 0 条（排除项见下） |
| `py_compile` | `orchestrator.py` 和 `ticket_pipeline.py` 通过 |
| 上一步的 AST 对比脚本 | 重跑仍然全部一致 |

**改坏检查。** 59 条用例首次运行就全绿，需要确认它们真能发现问题。做法是逐个把代码改错一处，
跑这份测试文件，看有没有用例变红，然后恢复。15 处是：跳过阶段时先发事件后释放、`agent_chosen` 不置真、
两处止损的 `>=` 改成 `>`、不清 LLM 上下文、不写 `trigger_status`、续跑前不释放、依赖检查不限 pending、
Agent 不标空闲、Failure Library 的失败类型写反、回退生效后不停止、主分支上切换失败后继续执行，
以及外层骨架的三处（`finally` 不释放、无条件给 Agent 记失败、吞掉取消）。15 处全部有用例变红。
这项检查是在拆分后的代码上做的。

**搬移核对脚本。** 这次控制流变了，不能像上一步那样逐分支比 AST。`ticket_pipeline.py` 是由脚本按行号区间
从拆分前的 `orchestrator.py` 生成的，核对脚本检查七件事：

1. 重新生成的结果和磁盘上的文件逐字节相同，说明生成之后没有手工改动；
2. 原函数体第 2141 到 2752 行，每一行恰好被搬走一次；没搬的 18 行都是步骤之间的空行；
   `STEPS` 的顺序和原代码的行序一致；
3. 每个步骤写过的共享变量都存回了 `run`；没有步骤读到还没写入的字段；
4. 原函数里跨越步骤边界的局部变量一共 9 个，8 个在 `TicketRun` 上，`last_reflection` 作为参数传递；
5. 原函数的局部变量和新模块的模块级名字没有重名；
6. 行数和圈复杂度（见下表）；
7. `orchestrator.py` 在 `process_ticket` 之外的部分，和拆分前只差一行导入。

生成脚本和核对脚本都放在临时目录，没有进仓库。

**覆盖率。** 73 条用例单独跑时，`ticket_pipeline.py` 的 422 条语句漏 10 条（97.6%），
84 条分支有 7 条没走全，语句和分支合计 96.6%。`process_ticket` 外层骨架的 38 条语句漏 6 条。
漏掉的仍然都是 `except` 兜底。

**flake8 的排除项。** CI 的命令排除了 `skills/marketplace`、`skills/packs`、`skills/use_skills`。
本机 `backend/projects/` 下有运行时生成的项目代码，其中一个文件有 3 条 F824。这个目录没有被 git 跟踪，
CI 上不存在，本机检查时一并排除了。

## 度量变化

| 指标 | 拆分前 | 拆分后 |
|---|---|---|
| `orchestrator.py` 行数 | 5,841 | 5,236 |
| `process_ticket` 行数 | 682 | 77 |
| `process_ticket` 圈复杂度 | 113 | 19 |
| 管线里最长的步骤 | — | `run_agent` 76 行 |
| 管线里圈复杂度最高的步骤 | — | `skip_inapplicable_stage` 13 |
| `orchestrator.py` 里超过 200 行的函数 | 4 | 3 |
| `orchestrator.py` 里超过 150 行的函数 | 9 | 8 |
| 全仓超过 200 行的函数 | 31 | 30 |
| 全仓超过 300 行的函数 | 10 | 9 |
| 全仓最长函数 | `process_ticket` 682 行 | `query_engine/engine.py` 的 `run` 559 行 |
| 最大 Python 文件 | `orchestrator.py` 5,841 行 | `api/chat.py` 5,566 行 |
| 模块总数（守卫口径） | 486 | 487 |
| 未归层模块 | 230 | 230 |
| 延迟导入占比 | 42.3% | 42.2% |

从 `7b9e7f0` 算起，`orchestrator.py` 从 6,694 行降到 5,236 行。全仓的函数统计是本轮用临时脚本按方案附录的
文件范围重算的；「全仓超过 300 行」的拆分前数字是由拆分后的 9 加回 `process_ticket` 得到的。
`api/chat.py` 有另一批未提交的改动，5,566 是工作区里的行数。

## 特征测试钉住的可疑现状

这几处是写测试时读出来的，测试按现状断言，本轮没有修：

1. **切分支失败且停在主分支时，工单卡在进行中。** 这一步排在派单之后。停止时工单已经是进行中状态、
   Agent 已标忙碌，这条路径不会改回去，也不写日志。目前靠轮询里的僵尸检测兜底。
2. **Agent 抛异常后，工单停在进行中，LLM 上下文不清。** 异常处理会写 `error` 日志、发 `ticket_error`、
   给 Agent 记一次失败，但不改工单状态，`clear_llm_context` 也被跳过。
3. **选出 Agent 之后、标忙碌之前出错，也会给这个 Agent 记一次失败。** 例如读 SOP 阶段时抛异常。
   这时 Agent 其实还没开始干活。
4. **两处止损各写了一份相似的收尾代码**，见「和方案的偏差」第 5 条。

前三条要不要改、怎么改，需要确认。改之前这些用例会先变红，改的时候同步更新断言即可。

## 没有验证的部分

- **桌面版打包。** `desktop.spec` 只确认了语法能解析，没有实际打包和启动。
- **真实服务启动和端到端流程。** 没有起服务跑一张真实工单。真实的 Git 切分支、检查点、CLI 流式调用
  在测试里都是桩。
- **Linux 和 CI。** 只在本机 Windows 上跑过。
- **根目录的 `_test_*.py` 脚本。** 没有跑。搜过一遍，没有脚本读 `process_ticket` 的源码。
  `_test_command_log.py` 有一条检查在 `orchestrator.py` 文本里找 `requirement_id=ticket.get`，
  原来有 3 处匹配，搬走 2 处后还剩 1 处，检查仍然成立，但它现在匹配到的不一定是当初想锁的那一行。

## 已知影响

- 读 `process_ticket` 源码做断言的代码要改看 `ticket_pipeline`。仓库里搜到的两处都已改。
- 代码注释和文档里有十来处 `orchestrator.py:行号` 形式的引用，行号在上一步拆分时就已经对不上，
  本轮没有逐个修。
- 往 `process_ticket` 里加逻辑时，改成往 `STEPS` 里加步骤或改对应的步骤函数。
  跨步骤要用的值放到 `TicketRun` 上。
- 异常堆栈会多两层（`run_pipeline` 和步骤函数），日志里的 logger 名仍是 `orchestrator`。

## 遗留与后续

1. `_handle_skill_agent_result`（255 行）搬进 `result_handlers/`，它已有 `test_orchestrator_skill_branch.py` 保护。
2. `handle_requirement`（456 行，覆盖率 1%）补特征测试，它是 `orchestrator.py` 里剩下的最长函数。
3. R2 第 3 步按职责拆类。步骤对 `orch` 私有方法的依赖到时一起整理。
4. 上面三处可疑现状是否要修。
5. R0 的其余几步都还没做：度量脚本和基线、CI 覆盖率、`_call_cli_stream` 和聊天流的特征测试、
   83 个业务模块补归层、根目录脚本归位。本轮用到的度量脚本和核对脚本可以作为 `scripts/code_metrics.py` 的起点。
6. 工作区现在叠了四批未提交改动（`ai_gen_tasks`、体检修复第一批、结果处理器、本轮管线），提交时建议分开。

## 复核命令

```powershell
# 特征测试和相关用例，在 backend/ 下执行
cd backend
python -m pytest tests/agents/test_orchestrator_process_ticket.py tests/agents/test_orchestrator_result_branches.py tests/agents/test_orchestrator_skill_branch.py tests/agents/test_dispatch_gate.py tests/e2e/test_demo_chain.py -q -p no:cacheprovider

# 全量
python -m pytest -q -p no:cacheprovider
cd ..

# 分层守卫，在仓库根目录执行
python scripts/check_layers.py
```
