# NextPhase A-2：Thinking 三态模式 + 能力下沉 BaseAgent

> 系列：NextPhase  
> 日期：2026-05-18  
> 提交：`cddbd94`  
> 对应计划：`docs/20260518_04_ADS下一阶段综合开发计划.md` 方向 A-2

---

## 一、Thinking 三态模式（对标 Claude Code）

### 之前
`enable_thinking = _model_supports_thinking(model_id)`——模型支持就开，不支持就关，没有用户控制。

### 现在
三种模式，通过 Feature Flags 控制：

| 模式 | 行为 | 触发方式 |
|---|---|---|
| `adaptive`（默认）| 模型支持才开启 | 无需操作 |
| `on` | 强制开启，忽略模型支持 | `/think on` 或 `ultrathink` 关键字 |
| `off` | 强制关闭，禁用推理链 | `/think off` |

**实现路径**：
```
/think on → commands/think → Feature Flags thinking_mode=on
                                ↓
                    _resolve_thinking_enabled(session_id, model)
                                ↓
                    QueryEngine(enable_thinking=True, thinking_budget=N)
```

### ultrathink 关键字
输入含 `ultrathink`（大小写不敏感）时：
1. 自动设 `thinking_mode=on` + `thinking_budget=32000`
2. 输入框短暂显示紫色边框（视觉提示）
3. Toast 通知：「⚡ ultrathink 已启动」

---

## 二、能力下沉到 BaseAgent（架构重构核心）

### 问题
`compact_history` 和 `get_memory_prompt` 之前只在 `ChatAssistantAgent`，
DevAgent / TestAgent / 未来的 UEEditorAgent 全部拿不到。

### 修复
在 `BaseAgent` 加两个公共方法，所有 Agent 自动继承：

```python
class BaseAgent:
    async def compact_history(self, messages: list) -> str:
        """LLM 对话压缩——任何 Agent 的 REACT 循环均可调用"""
        
    async def get_memory_prompt(self, project_id: str, limit: int = 3) -> str:
        """查 agent_memory，返回适合注入 system prompt 的文本"""
```

`ChatAssistantAgent._compact_history_with_llm` 现在委托到 `BaseAgent.compact_history()`，原逻辑保留为 `_compact_history_with_llm_legacy` 备用。

### 验证
```python
# 任何 Agent 子类现在都可以：
result = await dev_agent.compact_history(history)
mem_text = await test_agent.get_memory_prompt(project_id)
```

---

## 三、Feature Flags 新增

`set_session_flag.py` 新增两个 flag：

| Flag | 默认 | 说明 |
|---|---|---|
| `thinking_mode` | `"adaptive"` | adaptive / on / off |
| `thinking_budget` | `8000` | thinking token 预算（≥ 1024）|

使用 `/think on/off/adaptive` 命令或 A-1 Commands 系统直接设置。

---

## 下一步

- **B-0**：UE Python 桥接（`/ue-run` 和 `/ue-bp-gen` 命令依赖）
- **A-3**（可选）：Memory 类型对齐 Claude Code 4 类型
