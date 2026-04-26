"""快速跑 TestFPS UBT 编译，打印结构化错误"""
import asyncio, sys
sys.path.insert(0, ".")

async def main():
    from database import db
    from git_manager import git_manager
    from actions.ue_compile_check import UECompileCheckAction
    await db.connect()
    git_manager.set_project_path("TFP", "D:/Projects/TestFPS")

    hits = []
    async def log(line):
        low = line.lower()
        if any(k in low for k in ("error", "warning", "fatal", "[ubt]", "[error]", "result")):
            hits.append(line)
            print("  LOG>", line[:280])

    ctx = {"project_id": "TFP",
           "uproject_path": "D:/Projects/TestFPS/TestFPS.uproject",
           "timeout_seconds": 600,
           "log_callback": log}
    r = await UECompileCheckAction().run(ctx)
    d = r.data or {}
    print("\n" + "="*60)
    print("status:", d.get("status"), "  exit:", d.get("exit_code"),
          "  errors:", len(d.get("errors") or []),
          "  warnings:", len(d.get("warnings") or []),
          "  duration:", d.get("duration_ms"), "ms")
    for e in (d.get("errors") or [])[:20]:
        fname = (e.get("file") or "?").replace("\\","/").split("/")[-1]
        print(f"  [{e.get('category')}] {fname}:{e.get('line')} {e.get('code')} — {(e.get('msg') or '')[:200]}")
    if d.get("raw_tail"):
        print("\n--- raw tail (last 1KB) ---")
        print(d["raw_tail"][-1000:])

asyncio.run(main())
