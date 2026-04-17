"""
P0 验证：企业代理 api-skynetyu.woa.com/anthropic 是否支持 tool_use
独立脚本，不依赖数据库/事件总线/agent_registry
运行：cd backend && python _test_tool_use.py
"""
import asyncio
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s  %(message)s')
logger = logging.getLogger("tool_use_test")


async def main():
    from llm_client import llm_client

    if not llm_client.is_configured:
        print("❌ LLM 未配置（缺 LLM_BASE_URL / LLM_API_KEY）")
        sys.exit(1)

    print(f"✅ LLM 已配置: {llm_client.base_url} / {llm_client.model} / format={llm_client.api_format}")

    # 定义一个最简单的假工具：get_weather
    tools = [
        {
            "name": "get_weather",
            "description": "获取指定城市的当前天气。用户问到天气时调用。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称，例如『北京』『上海』",
                    }
                },
                "required": ["city"],
            },
        },
    ]

    class FakeToolExecutor:
        """假执行器：不真的查天气，返回固定字符串"""
        async def execute(self, name: str, input: dict) -> str:
            print(f"   🔧 工具被调用: name={name}, input={input}")
            if name == "get_weather":
                city = input.get("city", "未知")
                return json.dumps({
                    "city": city,
                    "temp": "22°C",
                    "weather": "晴",
                }, ensure_ascii=False)
            return f"未知工具: {name}"

    messages = [
        {"role": "user", "content": "帮我查一下北京现在的天气怎么样？"}
    ]

    system = "你是一个天气助手。当用户问天气时，使用 get_weather 工具查询，然后基于结果用中文友好回答。"

    print("\n=== 开始测试 tool_use ===\n")
    try:
        result = await llm_client.chat_with_tools(
            messages=messages,
            tools=tools,
            tool_executor=FakeToolExecutor(),
            max_rounds=5,
            temperature=0.3,
            max_tokens=1024,
            system=system,
        )
    except Exception as e:
        print(f"\n❌ chat_with_tools 抛异常: {type(e).__name__}: {e}")
        sys.exit(2)

    print(f"\n=== 测试结果 ===")
    print(f"finished: {result.get('finished')}")
    print(f"rounds:   {result.get('rounds')}")
    print(f"messages 条数: {len(result.get('messages', []))}")

    # 检查是否真的触发了 tool_use
    tool_use_count = 0
    tool_result_count = 0
    final_text = ""
    for msg in result.get("messages", []):
        if msg["role"] == "assistant" and isinstance(msg.get("content"), list):
            for b in msg["content"]:
                if isinstance(b, dict):
                    if b.get("type") == "tool_use":
                        tool_use_count += 1
                    elif b.get("type") == "text":
                        final_text = b.get("text", "")
        elif msg["role"] == "user" and isinstance(msg.get("content"), list):
            for b in msg["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    tool_result_count += 1

    print(f"\ntool_use 块数: {tool_use_count}")
    print(f"tool_result 块数: {tool_result_count}")
    print(f"\n最终回复:\n{final_text}")

    print("\n=== 判定 ===")
    if tool_use_count >= 1 and tool_result_count >= 1:
        print("✅ 代理支持 tool_use — 迁移方案 P1/P2 可推进")
    elif tool_use_count == 0:
        print("❌ LLM 没触发 tool_use（可能代理剥离了 tools 字段，或模型没识别）")
        print("   迁移方案需要改路线：保留文本协议，但用 Action 结构化产出")
    else:
        print(f"⚠️  异常：tool_use={tool_use_count}, tool_result={tool_result_count}")


if __name__ == "__main__":
    asyncio.run(main())
