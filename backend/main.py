"""
AI自动开发系统 - FastAPI主应用

v0.5.0: Agent 上下文传递 + TestAgent + ProductAgent + SSE 实时推送 + 处理日志
"""
import os
import json
import asyncio
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse
from typing import Dict, Any, Optional

from config import settings
from llm import LLMClient
from models.schemas import ProcessRequest, ProcessResponse
from models.enums import TaskStatus
from tools.registry import ToolRegistry
from tools.file_tool import FileWriterTool, FileReaderTool, DirectoryListerTool
from tools.git_tool import (
    GitInitTool, GitAddTool, GitCommitTool, GitPushTool, GitCreateBranchTool
)
from orchestrator import Orchestrator
from orchestrator.db_state_manager import DbStateManager

# 创建FastAPI应用
app = FastAPI(
    title="AI自动开发系统",
    description="从自然语言需求到可运行软件的端到端自动化开发系统",
    version=settings.APP_VERSION,
)

# ============ SSE 事件总线 ============

class EventBus:
    """简易 SSE 事件总线，支持多客户端订阅项目事件"""

    def __init__(self):
        # project_id -> list[asyncio.Queue]
        self._subscribers: Dict[str, list] = {}

    def subscribe(self, project_id: str) -> asyncio.Queue:
        """订阅某项目的事件流"""
        q: asyncio.Queue = asyncio.Queue()
        if project_id not in self._subscribers:
            self._subscribers[project_id] = []
        self._subscribers[project_id].append(q)
        return q

    def unsubscribe(self, project_id: str, q: asyncio.Queue):
        """取消订阅"""
        subs = self._subscribers.get(project_id, [])
        if q in subs:
            subs.remove(q)
        if not subs and project_id in self._subscribers:
            del self._subscribers[project_id]

    async def publish(self, project_id: str, event: str, data: Dict[str, Any]):
        """向所有订阅者推送事件"""
        subs = self._subscribers.get(project_id, [])
        msg = json.dumps(data, ensure_ascii=False)
        for q in subs:
            await q.put({"event": event, "data": msg})

event_bus = EventBus()

