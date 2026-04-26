import asyncio, sys
sys.path.insert(0, ".")
async def go():
    from database import db
    await db.connect()
    rows = await db.fetch_all(
        "SELECT id, role, action_type, content, created_at "
        "FROM chat_messages WHERE project_id = ? "
        "ORDER BY created_at DESC LIMIT 10",
        ("PRJ-20260424-f650c9",),
    )
    for r in rows:
        ct = (r.get("content") or "")[:50].encode("ascii", errors="replace").decode()
        print(r["created_at"], r["role"], r["action_type"], ct)
asyncio.run(go())
