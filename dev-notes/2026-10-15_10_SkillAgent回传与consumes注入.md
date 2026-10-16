# SkillAgent 回传 + consumes 注入（2026-10-15）

2026-10-15

方案文档：`docs/20261015_01_能力自描述与动态组装框架方案.md`（§3.6）
前置：`2026-10-15_09_接进compose_sop与缓存.md`

## 一、做了什么

SkillAgent 从 89 行扩到 ~230 行，加了产物总线的两端：

```
_prepare_inputs  (跑之前) 天然源就位 + 上游产物注入 run_ctx
_register_outputs(跑之后) ArtifactOut → artifacts 表 + 回传给 orchestrator
```

`SkillRunner._build_system` 接上渲染（+13 行），实测效果：

```
按大纲写正文。

## 当前上下文
- 工单标题：写博客

## 上游产物（已就绪）
- `content_outline`: artifacts/a/b/content_outline/outline.md (text/markdown, 2.0KB)
  用 `read_file` 工具读取（path 相对仓库根）

## 缺失的上游产物
- `style_guide`（可选，未产出）
```

## 二、天然源必须被主动创建

`ticket_brief` 在 kinds.yaml 标了 `builtin: true`，组装器据此视为「已就绪」才没把以它为源的 skill 判缺源剔除。

**但没人会自动创建它。** 不在 `_prepare_inputs` 里补，第一个 skill 的 consumes 就落空——整条链从第一步就断，而组装期一切正常。

```python
wants_brief = any(c.get("kind") == "ticket_brief" for c in consumes)
if wants_brief:
    await artifact_store.put_ticket_brief(...)
```

加了 `wants_brief` 判断是为了不给无关 skill 造垃圾文件。注入「不创建」验证：对应测试红。

## 三、回传三个字段给 orchestrator

```python
"success_status": sop.get("_success_status")   # 省掉一次 compose_sop
"sop_config": sop                              # 分支里还要读 _stage_id
"artifacts": [...]                             # 已登记的产物摘要
```

`success_status` 是关键：orchestrator 的 SkillAgent 分支（下一个任务）据此推进状态。没有它只能靠 action 名反查 SOP——多一次 53ms 的 `compose_sop`，而且 skill 已被卸载时根本查不到。

`skipped` 路径也带上了。orchestrator 对 skipped 的处理是「直接跳到成功态，别卡流水线」，没有 success_status 就无从跳。

## 四、三处刻意的容错降级

| 位置 | 失败时 | 理由 |
|---|---|---|
| `_prepare_inputs` | 返回 `{}`，skill 照常跑 | 注入是增强，不是前置条件。prompt 里会显示缺了什么 |
| `_register_outputs` 单条 | 跳过该条，其余继续 | stage 成败由 SkillRunner 的 status 决定，不该被产物登记的意外左右 |
| `_build_system` 渲染 | 跳过该段 | 老 skill（openspec-*）没有 `_artifacts`，不该因此崩 |

注入 D（单条失败就整体抛）和 E（注入失败不降级）各抓到 1 个测试。

## 五、第 6 次假绿，又是新形态

注入 C「去掉 kind 为空的过滤」→ 测试全绿。

原因：kind 为空时 `validate_kind("")` 会 raise，被 `_register_outputs` 的 except 捕获，**结果和提前过滤完全一样**——`registered` 里都没有它。

但真实危害不在返回值，在**日志噪音**：每个老 skill 的每个产出都会触发一次失败的 put + 一条 WARNING。`openspec-propose` 一次跑 4 个文件 = 4 条无意义警告，真问题会被淹掉。

改用 `caplog` 断言「没有产生任何登记失败的警告」，再注入立刻红。

前五次假绿的形态：
1. T9b — 场景在当前实现下不可能发生
2. T11c — 两种实现产出相同结果
3. binary — 输入恰好触发了兜底路径
4. 缓存深拷贝 — 调用次数不够（第 1 次本来就独立）
5. pipeline_view — 代码路径无任何断言覆盖

这次是第 6 种：**可观测结果相同，差异只在副作用（日志）上。**

补充判断：

> 变异测试全绿时，除了「结果是否可区分」，还要问**副作用是否可区分** ——
> 日志、DB 写入次数、外部调用次数。有些退化不改变返回值，只是让系统变脏。

## 六、变异测试（6 注入，5 抓 1 补）

| 注入 | 结果 |
|---|---|
| A. 不创建 ticket_brief | 1 红 ✓ |
| B. 不回传 success_status | 2 红 ✓ |
| C. 不过滤 kind 为空 | **全绿 → 改用 caplog 后 1 红** |
| D. 单条失败整体抛 | 1 红 ✓ |
| E. 注入失败不降级 | 1 红 ✓ |
| F. 不渲染上游产物 | 1 红 ✓ |

## 七、新增测试（18 个）

`backend/tests/agents/test_skill_agent.py`（16 个）+ `test_runner_outputs.py`（2 个）

| 组 | 用例 | 锁什么 |
|---|---|---|
| 输入侧 | 7 | 天然源创建/不多造、上游注入、text 模式、缺必需产物报告、三种降级 |
| 输出侧 | 5 | 登记进表、kind 过滤（含日志）、二进制完好、部分失败、空列表 |
| 回传形状 | 3 | skipped 带 success_status、完整 `_run_skill` 的字段契约、缺 skill_id 报错 |
| prompt 渲染 | 2 | 产物出现在 system 且带 read_file 指示、无产物不留空标题 |

用真实 SQLite + 真实文件，只给 `SkillRunner.execute` / `is_available` 打桩（它们需要 LLM）。注入和登记这两段是纯数据搬运，必须真跑。

## 八、改动清单

```
backend/agents/skill_agent.py   +156 -18
backend/skills/runner.py        +13（_build_system 接渲染）
backend/tests/agents/test_skill_agent.py       新增 16 用例
backend/tests/skills/test_runner_outputs.py    +2 用例
```

测试总数 223 → 241。

## 九、验证

```bash
cd backend && python -m pytest tests/ -q    # 241 passed in 83s
python -c "import main"
```

## 十、下一步

任务 #13：orchestrator 补 SkillAgent 分支。

这是链路闭环的最后一块。**现在 skill 能被调度、能注入、能登记产物，但 orchestrator 没有对应分支** —— 结果会落到 `orchestrator.py:3108` 的 `else: new_status = current_status`，状态不推进 → 同一条 rule 反复命中 → 死循环烧 token。`orchestrator.py` 的 2233 / 2369 行注释都警告过这个坑（ArtistAgent 和 UEEditorAgent 都是踩了才补的）。
