# ActionNode 与 Legacy 机制对比

> 日期: 2026-04-15 | 移植来源: MetaGPT `action_node.py`

---

## 一、两种机制概览

### Legacy 机制（原有）

```python
# Agent 内部直接调 LLM，手动解析
class ProductAgent:
    async def acceptance_review(self, context):
        prompt = f"验收以下结果...请返回 JSON: {{passed: true/false, score: 1-10}}"
        result = await llm_client.chat_json([{"role": "user", "content": prompt}])
        if result and isinstance(result, dict):
            passed = result.get("passed", True)      # 可能不存在
            score = result.get("score", 8)            # 可能不是 int
            return {"status": "acceptance_passed" if passed else "acceptance_rejected"}
        return {"status": "acceptance_passed"}  # 降级：啥也不管直接过
```

### ActionNode 机制（新）

```python
# Action 通过 ActionNode 调 LLM，自动验证输出
class AcceptanceReviewAction(ActionBase):
    async def run(self, context):
        node = ActionNode(
            key="acceptance_review",
            expected_type=ReviewOutput,      # Pydantic 模型
            instruction="验收以下开发结果",
        )
        await node.fill(req=context_str, llm=llm_client)
        review = node.instruct_content       # 类型安全的 ReviewOutput 对象
        # review.passed  → bool（保证存在）
        # review.score   → int（保证类型正确）
        # review.issues  → List[str]（保证是列表）
```

---

## 二、执行流程对比

### Legacy 流程

```
Agent.execute(task_name, context)
  ↓
手动拼接 prompt 字符串
  ↓
llm_client.chat_json([messages])
  ↓ 返回 dict 或 None
手动 if/else 检查每个字段
  ↓ 字段缺失？类型错误？
手动降级处理
  ↓
返回裸 dict（无类型保证）
```

### ActionNode 流程

```
Action.run(context)
  ↓
ActionNode(key, expected_type=Schema, instruction)
  ↓
node.fill(req=context, llm=llm_client)
  ↓ 内部自动完成：
  │  1. _compile(): 从 Schema 提取字段 → 生成格式约束 → 拼入 prompt
  │  2. llm.chat_json(): 调用 LLM
  │  3. Pydantic 验证: Schema(**response)
  │  4. 失败 → _lenient_parse(): 宽松解析，缺字段填默认值
  ↓
node.instruct_content  → 类型安全的 Pydantic 对象
  ↓
ActionResult(data, files) → 结构化返回
```

---

## 三、逐项对比

### 3.1 输出验证

| | Legacy | ActionNode |
|--|--------|-----------|
| **类型检查** | `isinstance(result, dict)` 手动判断 | Pydantic 自动校验类型 |
| **缺字段** | `result.get("score", 8)` 每个字段手写默认值 | Schema 定义默认值，自动填充 |
| **多余字段** | 静默忽略或报错 | 自动过滤，只保留 Schema 定义的字段 |
| **嵌套结构** | 手动层层 get | Pydantic 嵌套模型自动解析 |

**示例**：LLM 返回 `{"passed": "yes", "score": "八分"}`

```python
# Legacy: 可能出错
passed = result.get("passed", True)     # "yes" 不是 bool，但代码不检查
score = result.get("score", 8)          # "八分" 不是 int，后续计算会报错

# ActionNode: 宽松解析
# ReviewOutput(passed=True, score=6)  ← "yes"/"八分" 无法解析，用默认值
```

### 3.2 Prompt 工程

| | Legacy | ActionNode |
|--|--------|-----------|
| **格式约束** | 手动写 `请返回 JSON: {field1, field2}` | 自动从 Schema 生成格式约束 |
| **字段说明** | 手动写注释 | 自动提取类型和默认值 |
| **一致性** | 每个 Agent 各写各的 | 统一 compile 模板 |

**Legacy prompt**（手写）：
```
请返回 JSON 格式：
{
  "passed": true/false,
  "score": 1-10,
  "feedback": "验收意见",
  "issues": ["问题1", "问题2"]
}
```

**ActionNode prompt**（自动生成）：
```
请返回以下 JSON 格式（严格遵循字段名）:
{
  "passed": boolean  // 默认: true,
  "score": integer  // 默认: 6,
  "feedback": string,
  "issues": array
}
```

### 3.3 错误处理

| | Legacy | ActionNode |
|--|--------|-----------|
| **LLM 返回 None** | 各 Agent 自己写 if/else | 统一返回空 Schema（model_construct） |
| **JSON 解析失败** | 返回 None → 降级模板 | 宽松解析 → 尽量提取有效字段 |
| **字段类型错误** | 运行时报错（可能到下游才爆） | Pydantic 构造时捕获，用默认值 |
| **整个调用异常** | 各 Agent 各自 try/catch | ActionNode.fill 统一异常处理 |

**错误传播对比**：
```
Legacy:
  LLM 返回坏 JSON → json.loads 失败 → return None
  → Agent 降级生成空壳代码 → ProductAgent 验收看到空文件 → 打回
  → DevAgent 重试 → 又失败 → 死循环 53 次

ActionNode:
  LLM 返回坏 JSON → chat_json 尝试修复 → ActionNode 宽松解析
  → 至少有默认值的 Schema → 后续流程有基本数据可用 → 不会死循环
```

