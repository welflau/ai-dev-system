"""OpenSpec Verify 触发点 + playtest 超时降级 —— 回归测试

    cd backend && python _test_openspec_verify_trigger.py

覆盖三件事（对应 docs/20260918_01_OpenSpec四阶段闭环修复方案.md）：
  1. _maybe_openspec_verify 的幂等：verified/archived 不重跑
  2. play_test 成功分支确实调了 _maybe_openspec_verify（源码接线检查）
  3. playtest 超时返回 playtest_failed 而不是 error（否则 orchestrator 判 BLOCKED）
"""
import asyncio
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

_pass, _fail = 0, 0


def check(name, cond, detail=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"[OK] {name}" + (f" — {detail}" if detail else ""))
    else:
        _fail += 1
        print(f"[FAIL] {name}" + (f" — {detail}" if detail else ""))


# ==================== 1. 幂等 ====================
async def test_idempotent():
    from orchestrator import orchestrator as orch
    import database

    calls = []

    class _FakeDB:
        def __init__(self, stage):
            self.stage = stage

        async def fetch_one(self, *a, **kw):
            return {"openspec_stage": self.stage}

    # 打桩 TestAgent._run_openspec_verify，记录是否被调用
    from agents.test import TestAgent
    orig = TestAgent._run_openspec_verify

    async def _spy(self, ctx, *, block_on_fail=True):
        calls.append((ctx.get("ticket_id"), block_on_fail))
        return True

    TestAgent._run_openspec_verify = _spy
    orig_db = database.db
    import orchestrator as orch_mod

    try:
        for stage, should_call in (
            ("verified", False),      # 已 verified → 不重跑
            ("archived", False),      # 已归档 → 不重跑
            ("applied", True),        # 正常触发点
            ("proposed", True),       # dev 还没写 applied 也允许（CLI 自己会判）
            ("", True),              # 无 OpenSpec → 交给 _run_openspec_verify 静默跳过
        ):
            calls.clear()
            orch_mod.db = _FakeDB(stage)
            ok = await orch._maybe_openspec_verify("P1", "TK-1", stage_label="t")
            check(
                f"stage={stage or '(空)'} → {'触发' if should_call else '跳过'} Verify",
                bool(calls) == should_call,
                f"calls={len(calls)} ok={ok}",
            )
            if not should_call:
                check(f"stage={stage} 直接返回 True（视为已完成）", ok is True)
    finally:
        TestAgent._run_openspec_verify = orig
        orch_mod.db = orig_db


# ==================== 2. 源码接线 ====================
def test_wiring():
    src = (BACKEND / "orchestrator.py").read_text(encoding="utf-8")

    # play_test 成功分支必须调 _maybe_openspec_verify
    m = re.search(
        r'new_status = "play_test_passed"(.{0,3000}?)else:', src, re.S,
    )
    check(
        "play_test 成功分支已接 OpenSpec Verify",
        bool(m) and "_maybe_openspec_verify" in m.group(1),
    )

    check(
        "_maybe_openspec_verify 是 orchestrator 的方法",
        "async def _maybe_openspec_verify" in src,
    )

    t_src = (BACKEND / "agents" / "test.py").read_text(encoding="utf-8")
    # run_tests 那条路径也改走同一个收口函数，不再各写一份
    check(
        "run_tests 路径改走 _maybe_openspec_verify",
        "_maybe_openspec_verify" in t_src,
    )
    check(
        "run_tests 不再直接调 self._run_openspec_verify",
        "await self._run_openspec_verify(context)" not in t_src,
    )
    # _run_openspec_verify 本体要留着：软收尾路径 (orchestrator:_finalize_openspec_after_done) 还在用
    check(
        "_run_openspec_verify 实现仍保留（软收尾在用）",
        "async def _run_openspec_verify" in t_src,
    )


# ==================== 3. 超时降级 ====================
def test_timeout_downgrade():
    src = (BACKEND / "actions" / "ue_playtest.py").read_text(encoding="utf-8")

    m = re.search(r"if timed_out:(.{0,2500}?)\n        proc\.wait", src, re.S)
    check("找到超时分支", bool(m))
    if not m:
        return
    body = m.group(1)
    check(
        '超时返回 status="playtest_failed"（不是 error）',
        '"playtest_failed"' in body,
    )
    check("超时分支不再走 _err()（_err 写死 status=error）", "_err(" not in body)
    check('超时结果带 timed_out 标记', '"timed_out": True' in body)
    # 超时也要把已解析到的测试结果带出来，否则前端看不到「跑到哪挂的」
    check("超时保留已解析的 tests/summary", "_parse_automation_output(partial)" in body)

    # -TestExit：没有它，空队列必然空转到超时
    check(
        "命令里有 -TestExit（空队列自动退出）",
        "-TestExit=Automation Test Queue Empty" in src,
    )


async def main():
    await test_idempotent()
    test_wiring()
    test_timeout_downgrade()
    print(f"\n=== {_pass} passed / {_fail} failed ===")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
