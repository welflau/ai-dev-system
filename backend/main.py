"""
AI 自动开发系统 - 主入口
FastAPI 应用启动
"""
import os
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    print("=" * 60)
    print("  AI 自动开发系统 v0.7.0")
    print("  工单管理模式")
    print("=" * 60)

    await db.connect()
    await db.init_tables()
    print("[DB] SQLite 数据库就绪")

    from llm_client import llm_client
    if llm_client.is_configured:
        print(f"[LLM] 已配置: {llm_client.base_url} / {llm_client.model}")
    else:
        print("[LLM] 未配置，将使用规则引擎降级")

    print(f"[Server] http://localhost:{settings.PORT}")
    print(f"[App] http://localhost:{settings.PORT}/app")
    print("=" * 60)

    yield

    # 关闭时
    await db.disconnect()
    print("[DB] 数据库连接已关闭")


app = FastAPI(
    title="AI 自动开发系统",
    version="0.7.0",
    description="工单驱动的 AI 自动开发管理平台",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
from api.projects import router as projects_router
from api.requirements import router as requirements_router
from api.tickets import router as tickets_router

app.include_router(projects_router)
app.include_router(requirements_router)
app.include_router(tickets_router)


# ==================== 系统端点 ====================


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": "0.7.0"}


@app.get("/api/llm/status")
async def llm_status():
    """LLM 状态"""
    from llm_client import llm_client
    return {
        "configured": llm_client.is_configured,
        "base_url": llm_client.base_url if llm_client.is_configured else None,
        "model": llm_client.model if llm_client.is_configured else None,
    }


@app.post("/api/llm/test")
async def llm_test():
    """测试 LLM 连接"""
    from llm_client import llm_client
    result = await llm_client.test_connection()
    return result


# ==================== 前端静态文件 ====================

# 挂载前端静态文件
frontend_dir = Path(settings.FRONTEND_DIR)
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.get("/app")
@app.get("/app/{path:path}")
async def serve_frontend(path: str = ""):
    """提供前端页面"""
    index_file = frontend_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse(
        {"message": "前端文件未找到，请确保 frontend/ 目录存在"},
        status_code=404,
    )


# ==================== 启动入口 ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
