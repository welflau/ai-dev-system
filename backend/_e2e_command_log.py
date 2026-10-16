"""端到端：真 SkillRunner → 真 QueryEngine → 真 GenericCLIAction → 真 subprocess
   cd backend && python _e2e_command_log.py

只 mock LLM（不然要花钱、要等）。其余全走生产代码路径：
SkillRunner.__init__ 的 hooks 兜底 → engine 的 POST_TOOL_USE → command_record_hook
→ ticket_command_log + ticket_logs。验的是「这条链在真实调用栈里确实通」，
而不是单测里一段段拼出来的等价物。
"""
import asyncio
import json
import sys

sys.path.insert(0, '.')

PASS = FAIL = 0


def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[OK] {name}" + (f" -- {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name}" + (f" -- {detail}" if detail else ""))


def _mock_llm(script):
    """script: [[{name, input}, ...], ...] —— 每轮要调的工具，最后一轮调 done。"""
    class _LLM:
        is_configured = True

        def __init__(self):
            self.round = 0

        async def _call_anthropic_tools_stream(self, messages, tools, system, **kw):
            calls = script[self.round] if self.round < len(script) else [{"name": "done", "input": {}}]
            self.round += 1
            for i, c in enumerate(calls):
                yield {"type": "tool_use_block", "id": f"tu_{self.round}_{i}",
                       "name": c["name"], "input": c["input"]}
            yield {"type": "stop", "stop_reason": "tool_use",
                   "usage": {"input_tokens": 4000, "output_tokens": 2000}}
    return _LLM()


