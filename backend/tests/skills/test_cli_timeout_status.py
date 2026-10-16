"""CLI 超时 ≠ 成功 —— 状态判定回归。

dev-notes/2026-10-16_01 记录的真实 CLI 验证暴露了一个假成功：
CLI 超时时产物恰好写完了（MCP 工具调用在超时前成功），`_collect_outputs`
扫到产物、`expected_output_count` 满足 → `status="success"`，但 message 是
`[CLI错误] 调用超时`。

修复链路：
  llm_client._call_cli_stream 超时 → yield {"type": "cli_timeout", ...}
  query_engine CLI 分支 → 收到 cli_timeout → yield BudgetExceededEvent
  SkillRunner.execute → BudgetExceededEvent → status="budget_exceeded"

这里验引擎层和 runner 层，不打桩 QueryEngine 本体，只打桩 LLM 的
`_call_cli_stream`（它要起真子进程）。
"""
import asyncio
from pathlib import Path

import pytest

from query_engine.engine import QueryEngine
from query_engine.events import BudgetExceededEvent, MessageDoneEvent

pytestmark = pytest.mark.real_builtin_skills


class _TimeoutLLM:
    """api_format=cli，_call_cli_stream 先给一段文本再给 cli_timeout。"""
    is_configured = True
    api_format = "cli"

    def __init__(self, with_text: bool = True):
        self.with_text = with_text

    async def _call_cli_stream(self, messages, temperature, max_tokens,
                               resume_session_id="", timeout_override=None):
        if self.with_text:
            yield {"type": "text_delta", "delta": "正在生成…"}
        yield {"type": "cli_timeout", "timeout": 240.0, "partial_text": ""}


class _NoopExecutor:
    async def execute(self, tool_name, tool_input, context):
        return "{}", None


def _collect(engine, messages, system, tools, context):
    async def main():
        events = []
        async for ev in engine.run(messages, system, tools, context):
            events.append(ev)
        return events
    return asyncio.run(main())


def test_cli_timeout_yields_budget_exceeded_not_done():
    """引擎层：cli_timeout 事件 → BudgetExceededEvent，而不是 MessageDoneEvent。"""
    engine = QueryEngine(llm_client=_TimeoutLLM(), tool_executor=_NoopExecutor())
    events = _collect(engine, [{"role": "user", "content": "跑 skill"}],
                      "system", [], {})

    kinds = [type(e).__name__ for e in events]
    assert "BudgetExceededEvent" in kinds, f"缺 BudgetExceededEvent: {kinds}"
    assert "MessageDoneEvent" not in kinds, (
        f"超时不该以 MessageDoneEvent 收尾（会误判 success）: {kinds}"
    )
    budget_ev = next(e for e in events if isinstance(e, BudgetExceededEvent))
    assert "240" in budget_ev.reason


def test_cli_timeout_without_text_still_budget_exceeded():
    """边界：超时前没有任何文本（full_text 为空）也走超限，不能吞掉。"""
    engine = QueryEngine(llm_client=_TimeoutLLM(with_text=False),
                         tool_executor=_NoopExecutor())
    events = _collect(engine, [{"role": "user", "content": "跑 skill"}],
                      "system", [], {})

    kinds = [type(e).__name__ for e in events]
    assert "BudgetExceededEvent" in kinds
    assert "MessageDoneEvent" not in kinds


def test_runner_timeout_is_budget_exceeded_even_with_artifact(tmp_path, monkeypatch):
    """runner 层：超时但产物已落盘 → status=budget_exceeded，不是 success。

    这是假成功的直接复现场景：LLM 在超时前用 MCP 工具写好了 outline.md，
    但这一轮没走完。旧代码会判 success；修复后必须 budget_exceeded。
    """
    from skills.executable_loader import ExecutableSkill
    from skills.runner import SkillRunner

    repo = tmp_path / "repo"
    repo.mkdir()

    skill = ExecutableSkill(
        skill_id="demo-outline", name="demo-outline", description="", body="",
        source_path=Path("SKILL.md"),
        builtin_tools=["write_file"],
        outputs={"root": "artifacts/{req_short}/{ticket_short}/content_outline",
                 "globs": ["outline.md"]},
    )

    # 模拟「超时前已用 MCP 工具写好了 outline.md」
    out_root = repo / "artifacts" / "c0ffee" / "beef01" / "content_outline"
    out_root.mkdir(parents=True)
    (out_root / "outline.md").write_text("# 大纲\n", encoding="utf-8")

    # 打桩 QueryEngine：只吐一个 BudgetExceededEvent（等价于引擎层
    # 收到 cli_timeout 后的上抛）。runner.execute 内部是
    # `from query_engine import QueryEngine`，得打 package 命名空间，
    # 打 query_engine.engine.QueryEngine 不会生效（会真起 CLI）。
    import query_engine as qe_pkg

    class _FakeEngine:
        def __init__(self, *a, **kw):
            pass

        def run(self, messages, system, tools, context):
            async def _gen():
                yield BudgetExceededEvent(reason="CLI 调用超时（240s）")
            return _gen()

    monkeypatch.setattr(qe_pkg, "QueryEngine", _FakeEngine)

    runner = SkillRunner(skill)
    context = {
        "repo_path": str(repo),
        "req_short": "c0ffee", "ticket_short": "beef01",
    }
    result = asyncio.run(runner.execute(context))

    assert result.status == "budget_exceeded", (
        f"超时不该判 success（旧假成功）: {result.status}"
    )
    # 但产物确实在 —— 已经写好的不该丢，供 orchestrator 决定重试还是收下
    assert len(result.outputs) == 1
    assert result.outputs[0].rel_path == "outline.md"
    assert "超时" in (result.message or "")
