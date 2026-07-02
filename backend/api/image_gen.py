"""图片生成 API — LightAI 图片请求管理"""
import asyncio
import json
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
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


@router.get("/config/refresh-key/urls")
async def get_lightai_community_urls():
    """读取 refresh_key.py 已配置的社区 URL 列表"""
    for base in [".codebuddy", ".claude"]:
        env_json = Path.home() / base / "skills" / "lightai-skill" / "scripts" / "env.json"
        if env_json.exists():
            try:
                data = json.loads(env_json.read_text(encoding="utf-8"))
                urls = data.get("SKILL_COMMUNITY_URLS", [])
                if isinstance(urls, str):
                    urls = [urls] if urls else []
                old = data.get("SKILL_COMMUNITY_URL", "")
                if old and old not in urls:
                    urls.append(old)
                return {"urls": urls}
            except Exception:
                pass
    return {"urls": []}


@router.post("/config/refresh-key")
async def refresh_lightai_key(body: dict = {}):
    """执行 refresh_key.py 自动刷新 LightAI API Key，SSE 流式输出日志"""
    community_url = (body or {}).get("community_url", "").strip()

    skill_refresh = (
        Path.home() / ".codebuddy" / "skills" / "lightai-skill" / "scripts" / "refresh_key.py"
    )
    if not skill_refresh.exists():
        skill_refresh = (
            Path.home() / ".claude" / "skills" / "lightai-skill" / "scripts" / "refresh_key.py"
        )
    if not skill_refresh.exists():
        async def _not_found():
            yield f"data: {json.dumps({'type': 'error', 'text': 'lightai-skill 未安装，找不到 refresh_key.py'})}\n\n"
        return StreamingResponse(_not_found(), media_type="text/event-stream")

    async def _run(args: list):
        if sys.platform == "win32":
            cmd = " ".join(f'"{a}"' for a in [sys.executable] + args)
            return await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**__import__("os").environ},
            )
        return await asyncio.create_subprocess_exec(
            sys.executable, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

    async def _stream():
        env_json = skill_refresh.parent / "env.json"
        try:
            # 若传入 URL 且尚未配置，先 --add-url
            if community_url:
                add_proc = await _run([str(skill_refresh), "--add-url", community_url])
                async for raw in add_proc.stdout:
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    yield f"data: {json.dumps({'type': 'line', 'text': line})}\n\n"
                await add_proc.wait()

            yield f"data: {json.dumps({'type': 'start'})}\n\n"
            proc = await _run([str(skill_refresh)])
            new_key = ""
            async for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip()
                yield f"data: {json.dumps({'type': 'line', 'text': line})}\n\n"
                if line.startswith("UPDATED:") or line.startswith("NO_CHANGE:"):
                    new_key = line.split(":", 1)[1].strip()
            await proc.wait()
            if not new_key and env_json.exists():
                try:
                    new_key = json.loads(env_json.read_text(encoding="utf-8")).get("LIGHTAI_API_KEY", "")
                except Exception:
                    pass
            if proc.returncode == 0 and new_key:
                from config import BASE_DIR
                settings.LIGHTAI_API_KEY = new_key
                env_path = BASE_DIR / ".env"
                env_lines = {}
                if env_path.exists():
                    for line in env_path.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            env_lines[k.strip()] = v.strip()
                env_lines["LIGHTAI_API_KEY"] = new_key
                env_path.write_text(
                    "\n".join(f"{k}={v}" for k, v in env_lines.items()) + "\n",
                    encoding="utf-8",
                )
                yield f"data: {json.dumps({'type': 'done', 'new_key': new_key})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'error', 'text': f'刷新失败 (exit={proc.returncode})'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
