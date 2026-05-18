# NextPhase B-1：BlueprintGenAction

> 系列：NextPhase  
> 日期：2026-05-18  
> 提交：`63e1635`  
> 依賴：B-0 `ue_python_bridge`

---

## 實現

### 執行流程

```
用戶輸入描述（自然語言）
  ↓
LLM（temperature=0.2）
  system: _BP_SYSTEM_PROMPT（含常用模式 few-shot）
  ↓ 生成 UE Python 代碼
ue_python_bridge.run_python(code, project_id)
  ↓ 通過 Remote Execution 發送到 UE Editor
Blueprint 創建/修改/編譯
  ↓
返回 stdout + result
```

### `_BP_SYSTEM_PROMPT` 內容

- Blueprint vs C++ 決策規則
- 新建 Blueprint 類模式
- 修改 CDO 屬性模式
- 添加組件模式
- 編譯 Blueprint 模式
- API 限制說明（節點圖級別需 `/ue-extend Blueprint`）

### 使用方式

**通過 `/ue-bp-gen` 命令**：
```
/ue-bp-gen 創建一個波次生成器，每隔5秒在隨機位置生成一個敵人
/ue-bp-gen 修改 BP_PlayerCharacter 的移動速度為 600
/ue-bp-gen 為 BP_Door 添加一個 IsLocked 布爾屬性，默認 false
```

**通過 AI 助手自然語言**（LLM 自動調用 `ue_blueprint_gen` 工具）：
```
「幫我創建一個 BP_WaveSpawner Blueprint，繼承自 Actor」
```

### 返回內容

- 執行成功：UE Editor 輸出的 stdout（如「✅ 已創建：/Game/Blueprints/BP_WaveSpawner」）
- 執行失敗：錯誤信息
- 附帶：生成的 Python 代碼（供用戶審查/複用）

---

## 下一步

- **B-2**：LevelGenAction — 類似架構，生成關卡布置代碼
- **B-3**：UEEditorAgent — 封裝 BP/Level 生成為工單 Agent，繼承 BaseAgent 公共能力
