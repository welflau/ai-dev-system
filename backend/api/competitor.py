"""竞品反拆 API"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/competitor-analysis", tags=["competitor"])


class CompetitorRequest(BaseModel):
    url: str
    game_name: Optional[str] = ""
    focus: Optional[str] = "全面分析"
    project_id: Optional[str] = ""


@router.post("")
async def analyze_competitor(req: CompetitorRequest):
    """触发竞品反拆分析，结果自动入 planning_knowledge"""
    from actions.chat.competitor_analysis import CompetitorAnalysisAction
    action = CompetitorAnalysisAction()
    result = await action.run({
        "url": req.url,
        "game_name": req.game_name or "",
        "focus": req.focus or "全面分析",
        "project_id": req.project_id or "",
    })
    if result.success:
        return result.data
    else:
        from fastapi import HTTPException
        raise HTTPException(400, result.error or "分析失败")


@router.get("/list")
async def list_competitor_reports():
    """列出已存入知识库的竞品报告"""
    from database import db
    rows = await db.fetch_all(
        """SELECT id, filename, title, summary, updated_at
           FROM planning_knowledge
           WHERE category = 'competitors'
           ORDER BY updated_at DESC LIMIT 50"""
    )
    return {"reports": [dict(r) for r in rows]}
