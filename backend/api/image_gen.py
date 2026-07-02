"""图片生成 API — LightAI 图片请求管理"""
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from database import db
from utils import now_iso
from config import settings

router = APIRouter(prefix="/api/image-gen", tags=["image-gen"])


class ImageRequest(BaseModel):
    prompt: str = Field(..., description="生图描述")
    project_id: str = Field(default="", description="所属项目 ID")
    ticket_id: str = Field(default="", description="所属工单 ID")
    requester: str = Field(default="manual", description="请求方")
    engine: str = Field(default="", description="引擎：gemini/gemini2/jimeng/midjourney")
    aspect_ratio: str = Field(default="1:1")
    image_size: str = Field(default="2K")
    callback_doc: str = Field(default="", description="文档路径（用于替换占位符）")


@router.post("")
async def create_image_request(req: ImageRequest):
    """提交图片生成请求"""
    from image_processor import request_image
    tag = await request_image(
        prompt=req.prompt,
        project_id=req.project_id,
        ticket_id=req.ticket_id,
        requester=req.requester,
        engine=req.engine,
        aspect_ratio=req.aspect_ratio,
        image_size=req.image_size,
        callback_doc=req.callback_doc,
    )
    return {"tag": tag, "message": "图片请求已入队"}


@router.get("")
async def list_image_requests(project_id: str = "", limit: int = 20):
    """查询图片请求列表"""
    if project_id:
        rows = await db.fetch_all(
            "SELECT * FROM image_requests WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit)
        )
    else:
        rows = await db.fetch_all(
            "SELECT * FROM image_requests ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
    return {"requests": [dict(r) for r in rows]}


@router.get("/{req_id}")
async def get_image_request(req_id: str):
    """查询单个图片请求状态"""
    row = await db.fetch_one("SELECT * FROM image_requests WHERE id = ?", (req_id,))
    if not row:
        raise HTTPException(404, "请求不存在")
    return dict(row)


@router.get("/config/status")
async def get_lightai_config_status():
    """返回 LightAI 配置状态（前端 AI 配置面板使用）"""
    has_key = bool(settings.LIGHTAI_API_KEY)
    return {
        "configured": has_key,
        "api_base": settings.LIGHTAI_API_BASE,
        "engine": settings.LIGHTAI_IMAGE_ENGINE,
        "timeout": settings.LIGHTAI_IMAGE_TIMEOUT,
        "engines": ["gemini", "gemini2", "jimeng", "midjourney"],
    }


@router.post("/config/test")
async def test_lightai_connection():
    """测试 LightAI API 连接"""
    if not settings.LIGHTAI_API_KEY:
        return {"status": "not_configured", "message": "LIGHTAI_API_KEY 未配置"}
    try:
        import json as _json, ssl, urllib.request, urllib.error
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        # 用 create_async_task 做鉴权探针：服务端先验 Key 再验参数，
        # 所以 401/403 = Key 无效，其余状态码（400/422/500）= Key 有效
        url = f"{settings.LIGHTAI_API_BASE.rstrip('/')}/api/lightai/create_async_task"
        payload = _json.dumps({
            "service_name": "_validate_", "api_name": "_test_",
            "app_info": {"model": "", "mode": ""},
            "task_query": {"path": {}, "params": {}, "json": {}, "data": {}, "file": {}},
            "custom_data": {},
        }).encode()
        req = urllib.request.Request(url, data=payload, method="POST", headers={
            "Authorization": f"Bearer {settings.LIGHTAI_API_KEY}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=10, context=ctx):
                pass
            return {"status": "ok", "message": "LightAI 连接正常"}
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return {"status": "error", "message": f"API Key 无效或已过期 (HTTP {e.code})"}
            # 400/404/422/500 等表示 Key 有效，只是参数校验失败
            return {"status": "ok", "message": "LightAI 连接正常"}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}
