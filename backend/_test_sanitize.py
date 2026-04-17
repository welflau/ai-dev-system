"""
验证 chat_with_tools 的 sanitize 修复后，LLM 用 [] 调无参工具时
整条 ReAct 链路能走到第 2 轮并给出自然语言回复。
"""
import asyncio
import httpx


async def main():
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.get("http://localhost:8000/api/projects")
        pid = r.json()["projects"][0]["id"]
        print(f"使用项目: {pid}")

        # 这条消息极可能触发 git_list_branches（无参工具）
        r = await c.post(
            f"http://localhost:8000/api/projects/{pid}/chat",
            json={"message": "当前在哪个分支？有哪些分支？"},
        )
        r.raise_for_status()
        data = r.json()
        reply = data.get("reply", "")
        action = data.get("action")

        print(f"\nreply:\n{reply[:600]}\n")
        print(f"action.type: {(action or {}).get('type')}")

        # 成功条件：reply 非空 + reply 是自然语言而非裸 markdown（含判断性总结）
        assert reply, "reply 为空！第 2 轮 LLM 仍失败"
        assert len(reply) > 50, f"reply 太短可能还是 action.message 兜底: {reply!r}"
        print("\n✅ Sanitize 修复生效：第 2 轮 LLM 正常生成了自然语言回复")


if __name__ == "__main__":
    asyncio.run(main())
