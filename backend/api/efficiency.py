"""研发效率统计 API"""
from fastapi import APIRouter, HTTPException
from database import db

router = APIRouter(prefix="/api/projects/{project_id}/efficiency", tags=["efficiency"])


@router.get("")
async def get_efficiency(project_id: str):
    """项目研发效率统计"""
    project = await db.fetch_one("SELECT id, name FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    # 1. 需求交付周期（创建→完成，天）
    req_stats = await db.fetch_all("""
        SELECT id, title, status, created_at, completed_at,
               CAST((julianday(COALESCE(completed_at, datetime('now'))) -
                     julianday(created_at)) AS INTEGER) AS days
        FROM requirements WHERE project_id = ?
        ORDER BY created_at DESC LIMIT 20
    """, (project_id,))

    completed_reqs = [r for r in req_stats if r["status"] == "completed" and r["completed_at"]]
    avg_days = (sum(r["days"] for r in completed_reqs) / len(completed_reqs)) if completed_reqs else None

    # 2. Agent 耗时占比 + Token 消耗（按 agent_type 统计）
    agent_time = await db.fetch_all("""
        SELECT agent_type,
               COUNT(*) as calls,
               SUM(duration_ms) as total_ms,
               AVG(duration_ms) as avg_ms,
               SUM(COALESCE(input_tokens, 0))  as total_input_tokens,
               SUM(COALESCE(output_tokens, 0)) as total_output_tokens
        FROM llm_conversations
        WHERE project_id = ?
        GROUP BY agent_type
        ORDER BY total_ms DESC
    """, (project_id,))

    # 3. Reflexion 重试排行（返工最多的工单）
    rework_rank = await db.fetch_all("""
        SELECT t.id, t.title,
               COUNT(tl.id) as rework_count
        FROM tickets t
        JOIN ticket_logs tl ON tl.ticket_id = t.id
        WHERE t.project_id = ? AND tl.action IN ('rework', 'fix_issues')
        GROUP BY t.id
        ORDER BY rework_count DESC
        LIMIT 10
    """, (project_id,))

    # 4. Smart Probe 平均清晰度
    prd_artifacts = await db.fetch_all("""
        SELECT content FROM artifacts
        WHERE project_id = ? AND type = 'prd'
        LIMIT 50
    """, (project_id,))
    import json
    probe_scores = []
    for a in prd_artifacts:
        try:
            d = json.loads(a["content"] or "{}")
            s = d.get("smart_probe_score")
            if s is not None:
                probe_scores.append(s)
        except Exception:
            pass
    avg_probe = sum(probe_scores) / len(probe_scores) if probe_scores else None

    # 5. 工单状态分布
    ticket_dist = await db.fetch_all("""
        SELECT status, COUNT(*) as cnt
        FROM tickets WHERE project_id = ?
        GROUP BY status ORDER BY cnt DESC
    """, (project_id,))

    return {
        "project_id": project_id,
        "project_name": project["name"],
        "delivery": {
            "completed_requirements": len(completed_reqs),
            "avg_delivery_days": round(avg_days, 1) if avg_days else None,
            "recent_requirements": [
                {"id": r["id"], "title": r["title"], "status": r["status"],
                 "days": r["days"], "completed": bool(r["completed_at"])}
                for r in req_stats[:10]
            ],
        },
        "agent_time": [
            {"agent": r["agent_type"], "calls": r["calls"],
             "total_seconds": round((r["total_ms"] or 0) / 1000, 1),
             "avg_seconds": round((r["avg_ms"] or 0) / 1000, 1),
             "input_tokens": r["total_input_tokens"] or 0,
             "output_tokens": r["total_output_tokens"] or 0}
            for r in agent_time
        ],
        "rework": {
            "top_tickets": [
                {"id": r["id"], "title": r["title"], "rework_count": r["rework_count"]}
                for r in rework_rank
            ],
        },
        "smart_probe": {
            "avg_score": round(avg_probe, 1) if avg_probe else None,
            "sample_count": len(probe_scores),
        },
        "ticket_distribution": [{"status": r["status"], "count": r["cnt"]} for r in ticket_dist],
    }
