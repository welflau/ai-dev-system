"""
P2-5 冒烟测试：验证 ChatAssistantAgent 能正确注册、实例化、暴露工具，
以及 tool_executor 能正常 dispatch 到 Action。

不需要起后端、不强制真实 LLM 调用。

运行：cd backend && PYTHONIOENCODING=utf-8 python _test_chat_agent.py
"""
import asyncio
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s  %(message)s')


async def main():
    # --- 1. agent_registry 能发现并注册 ChatAssistant ---
    print("=== Test 1: agent_registry 注册 ===")
    import agent_registry as ar
    ar.discover_agents()
    registry = ar.get_registry()
    assert "ChatAssistant" in registry, "ChatAssistant 未注册！"
    print(f"已注册 Agent: {list(registry.keys())}")
    print("✅ 通过\n")

    # --- 2. 实例化 ---
    print("=== Test 2: ChatAssistantAgent 实例化 ===")
    ChatAssistantAgent = registry["ChatAssistant"]
    agent = ChatAssistantAgent()
    print(f"agent_type: {agent.agent_type}")
    print(f"react_mode: {agent.react_mode}")
    print(f"action 数量: {len(agent._actions)}")
    print(f"action 名称: {list(agent._actions.keys())}")
    assert agent.agent_type == "ChatAssistant"
    assert len(agent._actions) == 15
    print("✅ 通过\n")

    # --- 3. 暴露给 LLM 的 tool schema 排掉了 create_requirement ---
    print("=== Test 3: 暴露给 LLM 的 tool schemas ===")
    schemas = agent._exposed_tool_schemas()
    names = [s["name"] for s in schemas]
    print(f"暴露的 tool 名: {names}")
    assert "create_requirement" not in names, "create_requirement 不应暴露给 LLM！"
    assert "confirm_requirement" in names
    assert "git_log" in names
    print(f"共 {len(schemas)} 个工具（14 个，排除 create_requirement）")
    assert len(schemas) == 14
    print("✅ 通过\n")

    # --- 4. tool schema 结构符合 Anthropic 格式 ---
    print("=== Test 4: tool schema 结构 ===")
    for s in schemas:
        assert "name" in s and "description" in s and "input_schema" in s, f"schema 缺字段: {s}"
        assert s["input_schema"].get("type") == "object", f"input_schema 非 object: {s['name']}"
    print(f"✅ {len(schemas)} 个 schema 结构正确\n")

    # --- 5. _ChatToolExecutor 能 dispatch 到 Action ---
    print("=== Test 5: _ChatToolExecutor dispatch ===")
    from agents.chat_assistant import _ChatToolExecutor
    from database import db
    await db.connect()

    # 找一个真实 project_id
    projects = await db.fetch_all("SELECT id FROM projects LIMIT 1")
    if not projects:
        print("⚠️ 跳过（没有项目）")
    else:
        project_id = projects[0]["id"]
        executor = _ChatToolExecutor(agent, project_id)

        # 调 confirm_requirement：不写库，只返回卡片
        result_json = await executor.execute("confirm_requirement", {
            "title": "dispatch 测试",
            "description": "验证 tool_executor 路由正确",
            "priority": "low",
        })
        result = json.loads(result_json)
        print(f"confirm_requirement 返回: {result}")
        assert result["type"] == "confirm_requirement"
        assert result["title"] == "dispatch 测试"
        assert executor.first_action_result == result
        print("✅ 通过\n")

        # 再调一个：验证 first_action_result 保持第一次
        result2_json = await executor.execute("confirm_requirement", {
            "title": "第二次调用",
            "description": "",
        })
        result2 = json.loads(result2_json)
        assert result2["title"] == "第二次调用"
        assert executor.first_action_result["title"] == "dispatch 测试", \
            f"first_action_result 不应变！实际: {executor.first_action_result}"
        print("=== Test 6: first_action_result 只记录第一次 ===")
        print("✅ 通过\n")

    # --- 6. 直接调 create_requirement 被拒 ---
    print("=== Test 7: create_requirement 不允许 LLM 直接调 ===")
    executor2 = _ChatToolExecutor(agent, "FAKE_PRJ")
    blocked_result = await executor2.execute("create_requirement", {
        "title": "should be blocked",
        "description": "x",
    })
    print(f"返回: {blocked_result!r}")
    assert "不允许" in blocked_result or "blocked" in blocked_result.lower()
    print("✅ 通过（内部 Action 被拦截）\n")

    # --- 8. 未知工具 ---
    print("=== Test 8: 未知工具返回错误字符串 ===")
    r = await executor2.execute("foo_bar_xyz", {})
    print(f"返回: {r!r}")
    assert "未知工具" in r
    print("✅ 通过\n")

    # --- 9. 系统提示词构建（最小输入） ---
    print("=== Test 9: _build_system_prompt 最小输入 ===")
    prompt = agent._build_system_prompt(
        {"id": "PRJ-X", "name": "TestProject"},
        {"recent_requirements": [], "ticket_summary": "暂无", "file_tree": "", "key_files_content": "", "artifacts_summary": "暂无", "knowledge_content": ""},
    )
    print(f"prompt 长度: {len(prompt)} 字符（应显著小于旧版 ~3000+）")
    assert "你是 AI 自动开发系统的智能助手" in prompt
    # 关键：新 prompt 不应再出现 [ACTION:XXX] 格式说明
    assert "[ACTION:" not in prompt, "新 prompt 不应再有 [ACTION:XXX] 文本协议！"
    assert "说到做到" not in prompt
    print("✅ 通过（无 [ACTION:XXX] 文本协议残留）\n")

    print("🎉 所有 P2 结构性冒烟测试通过")


if __name__ == "__main__":
    asyncio.run(main())
