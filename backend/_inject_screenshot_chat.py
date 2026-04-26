"""一次性：把已存在的截图注入到项目聊天消息表"""
import asyncio, sys
sys.path.insert(0, ".")

async def go():
    from database import db
    from api.chat import _save_chat_message
    await db.connect()
    await db.init_tables()

    pid = "PRJ-20260424-f650c9"
    # 找已存在的截图文件
    from pathlib import Path
    from config import BASE_DIR
    shot_dir = BASE_DIR / "chat_images" / "ue_screenshots" / pid
    shots = sorted(shot_dir.glob("*.png"), key=lambda x: x.stat().st_mtime, reverse=True) if shot_dir.exists() else []
    if not shots:
        print("未找到截图文件，先跑一次截图")
        return

    img_urls = [f"/api/projects/{pid}/screenshots/{p.name}" for p in shots[:3]]
    content = "📸 **Editor 截图** (Lvl_FirstPerson)"
    action = {
        "type": "ue_screenshot_result",
        "screenshots": img_urls,
        "local_paths": [str(p) for p in shots[:3]],
        "project_id": pid,
        "build_id": "manual-inject",
    }
    await _save_chat_message(project_id=pid, role="assistant", content=content, action=action)
    print(f"已注入 {len(img_urls)} 张截图到聊天: {img_urls}")

asyncio.run(go())
