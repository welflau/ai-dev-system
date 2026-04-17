"""
AI 助手 (ChatAssistantAgent) 的 Action 集合

每个 Action 独立一个文件，继承 ActionBase。
相比通用 Agent 的 Action：
- 多一个 `tool_schema` 属性（Anthropic tool-use 格式），供 tool_use 场景使用
- 多数 Action 的 run() 返回结果直接对前端 action 字段可见，需保持结构稳定
"""
