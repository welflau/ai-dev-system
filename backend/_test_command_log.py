"""工单命令记录（ticket_command_log）+ 后台链接：
    cd backend && python _test_command_log.py

压的是「工单执行期真实跑过的命令有没有留下可重放的记录」这条链，
以及一路上踩到的几个坑（每条都有对应注释说明为什么值得单独钉一颗钉子）。
"""
import asyncio
import inspect
import re
import subprocess
import sys
import time

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


async def main():
    # ═══ 1. 根因回归：SkillRunner 默认必须接上 hooks ═══════════════════
    # 这是整件事的起因 —— 全库每个 QueryEngine 都传了 hooks=hook_registry，
    # 唯独 SkillRunner 三个构造点（dev/architect/skill_agent）都只传 skill。
    # 于是唯一真正跑 shell 的路径（GenericCLIAction / ShellAction 只在这条路上）
    # 成了唯一没有审计的路径。默认值是唯一保障，钉死它。
    from skills.runner import SkillRunner

    class _FakeSkill:
        cli_tools = []
        outputs = {}
        availability = []
        output_root_template = ""

    r = SkillRunner(_FakeSkill())
    check("SkillRunner 默认接上 hooks", r._hooks is not None,
          f"_hooks={type(r._hooks).__name__}")
    from hooks.registry import hook_registry
    check("默认 hooks 就是全局 registry", r._hooks is hook_registry)
    check("显式传 hooks 仍然生效", SkillRunner(_FakeSkill(), hooks="X")._hooks == "X")

    # 三个构造点确实都不传 hooks —— 所以上面那条默认值不能删
    import pathlib
    nohook = 0
    for f in ("agents/dev.py", "agents/architect.py", "agents/skill_agent.py"):
        src = pathlib.Path(f).read_text(encoding="utf-8")
        for m in re.finditer(r"SkillRunner\(([^)]*)\)", src):
            if "hooks" not in m.group(1):
                nohook += 1
    check("三个构造点仍然不传 hooks（默认值是唯一保障）", nohook >= 3, f"{nohook} 处")

    # ═══ 2. 建表：必须在 SCHEMA_SQL 里，不能走 _auto_migrate ═══════════
    # _auto_migrate 是给**加列**用的。init_tables 先 executescript(SCHEMA_SQL)
    # 再迁移，而 executescript **一条语句失败会整段中止** —— 索引引用尚不存在
    # 的列，那条之后的表全都建不出来。所以表+索引必须一次给全。
    import sqlite3
    import database as D
    conn = sqlite3.connect(":memory:")
    conn.executescript(D.SCHEMA_SQL)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    check("ticket_command_log 在 SCHEMA_SQL 里", "ticket_command_log" in names)
    for idx in ("idx_tcl_ticket", "idx_tcl_log", "idx_tcl_project"):
        check(f"索引 {idx} 存在", idx in names)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ticket_command_log)")}
    for c in ("id", "ticket_id", "requirement_id", "log_id", "source", "tool",
              "command", "cwd", "exit_code", "status", "duration_ms",
              "output", "output_bytes", "truncated", "noise", "created_at"):
        check(f"列 {c} 存在", c in cols)
    mig_src = inspect.getsource(D.Database._auto_migrate)
    check("没把新表的列塞进 _auto_migrate", "ticket_command_log" not in mig_src)
    conn.close()

    # ═══ 3. ContextVar 交接：offer / take ═════════════════════════════
    import command_log as CL
    CL.offer_command_record(source="shell", tool="t", command="ls", exit_code=0)
    got = CL.take_command_record()
    check("offer 后 take 拿得到", got and got.get("command") == "ls")
    # 取走即清：实测调用方 Context 同样看得见这个值，不清的话上一条命令
    # 会漏给下一个工具，把两次执行串成一条假记录。
    check("再 take 返回 None（一次性，防串台）", CL.take_command_record() is None)

    # ═══ 4. ANSI 剥离 + 截断 ══════════════════════════════════════════
    txt, n, tr = CL._truncate_output("\x1b[31merror\x1b[0m")
    check("ANSI 在写入侧剥掉", txt == "error", repr(txt))
    check("短输出不截断", tr is False and n == 5)
    big = "HEAD_SENTINEL" + "x" * 200000 + "TAIL_SENTINEL"
    txt, n, tr = CL._truncate_output(big)
    check("超限截断", tr is True)
    check("原始大小按未截断算", n == len(big.encode()), f"{n}")
    # 头尾都留是刻意的：头部有「跑的什么、环境如何」，尾部有「错在哪」
    check("截断后头部哨兵仍在", txt.startswith("HEAD_SENTINEL"))
    check("截断后尾部哨兵仍在", txt.endswith("TAIL_SENTINEL"))

    # ═══ 5. checkpoint 嵌套上下文：push/pop 不能清掉外层 ═══════════════
    # 原来 set_* 是 merge、clear_* 是无条件 set(None)，不对称。
    # orchestrator 设工单级 → agents/base 嵌套再设 → finally 一 clear，
    # 把工单级的一起清了，后续 git 操作全成了没有 ticket_id 的孤儿
    # （实库 ToolError:git:commit_failed 2921 行 ticket_id 全空）。
    from checkpoint import (set_checkpoint_context, clear_checkpoint_context,
                            push_checkpoint_context, pop_checkpoint_context,
                            get_checkpoint_context)
    clear_checkpoint_context()
    set_checkpoint_context(project_id="P1", ticket_id="TK-OUTER")
    tok = push_checkpoint_context(agent_type="DevAgent", action="develop")
    inner = get_checkpoint_context()
    check("嵌套后内层能看到自己的字段", inner.get("agent_type") == "DevAgent")
    check("嵌套后外层 ticket_id 仍在", inner.get("ticket_id") == "TK-OUTER")
    pop_checkpoint_context(tok)
    outer = get_checkpoint_context()
    check("pop 后外层 ticket_id 没被清掉（钉死修的 bug）",
          outer.get("ticket_id") == "TK-OUTER", str(outer))
    check("pop 后内层字段已还原", "agent_type" not in outer)
    check("pop(None) 是 no-op", pop_checkpoint_context(None) is None)
    check("set 支持 requirement_id", (
        set_checkpoint_context(requirement_id="REQ-1") or
        get_checkpoint_context().get("requirement_id") == "REQ-1"))

    # 两个嵌套点都改成了 push/pop
    for f, fn in (("agents/base.py", "_react_with_think"),
                  ("agents/chat_assistant.py", "chat_stream")):
        src = pathlib.Path(f).read_text(encoding="utf-8")
        check(f"{f} 用 pop 而不是 clear", "pop_checkpoint_context" in src)
    orch = pathlib.Path("orchestrator.py").read_text(encoding="utf-8")
    check("orchestrator 注入 requirement_id", "requirement_id=ticket.get" in orch)

    # ═══ 6. git 噪音分类（表驱动）══════════════════════════════════════
    import git_manager as G
    noise_cases = [
        (["git", "status", "--porcelain"], True),
        (["git", "rev-parse", "HEAD"], True),
        (["git", "remote", "-v"], True),
        (["git", "branch", "--list"], True),
        (["git", "log", "-1"], True),
        (["git", "remote", "add", "origin", "u"], False),
        (["git", "branch", "feat/x"], False),
        (["git", "checkout", "-b", "feat/x"], False),
        (["git", "commit", "-m", "x"], False),
        (["git", "push", "origin", "main"], False),
        (["git", "add", "."], False),
        (["git", "merge", "develop"], False),
    ]
    for cmd, exp in noise_cases:
        check(f"noise({' '.join(cmd[1:3])}) == {exp}", G._is_noise_git(cmd) is exp)

    # ═══ 7. git 超时：124 + 保留部分输出 + 不阻塞事件循环 ═══════════════
    check("本地/网络两档超时", G._GIT_TIMEOUT == 120 and G._GIT_TIMEOUT_NETWORK == 600)
    check("push/clone 走长档", {"push", "clone", "fetch"} <= G._GIT_NETWORK_VERBS)

    from database import db
    await db.connect()
    # 建表：新表在 SCHEMA_SQL 里，跑真实库时得先让 init_tables 把它建出来
    # （生产路径由 main.py 启动时调用，这里是测试自己补上）
    await db.init_tables()

    orig_run = subprocess.run
    try:
        def fake_timeout(*a, **kw):
            # TimeoutExpired.output / .stderr 在 text=True 下是 str（非 bytes），
            # 而且含超时前已经收到的部分输出 —— 超时现场唯一的线索，不能丢
            raise subprocess.TimeoutExpired(a[0] if a else "git", 1,
                                            output="partial-out\n", stderr="partial-err")
        subprocess.run = fake_timeout
        rc, out, err = await G.git_manager._run_git(".", "status")
        check("超时返回 124（GNU timeout 约定，和普通失败区分）", rc == 124, f"rc={rc}")
        check("超时保留了部分 stdout", "partial-out" in out, repr(out))
        check("超时 stderr 说明是超时", "超时" in err, repr(err))
        check("超时也带上部分 stderr", "partial-err" in err)
    finally:
        subprocess.run = orig_run

    # 不阻塞事件循环：run_in_executor 生效的话，git 跑的同时计数器要能推进。
    # 不换线程的话 subprocess.run(timeout=) 是在调用线程里 wait 的，
    # 事件循环照样被钉死整个超时时长，加超时的意义就打了折。
    ticks = 0

    async def ticker():
        nonlocal ticks
        for _ in range(40):
            await asyncio.sleep(0.01)
            ticks += 1

    orig_run2 = subprocess.run

    def slow_run(*a, **kw):
        time.sleep(0.25)
        class R:
            returncode, stdout, stderr = 0, "", ""
        return R()
    subprocess.run = slow_run
    try:
        t = asyncio.create_task(ticker())
        await G.git_manager._run_git(".", "status")
        await asyncio.sleep(0)
        check("_run_git 期间事件循环仍在转（run_in_executor 生效）", ticks > 5, f"ticks={ticks}")
        t.cancel()
    finally:
        subprocess.run = orig_run2

    # 契约回归：124 之所以安全，是因为没有调用点判具体码值
    gsrc = inspect.getsource(G)
    bad = [m for m in re.findall(r"rc\s*==\s*(\d+)", gsrc) if m != "0"]
    check("没有调用点判具体的非零 rc（124 才安全）", not bad, str(bad))

    # ═══ 8. record_command 落库 ═══════════════════════════════════════
    # ticket_logs 有外键（project_id NOT NULL REFERENCES projects(id)，
    # ticket_id REFERENCES tickets(id)），所以得借一张**真**工单，
    # 不然 hook 里那条时间轴插不进去。
    real = await db.fetch_one(
        "SELECT id, project_id FROM tickets ORDER BY created_at DESC LIMIT 1")
    if not real:
        print("[SKIP] 库里没有工单，跳过落库相关断言")
        print(f"\n=== {PASS} 通过 / {FAIL} 失败 ===")
        return 1 if FAIL else 0
    tid, pid = real["id"], real["project_id"]
    await db.execute("DELETE FROM ticket_command_log WHERE ticket_id = ?", (tid,))
    rid = await CL.record_command(
        source="cli_tool", tool="openspec_validate",
        command="openspec validate --strict", cwd="/repo",
        exit_code=0, status="success", duration_ms=1234,
        output="\x1b[32mok\x1b[0m", ticket_id=tid, project_id=pid,
    )
    row = await db.fetch_one("SELECT * FROM ticket_command_log WHERE id = ?", (rid,))
    check("record_command 落库", row is not None)
    check("记录的是真 argv", row["command"] == "openspec validate --strict")
    check("落库时已剥 ANSI", row["output"] == "ok", repr(row["output"]))
    check("id 前缀 TCMD", rid.startswith("TCMD-"), rid)

    # ═══ 9. hook 双向配对 ═════════════════════════════════════════════
    from hooks.builtin import command_record_hook
    from hooks.types import HookEvent, ToolHookContext
    import json

    CL.offer_command_record(source="cli_tool", tool="openspec_apply",
                            command="openspec apply x", cwd="/repo",
                            exit_code=0, status="success", duration_ms=88,
                            output="applied")
    await command_record_hook(ToolHookContext(
        event=HookEvent.POST_TOOL_USE, tool_name="openspec_apply",
        ticket_id=tid, project_id=pid, agent_type="DevAgent",
    ))
    rec = await db.fetch_one(
        "SELECT * FROM ticket_command_log WHERE ticket_id = ? AND tool = ?",
        (tid, "openspec_apply"))
    check("hook 写了命令记录", rec is not None)
    log = await db.fetch_one("SELECT * FROM ticket_logs WHERE id = ?", (rec["log_id"],)) if rec else None
    check("hook 同时写了一条时间轴日志", log is not None)
    check("时间轴 action 是 command_run", log and log["action"] == "command_run")
    # 两条记录在同一个 hook 里同时创建，天然对齐 —— 不必像 _annotate_chat_anchors
    # 那样按 ≤3s 时间差猜配对
    if log:
        d = json.loads(log["detail"])
        check("detail.task_id 指回命令记录（双向配对）", d.get("task_id") == rec["id"])
        check("detail 带真命令", d.get("command") == "openspec apply x")
    check("hook 取走后 ContextVar 已清", CL.take_command_record() is None)

    # 没有 offer 的工具不留骨架行（tool_audit_log 已经在记调用次数了）
    before = (await db.fetch_one(
        "SELECT COUNT(*) c FROM ticket_command_log WHERE ticket_id = ?", (tid,)))["c"]
    await command_record_hook(ToolHookContext(
        event=HookEvent.POST_TOOL_USE, tool_name="read_file", ticket_id=tid))
    after = (await db.fetch_one(
        "SELECT COUNT(*) c FROM ticket_command_log WHERE ticket_id = ?", (tid,)))["c"]
    check("没 offer 的工具不落记录", before == after)

    # ═══ 10. 时间轴标注 + 分层 ════════════════════════════════════════
    import api.tickets as T
    items = [{"_type": "log", "id": rec["log_id"], "action": "command_run"},
             {"_type": "log", "id": "no-such-log", "action": "complete"}]
    items = await T._annotate_task_refs(tid, items)
    check("有记录的 log 标了 _task_ref", items[0].get("_task_ref") == rec["id"])
    check("没记录的 log 不标（不留死链）", "_task_ref" not in items[1])

    check("command_run 在 _SECONDARY_ACTIONS", "command_run" in T._SECONDARY_ACTIONS)
    check("info 级 command_run → secondary",
          T._classify_tier({"_type": "log", "action": "command_run", "level": "info"}) == "secondary")
    check("error 级 command_run 自动提到 primary",
          T._classify_tier({"_type": "log", "action": "command_run", "level": "error"}) == "primary")
    # 进 Feed 会被标 _chat_anchor，多出一个「↗ 对话」死链
    from api.chat import FEED_LOG_ACTIONS
    check("command_run 不进 FEED_LOG_ACTIONS", "command_run" not in FEED_LOG_ACTIONS)

    # ═══ 11. 读路由 ═══════════════════════════════════════════════════
    await CL.record_command(source="git", tool="git:status", command="git status",
                            exit_code=0, status="success", noise=True, ticket_id=tid)
    d1 = await T.get_ticket_command_logs(tid, include_noise=0)
    d2 = await T.get_ticket_command_logs(tid, include_noise=1)
    check("默认过滤 noise", all(r["noise"] == 0 for r in d1["records"]))
    check("include_noise=1 能看到噪音", d2["total"] > d1["total"], f"{d2['total']} vs {d1['total']}")
    single = await T.get_command_log(rec["id"])
    check("单条接口返回全量", single["id"] == rec["id"] and "output" in single)

    # 孤儿检查：log_id 指向不存在的 ticket_logs
    orphan = await db.fetch_one(
        "SELECT COUNT(*) c FROM ticket_command_log c "
        "WHERE c.ticket_id = ? AND c.log_id != '' "
        "AND NOT EXISTS (SELECT 1 FROM ticket_logs l WHERE l.id = c.log_id)", (tid,))
    check("没有孤儿记录", orphan["c"] == 0, f"{orphan['c']} 条")

    # 清理：借的是真工单，只删本次自己造的两条，别碰人家原有的日志
    await db.execute("DELETE FROM ticket_command_log WHERE ticket_id = ?", (tid,))
    if rec and rec.get("log_id"):
        await db.execute("DELETE FROM ticket_logs WHERE id = ?", (rec["log_id"],))
    # §7 的 _run_git mock 是在 TK-OUTER 这个假上下文下跑的，_record_git_command
    # 照样落了库（正是我们要的行为）—— 但那是假工单，跑完得扫干净，
    # 否则每跑一遍测试就往真库里多塞几行 TK-OUTER。
    await db.execute("DELETE FROM ticket_command_log WHERE ticket_id = 'TK-OUTER'")
    clear_checkpoint_context()

    print(f"\n=== {PASS} 通过 / {FAIL} 失败 ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
