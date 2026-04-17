"""
端到端验证：问"XX 卡在哪 / 最近发生了什么"，AI 应调观测 Action。
"""
import asyncio
import httpx
import json


async def main():
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.get("http://localhost:8000/api/projects")
        pid = r.json()["projects"][0]["id"]
        print(f"项目: {pid}\n")

        # 问"访问计数卡在哪"——应触发 get_requirement_pipeline 或 logs
        r = await c.post(
            f"http://localhost:8000/api/projects/{pid}/chat",
            json={"message": "访问计数这个需求卡在哪里？最近发生了什么？"},
        )
        r.raise_for_status()
        data = r.json()
        reply = data.get("reply", "")
        action = data.get("action")

        print("=== AI 回复 ===")
        print(reply[:800])
        print()
        print(f"action.type: {(action or {}).get('type')}")
        if action:
            print(f"action keys: {list(action.keys())}")

        # 期望：AI 提到 force_pass / 打回 5 次 这种关键诊断信息
        hit_keywords = [k for k in ["打回", "force_pass", "强制", "testing_done", "合入"] if k in reply]
        print(f"\n命中诊断关键词: {hit_keywords}")

        assert reply, "reply 为空"
        if action and action.get("type") in ("requirement_pipeline", "ticket_status", "requirement_logs"):
            print("\n✅ AI 调用了观测 Action")
        else:
            print(f"\n⚠️  AI 没调观测 Action（action.type={(action or {}).get('type')}）")
            print("   可能原因：prompt 引导不够 / LLM 倾向用 git_log")


if __name__ == "__main__":
    asyncio.run(main())
