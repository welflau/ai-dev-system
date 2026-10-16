# orchestrator 的 SkillAgent 分支（2026-10-15）

2026-10-15

方案文档：`docs/20261015_01_能力自描述与动态组装框架方案.md`（§3.8）
前置：`2026-10-15_10_SkillAgent回传与consumes注入.md`

## 一、链路闭环

`orchestrator.py` +214 行：

```
_handle_agent_result        插入 SkillAgent 分发（ArtistAgent 之前，early-return）
_handle_skill_agent_result  状态推进 + 日志 + 评论 + SSE + 下一阶段派单
_resolve_skill_success_status  三级回退
_skill_produces_satisfied   budget 豁免判断
```

**没碰 12 个现有分支**——新增的是一条 early-return + 三个独立方法。

## 二、为什么这个分支非有不可

缺它结果会落到 `_handle_agent_result` 末尾的 `else: new_status = current_status`——状态原地不动 → 同一条 rule 反复命中 → skill 被无限重跑烧 token。

`orchestrator.py:2247`（ArtistAgent）和 `:2383`（UEEditorAgent）的注释都记着同一个坑，它们都是**踩了才补的**分支。

## 三、三个关键决策

### a) 状态来源三级回退

```
result["success_status"]        SkillAgent 回传，零 DB 查询
→ _sop_stage_for 反查          兼容手工构造的 context
→ f"{stage_id}_done" 约定推导   最后兜底 + warning
```

第一级命中时**不查 SOP**——`compose_sop` 单次 53ms，每次派单都查是浪费。写了测试确认有回传值时不会去查。

### b) `budget_exceeded` 但产出齐全 → 按成功处理

`query_engine/engine.py:391` 的 `Budget.check()` 只在**轮与轮之间**生效。`gen_image` 这种阻塞几十秒的工具跑完回来，下一轮开头就可能触发超时——**此时图已经落盘了**，判 blocked 等于白烧一次钱。

豁免条件是「produces 声明的 kind 全部拿到」。没有 produces 声明（老 skill）→ 不豁免，无从判断齐全性，宁可交人工。

### c) 失败不自动重试

skill 是 LLM 自由发挥的，重跑一次就再烧一轮 token，而失败原因（prompt 不清 / 工具不可用 / 预算太紧）重跑都解决不了。这与 `workflow_composer` 不给 skill stage 配 `reject_goto` 是同一个决策的两面。

## 四、第 7、8 次假绿——这次最严重

### 注入 A：删掉整个分支 → 19 个测试全绿

**测试绕过了被测的集成点。** 我直接调 `_handle_skill_agent_result`，完全没有覆盖「`_handle_agent_result` 里到底有没有那条分发语句」。

删掉分支后：分支函数本身没问题（直调测试照样过），但生产环境会死循环。**这是本轮最危险的假绿**——它让「最关键的一条测试」变成了装饰。

补了 `_call_via_dispatcher` 走真实入口的三条测试（success / skipped / blocked 各一条，因为它们走不同代码路径）。再注入立刻 3 红。

顺带踩到一个细节：`TicketOrchestrator.__new__` 绕过了 `__init__`，而 `_HARD_TERMINAL` 是**实例属性**（orchestrator.py:64）不是类属性，走真实入口会 `AttributeError`。在 fixture 里补上——不调真 `__init__` 是因为它会实例化 13 个 Agent + 连 event_bus。

### 注入 B：blocked 后仍派单 → 全绿

我的 `fake_rules` 只含 `SUCCESS_STATUS`，blocked 天然不在表里。测试通过靠的是派单前 `if updated["status"] in rules` 的过滤，**而非代码里的 BLOCKED 判断**。

真实的 `default_sop` 里有没有 blocked 规则，不该是这条不变式的依赖。改成规则表里显式放一条 blocked 规则，再注入立刻红。

## 五、假绿形态累计 8 种

