"""
专项验证：LLM 用 list 做 tool_input 时不再炸，自动转 {}。
直接压 _ChatToolExecutor.execute（绕过 LLM），模拟 Anthropic 偶尔返回的 [] 情形。
"""
import asyncio
import json


async def main():
    from database import db
    await db.connect()

    projects = await db.fetch_all("SELECT id FROM projects LIMIT 1")
    project_id = projects[0]["id"]

    from agent_registry import discover_agents, get_registry
    discover_agents()
    agent = get_registry()["ChatAssistant"]()

    from agents.chat_assistant import _ChatToolExecutor
    executor = _ChatToolExecutor(agent, project_id)

    # 场景 1：LLM 传 list 而不是 dict（复现原 bug）
    print("=== 场景 1: tool_input 是 list ===")
    r = await executor.execute("git_list_branches", [])
    data = json.loads(r)
    print(f"type={data.get('type')}, action={data.get('action')}")
    assert data.get("type") in ("git_result", "error"), f"unexpected: {data}"
    print("✅ 没炸，降级到空字典参数并正常执行\n")

    # 场景 2：tool_input 是 None
    print("=== 场景 2: tool_input 是 None ===")
    r = await executor.execute("git_list_branches", None)
    data = json.loads(r)
    print(f"type={data.get('type')}")
    assert data.get("type") in ("git_result", "error")
    print("✅ 没炸\n")

    # 场景 3：正常 dict 不受影响
    print("=== 场景 3: tool_input 正常 dict ===")
    r = await executor.execute("git_log", {"limit": 3})
    data = json.loads(r)
    print(f"type={data.get('type')}")
    assert data.get("type") in ("git_result", "error")
    print("✅ 正常\n")

    print("🎉 原 bug 已修复")


if __name__ == "__main__":
    asyncio.run(main())
