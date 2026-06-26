# ManualMode Phase4 — 智能任务识别：对话够清晰后弹「是否创建需求」

> 日期：2026-06-17
> 系列：ManualMode
> 关联文档：`docs/20260616_02_手动挡模式与多路径项目设计方案.md`
> 前置：`dev-notes/2026-06-16_07_ManualMode_Phase3_...`

---

## 背景

手动挡下用户直接在对话中处理任务，无工单流程。
但当任务变得清晰、涉及系统性改动时，应给用户一个机会正式创建需求进入工单流程。

Phase 4 实现：**对话 >= 2 轮后，AI 在 system prompt 中获得提示，判断任务是否足够清晰，主动询问是否创建需求**。

---

## 改动文件

### `backend/agents/chat_assistant.py`

#### `_build_manual_mode_section(project, history_len)` 签名更新

新增 `history_len` 参数，当 `history_len >= 2` 时，在手动挡区块末尾追加「智能任务识别」提示：

```
### 智能任务识别
在对话过程中，如果你判断用户的任务已经足够清晰（目标明确、影响范围确定）
且涉及较大改动（多个文件或系统性重构），可以主动询问：
> 「任务已明确，是否正式创建需求来跟踪进度？...」
询问后调用 confirm_requirement 工具产出草稿供用户确认。
注意：简单的单文件修改、提问、调试不需要询问。只有系统性改动才需要。
```

#### `chat()` 和 `chat_stream()` 传递 history_len

```python
history_len = len(history) if history else 0
system_prompt = await self._build_system_prompt(
    project, {**project_context, "history_len": history_len}
)
```

#### `_build_system_prompt()` 签名更新

```python
async def _build_system_prompt(self, project, context, history_len=0):
```

context 里的 `history_len` 透传给 `_build_manual_mode_section()`。

---

## 触发逻辑

```
对话 < 2 轮  → 无「智能任务识别」提示，AI 正常执行
对话 >= 2 轮 → system prompt 加入提示
                AI 判断任务是否够清晰
                  ├─ 简单改动/提问 → 直接处理，不询问
                  └─ 系统性改动   → 主动询问「是否创建需求？」
                                      ↓ 调 confirm_requirement 产草稿
                                      用户确认 → 进入工单流程（自动挡）
                                      用户拒绝 → 继续手动挡对话处理
```

---

## 设计决策

- **不强制弹卡片**：AI 自己判断，避免每轮都打断用户
- **门槛：history_len >= 2**：前 1-2 轮是探索阶段，不打断
- **只针对手动挡**：自动挡项目走原有需求创建流程
- **简单任务豁免**：单文件修改/提问/调试不触发

---

## 验证

1. 手动挡项目对话 1 轮：不出现创建需求询问
2. 对话 3 轮后提一个系统性改动（如「重构整个登录模块」）
3. AI 应主动问「是否正式创建需求？」并给出 confirm_requirement 卡片
4. 点「确认」→ 工单流程启动；点「取消」→ AI 继续直接处理
