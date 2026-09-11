# DevNote · 2026-09-10（四）

**类型**: TestAgent UE 分支 —— 静态分析/功能测试按 traits 分流
**状态**: 已落地，fixture 探针 5 项断言全绿（未经真实 UE 项目端到端验证）
**前置**: `dev-notes/2026-09-10_01_UE工单流转闭环修复.md`（同日，该 note 的遗留待办）

---

## 一、问题

`TestAgent.run_tests` 的检查项全部按 Web/Python 项目设计：

| 阶段 | 检查内容 | UE 项目结果 |
|---|---|---|
| 静态分析 | `src/**`、`index.html`/`main.py`/`app.py` | 必然 fail |
| 功能测试 | `_test_generic` 数 `src/**` 文件数 | 必然 fail |
| 用例生成 | LLM 编 pytest | 产出 `assert Path("index.html").exists()` 之类假用例 |
| 用例执行 | 跑 pytest | 必然 fail |

UE 项目产物是 `.uproject` / `Source/` / `Content/`，这些路径一个都不存在。
fixture 实测：一个**完全健康**的 UE 仓库走旧逻辑通过率 **20%**，
而阈值是 60% —— 恒定判失败，打回 DevAgent 空转。

---

## 二、修复

### 1. 按 traits 分流（`agents/test.py`）

新增 `_is_ue_project(context)`，读 orchestrator 注入的 `traits`（`engine:ue*`）。
命中则走 UE 专属三条分支：

| 阶段 | UE 分支 |
|---|---|
| 静态分析 | `_static_analysis_ue()` |
| 功能测试 | `_test_ue()` |
| 用例生成/执行 | **跳过**，phase 记 0/0 并留说明 |

跳过 pytest 的理由：C++ / Blueprint / uasset 不是 pytest 能跑的东西，
LLM 只会编出必然 fail 的假用例，既污染仓库又拉低通过率。
UE 的运行时验证由 `play_test` 阶段的 UE Automation Framework 负责，职责不重叠。

### 2. `_static_analysis_ue` —— 4 项

- `.uproject` 存在
- `.uproject` 可解析且有 `EngineAssociation`
- `Source/` 有 C++ 或 `Content/` 有 uasset（两者皆空 = 无产出）
- **C++ 静态规则**：复用 DevAgent 自测的 `actions.ue_lint`（R1-R8）

> 与 DevAgent 自测的区别：DevAgent 只扫本次写入的文件（增量），
> TestAgent 扫仓库全部 C++（截断 80 个）—— 验收看的是整体质量。
> lint 自身异常不判工单失败，记通过并留痕。

### 3. `_test_ue` —— 3 项

- 资产命名前缀（`BP_`/`SM_`/`M_`/`WBP_` 等 28 个前缀，对齐全局 `ue-asset-naming` 规范）
- 资产不得直接堆在 `Content/` 根目录
- 每个 `Build.cs` 同级必须有 `.cpp`/`.h`（空模块会让 UBT 报错）

不启服务、不截图 —— 只做仓库层面可静态检查的项。

---

## 三、连带修掉 ue_lint R3 误报（重要）

写 fixture 时发现：一个正常的 flat layout 模块

```
Source/MyGame/
  MyGame.Build.cs
  SprintComponent.h
  SprintComponent.cpp     → #include "SprintComponent.h"
```

R3 报 blocking，**且给出的 suggest 与原文一模一样**：

```
msg  = #include "SprintComponent.h" 在本模块同级找不到
建议 = 应改成 #include "SprintComponent.h"
```

**根因**：`rules.py` 的 R3 只把 `Public/` 或 `Private/` **根目录**下的头
视为"可直接 include"，没考虑模块根目录直接放 `.h/.cpp` 的 flat layout。
但 UBT 会把模块根加进 include 路径，这种写法完全合法，小型模块极常见。

**危害**：这不只是误报 —— DevAgent 拿到"改成和原文一样"的建议无从下手，
只能反复重写 → `self_test_failed` 循环 → blocked。
与 2026-09-10_01 note 里记录的「`engine_compile_failed` 连续空转 5 次」是同一类症状。

**修复**：R3 增加 flat layout 判定（`p.parent == module_root`）。
三种 layout 验证：

| layout | R3 | 期望 |
|---|---|---|
| flat（模块根直接放） | 0 | 无告警 ✅ |
| Public/ + Private/ | 0 | 无告警 ✅ |
| Public/Sub/ 子目录 | 1，建议 `"Sub/A.h"` | 仍应告警 ✅ |

真实违规仍被抓，且建议与原文不同（可执行）。

---

## 四、验证

fixture 造真实 UE 目录结构（`.uproject` + `Build.cs` + `.h/.cpp` + `.uasset`），
对照组用同一套 fixture 不注入 traits 走旧分支：

| 断言 | 结果 |
|---|---|
| 旧通用分支对健康 UE 仓库误判失败（20% < 60%） | PASS |
| UE 分支 · 规范仓库判通过（**100%**） | PASS |
| UE 分支 · 问题仓库判失败（43%） | PASS |
| UE 分支不生成假 pytest 文件 | PASS |
| 3 个植入问题全被检出 | PASS |

植入的 3 个问题（命名缺前缀 / 资产堆根目录 / 空模块）全部命中，
且 R5（`.uproject` 未声明 EmptyMod）也被 lint 独立抓到。

`_is_ue_project` 边界：`engine:ue5`/`engine:ue4` → True；
`platform:web`/无 traits/traits 为非法字符串/None → False（不会误伤 Web）。

---

## 五、改动清单

```
backend/agents/test.py
  + UE_TEST_STRATEGY / _is_ue_project()
  + _static_analysis_ue()      uproject + 模块 + ue_lint 全量扫
  + _test_ue()                 资产命名 + 目录结构 + 模块完整性
  ~ run_tests()                三处按 is_ue 分流；UE 跳过 pytest 生成与执行

backend/actions/ue_lint/rules.py
  ~ R3                         支持 flat layout，消除"建议 = 原文"的死循环误报
```

---

## 六、待办

- **ArtistAgent 仍未实现** —— `asset_gen` fragment 靠假 trait 关停中（承接自 01 note）
- **本次仍是 fixture 验证** —— 真实 UE 项目 + 真实 LLM 的端到端未跑
- **资产命名前缀表硬编码在 `_test_ue`** —— 与 `~/.codebuddy/rules/ue-asset-naming.md`
  重复维护，后续可考虑抽成配置

---

*相关：`dev-notes/2026-09-10_01_UE工单流转闭环修复.md`、`docs/20260426_01_DevAgent_UE项目自测方案.md`*
