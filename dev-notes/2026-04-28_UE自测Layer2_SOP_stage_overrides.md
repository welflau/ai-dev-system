# 开发日志 — 2026-04-28（UE 自测 Layer 2 + SOP stage_overrides）

## 背景

v0.19.x 完结总结中列为遗留：**DevAgent UE 自测 Layer 2（UBT -SingleFile 预编，30-90s）**。

Layer 1（7条静态规则）已在 2026-04-26 完成；Layer 2 的代码逻辑在 `self_test.py` 和
`ue_compile_check.py` 中也已就绪，唯一缺口是 `_core.yaml` 里 `ue_precompile: false` 无法
按项目 traits 自动开启——SOP loader 的 fragment 机制只支持插入新 stage，不支持 patch 已有 stage 的 config。

---

## 一、SOP loader 加 stage_overrides 支持

### 问题

fragments 可以向 SOP 插入新 stage，但无法修改已有 stage（如 `development`）的 `config` 字段。
注释里写着"通过 SOP fragment 覆盖即可"，但机制未实现。

### 实现

`backend/sop/loader.py` 的 `compose_sop()` 函数，在 fragment 插入循环结束后新增 **第 7 步**：

```python
# 7. 处理 stage_overrides：fragment 可以 patch 已有 stage 的 config
for frag in frag_entries:
    for ov in (frag.get("stage_overrides") or []):
        ov_id = ov.get("id")
        ov_cfg = ov.get("config") or {}
        if not ov_id or not ov_cfg:
            continue
        idx = _find_stage_idx(composed, ov_id)
        if idx is None:
            logger.warning("stage_overrides: stage '%s' 不存在，跳过", ov_id)
            continue
        composed[idx].setdefault("config", {}).update(ov_cfg)
```

**格式**（fragment YAML）：
```yaml
stage_overrides:
  - id: development          # 要 patch 的 stage id
    config:
      ue_precompile: true    # 覆盖/新增 config 字段
```

只覆盖声明的 key，其余 config 字段保持不变（`dict.update` 语义）。

---

## 二、engine_compile.yaml 启用 UE Layer 2

`backend/sop/fragments/engine_compile.yaml` 新增 `stage_overrides`：

```yaml
stage_overrides:
  - id: development
    config:
      ue_precompile: true
      ue_precompile_timeout: 120
```

- `engine_compile` fragment 的 `required_traits` 已包含 `engine:ue5/ue4/godot4/...`
- 对 Godot/Unity 项目设置此值是无副作用的（`self_test.py` 的 `_run_ue_self_test` 只在 UE traits 下执行）

---

## 三、验证

```
PASS: UE development.config.ue_precompile = True
PASS: UE development.config.ue_precompile_timeout = 120
PASS: Web development.config.ue_precompile = False
PASS: engine_compile fragment applied
ALL 3 assertions passed
```

---

## 四、完整 Layer 2 链路

```
DevAgent.develop
  └─ SelfTestAction._run_ue_self_test()
       ├─ Layer 1: run_all_rules()  ← 亚秒，7条规则
       │   blocking > 0 → fail，进 fix_issues（不跑 UBT）
       └─ Layer 2: sop_cfg["ue_precompile"] == True（UE 项目自动开启）
            └─ UECompileCheckAction(single_files=[first_cpp], timeout=120s)
                 success → pass
                 fail    → fail，进 fix_issues（省掉完整 UBT 3-5 min）
```

---

## 改动文件

| 文件 | 改动 |
|---|---|
| `backend/sop/loader.py` | `compose_sop()` 第 7 步：处理 `stage_overrides` |
| `backend/sop/fragments/engine_compile.yaml` | 新增 `stage_overrides`，UE 项目开启 `ue_precompile: true` |

---

*2026-04-28 · UE 自测 Layer 2 + SOP stage_overrides 机制*
