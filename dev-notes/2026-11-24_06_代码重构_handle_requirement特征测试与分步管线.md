# `handle_requirement` 特征测试与分步管线（2026-11-24）

> 关联方案：`docs/20261124_01_代码重构方案.md`（R0 第 3 步的 `handle_requirement` 部分、R2 第 2 步的延续）
> 前一篇：`dev-notes/2026-11-24_05_代码重构_skill结果处理器搬移.md`
> 提交基线：`7b9e7f0`；本篇的代码和文档都在工作区，**尚未提交**。

## 背景

`TicketOrchestrator.handle_requirement` 负责需求分析和拆单：调 ProductAgent、把回传的工单落库、回填依赖、
建开发分支、逐张派单。上一篇结束时它是 `orchestrator.py` 里最长的函数：456 行，圈复杂度 65，行覆盖率 1%。
没有测试就没法动它，所以本轮分两段做：先补特征测试并确认测试抓得住错误，再按 `process_ticket` 的做法拆成分步管线。

## 做了什么

### 1. 特征测试

新增 `backend/tests/agents/test_orchestrator_handle_requirement.py`，44 个测试函数，参数化后 63 条：60 条写在拆分之前，3 条是拆分之后补的（原因见「验证」一节）。
特征测试只记录现在的行为，不评判对错。

**夹具。** 沿用 `test_orchestrator_process_ticket.py` 的做法：真实 SQLite 加 `init_tables()`，
用 `TicketOrchestrator.__new__` 造实例，只设 `_analyzing_reqs` 和一个假的 ProductAgent。
需求初始状态是 `analyzing`。

真跑的部分：`_log`、建工单、建子任务、建子工单、回填依赖、需求状态改写、PRD 产物入库。

打桩的部分：

| 桩 | 作用 |
|---|---|
| `event_manager.publish_to_project` | 记下发出的 SSE |
| `orchestrator.llm_client` | 换成只有几个属性的对象，用来拼开场文案和超时 |
| `memory.AgentMemory` | 返回指定的代码上下文，或抛指定的异常 |
| `api.milestones.auto_associate_requirement` | 记下调用参数和当时的需求状态 |
| `git_manager` 的四个方法 | 记下调用顺序，返回值可调 |
| `session_logger.log_event` | 不往 `backend/logs/` 写文件 |
| `_log_agent_thought`、`_handle_git_files`、`process_ticket` | 记下调用；`process_ticket` 可以设成抛异常 |
| `asyncio.sleep` | 心跳的 20 秒等待改成由测试放行 |

**八组用例：**

1. 入口：已在分析、需求不存在、分析途中再次调度。
2. 准备和执行：开场文案、模型名和超时的取值顺序、代码上下文、项目 traits、`on_step` 进度、心跳、心跳失败被吞。
3. Agent 失败：回传非 success、抛异常、被取消、取消后被轮询续跑、错误兜底自身失败。
4. 记录结果：PRD 入库、产物、规则引擎降级告警、投票留痕、PRD 文件走 Git。
5. 建工单：按规模定初始状态（7 种组合）、字段默认值、`use_aigc` 继承、子任务、子工单。
6. 回填依赖：下标换工单号、自引用、越界、字符串依赖、夹了坏数据时的下标。
7. 收尾：状态、里程碑、分支（成功、切换失败、创建失败、Git 抛异常）、零工单、派单顺序。
8. 拆单中途出错。

44 个测试函数里有 14 个在结束前查占用标记已释放、没有残留的心跳任务，覆盖正常走完、重复调度、Agent 失败、
异常兜底、取消、零工单这几种出口。其余 30 个只查各自关心的结果。

### 2. 确认测试抓得住错误

**覆盖率。** 首版 56 条跑完，`handle_requirement`（原第 1552–2007 行）的 190 条语句全部执行到，
54 个分支走到 52 个。漏的两个分支都在依赖处理里：依赖全是认不出的值时建单日志不带依赖信息；
字符串形式的工单号指向自己。补 2 条之后是 190/190 条语句、54/54 个分支。此前的行覆盖率是 1%。