| # | 形态 | 本轮 |
|---|---|---|
| 1 | 场景在当前实现下不可能发生 | T9b |
| 2 | 两种实现产出相同结果 | T11c |
| 3 | 输入恰好触发了兜底路径 | binary |
| 4 | 调用次数不够 | 缓存深拷贝 |
| 5 | 代码路径无任何断言覆盖 | pipeline_view |
| 6 | 返回值相同，差异只在副作用 | kind 过滤日志 |
| 7 | **测试绕过集成点，只测了内部函数** | 注入 A |
| 8 | **通过靠的是别处的过滤，不是被测逻辑** | 注入 B |

7 和 8 有共同点：**测试的「通过路径」和代码的「正确性来源」不是同一条**。

补充判断标准：

> 写完测试后问两个问题：
> (1) 这个测试走的是**生产环境的真实调用路径**吗？还是我为了方便直接调了内部函数？
> (2) 它通过是因为**被测逻辑正确**，还是因为测试环境的某个无关设置恰好让它通过？

## 六、变异测试（5 注入，3 抓 2 补）

| 注入 | 结果 |
|---|---|
| A. 删掉整个分支 | **全绿 → 补分发测试后 3 红** |
| B. blocked 后仍派单 | **全绿 → 改规则表后 1 红** |
| C. budget 豁免关闭 | 1 红 ✓ |
| D. skipped 当失败处理 | 3 红 ✓ |
| E. success_status 不用回传值 | 1 红 ✓ |

## 七、另一个坑：`init_tables` vs `executescript(SCHEMA_SQL)`

测试第一版只跑 `executescript(SCHEMA_SQL)`，`_write_phase_comment` 的 insert 全部失败——评论数为 0 而不是报错。

根因：`ticket_comments.reply_to_comment_id` **只在 `_auto_migrate` 的 migrations 列表**（database.py:133），SCHEMA_SQL 里没有。而 `_write_phase_comment` 把异常吞在 `logger.debug`（orchestrator.py:4652）。

这和上一轮 artifacts 表那次是同一类问题的两面：**有些列只在 migrations，有些只在 SCHEMA_SQL**。测试必须跑 `init_tables()` 走完整路径。已在 fixture 的 docstring 里写明。

## 八、新增测试（22 个）

`backend/tests/agents/test_orchestrator_skill_branch.py`

| 组 | 用例 | 锁什么 |
|---|---|---|
| **分发（真实入口）** | 3 | success / skipped / blocked 都经 `_handle_agent_result` 路由 |
| 状态推进 | 5 | 推进不卡住、日志+评论、partial warning、SSE、下一阶段派单 |
| skipped | 2 | 跳到成功态（不停在原状态）、仍派单 |
| 失败 | 4 | blocked、不派单、未知状态也 blocked、写评论 |
| budget 豁免 | 3 | 齐全→partial、部分→blocked、无声明→不豁免 |
| success_status | 3 | 优先回传值（不查 SOP）、反查兜底、约定推导 |
| 容错 | 2 | 最小 result 不崩、同状态不重复派单 |

## 九、改动清单

```
backend/orchestrator.py  +214
backend/tests/agents/test_orchestrator_skill_branch.py  新增 22 用例
```

测试总数 241 → 263。

## 十、验证

```bash
cd backend && python -m pytest tests/ -q    # 263 passed in 85s
python -c "import main"
```

## 十一、链路现状

```
compose_sop 扫 SKILL.md → 拓扑排序 → 插入 skill 子链 ✓
orchestrator 调度到 skill stage                      ✓
SkillAgent 注入上游产物 + 跑 SkillRunner              ✓
产出登记进 artifacts 表                               ✓
orchestrator 推进状态 + 派下一阶段                     ✓
```

**框架已闭环。** 剩下的是能力（gen_image）和验证（demo 链 + CI 防漂）。

## 十二、下一步

任务 #14：`gen_image` builtin 工具。

复用 `image_processor.py` 的 `_create_lightai_task` / `_poll_lightai_task` / `_download_image`，阻塞等待直到出图。不走 `image_requests` 表 + `[IMG_PENDING:id]` 占位符那套（它服务「文档先写图后补」，与 skill 链「产物须在 stage 结束时就绪」冲突）。

实测要关注 `Budget.max_seconds` 的边界——这正是上面 budget 豁免逻辑存在的原因。
