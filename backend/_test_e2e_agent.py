"""
P2-5 端到端：通过 HTTP 直打 /api/projects/.../chat 端点，
CHAT_USE_AGENT=1 已启用，验证整条新链路：
  HTTP → chat_with_ai → _chat_via_agent → ChatAssistantAgent.chat → chat_with_tools → tool_use → Action
"""
import asyncio
import json
import sys
import httpx


BASE = "http://localhost:8001"


async def pick_project():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BASE}/api/projects")
        r.raise_for_status()
        ps = r.json().get("projects", [])
        if not ps:
            raise RuntimeError("没有项目")
        return ps[0]


async def chat(project_id: str, message: str):
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(
            f"{BASE}/api/projects/{project_id}/chat",
            json={"message": message},
        )
        r.raise_for_status()
        return r.json()


async def main():
    p = await pick_project()
    pid = p["id"]
    print(f"=== 项目: {p['name']} ({pid}) ===\n")

    # Test 1: 查询类（应触发 git_log）
    print("=== Test 1: 问『最近提交了什么』 ===")
    data = await chat(pid, "最近提交了什么？")
    reply = data.get("reply", "")
    action = data.get("action")
    print(f"reply: {reply[:300]}")
    print(f"action.type: {(action or {}).get('type')}")
    if action:
        print(f"action 完整: {json.dumps(action, ensure_ascii=False)[:500]}")
    print()

    # Test 2: 识别需求（应触发 confirm_requirement）
    print("=== Test 2: 说『帮我加一个访问计数功能』 ===")
    data = await chat(pid, "帮我加一个访问计数功能，显示在右下角")
    reply = data.get("reply", "")
    action = data.get("action")
    print(f"reply: {reply[:300]}")
    print(f"action.type: {(action or {}).get('type')}")
    if action:
        print(f"action 完整: {json.dumps(action, ensure_ascii=False)[:500]}")
    print()

    # Test 3: 纯闲聊（不应调任何工具）
    print("=== Test 3: 说『你好呀』（不应调工具）===")
    data = await chat(pid, "你好呀")
    reply = data.get("reply", "")
    action = data.get("action")
    print(f"reply: {reply[:200]}")
    print(f"action: {action}")
    assert action is None or action == {}, "闲聊不应触发工具！"
    print("✅ 纯文本回复，未触发工具\n")

    print("🎉 端到端测试完成（人工检查上面的 reply 和 action 是否合理）")


if __name__ == "__main__":
    asyncio.run(main())