**改坏检查。** 覆盖率只说明代码被执行过。在原函数上逐个做 105 处故意的错误改动
（条件取反、事件改名、默认值改掉、字段丢弃、顺序对调等），每处只跑这一个测试文件，结束后恢复并核对哈希。
第一遍发现 104 处，漏 1 处：把「查不到需求就返回」的判断去掉。去掉之后函数会往下走、
在取标题时出错、进异常兜底；兜底里写日志撞外键，被最外层的 `except` 吞掉。库里和事件上都看不出痕迹，
原用例只查了这两处。给 `test_missing_requirement_returns_quietly` 加一条「没有 error 级日志」的断言后，这一处也被发现。

检查过程中又补了 2 条用例，记的是读代码时注意到的行为：

- `test_cancelled_analysis_is_picked_up_by_resume_poll`：分析被取消后，下一轮 `_resume_stuck_analyses` 会重新拆单；
- `test_dependency_indexes_follow_filtered_list`：回传里夹一条坏数据时，依赖下标整体错一位。

另有一条用例重写了造数据的方式。`test_string_dependency_on_itself_is_dropped` 原来靠替换
`orchestrator.generate_id` 拿到固定工单号，这等于把测试绑在「拆单代码住在 `orchestrator.py`」上，
拆分之后就会失效。改成在建单日志写入时把真实工单号追加进依赖列表，不再依赖代码位置。
改完后重跑了和依赖有关的 3 处改动，都被发现。

到这里测试文件是 60 条。拆分期间没有改它；拆分后的改坏检查又补了 3 条，见「验证」一节。

### 3. 拆成分步管线

新增 `backend/orchestration/requirement_pipeline.py`，678 行。结构和 `ticket_pipeline.py` 相同：
`RequirementRun` 承载步骤之间共享的状态，12 个步骤函数登记在 `STEPS` 里，`run_pipeline` 按顺序执行，
每个步骤返回 `CONTINUE` 或停止原因。

| 步骤 | 原行号 | 行数 | 做什么 |
|---|---|---|---|
| `load_requirement` | 1559–1567 | 17 | 取需求，查不到就停 |
| `announce_start` | 1569–1612 | 58 | 开场进度、`agent_working`、设 LLM 上下文 |
| `read_code_context` | 1614–1631 | 27 | 读项目已有代码 |
| `run_analysis` | 1633–1685 | 70 | 调 ProductAgent，期间写心跳 |
| `check_analysis_result` | 1687–1698 | 22 | 回传非 success 时退回已提交并停 |
| `record_analysis` | 1700–1732 | 44 | 降级告警、投票留痕、PRD 入库、PRD 文件走 Git |
| `create_tickets` | 1734–1864 | 144 | 建父工单、子任务、子工单 |
| `backfill_dependencies` | 1866–1886 | 29 | 依赖下标换成工单号 |
| `mark_decomposed` | 1888–1922 | 47 | 需求改成已拆单、发事件、存 PRD 产物 |
| `associate_milestone` | 1924–1933 | 19 | 关联里程碑 |
| `create_feature_branch` | 1935–1971 | 46 | 建开发分支 |
| `dispatch_tickets` | 1973–1981 | 19 | 需求改成进行中，逐张派单 |

行数是新文件里的函数长度，含文档字符串和从 `run` 取值、往 `run` 存值的那几行。

`orchestrator.py` 这边：

- `handle_requirement` 从 456 行降到 45 行，圈复杂度从 65 降到 4。留下的是占用标记、异常兜底和释放，
  `try` 里只有两句：造 `RequirementRun`，调 `run_pipeline`。
- 心跳文案函数 `analysis_progress_message` 跟着搬到了新文件，`orchestrator.py` 里改成导入，
  `from orchestrator import analysis_progress_message` 照常可用。
- 顶部的 `set_llm_context`、`clear_llm_context` 导入只有搬走的那段在用，一并去掉。另一处使用点自己在函数内导入。
- 文件从 4,907 行降到 4,493 行。

新文件由脚本按行号区间从拆分前的 `orchestrator.py` 生成，生成后没有手改。

`db` 和 `llm_client` 由 `handle_requirement` 在调用时从模块全局取出、经 `RequirementRun` 传入，新文件不导入这两个对象。
测试靠 `monkeypatch.setattr(orchestrator, "db", ...)` 换库，步骤必须拿到同一个对象。

### 4. 配套

