"""
SessionLogger 单元测试（5 用例）

1. 首次 log_event 创建目录 + banner
2. 多次事件顺序追加
3. log_llm 写入 transcript + jsonl
4. tool_calls.jsonl 每行是合法 JSON
5. asyncio.gather 并发 100 条不乱序不截断

运行：cd backend && PYTHONIOENCODING=utf-8 python _test_session_logger.py
"""
import asyncio
import json
import tempfile
from pathlib import Path


async def test_creates_session_dir_and_header():
    from session_logger import SessionLogger

    with tempfile.TemporaryDirectory() as td:
        sl = SessionLogger(root=Path(td))
        await sl.log_event(
            requirement_id="REQ-TEST-1",
            kind="log",
            agent="DevAgent",
            action="develop",
            ticket_id="T-abc",
            message="工单开始",
        )
        session_dir = Path(td) / "session_REQ-TEST-1"
        assert session_dir.exists(), "目录应被懒创建"

        transcript = session_dir / "transcript.txt"
        jsonl = session_dir / "tool_calls.jsonl"
        assert transcript.exists() and jsonl.exists()

        content = transcript.read_text(encoding="utf-8")
        assert "Session: requirement REQ-TEST-1" in content, "banner 应存在"
        assert "Started:" in content
        assert "工单开始" in content
    print("✅ Test 1 目录 + banner + 首次写入通过")


async def test_events_appended_in_order():
    from session_logger import SessionLogger

    with tempfile.TemporaryDirectory() as td:
        sl = SessionLogger(root=Path(td))
        for i in range(5):
            await sl.log_event(
                requirement_id="REQ-ORDER",
                kind="log",
                agent="DevAgent",
                action="develop",
                ticket_id=f"T-{i}",
                message=f"事件 #{i}",
            )
        transcript = (Path(td) / "session_REQ-ORDER" / "transcript.txt").read_text(encoding="utf-8")
        # 五个事件应按顺序出现
        positions = [transcript.find(f"事件 #{i}") for i in range(5)]
        assert all(p > 0 for p in positions), "所有事件应都出现"
        assert positions == sorted(positions), "顺序应严格递增"
    print("✅ Test 2 事件顺序追加通过")


async def test_log_llm_writes_both_files():
    from session_logger import SessionLogger

    with tempfile.TemporaryDirectory() as td:
        sl = SessionLogger(root=Path(td))
        await sl.log_llm(
            requirement_id="REQ-LLM",
            agent="DevAgent",
            action="write_code",
            ticket_id="T-1",
            model="claude-sonnet-4-6",
            input_tokens=1234,
            output_tokens=567,
            duration_ms=2100,
            status="success",
        )
        session_dir = Path(td) / "session_REQ-LLM"
        transcript = (session_dir / "transcript.txt").read_text(encoding="utf-8")
        assert "🧠" in transcript
        assert "DevAgent.write_code" in transcript
        assert "1234/567 tokens" in transcript
        assert "2.1s" in transcript

        lines = [l for l in (session_dir / "tool_calls.jsonl").read_text(encoding="utf-8").splitlines() if l]
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["kind"] == "llm"
        assert rec["model"] == "claude-sonnet-4-6"
        assert rec["input_tokens"] == 1234
        assert rec["status"] == "success"
    print("✅ Test 3 LLM 写入双格式通过")


async def test_jsonl_lines_are_valid_json():
    from session_logger import SessionLogger

    with tempfile.TemporaryDirectory() as td:
        sl = SessionLogger(root=Path(td))
        # 写混合事件
        await sl.log_event(requirement_id="REQ-JSON", kind="log", agent="A", action="x", message="第一条 含中文")
        await sl.log_event(requirement_id="REQ-JSON", kind="reflection", agent="DevAgent", action="reflection",
                           ticket_id="T-1", message="reflection #2",
                           detail={"reflection": {"root_cause": "DOM 缺失", "confidence": 0.85}})
        await sl.log_llm(requirement_id="REQ-JSON", agent="DevAgent", action="reflect",
                         model="m", input_tokens=10, output_tokens=5, duration_ms=100)

        jsonl_path = Path(td) / "session_REQ-JSON" / "tool_calls.jsonl"
        lines = [l for l in jsonl_path.read_text(encoding="utf-8").splitlines() if l]
        assert len(lines) == 3
        for line in lines:
            rec = json.loads(line)  # 应全部合法
            assert "ts" in rec and "kind" in rec
        # 验证 detail 嵌套结构保留
        rec = json.loads(lines[1])
        assert rec["detail"]["reflection"]["root_cause"] == "DOM 缺失"
        assert rec["detail"]["reflection"]["confidence"] == 0.85
    print("✅ Test 4 jsonl 全合法 + detail 嵌套保留通过")


async def test_concurrent_writes_no_corruption():
    from session_logger import SessionLogger

    with tempfile.TemporaryDirectory() as td:
        sl = SessionLogger(root=Path(td))
        N = 100

        async def write(i):
            await sl.log_event(
                requirement_id="REQ-CONCUR",
                kind="log",
                agent="A",
                action="x",
                ticket_id=f"T-{i}",
                message=f"msg-{i}",
            )

        await asyncio.gather(*(write(i) for i in range(N)))

        session_dir = Path(td) / "session_REQ-CONCUR"
        # transcript 行数：banner 4 行 + 空行 1 + N 条事件
        transcript = (session_dir / "transcript.txt").read_text(encoding="utf-8")
        event_lines = [l for l in transcript.splitlines() if l.startswith("[")]
        assert len(event_lines) == N, f"应有 {N} 条事件行，实际 {len(event_lines)}"

        jsonl_lines = [l for l in (session_dir / "tool_calls.jsonl").read_text(encoding="utf-8").splitlines() if l]
        assert len(jsonl_lines) == N
        for line in jsonl_lines:
            rec = json.loads(line)  # 全部合法（无截断 / 重叠）
            assert rec["kind"] == "log"
    print("✅ Test 5 并发 100 条无损通过")


async def main():
    await test_creates_session_dir_and_header()
    await test_events_appended_in_order()
    await test_log_llm_writes_both_files()
    await test_jsonl_lines_are_valid_json()
    await test_concurrent_writes_no_corruption()
    print("\n🎉 SessionLogger 单测全部通过（5/5）")


if __name__ == "__main__":
    asyncio.run(main())
