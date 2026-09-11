"""一次性脚本：跑 TestFPS 的 UBT 编译，打印结构化错误"""
import asyncio
import sys
sys.path.insert(0, ".")


async def main():
    from database import db
    from git_manager import git_manager
    from actions.ue_compile_check import UECompileCheckAction

    await db.connect()
    git_manager.set_project_path("TESTFPS", "D:/Projects/TestFPS")

    line_count = [0]

    async def _log(line):
        line_count[0] += 1
        # 只打重要行，减少噪音
        low = line.lower()
        if ("error" in low or "fatal" in low or "warning" in low
                or line.startswith("[ubt]") or line.startswith("[error]")
                or "unresolved" in low or "cannot open" in low
                or ": c" in low[:60] or "unable" in low):
            print("  LOG>", line[:300])

    ctx = {
        "project_id": "TESTFPS",
        "uproject_path": "D:/Projects/TestFPS/TestFPS.uproject",
        "timeout_seconds": 600,
        "log_callback": _log,
    }
    r = await UECompileCheckAction().run(ctx)
    d = r.data or {}
    print()
    print("=" * 70)
    print("status:", d.get("status"))
    print("exit_code:", d.get("exit_code"))
    print("duration:", d.get("duration_ms"), "ms")
    print("command:", d.get("command"))
    print("target:", d.get("target_name"))
    print("log_lines_total:", line_count[0])
    errors = d.get("errors") or []
    warnings = d.get("warnings") or []
    print(f"errors: {len(errors)}  warnings: {len(warnings)}")
    print()
    print("=" * 30 + " errors " + "=" * 30)
    for e in errors[:30]:
        fname = (e.get("file") or "?").replace("\\", "/").split("/")[-1]
        print(f"  [{e.get('category', '?')}] {fname}:{e.get('line', '?')} "
              f"{e.get('code', '')} — {(e.get('msg') or '')[:200]}")
    if len(errors) > 30:
        print(f"  ... (+{len(errors) - 30} more)")

    print()
    print("=" * 30 + " raw_tail (last 3KB) " + "=" * 30)
    print((d.get("raw_tail") or "")[-3000:])


if __name__ == "__main__":
    asyncio.run(main())
