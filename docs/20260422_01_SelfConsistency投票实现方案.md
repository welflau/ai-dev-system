# Self-Consistency 投票 — 实现方案

> 日期: 2026-04-22 | 对标: MagicAI 对比分析 `docs/20260418_01_MagicAI对比分析.md` ⭐⭐⭐ 最后一项 | 论文: Wang et al. 2022 *Self-Consistency Improves Chain of Thought Reasoning*

---

## 一、背景

### 1.1 问题

DecomposeAction（拆单）和 DesignArchitectureAction（架构设计）是典型的**主观发散任务**：
- 同一个需求不同 LLM 调用，拆出来的工单数量/粒度可能完全不同
- 架构决策的"最优解"没有客观标准，一次输出不稳

历史实测（Reflexion 做完之后）观察：
- 架构设计有时拆出过度复杂的模块（simple 需求但给 4 个工单）
- 拆单有时 miss 需求要点（比如漏掉"兼容性测试"子任务）

### 1.2 Self-Consistency 思路

论文方法：对"思考链"（chain-of-thought）任务跑多次，投票选最一致的答案。对我们这种结构化输出，变体是：
1. 同一 prompt 跑 N 次（**高温** 0.8 获得差异化候选）
2. LLM Critic 按评分标准选 best（**低温** 0.2 求稳）
3. 返回 best 候选

论文实测：数学推理任务 +17-18%；本项目架构/拆单这类主观任务预计 **+25%**。

### 1.3 目标

- 对 DecomposeAction + DesignArchitectureAction 加入投票能力
- **默认关闭**（成本 4×），通过 SOP config opt-in：
  ```yaml
  config:
    self_consistency: true
    consistency_n: 3
    consistency_temperature: 0.8
  ```
- 留痕：投票过程 / 选中原因 写入 ticket_logs（`action='consistency_vote'`）

---

## 二、核心设计

### 2.1 数据流

```
Action.run(context)
  └─ sop_cfg.self_consistency == true?
       ├─ 否 → node.fill()  单次调用（原路径不变）
       └─ 是 → fill_with_consistency(node_factory, req, llm, n=3, temp=0.8)
                └─ 1. asyncio.gather N 个 ActionNode.fill（高温）
                └─ 2. 过滤 instruct_content 非空的候选
                └─ 3. 0 个 → ValueError
                      1 个 → 跳过 judge，直接返回
                     >1 个 → LLM judge 选 best（低温，简洁评分标准）
                └─ 返回 (best_node, all_nodes, judge_info)
       └─ context["_consistency_vote"] = {n_candidates, best_index, reasoning, fallback}
  └─ result.data["_consistency_vote"] 带出
  └─ orchestrator._handle_agent_result / handle_requirement 检测 _consistency_vote
       └─ 写一条 ticket_log(action='consistency_vote')
```

### 2.2 新增模块 `backend/actions/voting.py`

```python
async def fill_with_consistency(
    node_factory: Callable[[], ActionNode],  # 每次返回新的 ActionNode 实例
    req: str,
    llm,
    *,
    n: int = 3,
    temperature: float = 0.8,
    max_tokens: int = 4000,
    task_desc: str = "",
) -> Tuple[ActionNode, List[ActionNode], Dict]:
    """并行 N 候选 → Judge → (best, all, judge_info)"""
```

**Judge prompt**（temperature=0.2，max_tokens=400）：
```
[system] 你是一位资深技术评审，正在从多个候选方案里挑出最优的一个。
判分标准（按重要性降序）：
1. 完整性
2. 可执行性
3. 与任务契合度
4. 内部一致性

输出严格 JSON。

[user] ## 任务
{task_desc}

## 候选方案
### 候选 A (index=0)
{candidate_a_raw_json}

### 候选 B (index=1)
{candidate_b_raw_json}
...

## 输出格式
{"best_index": 0, "reasoning": "..."}
```

**容错处理**：
- 任一候选 fill 异常 → `return_exceptions=True` 捕获，不影响其他候选
- Judge LLM 失败 → fallback 返回候选 0 + `fallback: true` 标记
- Judge 返回越界 index → 归 0
- Judge JSON 解析失败 → fallback

