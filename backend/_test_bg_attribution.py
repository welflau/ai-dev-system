"""后台轮询发出的 git 命令，记录里能不能归到项目头上：
    cd backend && python _test_bg_attribution.py

背景：`ticket_command_log` 头 60 行里有 54 行 `ticket_id=''` **且** `project_id=''`。
查下来不是 DevAgent 漏了上下文，而是两个**项目级后台轮询**压根没设过上下文：

  - `ci_pipeline._scheduler_tick`（每 60s）→ `_get_branch_head`
    → `_run_git(rev-parse develop/main)`，实测 42 行全是它
  - `image_processor._replace_placeholder` → `git_manager.read_file`
    → `_run_git(show HEAD:path)`

**ticket_id 留空在这两处是对的** —— 它们确实没有工单，硬塞一个是伪造归属。
错的是 `project_id` 也空着：项目明明知道，不设就连「哪个项目在刷 git」都答不了。
所以这个测试钉两件事：project_id 必须有，ticket_id 必须仍然没有。
"""
import asyncio
import inspect
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


async def main():
    from checkpoint import (get_checkpoint_context, clear_checkpoint_context,
                            set_checkpoint_context, push_checkpoint_context,
                            pop_checkpoint_context)

    # ═══ 1. 两个轮询点确实接上了 push/pop ═════════════════════════════
    import ci_pipeline as C
    import image_processor as I

    s1 = inspect.getsource(C.CIPipelineRunner._scheduler_tick)
    check("CI 调度器 push 了上下文", "push_checkpoint_context" in s1)
    check("CI 调度器在 finally 里 pop", "finally" in s1 and "pop_checkpoint_context" in s1)
    # 用 push/pop 而不是 set/clear：clear 是无条件 set(None)，
    # 会把外层（orchestrator 工单级）的上下文一起清掉
    check("CI 调度器不用 clear（会清掉外层工单上下文）",
          "clear_checkpoint_context" not in s1)
    check("CI 调度器**不**编造 ticket_id", "ticket_id" not in s1.split("push_checkpoint_context")[1][:200])

    s2 = inspect.getsource(I._replace_placeholder)
    check("图片处理器 push 了上下文", "push_checkpoint_context" in s2)
    check("图片处理器在 finally 里 pop", "finally" in s2)

    # ═══ 2. for 循环里多项目不串台 ════════════════════════════════════
    # _scheduler_tick 是 `for project in projects` —— 每轮都得独立 push/pop，
    # 不然 B 项目的 git 命令会记到 A 项目头上
    clear_checkpoint_context()
    seen = []
    for pid in ("PRJ-A", "PRJ-B", "PRJ-C"):
        tok = push_checkpoint_context(project_id=pid, agent_type="CI",
                                      action="ci_scheduler_tick")
        try:
            ck = get_checkpoint_context()
            seen.append(ck.get("project_id"))
            check(f"tick({pid}) 看到的是自己的 project_id",
                  ck.get("project_id") == pid, str(ck.get("project_id")))
            check(f"tick({pid}) 没有 ticket_id（没工单就是没工单）",
                  not ck.get("ticket_id"))
            check(f"tick({pid}) agent_type 标成 CI（和 Orchestrator 区分）",
                  ck.get("agent_type") == "CI")
        finally:
            pop_checkpoint_context(tok)
    check("三轮之间没串台", seen == ["PRJ-A", "PRJ-B", "PRJ-C"], str(seen))
    check("循环结束后上下文干净", not get_checkpoint_context(),
          str(get_checkpoint_context()))

    # ═══ 3. 最关键：CI 的 push 不能污染工单级上下文 ═════════════════════
    # CI 调度器和 orchestrator 跑在同一个进程里。要是这里用了 set/clear，
    # 一次 CI tick 就能把正在处理的工单的 ticket_id 抹掉 ——
    # 那正是这轮改动之前 agents/base.py 犯过的错（见 dev-notes/2026-09-20_03 改动 5）。
    clear_checkpoint_context()
    set_checkpoint_context(project_id="PRJ-X", ticket_id="TK-REAL",
                           agent_type="Orchestrator")
    tok = push_checkpoint_context(project_id="PRJ-CI", agent_type="CI")
    inner = get_checkpoint_context()
    check("CI 嵌套期间看到的是 CI 自己的 project_id",
          inner.get("project_id") == "PRJ-CI")
    pop_checkpoint_context(tok)
    outer = get_checkpoint_context()
    check("pop 后工单 ticket_id 幸存（钉死不许用 clear）",
          outer.get("ticket_id") == "TK-REAL", str(outer))
    check("pop 后工单 project_id 幸存", outer.get("project_id") == "PRJ-X")
    check("pop 后 agent_type 还原成 Orchestrator",
          outer.get("agent_type") == "Orchestrator", str(outer.get("agent_type")))
    clear_checkpoint_context()

    # ═══ 4. 端到端：_run_git 真的把 project_id 记进去了 ═════════════════
    # 走的是产生那 42 行孤儿的同一条路：_get_branch_head → _run_git → _record_git_command
    from database import db
    await db.connect()
    await db.init_tables()

    proj = await db.fetch_one(
        "SELECT id, git_repo_path FROM projects WHERE status = 'active' "
        "AND (mode IS NULL OR mode != 'manual') AND git_repo_path IS NOT NULL "
        "ORDER BY created_at DESC LIMIT 1")
    if not proj:
        print("[SKIP] 库里没有带 git_repo_path 的 active 项目，跳过端到端断言")
        print(f"\n=== {PASS} 通过 / {FAIL} 失败 ===")
        return 1 if FAIL else 0
    pid = proj["id"]

    import git_manager as G
    # `_custom_paths` 是**进程内缓存**，全新进程里是空的 —— 生产里由
    # `api/projects._ensure_repo_path` 在请求路径上恢复（注释写明「防止重启后丢失」）。
    # 不补这一步，`_repo_path` 会回落到 PROJECTS_DIR/<id>，而真仓库在
    # F:\Projects\... 这类外部路径上，于是 repo_exists 为假、端到端段整段跳过。
    if proj["git_repo_path"]:
        G.git_manager.set_project_path(pid, proj["git_repo_path"])
    if not G.git_manager.repo_exists(pid):
        print(f"[SKIP] 项目 {pid} 仓库不存在（{proj['git_repo_path']}），跳过端到端断言")
        print(f"\n=== {PASS} 通过 / {FAIL} 失败 ===")
        return 1 if FAIL else 0

    marker = "__attr_probe__"          # 故意用不存在的 ref，只为触发一次 _run_git
    clear_checkpoint_context()
    tok = push_checkpoint_context(project_id=pid, agent_type="CI",
                                  action="ci_scheduler_tick")
    try:
        # 直接调 _get_branch_head：就是 CI 轮询里那一行（ci_pipeline.py:589）
        await C.ci_pipeline._get_branch_head(pid, marker)
    finally:
        pop_checkpoint_context(tok)

    row = await db.fetch_one(
        "SELECT project_id, ticket_id, agent_type, source, command, exit_code, noise "
        "FROM ticket_command_log WHERE command LIKE ? "
        "ORDER BY created_at DESC LIMIT 1", (f"%{marker}%",))
    check("CI 轮询的 git 命令落库了", row is not None)
    if row:
        check("落库时带上了 project_id（本轮修的就是这个）",
              row["project_id"] == pid, f"{row['project_id']!r}")
        check("ticket_id 仍然为空（没工单就是没工单，不伪造）",
              not row["ticket_id"], f"{row['ticket_id']!r}")
        check("agent_type 是 CI 而不是兜底的 Git",
              row["agent_type"] == "CI", f"{row['agent_type']!r}")
        # rev-parse 一个不存在的 ref 会失败 → 失败一律不算噪音
        check("失败的 rev-parse 不算噪音（失败的 plumbing 往往就是断点）",
              row["noise"] == 0, f"noise={row['noise']}")

        # 清掉这条探针，别留在真库里
        await db.execute("DELETE FROM ticket_command_log WHERE command LIKE ?",
                         (f"%{marker}%",))

    # 反证：不 push 上下文时，project_id 就是空的（说明上面那条不是碰巧）
    marker2 = "__attr_probe_nocxt__"
    clear_checkpoint_context()
    await C.ci_pipeline._get_branch_head(pid, marker2)
    row2 = await db.fetch_one(
        "SELECT project_id FROM ticket_command_log WHERE command LIKE ? "
        "ORDER BY created_at DESC LIMIT 1", (f"%{marker2}%",))
    check("反证：没上下文时 project_id 确实为空（证明是 push 起的作用）",
          row2 is not None and not row2["project_id"],
          f"{row2['project_id']!r}" if row2 else "无记录")
    await db.execute("DELETE FROM ticket_command_log WHERE command LIKE ?",
                     (f"%{marker2}%",))

    clear_checkpoint_context()
    print(f"\n=== {PASS} 通过 / {FAIL} 失败 ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
