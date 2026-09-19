"""generate_ue_tests 的 orchestrator 接线回归 —— 防死循环 + 防污染 dev_result

    cd backend && python _test_ue_test_gen_wiring.py

为什么要有这个文件：ue_test_gen 的 Action 本体单测全绿（28 项）、真机也跑通了，
但第一次挂到真工单上跑，**空转了 114 轮**。原因不在 Action 里，在 orchestrator：

  _handle_agent_result 的 DevAgent 分支是按 action 逐个写死的。generate_ue_tests
  没有自己的分支 → 掉进「常规 develop」的收尾：
    ① status 被写回 development_done，而 development_done 的 trigger 正是
       generate_ue_tests 自己 → 派单→成功→写回原状态→再派单，每秒一轮；
    ② 结果被存成 type='code' 的 artifact，_build_context 取**最后一条** code
       artifact 当 dev_result → dev_result 被覆盖成没有 files 的东西，
       于是第 2 轮起报「本次改动里没有可测的 UE 头文件」——
       症状指向选目标逻辑，根因却在 orchestrator，极难查。

所以这里测的是**行为**（真调 _handle_agent_result），不是 grep 源码：
grep 只能证明代码长什么样，证明不了状态真的推进了。

用真 DB，建一张带 _WIRETEST_ 前缀的临时工单，finally 里删干净。
"""
import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

PROJECT_ID = "PRJ-20260624-28f539"   # TestFPS，traits 含 engine:ue5
TICKET_ID = "TK-_WIRETEST_-uetg"

_pass, _fail = 0, 0
_lines = []


def check(name, cond, detail=""):
    global _pass, _fail
    if cond:
        _pass += 1
        _lines.append(f"[OK] {name}" + (f" -- {detail}" if detail else ""))
    else:
        _fail += 1
        _lines.append(f"[FAIL] {name}" + (f" -- {detail}" if detail else ""))


def _ok_result(generated=("Source/TestFPS/Tests/FooTest.cpp",), warnings=()):
    return {
        "status": "success",
        "ue_test_gen": {
            "generated": list(generated),
            "warnings": list(warnings),
            "details": [],
            "summary": f"生成 {len(generated)} 个 Automation 测试",
        },
        "message": "ok",
    }


