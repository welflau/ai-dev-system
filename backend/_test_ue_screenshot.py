"""快速测 UEScreenshotAction，跑 MyFPS 截图"""
import asyncio, sys
sys.path.insert(0, ".")

async def main():
    from database import db
    from git_manager import git_manager
    from actions.ue_screenshot import UEScreenshotAction
    await db.connect()
    pid = "PRJ-20260424-f650c9"
    repo = r"D:\A_Works\ai-dev-system\backend\projects\PRJ-20260424-f650c9"
    git_manager.set_project_path(pid, repo)

    async def log(line):
        low = line.lower()
        if any(k in low for k in ("screenshot", "[screenshot]", "error", "result", "exit", "shot")):
            print("  LOG>", line[:200])

    ctx = {
        "project_id": pid,
        "uproject_path": f"{repo}/MyFPS.uproject",
        "timeout_seconds": 450,  # 300s load + 150s buffer for HighResShot + cleanup
        "screenshot_width": 1280,
        "screenshot_height": 720,
        "log_callback": log,
    }
    print("[*] 启动游戏截图（首次可能需要 1-3 分钟着色器编译）...")
    r = await UEScreenshotAction().run(ctx)
    d = r.data or {}
    print()
    print("="*60)
    print("status:", d.get("status"))
    print("screenshots:", d.get("screenshots"))
    print("count:", d.get("screenshot_count"))
    print("duration:", d.get("duration_ms"), "ms")
    print("message:", d.get("message"))
    if d.get("partial_log"):
        print("\n--- last log ---")
        print(d["partial_log"][-1000:])

asyncio.run(main())