- `desktop.spec`：`hiddenimports` 补 `orchestration.requirement_pipeline`。

## 和原文的差别

原函数体（`try` 里的第 1559–1981 行）共 423 行：412 行搬进步骤，其中 397 行原样、15 行有替换；
另外 11 行是步骤交界处的空行。替换只有两种：

1. 13 处 `self.` 写成 `orch.`；
2. 2 处 `return` 带上停止原因：`"requirement_not_found"` 和 `"analysis_failed"`。

步骤函数里新增的行有三类，共 82 行：开头从 `run` 取局部变量、结尾往 `run` 存、`return CONTINUE`。

有步骤停止时 `run_pipeline` 多打一条 debug 级日志，这是唯一新增的可观察行为，和 `ticket_pipeline` 一样。

原文里两处没用到的东西原样带了过去，没有清：`record_analysis` 里赋值后没人读的 `git_result`，
`create_feature_branch` 里导入后没用的 `re`。

## 验证

| 检查 | 结果 |
|---|---|
| 特征测试首版，原实现 | 56 条通过；190/190 条语句，52/54 个分支 |
| 补 2 条后，原实现 | 58 条通过；190/190 条语句，54/54 个分支 |
| 改坏检查，原实现 | 105 处，第一遍发现 104 处；补断言后 105 处全部发现 |
| 定稿后，原实现 | 60 条通过；190/190 条语句，54/54 个分支 |
| 全量 pytest，拆分前 | 1,068 条通过 |
| 拆分后，同一个测试文件（哈希未变） | 60 条通过；这一次跑在清理顶部导入之前 |
| 搬移核对脚本 | 通过 |
| 改坏检查，拆分后 | 129 处，第一遍发现 126 处；补 3 条用例后漏掉的 3 处全部发现 |
| 补的 3 条放回拆分前的实现 | 通过 |
| 拆分后的覆盖率（63 条） | 新文件 311/311 条语句、56/56 个分支；`handle_requirement` 17/17 条语句、2/2 个分支 |
| 全量 pytest，拆分后 | 1,071 条通过，退出码 0 |
| 分层守卫 | 退出码 0，新增违规 0 |
| CI 那组 flake8 规则 | 0 条 |

表里从「改坏检查，拆分后」往下的各行，加上搬移核对脚本，都是在清理完 `orchestrator.py` 顶部导入之后跑的；
覆盖率、全量 pytest、分层守卫、flake8 和搬移核对脚本还在补完 3 条用例之后又跑了一遍，表里是最后这一遍的结果。

**搬移核对脚本**检查这几件事：

1. 重新生成的 `requirement_pipeline.py` 和磁盘上的文件逐字节相同；
2. `orchestrator.py` 仍是 CRLF，新文件是 LF、无 BOM；
3. `orchestrator.py` 被删的行都落在切掉的区间里，新增 16 行；
4. 原函数体 387 行非空代码，做完上一节的两种替换后，全部按原顺序出现在新文件里；
5. 把步骤函数里的取值、存值、`return CONTINUE` 去掉后，逐词元和原函数体比对，2,415 个词元完全一致；
6. `STEPS` 的顺序和函数定义顺序一致，共 12 步；
7. 新文件不导入 `orchestrator`、`actions`、`agents`、`database`；
8. `handle_requirement` 的 `try` 里只剩两句，`except` 和 `finally` 和拆分前逐字相同。

这个脚本第一次运行报了两处失败、崩了一次，三处都是脚本自己的问题：相邻的空行在 difflib 里可以互换，
脚本把其中一行算成了区间外的删除；切 `async def f():` 前缀时少切一个冒号，12 个步骤比原文多出 11 个词元；
一处打印格式写错。改掉之后通过，期间被核对的代码没有动。

**拆分后的改坏检查。** 原实现上的 105 处改动按新位置重新定位（96 处落在新文件，9 处落在 `handle_requirement` 留下的骨架里），
另加 24 处针对拆分本身：让停止原因不生效、去掉某一步、对调相邻两步、让某个共享值不往 `run` 上存、
调用时不传 `llm_client`、改心跳文案。共 129 处，每处跑特征测试和 `test_prd_analysis_progress.py`，用时约 20 分钟，
结束后两个文件的哈希和开始前一致。没有定位不到的改动。