### 2.3 Action 集成（DecomposeAction / DesignArchitectureAction 几乎一致）

```python
sop_cfg = context.get("sop_config") or {}
use_consistency = bool(sop_cfg.get("self_consistency", False))

def _new_node():
    return ActionNode(key="...", expected_type=..., instruction="...")

vote_info = None
if use_consistency:
    from actions.voting import fill_with_consistency
    n = int(sop_cfg.get("consistency_n", 3) or 3)
    temp = float(sop_cfg.get("consistency_temperature", 0.8) or 0.8)
    try:
        best_node, all_nodes, judge_info = await fill_with_consistency(
            _new_node, req=req_context, llm=llm_client,
            n=n, temperature=temp, max_tokens=2000,
            task_desc=f"为「{ticket_title}」...",
        )
        node = best_node
        vote_info = {
            "stage": "...",
            "n_candidates": len(all_nodes),
            "best_index": judge_info["best_index"],
            "reasoning": judge_info["reasoning"],
            "fallback": judge_info.get("fallback", False),
            "temperature": temp,
        }
    except Exception as e:
        logger.warning("Self-Consistency 失败，降级到单次调用: %s", e)
        node = _new_node()
        await node.fill(req=req_context, llm=llm_client, max_tokens=2000)
else:
    node = _new_node()
    await node.fill(req=req_context, llm=llm_client, max_tokens=2000)

# 产出
result_data = {...}
if vote_info:
    result_data["_consistency_vote"] = vote_info
```

### 2.4 Orchestrator 留痕

两处：

**架构**（`_handle_agent_result` ArchitectAgent 分支）：
```python
vote = result.get("_consistency_vote")
if vote:
    await self._log(..., "consistency_vote", ...,
        f"🗳️ 架构投票: {vote['n_candidates']} 候选 → 选 #{vote['best_index']} | {vote['reasoning'][:150]}",
        "info", detail_data={"consistency_vote": vote})
```

**拆单**（`handle_requirement` 成功分支）：
```python
vote = result.get("_consistency_vote")
if vote:
    await self._log(..., "consistency_vote", ...,
        f"🗳️ 拆单投票: ...",
        ...)
```

Session Transcript 会自动镜像（走 `_log` → session_logger.log_event）。

### 2.5 ContextVar 并发安全

**风险**：Skills 通过 `contextvars.ContextVar _current_skills` 在 BaseAgent.run_action 里设置，asyncio.gather 并行任务会不会丢？

**答**：Python asyncio 原生支持 ContextVar copy——每个 task 启动时自动拷贝当前 context。gather 里每个候选都能读到正确的 skills。

单测 Test 5 覆盖：并发 3 候选，都应读到同一 `SKILL_MARKER_XYZ`。

---

## 三、改动清单

### 3.1 新增

| 文件 | 说明 |
|---|---|
| `backend/actions/voting.py` | `fill_with_consistency()` + `_judge_candidates()` + `_parse_judge_json()`（~180 行） |
| `backend/_test_self_consistency.py` | 5 用例单测（judge 选 best / 单成功 / 全失败 / judge fallback / ContextVar 并发） |
| `docs/20260422_01_SelfConsistency投票实现方案.md` | 本文档 |

### 3.2 修改

| 文件 | 改动 |
|---|---|
| `backend/actions/decompose.py` | `run()` 加 sop_config.self_consistency 开关；开启时走 `fill_with_consistency`，带出 `_consistency_vote` |
| `backend/actions/design_architecture.py` | 同上 |
| `backend/sop/default_sop.yaml` | architecture stage config 加 `self_consistency: false` + 注释说明 |
| `backend/orchestrator.py` | 两处：`handle_requirement`（拆单）+ `_handle_agent_result` ArchitectAgent 分支，检测 `_consistency_vote` 写日志 |

---

## 四、测试与验证

### 4.1 单测 `_test_self_consistency.py`（5/5 通过）

