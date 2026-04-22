"""
Self-Consistency 投票单元测试（不依赖 LLM / DB，mock ActionNode.fill + llm.chat）

5 用例：
1. 3 个不同候选 + judge 选 #1 → best 是候选 1
2. 3 个候选里 2 个抛异常 → 剩 1 个不走 judge 直接返回
3. 3 个候选全失败 → raise ValueError
4. Judge LLM 失败 → fallback 到候选 0 + fallback=True
5. 并发 ContextVar（Skills）在各候选里能正确读到

运行：cd backend && PYTHONIOENCODING=utf-8 python _test_self_consistency.py
"""
import asyncio
import json
from unittest.mock import AsyncMock, patch

from pydantic import BaseModel


class FakeSchema(BaseModel):
    label: str = ""
    value: int = 0


def _make_fill_side_effect(outputs):
    """每次 fill 调用按顺序返回预制 output（以 FakeSchema 填充 instruct_content）"""
    state = {"i": 0}

    async def _fill(self, req, llm, max_tokens=16000, temperature=0.3, images=None):
        idx = state["i"]
        state["i"] += 1
        if idx < len(outputs):
            payload = outputs[idx]
            if isinstance(payload, Exception):
                raise payload
            self.instruct_content = FakeSchema(**payload)
            self.raw_content = json.dumps(payload, ensure_ascii=False)
        return self
    return _fill


def _make_node_factory():
    from actions.action_node import ActionNode
    return lambda: ActionNode(key="t", expected_type=FakeSchema, instruction="test")


class _FakeLLM:
    def __init__(self, judge_response=None, should_fail=False):
        self.judge_response = judge_response or '{"best_index": 0, "reasoning": "default"}'
        self.should_fail = should_fail
        self.judge_calls = 0

    async def chat(self, messages, temperature=0.3, max_tokens=400, **kwargs):
        self.judge_calls += 1
        if self.should_fail:
            raise RuntimeError("simulated judge failure")
        return self.judge_response


async def test_three_candidates_judge_picks_one():
    from actions.voting import fill_with_consistency
    from actions.action_node import ActionNode

    outputs = [
        {"label": "A", "value": 1},
        {"label": "B", "value": 2},
        {"label": "C", "value": 3},
    ]
    fake_llm = _FakeLLM(judge_response='{"best_index": 1, "reasoning": "B 更完整"}')

    with patch.object(ActionNode, "fill", _make_fill_side_effect(outputs)):
        best, all_nodes, info = await fill_with_consistency(
            _make_node_factory(), req="dummy", llm=fake_llm,
            n=3, temperature=0.8, max_tokens=200, task_desc="挑选最优",
        )
    assert len(all_nodes) == 3
    assert info["best_index"] == 1
    assert info["fallback"] is False
    assert best.instruct_content.label == "B"
    assert fake_llm.judge_calls == 1
    print("✅ Test 1 3 候选 + judge 选中 #1 通过")


async def test_single_successful_candidate_skips_judge():
    from actions.voting import fill_with_consistency
    from actions.action_node import ActionNode

    outputs = [
        RuntimeError("fail A"),
        {"label": "B", "value": 2},
        RuntimeError("fail C"),
    ]
    fake_llm = _FakeLLM()

    with patch.object(ActionNode, "fill", _make_fill_side_effect(outputs)):
        best, all_nodes, info = await fill_with_consistency(
            _make_node_factory(), req="dummy", llm=fake_llm, n=3, max_tokens=200,
        )
    assert len(all_nodes) == 1, f"应只剩 1 个成功候选，实际 {len(all_nodes)}"
    assert best.instruct_content.label == "B"
    assert fake_llm.judge_calls == 0, "单候选不应调 judge"
    assert "唯一成功" in info["reasoning"]
    print("✅ Test 2 单成功候选跳过 judge 通过")


async def test_all_fail_raises():
    from actions.voting import fill_with_consistency
    from actions.action_node import ActionNode

    outputs = [RuntimeError("A"), RuntimeError("B"), RuntimeError("C")]
    fake_llm = _FakeLLM()

    with patch.object(ActionNode, "fill", _make_fill_side_effect(outputs)):
        try:
            await fill_with_consistency(
                _make_node_factory(), req="x", llm=fake_llm, n=3, max_tokens=100,
            )
            assert False, "应该 raise"
        except ValueError as e:
            assert "全部失败" in str(e)
    print("✅ Test 3 全失败 raise 通过")


async def test_judge_fallback():
    from actions.voting import fill_with_consistency
    from actions.action_node import ActionNode

    outputs = [
        {"label": "A", "value": 1},
        {"label": "B", "value": 2},
    ]
    fake_llm = _FakeLLM(should_fail=True)

    with patch.object(ActionNode, "fill", _make_fill_side_effect(outputs)):
        best, _, info = await fill_with_consistency(
            _make_node_factory(), req="x", llm=fake_llm, n=2, max_tokens=100,
        )
    assert info["fallback"] is True
    assert info["best_index"] == 0
    assert best.instruct_content.label == "A"  # fallback 候选 0
    print("✅ Test 4 judge 失败 fallback 通过")


async def test_contextvar_preserved_in_parallel():
    """并行任务里 ContextVar（Skills）应能正确继承到每个候选的 ActionNode._compile()"""
    from contextvars import ContextVar
    from actions.voting import fill_with_consistency
    from actions.action_node import ActionNode
    from skills import _current_skills

    captured = []

    async def capture_fill(self, req, llm, max_tokens=16000, temperature=0.3, images=None):
        captured.append(_current_skills.get())
        self.instruct_content = FakeSchema(label="x", value=1)
        self.raw_content = '{"label":"x","value":1}'
        return self

    token = _current_skills.set("SKILL_MARKER_XYZ")
    try:
        with patch.object(ActionNode, "fill", capture_fill):
            best, all_nodes, _ = await fill_with_consistency(
                _make_node_factory(), req="r", llm=_FakeLLM(), n=3, max_tokens=100,
            )
    finally:
        _current_skills.reset(token)

    assert len(captured) == 3
    assert all(v == "SKILL_MARKER_XYZ" for v in captured), \
        f"所有并发候选应读到同一 ContextVar，实际: {captured}"
    print("✅ Test 5 并发 ContextVar 继承通过")


async def main():
    await test_three_candidates_judge_picks_one()
    await test_single_successful_candidate_skips_judge()
    await test_all_fail_raises()
    await test_judge_fallback()
    await test_contextvar_preserved_in_parallel()
    print("\n🎉 Self-Consistency 单测全部通过（5/5）")


if __name__ == "__main__":
    asyncio.run(main())
