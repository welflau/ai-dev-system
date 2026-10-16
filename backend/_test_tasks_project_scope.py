"""/tasks 后台任务面板的项目隔离回归

    cd backend && python _test_tasks_project_scope.py

背景：_cmd_tasks 收了 project_id 却一条查询都没用它 —— 在 TestFPS 的后台任务
面板里会列出 jizhang 项目的 30 条 pending 工单和别的项目的 CI 构建，而输出末尾
还印着「仅显示项目 xxx 内工单」，说的和做的正好相反。

这里断言的是**隔离**本身，不是具体条数：
  ① 传 project_id → 返回的每一条 task 的 project_id 都等于它；
  ② 不传 → 保持全局视图（全局聊天要的就是这个，别修过头）；
  ③ 隔离是真的生效而不是碰巧为空 —— 用一个「库里确实有任务、且不止一个项目
     有任务」的场景来验，否则全返回空也能骗过 ①。
"""
import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

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


async def main():
    from database import db
    from api.commands import _cmd_tasks
    await db.connect()
    try:
        # 找出「当前确实有在办/待办任务」的项目，至少两个才测得出隔离
        rows = await db.fetch_all(
            """SELECT project_id, COUNT(*) AS n FROM tickets
               WHERE status IN ('pending','queued','todo','running','in_progress','executing')
               GROUP BY project_id ORDER BY n DESC"""
        )
        owners = [r["project_id"] for r in rows if r["project_id"]]
        _lines.append(f"     有任务的项目: {len(owners)} 个 "
                      + ", ".join(f"{r['project_id'][:14]}({r['n']})" for r in rows[:4]))

        # ② 全局视图：不传 project_id 时不做过滤
        g = await _cmd_tasks("", None, {})
        g_tasks = (g.data or {}).get("tasks", [])
        g_pids = {t.get("project_id") for t in g_tasks}
        check("不传 project_id 时是全局视图", g.success and len(g_pids) >= min(2, len(owners)),
              f"{len(g_tasks)} 条任务，来自 {len(g_pids)} 个项目")
        check("全局视图提示文案正确", "全局视图" in (g.output or ""))

        if len(owners) < 2:
            _lines.append("[SKIP] 库里只有 <2 个项目有任务，隔离用例意义不大")
            return

        # ① 逐个项目验隔离
        for pid in owners[:3]:
            r = await _cmd_tasks("", pid, {})
            tasks = (r.data or {}).get("tasks", [])
            strays = [t for t in tasks if t.get("project_id") and t["project_id"] != pid]
            check(f"{pid[:14]} 只返回本项目任务", r.success and not strays,
                  f"{len(tasks)} 条" + (f"，混入 {len(strays)} 条外部任务：" +
                   ", ".join(sorted({t['project_id'][:14] for t in strays})) if strays else ""))
            # ③ 隔离生效而不是碰巧返回空
            check(f"{pid[:14]} 确实拿到了自己的任务（不是空表蒙混）", len(tasks) > 0,
                  f"{len(tasks)} 条")
            check(f"{pid[:14]} 提示文案说的是本项目", pid[:8] in (r.output or ""))

        # 交叉验证：两个项目的返回不应重叠
        a, b = owners[0], owners[1]
        ta = {t["id"] for t in ((await _cmd_tasks("", a, {})).data or {}).get("tasks", [])}
        tb = {t["id"] for t in ((await _cmd_tasks("", b, {})).data or {}).get("tasks", [])}
        check("两个项目的任务集合不相交", not (ta & tb),
              f"交集 {len(ta & tb)} 条")
        # 注意方向：**不是** scoped ⊆ global。LIMIT 是每条查询各自算的，
        # 全局视图只取跨项目最早的 10 条 pending，所以某个项目自己的任务
        # 完全可能被全局那 10 条挤掉 —— 那是截断，不是漏查。
        # 真正成立的是反向：全局视图里属于 P 的条目，必然出现在 P 的视图里。
        for pid, scoped in ((a, ta), (b, tb)):
            g_of_p = {t["id"] for t in g_tasks if t.get("project_id") == pid}
            check(f"{pid[:14]} 全局视图里属于它的条目，在本项目视图里都能找到",
                  g_of_p <= scoped, f"全局含 {len(g_of_p)} 条，缺 {len(g_of_p - scoped)} 条")

        # 不存在的项目 → 空表，不报错（别 500）
        r = await _cmd_tasks("", "PRJ-NOT-EXIST", {})
        check("不存在的项目返回空表且不报错",
              r.success and not ((r.data or {}).get("tasks")))
    finally:
        await db.disconnect()   # aiosqlite 后台线程不断开会吊住进程


if __name__ == "__main__":
    asyncio.run(main())
    _lines.append(f"\n=== {_pass} passed / {_fail} failed ===")
    (BACKEND / "_tasks_scope_out.txt").write_text("\n".join(_lines), encoding="utf-8")
    print(f"pass={_pass} fail={_fail}")
    sys.exit(1 if _fail else 0)