第一遍发现 126 处。重新定位的 105 处全部发现；漏的 3 处都在新加的 24 处里：

1. **对调「关联里程碑」和「建分支」。** 这两步互不依赖，对调后库里的最终结果一样。
   原用例只记了关联里程碑时的需求状态，两种顺序下都是 `decomposed`。
2. **对调「回填依赖」和「标记已拆单」。** 最终结果也一样，差别在 `requirement_decomposed` 发出的那一刻：
   对调后，这时库里的依赖还是占位的 `[]`。收到事件就去读工单的一方会读到空依赖。
3. **改心跳文案。** 心跳用例拿 `analysis_progress_message` 自己的返回值当期望，文案改了两边一起变；
   `test_prd_analysis_progress.py` 只查了几个子串。

针对这 3 处补了 3 条用例：

- `test_milestone_is_associated_before_branch_is_created`：关联里程碑时还没有任何 Git 调用，需求上也没有分支名；
- `test_dependencies_are_backfilled_before_decomposed_event`：事件发出时依赖已经换成工单号；
- `test_heartbeat_text_is_pinned`：写死心跳文案的原文。

这 3 条是拆分之后写的，所以单独做了一步：把 `orchestrator.py` 临时换回拆分前的版本，63 条加文案用例 2 条全部通过，
说明它们记的是原来就有的行为。换回拆分后的版本，只重跑漏掉的 3 处，都被发现。其余 126 处没有重跑：
这一步只加了用例，没有改已有的断言，已经发现的不会变成漏掉。

写第三条时自己先错了一次：以为只有空白的步骤名会回落到「等待 LLM」，实际不会，用例第一次跑就红了。
按实际行为改了断言，这个现状记在下面第 12 条。

**全量 pytest。** 1,071 条通过，退出码 0，用时约 3 分钟。拆分前是 1,068 条，多出的 3 条就是上面补的。

**分层守卫。** 模块 489（多了 `requirement_pipeline.py`），未归层 230，方向违规 92，相对基线新增 0，延迟导入占比 42.0%。

## 度量变化

| 指标 | 本轮之前 | 本轮之后 |
|---|---|---|
| `orchestrator.py` 行数 | 4,907 | 4,493 |
| `handle_requirement` 行数 / 圈复杂度 | 456 / 65 | 45 / 4 |
| `handle_requirement` 及其步骤的行覆盖率 | 1% | 100%（分支 58/58） |
| `orchestrator.py` 里超过 200 行的函数 | 2 | 1 |
| 全仓超过 200 行的函数 | 30 | 29 |
| `orchestration/` 里最长的步骤函数 | `run_agent` 76 行 | `create_tickets` 144 行 |
| 模块总数（守卫口径） | 488 | 489 |
| 未归层模块 | 230 | 230 |
| 方向违规 | 92 | 92 |
| 延迟导入占比 | 42.1% | 42.0% |

从 `7b9e7f0` 算起，`orchestrator.py` 从 6,694 行降到 4,493 行。最大的 Python 文件仍是 `api/chat.py`（5,566 行），
最长的函数仍是 `query_engine/engine.py` 的 `run`（559 行），这两项本轮没有变化。
`orchestrator.py` 里超过 200 行的函数只剩 `_generate_requirement_report`（206 行）；
`orchestration/` 里还有两个：`handle_skill`（256 行）和 `handle_dev`（207 行）。

新文件里圈复杂度最高的是 `create_tickets`（26）和 `backfill_dependencies`（11），其余步骤都在 8 以内。
原函数的 65 没有消失，只是分到了各个步骤里。

## 钉住的可疑现状

下面这些都按现在的样子写进了断言，本轮没有修。前三条会直接影响用户。

1. **拆单不在事务里，重试会重复建单。** 建工单到一半出错时，已经建好的工单留在库里，需求退回 `submitted`。
   用户点重试，会把全部工单再建一遍。触发方式之一：Agent 回传的某张工单 `subtasks` 是 `None`。
2. **派单出错会把需求退回已提交。** 逐张派单时任何一张抛异常，都走同一个兜底：需求从 `in_progress` 退回 `submitted`，
   工单和分支留着，排在后面的工单这一轮不再派。日志写的是「从 analyzing 到 submitted」，和当时的真实状态不符。
