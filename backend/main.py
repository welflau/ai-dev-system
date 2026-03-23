"""
AI自动开发系统 - FastAPI主应用
"""
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Dict, Any, Optional

from models.schemas import ProcessRequest, ProcessResponse
from models.enums import TaskStatus
from tools.registry import ToolRegistry
from tools.file_tool import FileWriterTool, FileReaderTool, DirectoryListerTool
from tools.git_tool import (
    GitInitTool, GitAddTool, GitCommitTool, GitPushTool, GitCreateBranchTool
)
from orchestrator import Orchestrator

# 创建FastAPI应用
app = FastAPI(
    title="AI自动开发系统",
    description="从自然语言需求到可运行软件的端到端自动化开发系统",
    version="0.2.0"
)

# 前端文件目录
FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化工具注册表
tool_registry = ToolRegistry()
tool_registry.register(FileWriterTool())
tool_registry.register(FileReaderTool())
tool_registry.register(DirectoryListerTool())
tool_registry.register(GitInitTool())
tool_registry.register(GitAddTool())
tool_registry.register(GitCommitTool())
tool_registry.register(GitPushTool())
tool_registry.register(GitCreateBranchTool())

# 初始化协调器
orchestrator = Orchestrator()


# ============ 基础端点 ============

@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "AI自动开发系统",
        "version": "0.2.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    project_count = len(orchestrator.get_all_projects())
    return {
        "status": "healthy",
        "tools_available": len(tool_registry.list_tools()),
        "projects_count": project_count
    }


@app.get("/tools")
async def list_tools():
    """列出所有可用工具"""
    return {"tools": tool_registry.get_schemas()}


# ============ 项目 API ============

@app.post("/api/process")
async def process_request(request: ProcessRequest):
    """
    处理用户请求：分析需求，分解任务，创建项目
    """
    try:
        result = orchestrator.process_request(
            description=request.description,
            tech_stack=request.tech_stack,
            preferences=request.preferences,
        )

        return {
            "project_id": result["project_id"],
            "status": result["status"],
            "message": result["message"],
            "task_count": result["task_count"],
            "tasks": result["tasks"],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects")
async def list_projects():
    """获取所有项目列表"""
    return {"projects": orchestrator.get_all_projects()}


@app.get("/api/projects/{project_id}/state")
async def get_project_state(project_id: str):
    """获取项目完整状态"""
    state = orchestrator.get_project_state(project_id)
    if not state:
        raise HTTPException(status_code=404, detail="项目不存在")

    return {
        "project_state": state,
        "task_summary": state["task_summary"],
    }


@app.put("/api/projects/{project_id}/tasks/{task_id}")
async def update_task_status(
    project_id: str,
    task_id: str,
    status: str,
    error_message: Optional[str] = None,
):
    """更新任务状态"""
    try:
        task_status = TaskStatus(status)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"无效的状态: {status}，可选值: {[s.value for s in TaskStatus]}"
        )

    result = orchestrator.update_task(
        project_id=project_id,
        task_id=task_id,
        status=task_status,
        error_message=error_message,
    )

    if not result:
        raise HTTPException(status_code=404, detail="项目或任务不存在")

    return result


@app.post("/api/projects/{project_id}/execute")
async def execute_project(project_id: str):
    """执行项目（模拟：将第一个 pending 任务标记为 in_progress）"""
    state = orchestrator.get_project_state(project_id)
    if not state:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 找到第一个 pending 任务并标记为进行中
    started_tasks = []
    for phase, tasks in state["tasks_by_phase"].items():
        for task in tasks:
            if task["status"] == "pending":
                orchestrator.update_task(
                    project_id=project_id,
                    task_id=task["id"],
                    status=TaskStatus.IN_PROGRESS,
                )
                started_tasks.append(task["name"])
                break
        if started_tasks:
            break

    return {
        "project_id": project_id,
        "status": "executing",
        "message": f"已启动任务: {', '.join(started_tasks)}" if started_tasks else "没有待执行的任务",
        "started_tasks": started_tasks,
    }


# ============ 前端服务 ============

@app.get("/app")
async def serve_frontend():
    """提供前端主页面"""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Frontend not found")


# 挂载前端静态文件
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
