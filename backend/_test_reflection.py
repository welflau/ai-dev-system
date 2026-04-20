"""
ReflectionAction 单元测试（不依赖 DB / 后端 server，只 mock LLM）

4 个用例：
1. happy path：LLM 返回完整 JSON → 5 字段都有
2. markdown 包裹：LLM 返回 ```json ... ``` 要能剥掉
3. 降级：LLM 抛异常 → 返回最小反思（confidence <= 0.3）
4. 字段缺失容错：LLM 返回部分字段 → 其他字段有默认值

运行：cd backend && PYTHONIOENCODING=utf-8 python _test_reflection.py
"""
import asyncio
import json
from unittest.mock import AsyncMock, patch


async def test_happy_path():
    from actions.reflection import ReflectionAction

    fake = json.dumps({
        "root_cause": "上次没有修改 index.html 添加计数器 DOM",
        "missed_requirements": ["右下角 DOM 元素", "localStorage 持久化"],
        "previous_attempt_issue": "自测只跑了 pytest 没查前端",
        "strategy_change": "这次直接改 index.html 的 body",
        "specific_changes": [
            "在 </body> 前加 <div id=\"counter\">",
            "加 <script> 用 localStorage 计数",
        ],
        "confidence": 0.85,
    }, ensure_ascii=False)

    with patch("llm_client.llm_client.chat", AsyncMock(return_value=fake)):
        result = await ReflectionAction().run({
            "ticket_description": "加访问计数",
            "failure_type": "acceptance_rejected",
            "rejection_reason": "页面上看不到计数器",
            "retry_count": 2,
            "previous_code": {"index.html": "<html>...</html>"},
            "previous_reflections": [],
        })

    assert result.success, f"失败: {result.error}"
    refl = result.data["reflection"]
    assert refl["root_cause"].startswith("上次没有"), refl
    assert len(refl["missed_requirements"]) == 2
    assert len(refl["specific_changes"]) == 2
    assert refl["confidence"] == 0.85
    assert result.data["retry_count"] == 2
    print("✅ Test 1 happy path 通过")


async def test_markdown_wrap():
    from actions.reflection import ReflectionAction

    fake = """```json
{
  "root_cause": "x",
  "missed_requirements": ["a"],
  "previous_attempt_issue": "y",
  "strategy_change": "z",
  "specific_changes": ["c"],
  "confidence": 0.5
}
```"""
    with patch("llm_client.llm_client.chat", AsyncMock(return_value=fake)):
        result = await ReflectionAction().run({
            "ticket_description": "t",
            "failure_type": "acceptance_rejected",
            "rejection_reason": "r",
            "retry_count": 1,
        })

    assert result.success
    assert result.data["reflection"]["root_cause"] == "x"
    print("✅ Test 2 markdown 包裹剥离通过")


async def test_llm_failure_fallback():
    from actions.reflection import ReflectionAction

    with patch("llm_client.llm_client.chat", AsyncMock(side_effect=Exception("timeout"))):
        result = await ReflectionAction().run({
            "ticket_description": "加计数",
            "failure_type": "acceptance_rejected",
            "rejection_reason": "缺少 DOM",
            "retry_count": 1,
        })

    # 降级仍返回 success=True（不阻塞主流程），但 confidence 低
    assert result.success
    refl = result.data["reflection"]
    assert refl["confidence"] <= 0.5
    assert "缺少 DOM" in refl["strategy_change"]  # 降级会透传 rejection_reason
    print("✅ Test 3 LLM 失败降级通过")


async def test_partial_json_field_defaults():
    from actions.reflection import ReflectionAction

    fake = json.dumps({
        "root_cause": "只给了 root_cause",
        # 其他字段都没给
    })
    with patch("llm_client.llm_client.chat", AsyncMock(return_value=fake)):
        result = await ReflectionAction().run({
            "ticket_description": "t",
            "failure_type": "testing_failed",
            "test_issues": ["issue A"],
            "retry_count": 1,
        })

    assert result.success
    refl = result.data["reflection"]
    assert refl["root_cause"] == "只给了 root_cause"
    assert refl["missed_requirements"] == []
    assert refl["specific_changes"] == []
    assert 0.0 <= refl["confidence"] <= 1.0
    print("✅ Test 4 字段缺失容错通过")


async def test_reflection_with_history():
    """多次重试时 prompt 里能带上历次反思摘要"""
    from actions.reflection import ReflectionAction

    fake = json.dumps({
        "root_cause": "换了思路",
        "missed_requirements": [],
        "previous_attempt_issue": "",
        "strategy_change": "新策略",
        "specific_changes": ["新修改 1"],
        "confidence": 0.7,
    })

    captured_messages = []

    async def mock_chat(messages, **kwargs):
        captured_messages.extend(messages)
        return fake

    with patch("llm_client.llm_client.chat", side_effect=mock_chat):
        result = await ReflectionAction().run({
            "ticket_description": "改背景",
            "failure_type": "acceptance_rejected",
            "rejection_reason": "还是不对",
            "retry_count": 3,
            "previous_reflections": [
                {"root_cause": "根因 1", "strategy_change": "策略 1"},
                {"root_cause": "根因 2", "strategy_change": "策略 2"},
            ],
        })

    # 验证 prompt 里包含了历次反思
    user_prompt = next(m["content"] for m in captured_messages if m["role"] == "user")
    assert "历次反思" in user_prompt
    assert "根因 1" in user_prompt
    assert "根因 2" in user_prompt
    assert "第 3 次" in user_prompt  # retry_count
    assert result.success
    print("✅ Test 5 多次重试历史累积通过")


async def main():
    await test_happy_path()
    await test_markdown_wrap()
    await test_llm_failure_fallback()
    await test_partial_json_field_defaults()
    await test_reflection_with_history()
    print("\n🎉 Reflection 单测全部通过")


if __name__ == "__main__":
    asyncio.run(main())
