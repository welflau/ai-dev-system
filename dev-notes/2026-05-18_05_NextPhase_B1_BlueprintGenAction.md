# NextPhase B-1：BlueprintGenAction

> 系列：NextPhase  
> 日期：2026-05-18  
> 提交：`63e1635`  
> 依赖：B-0 `ue_python_bridge`

---

## 实现

### 执行流程

```
用户输入描述（自然语言）
  ↓
LLM（temperature=0.2）
  system: _BP_SYSTEM_PROMPT（含常用模式 few-shot）
  ↓ 生成 UE Python 代码
ue_python_bridge.run_python(code, project_id)
  ↓ 通过 Remote Execution 发送到 UE Editor
Blueprint 创建/修改/编译
  ↓
返回 stdout + result
```

### `_BP_SYSTEM_PROMPT` 内容

- Blueprint vs C++ 决策规则
- 新建 Blueprint 类模式
- 修改 CDO 属性模式
- 添加组件模式
- 编译 Blueprint 模式
- API 限制说明（节点图级别需 `/ue-extend Blueprint`）

### 使用方式

**通过 `/ue-bp-gen` 命令**：
```
/ue-bp-gen 创建一个波次生成器，每隔5秒在随机位置生成一个敌人
/ue-bp-gen 修改 BP_PlayerCharacter 的移动速度为 600
/ue-bp-gen 为 BP_Door 添加一个 IsLocked 布尔属性，默认 false
```

**通过 AI 助手自然语言**（LLM 自动调用 `ue_blueprint_gen` 工具）：
```
「帮我创建一个 BP_WaveSpawner Blueprint，继承自 Actor」
```

### 返回内容

- 执行成功：UE Editor 输出的 stdout（如「✅ 已创建：/Game/Blueprints/BP_WaveSpawner」）
- 执行失败：错误信息
- 附带：生成的 Python 代码（供用户审查/复用）

---

## 下一步

- **B-2**：LevelGenAction — 类似架构，生成关卡布置代码
- **B-3**：UEEditorAgent — 封装 BP/Level 生成为工单 Agent，继承 BaseAgent 公共能力