### 3.4 可维护性

| | Legacy | ActionNode |
|--|--------|-----------|
| **新增字段** | 改 prompt + 改 get + 改降级 + 改前端 | 改 Schema 加一行，其他自动 |
| **修改默认值** | 找到所有 `get("field", default)` 改 | Schema 改一处 |
| **复用** | 复制粘贴 prompt | 多个 Action 共用同一个 Schema |
| **测试** | 测整个 Agent | 单独测 Action + 单独测 Schema |

**新增字段示例**：给验收结果加一个 `suggestions` 字段

```python
# Legacy: 改 3 个地方
# 1. prompt 字符串加字段描述
# 2. result.get("suggestions", [])
# 3. 降级返回值加字段

# ActionNode: 改 1 个地方
class ReviewOutput(BaseModel):
    passed: bool = True
    score: int = 6
    feedback: str = ""
    issues: List[str] = []
    suggestions: List[str] = []  # ← 加这一行，完事
```

### 3.5 与 SOP 配置的集成

| | Legacy | ActionNode |
|--|--------|-----------|
| **行为配置** | 硬编码在 Agent 代码里 | SOP YAML `config` 字段传入 |
| **通过分数** | `if score >= 6` 写死 | `sop_config.get("pass_score", 6)` |
| **检查清单** | prompt 里写死 | YAML 定义 `check_items` 列表 |
| **修改行为** | 改代码 + 重启 | 改 YAML + 热重载 |

---

## 四、Schema 定义一览

```python
# actions/schemas.py — 所有 Action 的输出 Schema

class ArchitectureOutput(BaseModel):    # 架构设计
    architecture_type: str = ""
    tech_stack: Dict[str, str] = {}
    module_design: List[Dict] = []
    estimated_hours: float = 4

class DevOutput(BaseModel):             # 代码开发
    files: Dict[str, str] = {}          # 文件路径 → 内容
    notes: str = ""
    estimated_hours: float = 4

class ReviewOutput(BaseModel):          # 验收/审查
    passed: bool = True
    score: int = 6
    feedback: str = ""
    issues: List[str] = []

class TestReviewOutput(BaseModel):      # 代码审查
    score: int = 6
    issues: List[str] = []
    suggestions: List[str] = []

class DecomposeOutput(BaseModel):       # 需求拆单
    prd_summary: str = ""
    tickets: List[Dict] = []
```

---

## 五、优缺点总结

### ActionNode 优点

1. **类型安全**：输出是 Pydantic 对象，IDE 自动补全，运行时类型保证
2. **统一错误处理**：宽松解析 + 默认值，不会因为 LLM 输出格式问题导致崩溃或死循环
3. **Prompt 自动生成**：从 Schema 自动提取字段约束，不用手写 JSON 格式说明
4. **可维护**：加字段改一处 Schema，不用改 prompt + 解析 + 降级三个地方
5. **可复用**：多个 Action 可以共用 Schema（如 ReviewOutput 被验收和审查共用）
6. **可测试**：ActionNode 可以独立测试（不依赖 Agent 上下文）
7. **与 SOP 集成**：行为参数从 YAML 配置读取，不硬编码

### ActionNode 缺点

1. **学习成本**：需要理解 Pydantic + ActionNode + Schema 三层抽象
2. **间接层增加**：Agent → Action → ActionNode → LLM，调用链变长
3. **调试复杂**：出问题时需要追踪 Schema 验证 + 宽松解析 + 默认值三层逻辑
4. **Schema 约束**：输出必须是 JSON 结构，不适合自由文本输出（如生成文章）
5. **默认值陷阱**：宽松解析可能掩盖真实问题（LLM 返回垃圾也不报错，静默用默认值）

### Legacy 优点

1. **简单直接**：一个函数搞定，没有额外抽象
2. **灵活**：prompt 和解析逻辑完全自定义，无框架限制
3. **调试直观**：print 一下 result 就能看到 LLM 返回了什么

### Legacy 缺点

1. **脆弱**：LLM 输出稍有变化就崩溃
2. **重复代码**：每个 Agent 各写各的 prompt + 解析 + 降级
3. **类型不安全**：返回裸 dict，下游可能因为字段缺失或类型错误爆炸
4. **难维护**：加一个字段要改三个地方，容易遗漏

---

## 六、迁移建议

| 场景 | 推荐 |
|------|------|
| LLM 返回结构化 JSON（大多数场景） | **用 ActionNode** |
| LLM 返回自由文本（如生成文档正文） | 保持 Legacy |
| 不调 LLM 的纯规则逻辑 | 保持 Legacy |
| 需要 SOP 配置控制行为 | **用 ActionNode** |
| 复杂解析需要自定义（如 Markdown 拆分） | Legacy + 自定义解析 |

**结论**：结构化输出场景（90% 的 Agent 调用）应迁移到 ActionNode。自由文本和纯规则场景保持 Legacy。

---

*文档由 AI Dev System + Claude Code 协作生成*
