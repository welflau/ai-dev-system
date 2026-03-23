"""
AI自动开发系统 - FastAPI主应用
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any
import uuid

from models.schemas import (
    ProcessRequest,
    ProcessResponse,
    GetProjectStateRequest,
    GetProjectStateResponse
)
from tools.registry import ToolRegistry
from tools.file_tool import (
    FileWriterTool,
    FileReaderTool,
    DirectoryListerTool
)
from tools.git_tool import (
    GitInitTool,
    GitAddTool,
    GitCommitTool,
    GitPushTool,
    GitCreateBranchTool
)

# 创建FastAPI应用
app = FastAPI(
    title="AI自动开发系统",
    description="从自然语言需求到可运行软件的端到端自动化开发系统",
    version="0.1.0"
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

# 注册工具
tool_registry.register(FileWriterTool())
tool_registry.register(FileReaderTool())
tool_registry.register(DirectoryListerTool())
tool_registry.register(GitInitTool())
tool_registry.register(GitAddTool())
tool_registry.register(GitCommitTool())
tool_registry.register(GitPushTool())
tool_registry.register(GitCreateBranchTool())

# 内存中的项目状态存储(生产环境应使用数据库)
project_states: Dict[str, Dict[str, Any]] = {}


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "AI自动开发系统",
        "version": "0.1.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "tools_available": len(tool_registry.list_tools())
    }


@app.get("/tools")
async def list_tools():
    """列出所有可用工具"""
    return {
        "tools": tool_registry.get_schemas()
    }


@app.post("/api/process", response_model=ProcessResponse)
async def process_request(request: ProcessRequest):
    """
    处理用户请求,生成项目计划
    """
    try:
        # 生成项目ID
        project_id = str(uuid.uuid4())
        
        # 保存项目状态
        project_states[project_id] = {
            "project_id": project_id,
            "request": request.dict(),
            "status": "analyzing",
            "created_at": None  # 需要添加时间戳
        }
        
        # TODO: 实现任务分解逻辑
        # 这里暂时返回模拟数据
        return ProcessResponse(
            project_id=project_id,
            status="pending",
            message="项目已创建,正在分析需求..."
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_id}/state", response_model=GetProjectStateResponse)
async def get_project_state(project_id: str):
    """
    获取项目状态
    """
    if project_id not in project_states:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # TODO: 实现完整的状态获取逻辑
    project_state = project_states[project_id]
    
    # 计算任务摘要
    task_summary = {
        "total": 0,
        "completed": 0,
        "in_progress": 0,
        "pending": 0,
        "failed": 0
    }
    
    return GetProjectStateResponse(
        project_state=project_state,
        task_summary=task_summary
    )


@app.post("/api/projects/{project_id}/execute")
async def execute_project(project_id: str):
    """
    执行项目计划
    """
    if project_id not in project_states:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # TODO: 实现项目执行逻辑
    project_states[project_id]["status"] = "executing"
    
    return {
        "project_id": project_id,
        "status": "started",
        "message": "项目执行已开始"
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=True
    )