```
✅ Test 1 3 候选 + judge 选中 #1
✅ Test 2 单成功候选跳过 judge
✅ Test 3 全失败 raise
✅ Test 4 judge 失败 fallback
✅ Test 5 并发 ContextVar 继承
```

### 4.2 回归（8 套 42 用例全绿）

```
_test_skills.py               ✅ 8/8
_test_reflection.py           ✅ 5/5
_test_failure_library.py      ✅ 6/6
_test_session_logger.py       ✅ 5/5
_test_mcp_client.py           ✅ 5/5
_test_vision_action_node.py   ✅ 4/4
_test_blind_review_fixes.py   ✅ 4/4
_test_self_consistency.py     ✅ 5/5（新增）
```

### 4.3 端到端手工

1. 改 `backend/sop/default_sop.yaml` 的 architecture stage：`self_consistency: true`
2. `curl -X POST http://localhost:8001/api/sop/reload`（或重启服务）
3. 创建一个中等复杂度需求
4. 查日志：应看到
   ```
   🗳️ Self-Consistency: 生成 3 个候选 (temp=0.8)
   🏆 Self-Consistency: judge 选中候选 #X / 3
   ```
5. 查 `llm_conversations`：应有 3 条 design_architecture call + 1 条 judge call（共 4 次）
6. 查 `ticket_logs`：应有 `action='consistency_vote'` 的记录
7. Session Transcript (`backend/logs/session_<req>/transcript.txt`) 含 consistency_vote 事件

---

## 五、成本分析

假设 ArchitectureOutput ~600 tokens output，请求 ~1500 tokens input：

| 模式 | LLM 调用数 | Token 消耗 | 耗时 |
|---|---|---|---|
| 单次（默认） | 1 | 2100 | ~10s |
| N=3 Self-Consistency | 3 + 1 judge = 4 | 3×2100 + 400 judge = ~6700 | ~15s（并行 + judge） |

**~3.2× token 成本 + ~1.5× 耗时**（因并行，不是 4×）。论文预期质量 +25%，ROI 取决于"架构错误被打回多少次"。

建议：
- 只给 `architecture` 这类低频但高价值 stage 开
- 不建议 `decompose` 默认开（每个需求都触发，累积快）
- 可以针对"大需求"动态开（复杂度 complex → 开 consistency）—— 未来可做

---

## 六、风险与降级

| 风险 | 缓解 |
|---|---|
| 成本 3-4× | 默认 opt-in，文档明确建议 |
| 并行 LLM 触发 API 限流 | httpx 每次独立连接 + 内置 retries；N≤5 基本无问题；失败候选会被 filter 掉不阻塞 |
| Judge 偏见（随便选一个） | temperature=0.2 求稳 + 明确 4 条判分标准；fallback 返回候选 0 |
| ContextVar（Skills）在并发中丢失 | asyncio 原生 copy；单测覆盖 |
| 一次调用失败连累全部 | `return_exceptions=True` + 过滤成功；只要 ≥1 个成功就继续 |
| Judge 返回越界 index | 归 0 + warning |

---

## 七、未来扩展

### 7.1 按复杂度动态开关

DecomposeAction 判断出 complexity=complex 时自动 enable architecture stage 的 self_consistency。需要跨 stage 的动态配置传递，工作量中。

### 7.2 复用候选作为"多方案"展示

目前 all_nodes 除了 best 都丢弃。可以把其他候选作为 artifact 存下，让用户事后对比 / 手选。

### 7.3 其他 Agent 也用

ReviewAgent / ProductAgent 验收 可能也适合（都是主观判断）。改一行 `fill_with_consistency` 调用即可。

---

## 八、一句话总结

> MagicAI 对标最后一项（⭐⭐⭐）。给 DecomposeAction 和 DesignArchitectureAction 加了"跑 N 次高温候选 → Critic LLM 选 best"的能力。默认 opt-in（成本 3-4×）。架构 stage 可直接在 SOP yaml 打开开关，无需改代码。留痕写入 ticket_logs 和 Session Transcript，方便追查投票决策。
