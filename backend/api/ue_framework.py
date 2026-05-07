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
    install_ucp: bool = Field(False, description="v0.20 是否安装 UnrealClientProtocol 插件")
    commit_message: Optional[str] = Field(
        None, description="Git commit 消息，默认 'feat: 基于 {template} 生成 UE 项目框架'"
    )


class BaselineCompileRequest(BaseModel):
    engine_path: Optional[str] = None
    target_name: Optional[str] = None
    target_platform: str = "Win64"
    target_config: str = "Development"
    timeout_seconds: int = 600


class PlaytestRequest(BaseModel):
    """v0.19 Phase ②：UE Automation Framework 冒烟测试"""
    engine_path: Optional[str] = None
    test_filter: Optional[str] = None       # 默认 "Project."
    test_names: Optional[List[str]] = None  # 直接指定测试名；填了覆盖 filter
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
        "install_ucp": req.install_ucp,
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

    v0.20 改造：委托给 CI 策略 trigger_build("ubt_compile")，
    使基线编译和手动点「UBT 编译」按钮行为完全一致：
      - 在「最近构建」留一条 ci_builds 记录（可看详情/日志）
      - 通过 SSE 实时推日志
    """
    from ci.loader import ci_loader

    project = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    strategy = await ci_loader.pick_for_project(project_id)
    valid_ids = {bt.id for bt in strategy.build_types()}
    if "ubt_compile" not in valid_ids:
        raise HTTPException(400, f"策略 {strategy.name} 不支持 ubt_compile")

    kwargs: Dict[str, Any] = {}
    if req.engine_path:
        kwargs["engine_path"] = req.engine_path
    if req.target_name:
        kwargs["target_name"] = req.target_name

    result = await strategy.trigger_build(
        project_id, "ubt_compile", trigger="baseline", **kwargs
    )
    return {
        "status": "started",
        "build_id": result.get("build_id"),
        "message": "基线编译已触发，可在「最近构建」查看进度和日志",
    }


@router.post("/run-playtest")
async def run_playtest(project_id: str, req: PlaytestRequest):
    """v0.19 Phase ②：跑 UE Automation Framework 测试。

    **异步**：立即返回 {status:"started"}，UnrealEditor-Cmd 后台跑。事件流：
      - ue_playtest_started 启动事件（命令 + filter）
      - ue_playtest_log     每行 Editor 输出（流式）
      - ue_playtest_result  最终结果（含 tests / summary / screenshots）
    """
    import asyncio
    from events import event_manager

    async def _log_cb(line: str):
        try:
            await event_manager.publish_to_project(
                project_id, "ue_playtest_log", {"line": line},
            )
        except Exception:
            pass

    async def _run_bg():
        from actions.ue_playtest import UEPlaytestAction
        action = UEPlaytestAction()
        context: Dict[str, Any] = {
            "project_id": project_id,
            "timeout_seconds": req.timeout_seconds,
            "log_callback": _log_cb,
        }
        if req.engine_path:
            context["engine_path"] = req.engine_path
        if req.test_filter:
            context["test_filter"] = req.test_filter
        if req.test_names:
            context["test_names"] = req.test_names

        try:
            await event_manager.publish_to_project(
                project_id, "ue_playtest_started",
                {"test_filter": req.test_filter or "Project.",
                 "test_names": req.test_names},
            )
        except Exception:
            pass

        try:
            result = await action.run(context)
            data = result.data or {}
            cmd_str = data.get("command")
            if cmd_str:
                await _log_cb(f"[playtest] cmd: {cmd_str}")
                await _log_cb(
                    f"[playtest] exit={data.get('exit_code')} "
                    f"duration={data.get('duration_ms', 0)}ms"
                )
        except Exception as e:
            logger.exception("run-playtest 后台异常")
            data = {
                "status": "error",
                "message": f"Action 异常: {e}",
                "tests": [],
                "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            }

        try:
            await event_manager.publish_to_project(
                project_id, "ue_playtest_result",
                {
                    "status": data.get("status"),
                    "exit_code": data.get("exit_code"),
                    "duration_ms": data.get("duration_ms"),
                    "summary": data.get("summary"),
                    "tests": (data.get("tests") or [])[:20],
                    "screenshots": (data.get("screenshots") or [])[:10],
                    "message": data.get("message"),
                    "command": data.get("command"),
                },
            )
        except Exception:
            pass

    asyncio.create_task(_run_bg())
    return {"status": "started", "message": "Playtest 已在后台启动，请看实时日志"}


# ==================== v0.20 UCP 编辑态 MCP ====================

@router.get("/editor-status")
async def get_editor_status(project_id: str):
    """探测 UE Editor 是否运行 + UCP 插件是否可达（9876 端口）"""
    from actions.ue_editor_control import probe_ucp
    host, port = "127.0.0.1", 9876
    connected = await probe_ucp(host, port, timeout=2.0)
    return {
        "connected": connected,
        "host": host,
        "port": port,
        "hint": (
            "UE Editor 已连接，编辑态 AI 控制可用"
            if connected
            else "Editor 未开启或 UCP 插件未启用 —— 请打开 UE Editor 并确认 UnrealClientProtocol 插件已加载"
        ),
    }


@router.post("/editor-control")
async def editor_control(project_id: str, body: Dict[str, Any]):
    """直接调用 UCP 操作（调试 / ChatAssistant 工具调用入口）"""
    from actions.ue_editor_control import UEEditorControlAction
    project = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")
    ctx = {"project_id": project_id, **body}
    result = await UEEditorControlAction().run(ctx)
    return {"success": result.success, "data": result.data, "message": result.message}


@router.post("/editor-launch")
async def editor_launch(project_id: str):
    """启动 UE Editor（后台进程，不阻塞）+ SSE 推启动进度"""
    import asyncio, subprocess as _sp
    from engines.ue_resolver import resolve_project_engine
    from git_manager import git_manager
    from events import event_manager
    from utils import now_iso

    project = await db.fetch_one("SELECT id, ue_engine_path FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    # 找 .uproject 路径
    repo_path = git_manager._repo_path(project_id)
    uproject = None
    if repo_path:
        from pathlib import Path as _P
        found = sorted(_P(repo_path).glob("*.uproject"))
        if found:
            uproject = str(found[0])
    if not uproject:
        raise HTTPException(400, "找不到 .uproject 文件，请先生成 UE 框架")

    # 解析引擎
    engine_info = resolve_project_engine(uproject)
    if not engine_info or not engine_info.path:
        raise HTTPException(400, "找不到 UE 引擎，请在项目设置里配置 ue_engine_path")

    from pathlib import Path as _P
    editor_exe = _P(engine_info.path) / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
    if not editor_exe.is_file():
        raise HTTPException(400, f"找不到 UnrealEditor.exe: {editor_exe}")

    async def _push_log(msg: str):
        try:
            await event_manager.publish_to_project(project_id, "log_added", {
                "id": f"ue-editor-{now_iso()}",
                "agent_type": "UE-Editor",
                "action": "editor_launch",
                "level": "info",
                "detail": msg,
                "created_at": now_iso(),
            })
        except Exception:
            pass

    # 后台启动，不等待返回（Editor 是长驻进程）
    try:
        _sp.Popen(
            [str(editor_exe), uproject],
            creationflags=_sp.CREATE_NEW_PROCESS_GROUP if hasattr(_sp, 'CREATE_NEW_PROCESS_GROUP') else 0,
        )
    except Exception as e:
        raise HTTPException(500, f"启动 Editor 失败: {e}")

    await _push_log(f"[editor] 正在启动 UE Editor: {editor_exe.name} {_P(uproject).name}")
    await _push_log(f"[editor] 引擎版本: UE {engine_info.version} [{engine_info.type}]")
    await _push_log("[editor] 首次加载约 30-120 秒（shader 编译），请耐心等待…")

    # 后台轮询 UCP，连上后推通知
    asyncio.create_task(_poll_ucp_ready(project_id, _push_log))

    return {
        "status": "launching",
        "uproject": uproject,
        "engine": engine_info.path,
        "hint": "UE Editor 正在启动，首次加载约 30-120 秒，日志面板会实时更新状态",
    }


async def _poll_ucp_ready(project_id: str, push_log):
    """后台轮询 UCP 9876 端口，就绪后推通知并刷新环境状态"""
    import asyncio
    from actions.ue_editor_control import probe_ucp
    from events import event_manager

    await asyncio.sleep(10)  # 等 Editor 初始化
    for i in range(24):  # 最多等 2 分钟（24 × 5s）
        await asyncio.sleep(5)
        if await probe_ucp(timeout=2.0):
            await push_log("✅ [editor] UE Editor 已就绪！UCP 插件已连接（9876），编辑态 AI 控制可用")
            try:
                await event_manager.publish_to_project(project_id, "ue_editor_connected", {
                    "connected": True,
                    "hint": "UE Editor 已就绪，UCP 编辑态控制可用",
                })
            except Exception:
                pass
            return
        if i % 3 == 2:  # 每 15 秒报一次进度
            elapsed = (i + 1) * 5 + 10
            await push_log(f"[editor] 等待 Editor 加载… ({elapsed}s)")

    await push_log("⚠️ [editor] 超时未检测到 UCP 连接（2 分钟），请确认 UnrealClientProtocol 插件已启用")
