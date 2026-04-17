"""
观测 Action 3 件套的直调冒烟测试。

运行前需 backend 在线（从 DB 读数据，不依赖 LLM）。
"""
import asyncio
import json


async def main():
    from database import db
    await db.connect()

    # 挑一个有工单的项目+需求
    req = await db.fetch_one(
        """SELECT r.id, r.title, r.project_id FROM requirements r
           JOIN tickets t ON t.requirement_id = r.id
           WHERE r.status != 'cancelled' GROUP BY r.id ORDER BY r.created_at DESC LIMIT 1"""
    )
    if not req:
        print("❌ 没有可测试的需求"); return
    req_id = req["id"]
    project_id = req["project_id"]
    print(f"=== 使用需求: {req_id} ({req['title']}) ===\n")

    # === Test 1: GetRequirementPipelineAction ===
    from actions.chat.get_requirement_pipeline import GetRequirementPipelineAction
    print("=== Test 1: GetRequirementPipelineAction (精确 ID) ===")
    r = await GetRequirementPipelineAction().run({
        "project_id": project_id, "requirement_id": req_id,
    })
    assert r.success, f"failed: {r.data}"
    d = r.data
    print(f"requirement.status: {d['requirement']['status']}")
    print(f"stages:")
    for s in d["stages"]:
        print(f"  - {s['name']:<12} {s['status']}")
    print(f"ticket_count_total: {d['ticket_count_total']}")
    print(f"running_tickets: {len(d['running_tickets'])}")
    print(f"last_activity: {d['last_activity']['action'] if d['last_activity'] else 'N/A'}")
    print("✅ 通过\n")

    # === Test 2: 模糊匹配（用标题关键词）===
    print("=== Test 2: GetRequirementPipeline（标题关键词模糊）===")
    keyword = req["title"][:4]
    r = await GetRequirementPipelineAction().run({
        "project_id": project_id, "requirement_id": keyword,
    })
    assert r.success, f"failed: {r.data}"
    assert r.data["requirement"]["id"] == req_id, "模糊匹配命中错误需求"
    print(f"关键词「{keyword}」命中: {r.data['requirement']['id']}")
    print("✅ 通过\n")

    # === Test 3: 找不到 ===
    print("=== Test 3: GetRequirementPipeline（不存在的 ID）===")
    r = await GetRequirementPipelineAction().run({
        "project_id": project_id, "requirement_id": "REQ-NOT-EXIST-9999",
    })
    assert r.success is False
    assert "未找到" in r.data["message"]
    print(f"错误: {r.data['message']}")
    print("✅ 通过\n")

    # === Test 4: GetTicketStatusAction by requirement_id ===
    from actions.chat.get_ticket_status import GetTicketStatusAction
    print("=== Test 4: GetTicketStatus by requirement_id ===")
    r = await GetTicketStatusAction().run({
        "project_id": project_id, "requirement_id": req_id,
    })
    assert r.success, f"failed: {r.data}"
    d = r.data
    print(f"mode: {d['mode']}, ticket_count: {d['ticket_count']}")
    if d["tickets"]:
        t0 = d["tickets"][0]
        print(f"first ticket: {t0['title'][:30]}... status={t0['status']} idle_min={t0['idle_minutes']}")
        print(f"  last_activity: {t0['last_activity']['action'] if t0['last_activity'] else 'N/A'}")
    print("✅ 通过\n")

    # === Test 5: GetTicketStatusAction by ticket_id ===
    if d["tickets"]:
        tkt_id = d["tickets"][0]["id"]
        print("=== Test 5: GetTicketStatus by ticket_id ===")
        r = await GetTicketStatusAction().run({
            "project_id": project_id, "ticket_id": tkt_id,
        })
        assert r.success and r.data["mode"] == "single"
        print(f"single ticket: {r.data['ticket']['id']} status={r.data['ticket']['status']}")
        print("✅ 通过\n")

    # === Test 6: 两个 ID 都不给 ===
    print("=== Test 6: GetTicketStatus 必填参数缺失 ===")
    r = await GetTicketStatusAction().run({"project_id": project_id})
    assert r.success is False
    assert "必须提供其一" in r.data["message"]
    print(f"错误: {r.data['message']}")
    print("✅ 通过\n")

    # === Test 7: GetRequirementLogsAction ===
    from actions.chat.get_requirement_logs import GetRequirementLogsAction
    print("=== Test 7: GetRequirementLogs ===")
    r = await GetRequirementLogsAction().run({
        "project_id": project_id, "requirement_id": req_id, "limit": 5,
    })
    assert r.success, f"failed: {r.data}"
    print(f"count: {r.data['count']}")
    for log in r.data["logs"][:3]:
        print(f"  [{log['level']}] {log['agent']}.{log['action']} ({log['minutes_ago']}min ago) — {log['summary'][:80]}")
    print("✅ 通过\n")

    # === Test 8: 按 level 过滤 ===
    print("=== Test 8: GetRequirementLogs（只看 error）===")
    r = await GetRequirementLogsAction().run({
        "project_id": project_id, "requirement_id": req_id,
        "limit": 10, "level": "error",
    })
    assert r.success
    print(f"error 级别日志数: {r.data['count']}")
    print("✅ 通过\n")

    print("🎉 3 个观测 Action 全部通过")


if __name__ == "__main__":
    asyncio.run(main())
