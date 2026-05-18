# NextPhase A-2：Thinking 三態模式 + 能力下沉 BaseAgent

> 系列：NextPhase  
> 日期：2026-05-18  
> 提交：`cddbd94`  
> 對應計劃：`docs/20260518_04_ADS下一阶段综合开发计划.md` 方向 A-2

---

## 一、Thinking 三態模式（對標 Claude Code）

### 之前
`enable_thinking = _model_supports_thinking(model_id)`——模型支持就開，不支持就關，沒有用戶控制。

### 現在
三種模式，通過 Feature Flags 控制：

| 模式 | 行為 | 觸發方式 |
|---|---|---|
| `adaptive`（默認）| 模型支持才開啟 | 無需操作 |
| `on` | 強制開啟，忽略模型支持 | `/think on` 或 `ultrathink` 關鍵字 |
| `off` | 強制關閉，禁用推理鏈 | `/think off` |

**實現路徑**：
```
/think on → commands/think → Feature Flags thinking_mode=on
                                ↓
                    _resolve_thinking_enabled(session_id, model)
                                ↓
                    QueryEngine(enable_thinking=True, thinking_budget=N)
```

### ultrathink 關鍵字
輸入含 `ultrathink`（大小寫不敏感）時：
1. 自動設 `thinking_mode=on` + `thinking_budget=32000`
2. 輸入框短暫顯示紫色邊框（視覺提示）
3. Toast 通知：「⚡ ultrathink 已啟動」

---

## 二、能力下沉到 BaseAgent（架構重構核心）

### 問題
`compact_history` 和 `get_memory_prompt` 之前只在 `ChatAssistantAgent`，
DevAgent / TestAgent / 未來的 UEEditorAgent 全部拿不到。

### 修復
在 `BaseAgent` 加兩個公共方法，所有 Agent 自動繼承：

```python
class BaseAgent:
    async def compact_history(self, messages: list) -> str:
        """LLM 對話壓縮——任何 Agent 的 REACT 循環均可調用"""
        
    async def get_memory_prompt(self, project_id: str, limit: int = 3) -> str:
        """查 agent_memory，返回適合注入 system prompt 的文本"""
```

`ChatAssistantAgent._compact_history_with_llm` 現在委託到 `BaseAgent.compact_history()`，原邏輯保留為 `_compact_history_with_llm_legacy` 備用。

### 驗證
```python
# 任何 Agent 子類現在都可以：
result = await dev_agent.compact_history(history)
mem_text = await test_agent.get_memory_prompt(project_id)
```

---

## 三、Feature Flags 新增

`set_session_flag.py` 新增兩個 flag：

| Flag | 默認 | 說明 |
|---|---|---|
| `thinking_mode` | `"adaptive"` | adaptive / on / off |
| `thinking_budget` | `8000` | thinking token 預算（≥ 1024）|

使用 `/think on/off/adaptive` 命令或 A-1 Commands 系統直接設置。

---

## 下一步

- **B-0**：UE Python 桥接（`/ue-run` 和 `/ue-bp-gen` 命令依赖）
- **A-3**（可选）：Memory 類型對齊 Claude Code 4 類型
