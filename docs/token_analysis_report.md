# AI 开发系统 - Token 使用追踪分析报告

## 执行摘要

系统**已具备基础的 LLM 调用记录能力**，但**缺乏按 Agent 分类的深度使用分析**。当前统计面板不显示 Token 相关数据。

## 1. 当前 Token 追踪机制 ✓

### 数据库表结构 (database.py, lines 253-269)

llm_conversations 表包含:
- ✓ input_tokens (INTEGER) -- 输入 Token 数
- ✓ output_tokens (INTEGER) -- 输出 Token 数  
- ✓ agent_type (TEXT) -- Agent 类型
- ✓ model (TEXT) -- 使用的模型
- ✓ status (TEXT) -- success/fallback
- ✓ created_at (TEXT) -- 记录时间

### 数据库索引 (database.py, lines 392-394)

- ✓ idx_llm_conversations_ticket
- ✓ idx_llm_conversations_requirement  
- ✓ idx_llm_conversations_project (支持项目级统计)

## 2. LLM 上下文追踪 ✓

### set_llm_context() 函数 (llm_client.py, lines 55-77)

使用 contextvars 实现协程安全的上下文存储。

### 调用位置分布

- chat.py:289 -- ChatAssistant
- chat.py:167 -- 群聊
- orchestrator.py:481 -- ProductAgent
- orchestrator.py:914 -- 工单处理
- milestones.py:43 -- RoadmapPlanner

## 3. 当前统计面板 ❌ INCOMPLETE

### 前端 (frontend/app.js, lines 3483-3563)

loadStats() 显示：
- ✓ 工单统计
- ✓ 模块分布
- ✓ Agent 工作量（任务数）
- ❌ Token 消耗（完全缺失）

### 后端 API (backend/api/tickets.py, lines 463-511)

**关键发现**: llm_conversations 表有 Token 数据，但统计 API 完全没有查询它。

## 4. 需求缺口

| 缺陷 | 优先级 |
|------|-------|
| 无 Token 总数统计 | 高 |
| 无 Agent 级 Token 分解 | 高 |
| 无时间序列趋势 | 中 |
| 无实时告警 | 中 |
| 无成本估算 | 中 |

## 5. 实现路线图

### Phase 1: 后端数据查询 (1-2 小时)

扩展 get_project_stats() 返回 Token 统计:

```python
llm_stats = await db.fetch_all("""
    SELECT 
        SUM(input_tokens) as total_input,
        SUM(output_tokens) as total_output,
        COUNT(*) as call_count,
        agent_type
    FROM llm_conversations 
    WHERE project_id = ? AND status = 'success'
    GROUP BY agent_type
""", (project_id,))

return {
    ...existing_stats...,
    "llm_stats": {
        "total_input_tokens": sum(input),
        "total_output_tokens": sum(output),
        "by_agent": {...},
        "by_model": {...},
    }
}
```

### Phase 2: 前端展示 (2-3 小时)

添加 Token 卡片和分布图表到 loadStats()。

### Phase 3: 实时监控 (2-3 小时)

日志面板显示 Token，实现告警规则。

## 6. SQL 查询示例

### 按 Agent 统计 Token

```sql
SELECT 
    agent_type,
    COUNT(*) as call_count,
    SUM(input_tokens) as total_input,
    SUM(output_tokens) as total_output
FROM llm_conversations
WHERE project_id = ? AND status = 'success'
GROUP BY agent_type
ORDER BY total_input + total_output DESC;
```

### 时间序列趋势

```sql
SELECT 
    DATE(created_at) as date,
    SUM(input_tokens + output_tokens) as daily_tokens,
    COUNT(*) as call_count
FROM llm_conversations
WHERE project_id = ? AND created_at >= datetime('now', '-30 days')
GROUP BY DATE(created_at)
ORDER BY date DESC;
```

## 7. 文件修改清单

### 后端
- backend/api/tickets.py (lines 463-511): 扩展统计 API
- backend/llm_client.py (lines 354-361): 增强日志信息

### 前端
- frontend/app.js (lines 3491-3563): 添加 Token 显示
- frontend/styles.css: Token 样式

## 8. 优先级排序

### M0 - 本周完成
1. 扩展 /stats API 返回 Agent Token
2. 前端添加 Token 卡片
3. 成本估算

### M1 - 两周完成
4. Token 趋势图
5. 实时告警
6. 成本分摊

## 总结

**当前**:
- ✓ 底层数据完整
- ✗ 统计和展示缺失

**改进**: 需要添加 SQL 查询、API 端点和前端图表。

**预计工时**: 6-10 小时