async def _seed(db, req_id, status="development_done"):
    from utils import now_iso
    # 先删子表再删工单：ticket_logs / artifacts 有外键指过来，
    # 顺序反了会 FOREIGN KEY constraint failed（第 2 次 _seed 必中，因为
    # 上一轮 _handle_agent_result 已经写过一条 ticket_log）。
    await db.execute("DELETE FROM ticket_logs WHERE ticket_id = ?", (TICKET_ID,))
    await db.execute("DELETE FROM artifacts WHERE ticket_id = ?", (TICKET_ID,))
    await db.execute("DELETE FROM tickets WHERE id = ?", (TICKET_ID,))
    await db.insert("tickets", {
        "id": TICKET_ID,
        "requirement_id": req_id,
        "project_id": PROJECT_ID,
        "title": "[接线测试] ue_test_gen",
        "description": "",
        "type": "feature",
        "module": "other",
        "priority": 3,
        "status": status,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    return await db.fetch_one("SELECT * FROM tickets WHERE id = ?", (TICKET_ID,))


async def main():
    from database import db
    from orchestrator import orchestrator
    await db.connect()

    req = await db.fetch_one(
        "SELECT id FROM requirements WHERE project_id = ? LIMIT 1", (PROJECT_ID,)
    )
    if not req:
        _lines.append("[SKIP] TestFPS 项目下没有 requirement，跳过全部用例")
        await db.disconnect()
        return 0
    req_id = req["id"]

    try:
        # ---- ① 成功 → 必须推进到 ue_test_gen_passed（不能停在 development_done）----
        t = await _seed(db, req_id)
        await orchestrator._handle_agent_result(
            PROJECT_ID, TICKET_ID, dict(t), "DevAgent", "generate_ue_tests", _ok_result(),
        )
        row = await db.fetch_one("SELECT status FROM tickets WHERE id = ?", (TICKET_ID,))
        got = row["status"]
        check("成功后状态推进到 ue_test_gen_passed", got == "ue_test_gen_passed", got)
        check("成功后**没有**停在 development_done（死循环的直接症状）",
              got != "development_done", got)

        # ---- ② 新状态不得再次触发 generate_ue_tests（通用防自环）----
        rules = await orchestrator._rules_for_project(PROJECT_ID, "feature") \
            if hasattr(orchestrator, "_rules_for_project") else None
        if rules is None:
            from sop.loader import compose_sop, sop_to_transition_rules
            traits = ["platform:desktop", "category:game", "engine:ue5", "lang:cpp", "vcs:git"]
            rules = sop_to_transition_rules(compose_sop(traits, "feature"))
        nxt = (rules.get(got) or {}).get("action")
        check("新状态不会再派回 generate_ue_tests（自环即死循环）",
              nxt != "generate_ue_tests", f"{got} -> {nxt}")
        check("新状态接的是 run_engine_compile", nxt == "run_engine_compile", str(nxt))

        # ---- ③ 不得写 type='code' 的 artifact（会把 dev_result 覆盖掉）----
        arts = await db.fetch_all(
            "SELECT type FROM artifacts WHERE ticket_id = ?", (TICKET_ID,)
        )
        code_arts = [a for a in arts if a["type"] == "code"]
        check("不写 code artifact（否则覆盖 develop 的 dev_result）",
              len(code_arts) == 0, f"{len(code_arts)} 条")

        # ---- ④ warnings 不阻塞：照样 passed ----
        t = await _seed(db, req_id)
        await orchestrator._handle_agent_result(
            PROJECT_ID, TICKET_ID, dict(t), "DevAgent", "generate_ue_tests",
            _ok_result(generated=(), warnings=("编译未通过，已回滚",)),
        )
        row = await db.fetch_one("SELECT status FROM tickets WHERE id = ?", (TICKET_ID,))
        check("带 warnings 仍然 passed（生成是增强不是门禁）",
              row["status"] == "ue_test_gen_passed", row["status"])

        # ---- ⑤ 防御：非 success 走 SOP 声明的返工路径，不静默放行 ----
        t = await _seed(db, req_id)
        await orchestrator._handle_agent_result(
            PROJECT_ID, TICKET_ID, dict(t), "DevAgent", "generate_ue_tests",
            {"status": "ue_test_gen_failed", "ue_test_gen": {"summary": "x", "warnings": ["x"]}},
        )
        row = await db.fetch_one("SELECT status FROM tickets WHERE id = ?", (TICKET_ID,))
        check("非 success → ue_test_gen_failed（不静默当成功）",
              row["status"] == "ue_test_gen_failed", row["status"])

        # ---- ⑥ 全 SOP 自环扫描：阶段的 success_status 不得再派回它自己 ----
        # 这次的死循环本质就是「跑完 X 后的状态又触发 X」。orchestrator 侧写错状态
        # 这里测不到（那由 ①② 覆盖），但 SOP 本身配错也能造出同样的环，值得守住。
        #
        # 终态要排除：service SOP 里 deploy 的 success_status 就是 deployed，
        # 规则表上确实是个自环，但 process_ticket 开头的 _HARD_TERMINAL 门闩会先
        # return，环根本起不来。自环只在**非终态**上才致命 —— 不排除的话这条检查
        # 会对一个正常收尾的流水线长期报红，然后被人忽略掉，那就白设了。
        from sop.loader import compose_sop, sop_to_transition_rules
        terminal = orchestrator._HARD_TERMINAL
        for traits, label in (
            (["platform:desktop", "category:game", "engine:ue5", "lang:cpp", "vcs:git"], "UE"),
            (["platform:web", "category:service", "lang:python", "vcs:git"], "service"),
        ):
            cfg = compose_sop(traits, "feature")
            r = sop_to_transition_rules(cfg)
            loops = []
            for stage in cfg.get("stages") or []:
                act = stage.get("action")
                succ = stage.get("success_status")
                if not act or not succ or succ in terminal:
                    continue
                if (r.get(succ) or {}).get("action") == act:
                    loops.append(f"{act}: success_status={succ} 又触发自己")
            check(f"{label} SOP 无非终态 success_status 自环", not loops, str(loops))

    finally:
        await db.execute("DELETE FROM artifacts WHERE ticket_id = ?", (TICKET_ID,))
        await db.execute("DELETE FROM ticket_logs WHERE ticket_id = ?", (TICKET_ID,))
        await db.execute("DELETE FROM tickets WHERE id = ?", (TICKET_ID,))
        await db.disconnect()   # 不断开 aiosqlite 后台线程会吊住进程

    return 1 if _fail else 0


if __name__ == "__main__":
    rc = asyncio.run(main())
    _lines.append(f"\n=== {_pass} passed / {_fail} failed ===")
    (BACKEND / "_uetg_wiring_out.txt").write_text("\n".join(_lines), encoding="utf-8")
    print(f"pass={_pass} fail={_fail}")
    sys.exit(rc)
