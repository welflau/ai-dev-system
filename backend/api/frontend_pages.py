"""浏览器页面入口：深链接始终返回同一份首页，图标独立提供。"""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from config import settings

router = APIRouter()
frontend_dir = Path(settings.FRONTEND_DIR)
INDEX_MISSING = "前端文件未找到，请确保 frontend/ 目录存在"
INDEX_ERRORS = {404: {
    "description": "找不到可用的首页文件",
    "content": {"application/json": {"example": {"message": INDEX_MISSING}}},
}}


@router.get("/app", response_class=HTMLResponse, responses=INDEX_ERRORS)
@router.get("/app/{path:path}", response_class=HTMLResponse, responses=INDEX_ERRORS)
async def serve_frontend(path: str = ""):
    """提供前端页面"""
    index_file = frontend_dir / "index.html"
    if not index_file.is_file():
        return JSONResponse({"message": INDEX_MISSING}, status_code=404)
    return FileResponse(index_file, media_type="text/html",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<rect width="32" height="32" rx="6" fill="#7c6af7"/>'
        '<text x="16" y="23" font-size="20" text-anchor="middle" fill="white">🤖</text>'
        '</svg>'
    )
    return Response(content=svg, media_type="image/svg+xml")
