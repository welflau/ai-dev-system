"""VideoClaw 项目最小闭环：探活 → 动态取模型 → 创建项目 → 推进一阶段 → 查状态。

设计约束（docs/20261023_01_插件套件准入规范与五道约束.md）：
- 环境缺失（未启用 / 服务没起 / 缺 Key）→ success=False + env_missing=True，
  让 Orchestrator 转 blocked；**绝不返回 *_failed**，否则会错误触发 DevAgent 返工。
- 外部命令一律走 record_traced_command 落时间轴，data["command"] 必须是 str。
- Action 名加 vc_ 前缀：registry.py 全局 name 唯一，重名会静默覆盖并告警。
"""
from __future__ import annotations

import logging
import shlex
from typing import Any, Dict, Optional

from actions.base import ActionBase, ActionResult
from config import settings

from plugins.videoclaw import videoclaw_client as vc

logger = logging.getLogger("plugins.videoclaw.vc_project")


class VCRunProjectAction(ActionBase):
    available_for_traits = {"any_of": ["category:video", "pipeline:video"]}

    @property
    def name(self) -> str:
        return "vc_run_project"

    @property
    def description(self) -> str:
        return (
            "对独立 VideoClaw sidecar 跑一次最小闭环：探活、从 /api/config 动态读模型、"
            "创建项目、推进工作流、查询状态。缺 VIDEOCLAW_ENABLED 或服务未起时返回 "
            "env_missing → blocked，不要改业务代码。"
        )

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "idea": {"type": "string", "description": "视频创意/主题"},
                    "session_id": {"type": "string", "description": "已有会话则跳过创建、直接推进"},
                    "episodes": {"type": "integer", "description": "验证期建议 1，默认 1"},
                },
            },
        }

    @staticmethod
    async def _trace(context: Dict[str, Any], command: str, status: str) -> str:
        try:
            from command_log import record_traced_command
            return await record_traced_command(
                source="videoclaw",
                tool="vc_run_project",
                command=command,
                status=status,
                ticket_id=str(context.get("ticket_id") or ""),
                requirement_id=str(context.get("requirement_id") or ""),
                project_id=str(context.get("project_id") or ""),
                agent_type=str(context.get("agent_type") or "SkillAgent"),
            )
        except Exception as e:
            logger.debug("record_traced_command 跳过: %s", e)
            return ""

    def _command(self, idea: str, episodes: int, session_id: str) -> str:
        # shlex.quote 保证 data["command"] 是单个 str，绝不塞 List[str]
        return (
            f"vc_run_project idea={shlex.quote(idea)} "
            f"episodes={episodes} session={shlex.quote(session_id or '-')}"
        )

    @staticmethod
    def _blocked(command: str, task_id: str, error: str) -> ActionResult:
        return ActionResult(
            success=False,
            error=error,
            data={
                "env_missing": True,
                "command": command,
                "task_id": task_id,
                "scope": "videoclaw",
            },
        )

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        idea = str(context.get("idea") or "").strip()
        session_id = str(context.get("session_id") or "").strip()
        try:
            episodes = max(1, min(int(context.get("episodes") or 1), 4))
        except (TypeError, ValueError):
            episodes = 1
        command = self._command(idea, episodes, session_id)

        if not settings.VIDEOCLAW_ENABLED:
            return self._blocked(command, "", "VIDEOCLAW_ENABLED=false，VideoClaw sidecar 未启用")
        if not await vc.health():
            task_id = await self._trace(context, command, "error")
            return self._blocked(command, task_id, f"VideoClaw sidecar 不可达 {settings.VIDEOCLAW_BASE_URL}，请先启动服务")

        try:
            cfg = await vc.get_config()
            if not session_id:
                started = await vc.start_project(cfg, idea=idea or "一段测试短片", episodes=episodes)
                session_id = str(started.get("session_id") or "")
                if not session_id:
                    raise vc.VideoClawError(f"POST /api/project/start 未返回 session_id: {started}")
            advanced = await vc.continue_workflow(session_id)
            status = await vc.get_status(session_id)
        except vc.VideoClawUnavailable as e:
            task_id = await self._trace(context, command, "error")
            return self._blocked(command, task_id, str(e))
        except vc.VideoClawError as e:
            task_id = await self._trace(context, command, "error")
            return ActionResult(
                success=False,
                error=str(e),
                data={
                    "env_missing": False,
                    "command": command,
                    "task_id": task_id,
                    "session_id": session_id,
                },
            )

        task_id = await self._trace(context, command, "success")
        return ActionResult(
            success=True,
            data={
                "env_missing": False,
                "command": command,
                "task_id": task_id,
                "session_id": session_id,
                "base_url": settings.VIDEOCLAW_BASE_URL,
                "models": {k: v for k, v in cfg.get("models", {}).items() if isinstance(v, str)},
                "advanced": advanced if isinstance(advanced, dict) else {},
                # 不能叫 status：ActionResult.to_dict() 把 data 展开到顶层，
                # 同名会覆盖结果自身的 status，导致成功被误读成 VC 的阶段态。
                "vc_status": status if isinstance(status, dict) else {},
            },
            message=f"VideoClaw 项目 {session_id} 已创建并推进（episodes={episodes}）",
        )
