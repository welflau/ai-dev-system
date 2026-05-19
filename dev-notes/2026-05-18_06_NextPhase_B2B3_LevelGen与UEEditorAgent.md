# NextPhase B-2/B-3：LevelGenAction + UEEditorAgent

> 系列：NextPhase  
> 日期：2026-05-18  
> 提交：`b4094b1`（B-2）、`34c6b0f`（B-3）

---

## B-2：LevelGenAction（`actions/ue_level_gen.py`）

**功能**：LLM 根据关卡设计描述生成 UE Python 布局代码 → Python 桥接执行

**`_LEVEL_SYSTEM_PROMPT` 涵盖**：
- 地面格子铺设（StarterContent Floor_400x400）
- 玩家出生点（PlayerStart）
- 点光源 / 定向光
- NavMeshBoundsVolume
- 墙壁、障碍物（掩体）
- 设计原则（出生点间距、光源密度、Actor 命名规范）

**使用方式**：
```
/ue-level 8×8地面，四角各一盏灯，中央玩家出生点，NavMesh 全覆盖
/ue-level 室内竞技场 20m×20m，四角掩体，中央开阔
```

---

## B-3：UEEditorAgent（`agents/ue_editor.py`）

### 核心价值：自动继承 A-2 能力

```python
class UEEditorAgent(BaseAgent):
    # 不写任何 Thinking/Memory 代码
    # 自动继承 BaseAgent.compact_history()
    # 自动继承 BaseAgent.get_memory_prompt()
```

验证：
```python
agent = UEEditorAgent()
agent.compact_history    # ✅ 继承
agent.get_memory_prompt  # ✅ 继承
```

### 工单流转

```
需求（UE 项目 + type=ue_content）
  ↓ Orchestrator
ue_content_pending
  ↓ UEEditorAgent._do_auto_dispatch()
    ├─ 含 blueprint/bp_ → BlueprintGenAction
    ├─ 含 level/关卡   → LevelGenAction
    └─ 含 Python 代码  → UERunPythonAction
  ↓
ue_content_done
  ↓（正常流程继续）
development → engine_compile → test → deploy
```

### SOP 片段（`sop/fragments/ue_content_gen.yaml`）

- 触发条件：`ue_content_pending` 状态 + `engine:ue5/ue4` trait + `type=ue_content`
- 插入位置：`architecture` 之后（priority=88）
- 最大重试：2 次

---

## 整体 UE 创作流水线（B-0 ~ B-3 完成）

```
用户需求（「创建波次生成系统」）
  ↓
工单创建（type=ue_content, engine:ue5）
  ↓
UEEditorAgent 自动分发
  ↓ BlueprintGenAction
    LLM 生成 Python 代码
    ue_python_bridge 发送到 UE Editor
    ✅ BP_WaveSpawner 写入 /Game/Blueprints/
  ↓ ue_content_done
  ↓（继续正常流程）
DevAgent → engine_compile → TestAgent → DeployAgent
```

**斜杠命令入口**（A-1 Commands）：
```
/ue-run import unreal; print(unreal.SystemLibrary.get_engine_version())
/ue-bp-gen 创建一个波次生成器，每隔5秒生成一个敌人
/ue-level 8×8地面 + 四角灯光 + NavMesh 全覆盖
```
