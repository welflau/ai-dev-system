"""
P3-3 降级验证：强制让新路径抛异常，确认请求自动走旧路径并返回正常响应。
原理：Monkey-patch ChatAssistantAgent.chat 让它抛一个异常，
然后直接调 chat_with_ai（绕过 HTTP），观察返回与日志。

运行：cd backend && PYTHONIOENCODING=utf-8 python _test_fallback.py
"""
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s  %(message)s')


async def main():
    from database import db
    await db.connect()

    # 1. 找一个项目
    projects = await db.fetch_all("SELECT id, name FROM projects LIMIT 1")
    if not projects:
        print("❌ 没有项目")
        sys.exit(1)
    project_id = projects[0]["id"]
    project_name = projects[0]["name"]
    print(f"✅ 测试项目: {project_id} ({project_name})\n")

    # 2. Monkey-patch ChatAssistantAgent.chat 让它必炸
    from agents.chat_assistant import ChatAssistantAgent
    original_chat = ChatAssistantAgent.chat

    async def broken_chat(self, **kwargs):
        raise RuntimeError("[P3-3 fallback test] 人为注入的异常，模拟新路径失败")

    ChatAssistantAgent.chat = broken_chat

    try:
        # 3. 直接调 endpoint 函数（等价 HTTP 请求）
        from api.chat import chat_with_ai, ChatRequest

        print("=== Test: flag=on 且新路径抛异常，应降级到旧路径 ===")
        # 用一个简单消息（闲聊类，旧路径也能处理）
        req = ChatRequest(message="你好呀", history=None, images=None)
        try:
            resp = await chat_with_ai(project_id=project_id, req=req)
        except Exception as e:
            print(f"❌ 降级失败！异常冒泡到端点: {type(e).__name__}: {e}")
            sys.exit(2)

        print(f"reply: {resp.reply[:200]}")
        print(f"action: {resp.action}")
        print()

        # 4. 验证 fallback 日志落盘了
        fallback_logs = await db.fetch_all(
            "SELECT * FROM ticket_logs WHERE project_id = ? AND action = 'chat_fallback' ORDER BY created_at DESC LIMIT 3",
            (project_id,),
        )
        print(f"=== Fallback 日志记录数：{len(fallback_logs)} ===")
        for log in fallback_logs[:1]:
            print(f"  最新: {log['detail'][:200]}")
        assert len(fallback_logs) >= 1, "fallback 日志未写入 ticket_logs！"
        print("✅ fallback 已记录到 ticket_logs\n")

        # 5. 验证 reply 非空（旧路径成功返回）
        assert resp.reply, f"降级后 reply 仍为空！"
        print("✅ 降级后返回正常响应\n")

        print("🎉 P3-3 降级验证通过：新路径失败时自动降级到旧路径，不影响用户")

    finally:
        # 还原 monkeypatch
        ChatAssistantAgent.chat = original_chat


if __name__ == "__main__":
    asyncio.run(main())
