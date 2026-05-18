# NextPhase B-0：UE Python 橋接

> 系列：NextPhase  
> 日期：2026-05-18  
> 提交：`5bdbd8b`  
> 對應計劃：`docs/20260518_04_ADS下一阶段综合开发计划.md` 方向 B-0

---

## 背景

ADS 原有 UCP 協議（TCP 9876）發送結構化命令（截圖、啟動等），但無法發送任意 Python 代碼。ECC 的 `ue_python.py` 使用 UE 官方 `remote_execution.py`（UDP 多播發現 + TCP 執行），能發送任意 Python，是 Blueprint 生成、關卡布置等創作能力的基礎。

---

## 實現

### `backend/engines/ue_python_bridge.py`

移植 ECC/scripts/ue_python.py，適配 ADS 異步環境：

**通信協議**：
```
ADS 後端
  ↓ asyncio.create_subprocess_exec（非阻塞）
子進程（runner 腳本）
  ↓ UDP 多播（port 6776）
UE Editor（發現階段，3秒）
  ↓ TCP 連接
執行 Python 代碼 → 返回 JSON 結果
```

**引擎路徑優先順序**：
1. 顯式傳入 `engine_path`
2. 環境變量 `UE_ENGINE_PATH`
3. Windows 註冊表（復用 ADS `ue_resolver.detect_installed_engines()`）
4. 常見路徑枚舉（C:-I: 盤 × UE 5.1-5.7）

**多 Editor 匹配**：
- 查 `projects.local_repo_path` 作為 hint
- 按 `project_root` 或 `project_name` 精準匹配
- 多個 Editor 無法匹配時取第一個並警告

**返回格式**：
```python
{
    "success": bool,
    "stdout": str,   # 合並的 print() 輸出
    "result": str,   # 最後一個表達式的值
    "error": str | None,
    "exit_code": int,
}
```

### `backend/actions/ue_run_python.py`

`UERunPythonAction`：作為 ChatAssistantAgent 的工具暴露，LLM 可主動調用。

### `/ue-run` 命令升級

從「⚠️ 尚未實現」升級為真實橋接：
```
/ue-run import unreal; print(unreal.SystemLibrary.get_engine_version())
→ ✅ 執行成功
```
→ `5.5.0-37670630+++UE5+Release-5.5`

---

## 前置條件

UE Editor 啟用 Remote Execution Server：
```
Edit > Project Settings > Plugins > Python > Enable Remote Execution Server ✓
```

或設置環境變量：
```
set UE_ENGINE_PATH=C:\Epic Games\UE_5.5
```

---

## 下一步

- **B-1**：BlueprintGenAction — 基於 Python 橋接生成 BP
- **B-2**：LevelGenAction — 基於 Python 橋接布置關卡
- **B-3**：UEEditorAgent — 封裝 BP/Level 生成為工單 Agent