3. **零工单照样进行中。** Agent 一张工单都没拆出来（空列表、`None`、不是列表、全是坏数据），
   需求照样走到 `in_progress`，开发分支照建。
4. **依赖下标按过滤后的列表算。** 回传里不是字典的条目会被滤掉，依赖下标却是 Agent 按原始列表写的。
   夹一条坏数据，它后面的依赖就整体错一位，可能指向别的工单，也可能指向自己后被当成自引用丢掉。
5. **规模按原始条数算。** 同一批数据里，被滤掉的条目不建工单，但计入条数，影响工单的起始状态。
6. **异常路径不清 LLM 上下文。** Agent 抛异常时跳过了 `clear_llm_context`，上下文里留着这条需求的信息。
7. **取消时需求停在分析中。** `CancelledError` 原样抛出，不写日志也不发事件。占用标记会释放，
   所以下一轮 `_resume_stuck_analyses` 会把它重新拆一遍。续跑日志固定写「进程重启后中断」，被取消的情况也用这句话。
8. **建单日志的目标状态固定写 `pending`**，和工单真实的起始状态（可能是 `architecture_done` 或 `planning_done`）无关。
9. **建单日志里的依赖不滤自引用。** 落库的依赖滤了，日志里会把自己也列进去。
10. **子工单的处理和父工单不一致。** 不继承需求级 `use_aigc`，不写建单日志，不计入拆单数量，不在这里派单，起始状态固定 `pending`。
11. **Agent 回传非 success 时不发 `requirement_error`**，Agent 抛异常时才发。全仓只有 `orchestrator.py` 发这个事件，
    `frontend/` 里没有任何地方监听它，所以目前两种情况在界面上都只能从日志（`log_added`）看出来。
12. **只有空白的步骤名不回落到默认文案。** `analysis_progress_message` 对空字符串和 `None` 会写「等待 LLM」，
    对 `"  "` 这样的值不会，去掉空白后心跳文案的冒号后面什么都没有。

## 这一轮没有解决的事

1. **步骤内部没有整理。** `create_tickets` 144 行，接近 150 行的目标上限；父工单、子任务、子工单三段没有再拆。
   建工单的字段字典和子工单的字段字典大半相同，也没有合并。
2. **步骤仍调用 `orch` 的 4 个成员**：`_log`、`_log_agent_thought`、`_handle_git_files`、`process_ticket`，前三个是私有方法。
3. **到 `api.milestones` 和 `memory` 的延迟导入原样保留。** 守卫没有报新增违规。
4. **上面 12 条现状都没有修。** 修任何一条都要同时改对应的用例。

## 没有验证的部分

- **真实服务和真实 LLM 拆单。** 没有起服务提交一条真实需求。测试里 ProductAgent、Git、里程碑、派单都是桩。
- **桌面版打包。** `desktop.spec` 只确认了语法能解析，没有实际打包和启动。
- **Linux 和 CI。** 只在本机 Windows、Python 3.14.3 上跑过；flake8 用的是 Python 3.12 的环境。
- **根目录的 `_test_*.py` 脚本。** 没有跑。

## 遗留与后续

1. R2 第 3 步按职责拆类。`orchestrator.py` 现在 4,493 行，离 1,500 行的目标还远；剩下的体量主要是 `TicketOrchestrator` 的 85 个方法本身。
2. `orchestrator.py` 里最后一个超过 200 行的函数是 `_generate_requirement_report`（206 行）。
3. 上面 12 条可疑现状要不要修，建议先定前 4 条。
4. 核对脚本、改坏检查脚本和度量脚本仍只在 `%TEMP%\ads_r2_3`，没有进仓库。
5. 工作区现在叠了六批未提交改动，提交时建议分开。

## 复核命令

```powershell
# 相关用例，在 backend/ 下执行
cd backend
python -m pytest tests/agents/test_orchestrator_handle_requirement.py tests/agents/test_prd_analysis_progress.py -p no:cacheprovider

# 全量。pytest.ini 里已有 -q，再加 -q 不会打印汇总行，这时看点数和退出码
python -m pytest -p no:cacheprovider
cd ..

# 分层守卫，在仓库根目录执行
python scripts/check_layers.py
```
