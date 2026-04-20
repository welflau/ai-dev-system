"""
验证 ActionNode.fill() 的 vision 支持（不打真实 LLM，捕获 prompt messages）。

3 个用例：
1. 无 images 参数 → content 是字符串（老行为）
2. 有 images 参数 → content 是 list，含 image blocks + text block
3. 非法 data URL → 跳过不阻塞

运行：cd backend && PYTHONIOENCODING=utf-8 python _test_vision_action_node.py
"""
import asyncio
import base64
import json
from unittest.mock import AsyncMock, patch

from pydantic import BaseModel, Field


class _DummyOut(BaseModel):
    ok: bool = False
    note: str = ""


async def test_no_images_keeps_string_content():
    """无 images 参数：content 仍为字符串（向后兼容）"""
    from actions.action_node import ActionNode

    captured = []

    async def mock_chat_json(messages, **kwargs):
        captured.append(messages)
        return {"ok": True, "note": "pass"}

    node = ActionNode(key="t", expected_type=_DummyOut, instruction="test")
    mock_llm = type("M", (), {})()
    mock_llm.chat_json = mock_chat_json
    await node.fill(req="ctx", llm=mock_llm)

    assert len(captured) == 1
    msg = captured[0][0]
    assert msg["role"] == "user"
    assert isinstance(msg["content"], str), f"期望 str，实际 {type(msg['content'])}"
    assert "ctx" in msg["content"]
    print("✅ Test 1: 无 images → content 保持字符串")


async def test_with_images_builds_vision_content():
    """有 images 参数：content 变成 vision blocks list"""
    from actions.action_node import ActionNode

    captured = []

    async def mock_chat_json(messages, **kwargs):
        captured.append(messages)
        return {"ok": True}

    # 构造一个假的 1x1 PNG base64
    fake_png_b64 = base64.b64encode(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    ).decode("ascii")
    data_url = f"data:image/png;base64,{fake_png_b64}"

    node = ActionNode(key="t", expected_type=_DummyOut, instruction="test")
    mock_llm = type("M", (), {})()
    mock_llm.chat_json = mock_chat_json
    await node.fill(req="look at image", llm=mock_llm, images=[data_url])

    msg = captured[0][0]
    assert isinstance(msg["content"], list), f"期望 list，实际 {type(msg['content'])}"
    assert len(msg["content"]) == 2  # 1 image + 1 text
    img_block = msg["content"][0]
    assert img_block["type"] == "image"
    assert img_block["source"]["type"] == "base64"
    assert img_block["source"]["media_type"] == "image/png"
    assert img_block["source"]["data"] == fake_png_b64
    txt_block = msg["content"][1]
    assert txt_block["type"] == "text"
    assert "look at image" in txt_block["text"]
    print("✅ Test 2: 有 images → content 是 vision blocks list")


async def test_invalid_image_skipped():
    """非法 data URL 被跳过，text block 仍在"""
    from actions.action_node import ActionNode

    captured = []

    async def mock_chat_json(messages, **kwargs):
        captured.append(messages)
        return {"ok": True}

    node = ActionNode(key="t", expected_type=_DummyOut, instruction="test")
    mock_llm = type("M", (), {})()
    mock_llm.chat_json = mock_chat_json
    # 两张图：一张合法，一张非法
    good = "data:image/png;base64," + base64.b64encode(b"ok").decode("ascii")
    bad = "this is not a data url"
    await node.fill(req="x", llm=mock_llm, images=[good, bad])

    msg = captured[0][0]
    assert isinstance(msg["content"], list)
    # 好图 + text（1 + 1 = 2），坏图被跳过
    assert len(msg["content"]) == 2
    assert msg["content"][0]["type"] == "image"
    assert msg["content"][1]["type"] == "text"
    print("✅ Test 3: 非法 data URL 跳过不阻塞")


async def test_multiple_images():
    """多图都能进 content"""
    from actions.action_node import ActionNode

    captured = []

    async def mock_chat_json(messages, **kwargs):
        captured.append(messages)
        return {"ok": True}

    node = ActionNode(key="t", expected_type=_DummyOut, instruction="test")
    mock_llm = type("M", (), {})()
    mock_llm.chat_json = mock_chat_json
    img = "data:image/png;base64," + base64.b64encode(b"x").decode("ascii")
    await node.fill(req="x", llm=mock_llm, images=[img, img, img])

    msg = captured[0][0]
    # 3 images + 1 text
    assert len(msg["content"]) == 4
    assert sum(1 for b in msg["content"] if b["type"] == "image") == 3
    print("✅ Test 4: 多图都进 content")


async def main():
    await test_no_images_keeps_string_content()
    await test_with_images_builds_vision_content()
    await test_invalid_image_skipped()
    await test_multiple_images()
    print("\n🎉 ActionNode vision 单测全部通过")


if __name__ == "__main__":
    asyncio.run(main())
