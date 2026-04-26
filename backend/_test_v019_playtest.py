"""
v0.19 Phase ② UE Playtest —— parser + wiring smoke test

不真跑 UE（headless UE 启动要 30s+，着色编译要 3-5 min，不适合 smoke）。
只验证：
  1. _parse_automation_output 能从合成日志里抽出 tests / summary
  2. SOP loader 能把 play_test fragment 挂上去，派生出 play_test_failed → TestAgent.fix_issues？
     实际上 fragment 的 reject_goto=development → SOP loader 派生 DevAgent.fix_issues
  3. Agents 的 TestAgent.execute("run_playtest") 分派可触达（不跑 Action，只走 dispatch 路径）
  4. DevAgent._do_fix_issues 能识别 play_test_failed 状态并拉 failed_tests

用法：
    cd backend && python _test_v019_playtest.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")


def _banner(msg: str):
    print()
    print("=" * 70)
    print(f"  {msg}")
    print("=" * 70)


SAMPLE_OUTPUT_SUCCESS = """
LogInit: Running engine for game: TestFPS
LogAutomationController: Display: BeginEvents: Project.Functional.Smoke
LogAutomationController: Display: Test Completed. Result={Passed}  Name={Project.Functional.Smoke}
LogAutomationController: Display: BeginEvents: Project.Functional.MainMenuLoad
LogAutomationController: Display: Test Completed. Result={Passed}  Name={Project.Functional.MainMenuLoad}
LogAutomationController: Display: Results for test Group: Project
LogAutomationController: Display:  * 2 tests ran
LogAutomationController: Display:  * 2 passed
LogAutomationController: Display:  * 0 failed
LogExit: Exiting.
"""

SAMPLE_OUTPUT_FAILURE = """
LogAutomationController: Display: BeginEvents: Project.Functional.PlayerSpawn
LogAutomationController: Error: Screenshot comparison failed: pixel diff > threshold
LogAutomationController: Display: Test Completed. Result={Failed}  Name={Project.Functional.PlayerSpawn}
LogAutomationController: Display: BeginEvents: Project.Functional.Smoke
LogAutomationController: Display: Test Completed. Result={Passed}  Name={Project.Functional.Smoke}
LogAutomationController: Display:  * 2 tests ran
LogAutomationController: Display:  * 1 passed
LogAutomationController: Display:  * 1 failed
"""


async def main():
    passed, failed = 0, 0

    def check(name: str, ok: bool, detail: str = ""):
        nonlocal passed, failed
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {name}" + (f"  -- {detail}" if detail else ""))
        if ok:
            passed += 1
        else:
            failed += 1

    # =========== 1. 解析器成功 case ===========
    _banner("1. _parse_automation_output 解析 success 日志")
    from actions.ue_playtest import _parse_automation_output
    p1 = _parse_automation_output(SAMPLE_OUTPUT_SUCCESS)
    check("tests 数量=2", len(p1["tests"]) == 2, f"count={len(p1['tests'])}")
    check("summary.total=2", p1["summary"]["total"] == 2,
          f"total={p1['summary']['total']}")
    check("summary.passed=2", p1["summary"]["passed"] == 2)
    check("summary.failed=0", p1["summary"]["failed"] == 0)
    check("test 0 是 Smoke", p1["tests"][0]["name"].endswith("Smoke"))
    check("test 0 passed", p1["tests"][0]["result"] == "passed")

    # =========== 2. 解析器 failure case ===========
    _banner("2. _parse_automation_output 解析 failure 日志")
    p2 = _parse_automation_output(SAMPLE_OUTPUT_FAILURE)
    check("tests 数量=2", len(p2["tests"]) == 2, f"count={len(p2['tests'])}")
    check("summary.failed=1", p2["summary"]["failed"] == 1)
    check("summary.passed=1", p2["summary"]["passed"] == 1)
    failed_one = [t for t in p2["tests"] if t["result"] == "failed"]
    check("有 1 个 failed", len(failed_one) == 1)
    if failed_one:
        check("failed test 有 error",
              len(failed_one[0]["errors"]) >= 1,
              f"errors={failed_one[0]['errors']}")
        check("failed test name=PlayerSpawn",
              "PlayerSpawn" in failed_one[0]["name"])

    # =========== 3. SOP fragment 派生：play_test_failed → DevAgent.fix_issues ===========
    _banner("3. SOP loader 对 UE 项目派生 play_test_failed → fix_issues")
    from sop.loader import compose_sop, sop_to_transition_rules
    cfg = compose_sop(
        traits=["engine:ue5", "category:game", "genre:fps", "vcs:git"],
        ticket_type="feature",
    )
    rules = sop_to_transition_rules(cfg)
    rule = rules.get("play_test_failed")
    check("play_test_failed 规则存在", rule is not None, f"rule={rule}")
    if rule:
        check("reject → DevAgent", rule.get("agent") == "DevAgent")
        check("reject action = fix_issues", rule.get("action") == "fix_issues")

    rule_success = rules.get("play_test_passed")
    check("play_test_passed 规则存在", rule_success is not None,
          f"rule={rule_success}")

    # =========== 4. TestAgent dispatch ===========
    _banner("4. TestAgent.execute('run_playtest') 分派存在（不真跑）")
    from agents.test import TestAgent
    agent = TestAgent()
    check("TestAgent 有 run_playtest 方法",
          hasattr(agent, "run_playtest") and callable(agent.run_playtest))

    # 非法 task 应返回 error 而非 抛出
    bad = await agent.execute("nonexistent_task", {})
    check("未知 task 返回 error",
          bad.get("status") == "error", f"got={bad}")

    # =========== 5. Reflection prompt 含 playtest 支路 ===========
    _banner("5. Reflection prompt 含 play_test_failed 分支")
    # 直接检查 reflection.py 里有 play_test_failed 串，快路径
    refl_src = Path("actions/reflection.py").read_text(encoding="utf-8")
    check("reflection.py 含 'play_test_failed' 分支",
          "play_test_failed" in refl_src)
    check("reflection.py 含 UE Automation 常见坑提示",
          "UE Automation 常见失败原因" in refl_src)

    # =========== 6. DevAgent fix_issues 支持 play_test_failed ===========
    _banner("6. DevAgent._do_fix_issues 识别 play_test_failed")
    dev_src = Path("agents/dev.py").read_text(encoding="utf-8")
    check("dev.py 含 play_test_failed 分支", '"play_test_failed"' in dev_src)
    check("dev.py 拉 failed_tests 到 context", 'failed_tests' in dev_src)

    _banner("Summary")
    total = passed + failed
    print(f"  PASS {passed}/{total}  FAIL {failed}/{total}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