async def main():
    from database import db
    await db.connect()
    await db.init_tables()

    # 生产里由 main.py:81 在启动时注册；这里是测试自己补上，
    # 否则 registry 是空的，engine emit 出去没人接。
    from hooks.builtin import register_builtin_hooks
    register_builtin_hooks()

    real = await db.fetch_one(
        "SELECT id, project_id FROM tickets ORDER BY created_at DESC LIMIT 1")
    if not real:
        print("[SKIP] 库里没有工单")
        return 0
    tid, pid = real["id"], real["project_id"]
    print(f"借用工单 {tid} / 项目 {pid}\n")
    await db.execute("DELETE FROM ticket_command_log WHERE ticket_id = ?", (tid,))

    from skills.executable_loader import CliToolSpec, ExecutableSkill
    from skills.runner import SkillRunner
    from pathlib import Path

    spec_ok = CliToolSpec(name="e2e_ok", description="成功命令",
                          command_template="git --version", timeout=30)
    spec_bad = CliToolSpec(name="e2e_bad", description="失败命令",
                           command_template="git rev-parse {ref}", timeout=30,
                           free_slots=["ref"])
    spec_slow = CliToolSpec(name="e2e_slow", description="超时命令",
                            command_template='python -c "import time; time.sleep(5)"',
                            timeout=1)
    skill = ExecutableSkill(
        skill_id="e2e", name="e2e", description="", body="测试用",
        source_path=Path("."), cli_tools=[spec_ok, spec_bad, spec_slow],
        budget={"max_rounds": 6, "max_seconds": 120},
    )

    runner = SkillRunner(skill, llm_client=_mock_llm([
        [{"name": "e2e_ok", "input": {}}],
        [{"name": "e2e_bad", "input": {"ref": "no-such-ref-zzz"}}],
        [{"name": "e2e_slow", "input": {}}],
        [{"name": "done", "input": {}}],
    ]))
    # 根因回归，但这次是在真实构造路径上：不传 hooks 也得有
    check("SkillRunner 未显式传 hooks 也接上了 registry", runner._hooks is not None)

    ctx = {
        "project_id": pid, "ticket_id": tid, "agent_type": "DevAgent",
        "repo_path": str(Path.cwd().parent),
    }
    result = await runner.execute(ctx)
    print(f"\nskill 执行完毕: status={result.status} rounds={result.rounds}\n")

    rows = await db.fetch_all(
        "SELECT tool, command, cwd, exit_code, status, duration_ms, noise, "
        "       output, output_bytes, truncated, log_id, agent_type, source "
        "FROM ticket_command_log WHERE ticket_id = ? ORDER BY created_at", (tid,))
    print("── ticket_command_log ──")
    for r in rows:
        print(f"  {r['tool']:<10} exit={str(r['exit_code']):<5} {r['status']:<8} "
              f"{str(r['duration_ms']):>6}ms  {r['command']}")
        print(f"             output={r['output'][:70]!r}")
    print()

    check("三条命令都落了库", len(rows) == 3, f"{len(rows)} 条")
    by = {r["tool"]: r for r in rows}

    ok = by.get("e2e_ok")
    check("成功命令记录存在", ok is not None)
    if ok:
        # 对照 ticket_commands 里的中文散文（「写入文件: src/a.js」），这里是真 argv
        check("记的是真 argv 不是散文", ok["command"] == "git --version", ok["command"])
        check("exit_code=0", ok["exit_code"] == 0)
        check("落了真实输出", "git version" in (ok["output"] or ""), repr(ok["output"]))
        check("cwd 落到了 repo_path", ok["cwd"].endswith("ai-dev-system"), ok["cwd"])
        check("duration_ms 是真耗时不是 0", (ok["duration_ms"] or 0) > 0, str(ok["duration_ms"]))
        check("source=cli_tool", ok["source"] == "cli_tool")
        check("agent_type 从 hook ctx 带下来了", ok["agent_type"] == "DevAgent", str(ok["agent_type"]))

    bad = by.get("e2e_bad")
    check("失败命令也落库", bad is not None)
    if bad:
        check("失败 status=error", bad["status"] == "error", bad["status"])
        check("失败 exit_code 非 0", (bad["exit_code"] or 0) != 0, str(bad["exit_code"]))
        # LLM 填的槽过了 shlex.quote，但渲染后的真串仍要可读可重放
        check("LLM 填的槽出现在命令里", "no-such-ref-zzz" in bad["command"], bad["command"])
        check("失败输出留下了 git 的报错", (bad["output"] or "").strip() != "")

    slow = by.get("e2e_slow")
    check("超时命令也落库（最值得记的一类）", slow is not None)
    if slow:
        check("超时 status=timeout", slow["status"] == "timeout", slow["status"])
        check("超时 exit_code=124", slow["exit_code"] == 124, str(slow["exit_code"]))

    # ── 时间轴配对 ────────────────────────────────────────────────────
    logs = await db.fetch_all(
        "SELECT id, action, level, detail FROM ticket_logs "
        "WHERE ticket_id = ? AND action = 'command_run' ORDER BY created_at", (tid,))
    check("时间轴多了三条 command_run", len(logs) == 3, f"{len(logs)} 条")
    check("失败/超时的日志是 error 级（会被自动提到 primary）",
          sum(1 for l in logs if l["level"] == "error") == 2,
          str([l["level"] for l in logs]))
    ids = {r["log_id"] for r in rows}
    check("每条记录都指向一条真日志", all(l["id"] in ids for l in logs))
    for l in logs:
        d = json.loads(l["detail"])
        rec = next((r for r in rows if r["log_id"] == l["id"]), None)
        check(f"detail.task_id 回指命令记录（{d.get('tool')}）",
              rec is not None and d.get("command") == rec["command"])

    orphan = await db.fetch_one(
        "SELECT COUNT(*) c FROM ticket_command_log c WHERE c.ticket_id = ? "
        "AND c.log_id != '' AND NOT EXISTS "
        "(SELECT 1 FROM ticket_logs l WHERE l.id = c.log_id)", (tid,))
    check("孤儿数为 0", orphan["c"] == 0, f"{orphan['c']} 条")

    # ── 读路由：前端点「📟 后台记录」走的就是这两条 ────────────────────
    import api.tickets as T
    tl = await T.get_ticket_timeline(tid)
    items = tl["timeline"]
    marked = [i for i in items if i.get("_task_ref")]
    check("时间轴给 command_run 标了 _task_ref", len(marked) >= 3, f"{len(marked)} 条")
    check("_task_ref 指向真记录 id", all(m["_task_ref"].startswith("TCMD-") for m in marked))

    lst = await T.get_ticket_command_logs(tid, include_noise=0)
    check("列表接口拿得到三条", lst["total"] == 3, str(lst["total"]))
    # 列表不带 output（省流量），详情才带
    one = await T.get_command_log(rows[0]["log_id"] and marked[0]["_task_ref"])
    check("详情接口带全量 output", "output" in one and one["id"].startswith("TCMD-"))

    # ── 清理：借的是真工单，只删本次自己造的 ──────────────────────────
    await db.execute("DELETE FROM ticket_command_log WHERE ticket_id = ?", (tid,))
    for l in logs:
        await db.execute("DELETE FROM ticket_logs WHERE id = ?", (l["id"],))
    print(f"\n已清理 {len(rows)} 条记录 + {len(logs)} 条日志")

    print(f"\n=== {PASS} 通过 / {FAIL} 失败 ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