# 初始化 LLM 客户端
llm_client = LLMClient(
    base_url=settings.LLM_BASE_URL,
    api_key=settings.LLM_API_KEY,
    model=settings.LLM_MODEL,
    timeout=settings.LLM_TIMEOUT,
    max_retries=settings.LLM_MAX_RETRIES,
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

# 初始化协调器（配置项目输出目录 + SQLite 持久化）
PROJECTS_DIR = settings.PROJECTS_DIR
os.makedirs(PROJECTS_DIR, exist_ok=True)

DB_PATH = settings.DB_PATH
db_state_manager = DbStateManager(db_path=DB_PATH)
orchestrator = Orchestrator(
    state_manager=db_state_manager,
    work_dir=PROJECTS_DIR,
    llm_client=llm_client,
)


# 注入日志回调：Orchestrator 处理日志 -> SSE 推送到前端
def _orchestrator_log_callback(project_id: str, level: str, message: str, detail: str = ""):
    """将 Orchestrator 的处理日志推送到 SSE 事件总线"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(event_bus.publish(project_id, "log", {
                "level": level,
                "message": message,
                "detail": detail,
                "timestamp": time.time(),
            }))
    except RuntimeError:
        pass  # 没有运行中的事件循环时忽略


orchestrator.set_log_callback(_orchestrator_log_callback)


# ============ 基础端点 ============

@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "AI自动开发系统",
        "version": "0.5.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    project_count = len(orchestrator.get_all_projects())
    return {
        "status": "healthy",
        "tools_available": len(tool_registry.list_tools()),
        "projects_count": project_count,
        "llm_enabled": llm_client.enabled,
        "llm_model": llm_client.model,
    }


@app.get("/tools")
async def list_tools():
    """列出所有可用工具"""
    return {"tools": tool_registry.get_schemas()}


# ============ LLM API ============

@app.get("/api/llm/status")
async def llm_status():
    """获取 LLM 配置状态"""
    return llm_client.get_status()


@app.post("/api/llm/test")
async def llm_test():
    """测试 LLM 连接"""
    result = llm_client.test_connection()
    return result


@app.post("/api/llm/config")
async def update_llm_config(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
):
    """运行时更新 LLM 配置"""
    global llm_client
    llm_client = LLMClient(
        base_url=base_url or llm_client.base_url,
        api_key=api_key or llm_client.api_key,
        model=model or llm_client.model,
        timeout=settings.LLM_TIMEOUT,
        max_retries=settings.LLM_MAX_RETRIES,
    )
    # 同步更新 orchestrator 中的 llm_client
    orchestrator.update_llm_client(llm_client)
    return {
        "message": "LLM 配置已更新",
        "status": llm_client.get_status(),
    }


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
    """
    执行项目的下一个任务：
    1. 先将所有 in_progress 任务标记为 completed
    2. 调用对应 Agent 真正执行下一个 pending 任务
    """
    state = orchestrator.get_project_state(project_id)
    if not state:
        raise HTTPException(status_code=404, detail="项目不存在")

    completed_tasks = []

    # 第一步：完成所有正在进行的任务（补完上一轮）
    for phase, tasks in state["tasks_by_phase"].items():
        for task in tasks:
            if task["status"] == "in_progress":
                orchestrator.update_task(
                    project_id=project_id,
                    task_id=task["id"],
                    status=TaskStatus.COMPLETED,
                )
                completed_tasks.append(task["name"])

    # 第二步：调用 Agent 真正执行下一个 pending 任务
    result = orchestrator.execute_next_task(project_id)

    # 构建反馈消息
    messages = []
    if completed_tasks:
        messages.append(f"已完成: {', '.join(completed_tasks)}")

    task_name = result.get("task", "")
    if result.get("success") and task_name:
        messages.append(f"正在执行: {task_name}")
        output = result.get("output", "")
        if output:
            messages.append(output)
    elif not task_name and result.get("output"):
        messages.append(result["output"])

    files_created = result.get("files_created", [])

    response_data = {
        "project_id": project_id,
        "status": "executing" if task_name else "idle",
        "message": " | ".join(messages) if messages else "所有任务已完成！",
        "completed_tasks": completed_tasks,
        "current_task": task_name,
        "agent": result.get("agent", ""),
        "files_created": [os.path.basename(f) if isinstance(f, str) else f for f in files_created],
        "files_count": len(files_created),
    }

    # SSE 推送任务状态更新
    asyncio.ensure_future(event_bus.publish(project_id, "task_update", response_data))

    return response_data


@app.post("/api/projects/{project_id}/execute-all")
async def execute_all_tasks(project_id: str):
    """
    一键全量执行：自动依次执行所有 pending 任务直到完成
    """
    state = orchestrator.get_project_state(project_id)
    if not state:
        raise HTTPException(status_code=404, detail="项目不存在")

    results = []
    total_files = 0
    max_iterations = 50  # 安全上限

    for _ in range(max_iterations):
        # 先完成所有 in_progress 的任务
        current_state = orchestrator.get_project_state(project_id)
        for phase, tasks in current_state["tasks_by_phase"].items():
            for task in tasks:
                if task["status"] == "in_progress":
                    orchestrator.update_task(
                        project_id=project_id,
                        task_id=task["id"],
                        status=TaskStatus.COMPLETED,
                    )

        # 执行下一个
        result = orchestrator.execute_next_task(project_id)
        task_name = result.get("task", "")

        if not task_name:
            # 没有更多任务了
            break

        files_created = result.get("files_created", [])
        total_files += len(files_created)
        results.append({
            "task": task_name,
            "agent": result.get("agent", ""),
            "success": result.get("success", False),
            "files_count": len(files_created),
        })

        # SSE 推送每步进度
        asyncio.ensure_future(event_bus.publish(project_id, "task_progress", {
            "task": task_name,
            "agent": result.get("agent", ""),
            "success": result.get("success", False),
            "step": len(results),
            "files_count": len(files_created),
        }))

    # 最后把最后一个 in_progress 的任务也完成
    final_state = orchestrator.get_project_state(project_id)
    for phase, tasks in final_state["tasks_by_phase"].items():
        for task in tasks:
            if task["status"] == "in_progress":
                orchestrator.update_task(
                    project_id=project_id,
                    task_id=task["id"],
                    status=TaskStatus.COMPLETED,
                )

    summary = orchestrator.get_project_state(project_id)
    response_data = {
        "project_id": project_id,
        "status": "completed",
        "message": f"全量执行完成：共执行 {len(results)} 个任务，生成 {total_files} 个文件",
        "tasks_executed": len(results),
        "total_files_created": total_files,
        "results": results,
        "task_summary": summary["task_summary"] if summary else {},
    }

    # SSE 推送全量执行完成
    asyncio.ensure_future(event_bus.publish(project_id, "execute_all_done", response_data))

    return response_data


@app.get("/api/projects/{project_id}/files")
async def list_project_files(project_id: str):
    """
    列出项目生成的所有文件
    """
    project_dir = os.path.join(PROJECTS_DIR, project_id)
    if not os.path.exists(project_dir):
        return {"project_id": project_id, "files": [], "message": "项目目录尚未创建"}

    files = []
    for root, dirs, filenames in os.walk(project_dir):
        for fname in filenames:
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, project_dir).replace("\\", "/")
            size = os.path.getsize(full_path)
            files.append({
                "path": rel_path,
                "name": fname,
                "size": size,
                "size_display": f"{size:,} B" if size < 1024 else f"{size/1024:.1f} KB",
            })

    return {
        "project_id": project_id,
        "files": files,
        "total_files": len(files),
    }


@app.get("/api/projects/{project_id}/files/{file_path:path}")
async def read_project_file(project_id: str, file_path: str):
    """
    读取项目生成的文件内容
    """
    full_path = os.path.join(PROJECTS_DIR, project_id, file_path)

    # 安全检查：防止路径穿越
    abs_project = os.path.abspath(os.path.join(PROJECTS_DIR, project_id))
    abs_file = os.path.abspath(full_path)
    if not abs_file.startswith(abs_project):
        raise HTTPException(status_code=403, detail="路径不允许")

    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        content = "[二进制文件，无法预览]"

    return {
        "path": file_path,
        "content": content,
        "size": os.path.getsize(full_path),
    }


# ============ SSE 实时推送 ============

@app.get("/api/projects/{project_id}/events")
async def project_events(project_id: str):
    """
    SSE 实时推送项目事件流

    前端通过 EventSource 订阅，替代 8 秒轮询。
    事件类型：task_update, task_progress, execute_all_done
    """
    state = orchestrator.get_project_state(project_id)
    if not state:
        raise HTTPException(status_code=404, detail="项目不存在")

    queue = event_bus.subscribe(project_id)

    async def event_generator():
        try:
            # 先推送一次当前状态作为初始数据
            current = orchestrator.get_project_state(project_id)
            if current:
                yield {
                    "event": "init",
                    "data": json.dumps({
                        "task_summary": current["task_summary"],
                        "phase": current["phase"],
                    }, ensure_ascii=False),
                }

            # 持续监听事件队列
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield msg
                except asyncio.TimeoutError:
                    # 30 秒无事件，发送心跳保活
                    yield {"event": "heartbeat", "data": "ping"}
        except asyncio.CancelledError:
            pass
        finally:
            event_bus.unsubscribe(project_id, queue)

    return EventSourceResponse(event_generator())


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
