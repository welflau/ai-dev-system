# NextPhase B-2/B-3：LevelGenAction + UEEditorAgent

> 系列：NextPhase  
> 日期：2026-05-18  
> 提交：`b4094b1`（B-2）、`34c6b0f`（B-3）

---

## B-2：LevelGenAction（`actions/ue_level_gen.py`）

**功能**：LLM 根據關卡設計描述生成 UE Python 布局代碼 → Python 橋接執行

**`_LEVEL_SYSTEM_PROMPT` 涵蓋**：
- 地面格子鋪設（StarterContent Floor_400x400）
- 玩家出生點（PlayerStart）
- 點光源 / 定向光
- NavMeshBoundsVolume
- 牆壁、障礙物（掩體）
- 設計原則（出生點間距、光源密度、Actor 命名規範）

**使用方式**：
```
/ue-level 8×8地面，四角各一盞燈，中央玩家出生點，NavMesh 全覆蓋
/ue-level 室內競技場 20m×20m，四角掩體，中央開闊
```

---

## B-3：UEEditorAgent（`agents/ue_editor.py`）

### 核心價值：自動繼承 A-2 能力

```python
class UEEditorAgent(BaseAgent):
    # 不寫任何 Thinking/Memory 代碼
    # 自動繼承 BaseAgent.compact_history()
    # 自動繼承 BaseAgent.get_memory_prompt()
```

驗證：
```python
agent = UEEditorAgent()
agent.compact_history    # ✅ 繼承
agent.get_memory_prompt  # ✅ 繼承
```

### 工單流轉

```
需求（UE 項目 + type=ue_content）
  ↓ Orchestrator
ue_content_pending
  ↓ UEEditorAgent._do_auto_dispatch()
    ├─ 含 blueprint/bp_ → BlueprintGenAction
    ├─ 含 level/關卡   → LevelGenAction
    └─ 含 Python 代碼  → UERunPythonAction
  ↓
ue_content_done
  ↓（正常流程繼續）
development → engine_compile → test → deploy
```

### SOP 片段（`sop/fragments/ue_content_gen.yaml`）

- 觸發條件：`ue_content_pending` 狀態 + `engine:ue5/ue4` trait + `type=ue_content`
- 插入位置：`architecture` 之後（priority=88）
- 最大重試：2 次

---

## 整體 UE 創作流水線（B-0 ~ B-3 完成）

```
用戶需求（「創建波次生成系統」）
  ↓
工單創建（type=ue_content, engine:ue5）
  ↓
UEEditorAgent 自動分發
  ↓ BlueprintGenAction
    LLM 生成 Python 代碼
    ue_python_bridge 發送到 UE Editor
    ✅ BP_WaveSpawner 寫入 /Game/Blueprints/
  ↓ ue_content_done
  ↓（繼續正常流程）
DevAgent → engine_compile → TestAgent → DeployAgent
```

**斜杠命令入口**（A-1 Commands）：
```
/ue-run import unreal; print(unreal.SystemLibrary.get_engine_version())
/ue-bp-gen 創建一個波次生成器，每隔5秒生成一個敵人
/ue-level 8×8地面 + 四角燈光 + NavMesh 全覆蓋
```
