r"""
UE 框架生成 API（v0.18 Phase A.6）

端点：
- POST /api/projects/{pid}/ue-framework/propose        仅算方案，不落地（ChatAction 也会调同一逻辑）
- POST /api/projects/{pid}/ue-framework/instantiate    真实执行模板实例化 + Git commit
- POST /api/projects/{pid}/ue-framework/baseline-compile  基线编译（调 UECompileCheckAction）
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from database import db

logger = logging.getLogger("api.ue_framework")

router = APIRouter(prefix="/api/projects/{project_id}/ue-framework", tags=["ue-framework"])


# ==================== 请求模型 ====================


class ProposeRequest(BaseModel):
    project_name_override: Optional[str] = None
    genre_hint: Optional[str] = None
    force_template: Optional[str] = None


class InstantiateRequest(BaseModel):
    template_name: str = Field(..., description="TP_FirstPerson / TP_ThirdPerson / ... / TP_Blank")
    engine_path: str = Field(..., description="UE 引擎根目录绝对路径")
    project_name: str = Field(..., description="目标项目名（rename 用），首字母+字母数字下划线")
    allow_overwrite: bool = Field(False, description="目标目录非空时是否覆盖")
    copy_content_assets: bool = Field(True, description="是否拷贝 Content/ 下的 .uasset 资产")
    commit_message: Optional[str] = Field(
        None, description="Git commit 消息，默认 'feat: 基于 {template} 生成 UE 项目框架'"
    )


class BaselineCompileRequest(BaseModel):
    engine_path: Optional[str] = None
    target_name: Optional[str] = None
    target_platform: str = "Win64"
    target_config: str = "Development"
    timeout_seconds: int = 600


# ==================== 端点 ====================


@router.post("/propose")
async def propose(project_id: str, req: ProposeRequest):
    """只算方案，不落地。前端卡片确认前调一次拿到推荐引擎/模板 + 文件变化预览。"""
    from actions.chat.propose_ue_framework import ProposeUEFrameworkAction
    action = ProposeUEFrameworkAction()
    context = {
        "project_id": project_id,
        "project_name_override": req.project_name_override or "",
        "genre_hint": req.genre_hint or "",
        "force_template": req.force_template or "",
    }
    result = await action.run(context)
    if not result.success:
        raise HTTPException(400, result.error or "生成方案失败")
    return result.data


@router.post("/instantiate")
async def instantiate(project_id: str, req: InstantiateRequest):
    """真跑模板实例化。用户点 [✓ 确认生成] 触发。

    同步执行（1-5s），期间通过 SSE 事件 ue_instantiate_log 推每个里程碑 log 到前端日志面板。
    返回最终结果 data（含 files_created / uproject_path / git_commit）给卡片替换 DOM 用。
    """
    from events import event_manager

    proj = await db.fetch_one("SELECT id, name FROM projects WHERE id = ?", (project_id,))
    if not proj:
        raise HTTPException(404, "项目不存在")

    # 用项目的 git_repo_path（custom path 或 PROJECTS_DIR/{pid}）
    from git_manager import git_manager
    repo_path = git_manager._repo_path(project_id)
    if not repo_path:
        raise HTTPException(500, "无法确定项目仓库路径")
    target_dir = str(repo_path)

    async def _push_log(line: str):
        try:
            await event_manager.publish_to_project(
                project_id, "ue_instantiate_log", {"line": line}
            )
        except Exception:
            pass

    # 启动事件
    try:
        await event_manager.publish_to_project(
            project_id, "ue_instantiate_started",
            {
                "template": req.template_name,
                "project_name": req.project_name,
                "engine_path": req.engine_path,
                "target_dir": target_dir,
            },
        )
    except Exception:
        pass

    await _push_log(f"[api] POST /instantiate template={req.template_name} project={req.project_name}")

    # 执行 Action（带 log_callback）
    from actions.instantiate_ue_template import InstantiateUETemplateAction
    action = InstantiateUETemplateAction()
    context = {
        "engine_path": req.engine_path,
        "template_name": req.template_name,
        "target_dir": target_dir,
        "project_name": req.project_name,
        "allow_overwrite": req.allow_overwrite,
        "copy_content_assets": req.copy_content_assets,
        "log_callback": _push_log,
    }
    result = await action.run(context)
    if not result.success:
        data = result.data or {}
        await _push_log(f"[error] {result.error or data.get('message') or '实例化失败'}")
        raise HTTPException(400, result.error or data.get("message") or "实例化失败")

    # Git commit 落地（每步都推 log）
    git_commit: Optional[str] = None
    if git_manager.repo_exists(project_id):
        try:
            msg = req.commit_message or f"feat: 基于 {req.template_name} 生成 UE 项目框架"
            await _push_log(f"[git] cwd={target_dir}")
            await _push_log(f"[git] git add -A")
            await git_manager._run_git(target_dir, "add", "-A")
            await _push_log(f"[git] git commit -m \"{msg}\" --allow-empty")
            rc, out, err = await git_manager._run_git(
                target_dir, "commit", "-m", msg, "--allow-empty",
            )
            if rc == 0:
                rc2, out2, _ = await git_manager._run_git(
                    target_dir, "rev-parse", "HEAD",
                )
                if rc2 == 0:
                    git_commit = (out2 or "").strip()[:12]
                    await _push_log(f"[git] commit: {git_commit}")
            else:
                await _push_log(f"[git] commit rc={rc} err={(err or '').strip()[:200]}")
        except Exception as e:
            logger.warning("git commit 落地失败（非致命）: %s", e)
            await _push_log(f"[git] 异常（非致命）: {e}")

    # 完成事件（原有）
    try:
        await event_manager.publish_to_project(
            project_id,
            "ue_framework_instantiated",
            {
                "template": req.template_name,
                "project_name": req.project_name,
                "files_created": result.data.get("files_created"),
                "uproject_path": result.data.get("uproject_path"),
                "git_commit": git_commit,
            },
        )
    except Exception:
        pass

    await _push_log(
        f"[done] 实例化完成 · {result.data.get('files_created')} 文件 · commit={git_commit or '(无)'}"
    )

    return {
        **result.data,
        "git_commit": git_commit,
    }


@router.post("/baseline-compile")
async def baseline_compile(project_id: str, req: BaselineCompileRequest):
    """对刚生成的骨架跑一次 UnrealBuildTool 验证基线。

    **异步模式**：立即返回 {status: "started"}，UBT 在后台跑。过程通过 SSE 推：
      - ue_compile_log     每行 UBT 输出（流式）
      - ue_compile_started 启动事件（含命令）
      - ue_baseline_compile_result 最终结果
    前端订阅这三个事件即可实现实时日志流 + 最终结果展示。
    """
    import asyncio
    from events import event_manager

    async def _log_cb(line: str):
        try:
            await event_manager.publish_to_project(
                project_id,
                "ue_compile_log",
                {"line": line},
            )
        except Exception:
            pass

    async def _run_compile_bg():
        from actions.ue_compile_check import UECompileCheckAction
        action = UECompileCheckAction()
        context: Dict[str, Any] = {
            "project_id": project_id,
            "target_platform": req.target_platform,
            "target_config": req.target_config,
            "timeout_seconds": req.timeout_seconds,
            "log_callback": _log_cb,
        }
        if req.engine_path:
            context["engine_path"] = req.engine_path
        if req.target_name:
            context["target_name"] = req.target_name

        # 启动事件（给前端清空日志区做准备）
        try:
            await event_manager.publish_to_project(
                project_id,
                "ue_compile_started",
                {"target": req.target_name or "", "platform": req.target_platform,
                 "config": req.target_config},
            )
        except Exception:
            pass

        try:
            result = await action.run(context)
            data = result.data or {}

            # 执行的 UBT 命令也推一条 log（让"执行了什么"可追溯）
            cmd_str = data.get("command")
            if cmd_str:
                await _log_cb(f"[ubt] cmd: {cmd_str}")
                await _log_cb(f"[ubt] exit={data.get('exit_code')} duration={data.get('duration_ms', 0)}ms")
        except Exception as e:
            logger.exception("baseline-compile 后台异常")
            data = {
                "status": "error",
                "message": f"Action 异常: {e}",
                "errors": [],
                "warnings": [],
            }

        # 广播最终结果
        try:
            await event_manager.publish_to_project(
                project_id,
                "ue_baseline_compile_result",
                {
                    "status": data.get("status"),
                    "exit_code": data.get("exit_code"),
                    "duration_ms": data.get("duration_ms"),
                    "errors_count": len(data.get("errors") or []),
                    "warnings_count": len(data.get("warnings") or []),
                    "errors": (data.get("errors") or [])[:10],   # 前 10 条详细展示
                    "message": data.get("message"),
                    "products": data.get("products"),
                    "command": data.get("command"),
                },
            )
        except Exception:
            pass

    asyncio.create_task(_run_compile_bg())
    return {"status": "started", "message": "基线编译已在后台启动，请看实时日志"}
