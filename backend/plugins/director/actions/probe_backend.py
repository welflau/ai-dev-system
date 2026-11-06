"""探测 LightAI / LibTV / dreamina，不静默切换。"""
from __future__ import annotations

from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from plugins.director.backends import probe_backend, resolve_backend


class ProbeBackendAction(ActionBase):
    available_for_traits = {"any_of": ["category:video", "pipeline:video"]}

    @property
    def name(self) -> str:
        return "probe_backend"

    @property
    def description(self) -> str:
        return (
            "探测当前视频后端是否可用（Key 或 CLI）。"
            "指定 backend 时只查该后端，不可用就停，不要改打别的后端。"
        )

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "backend": {
                        "type": "string",
                        "description": "lightai / libtv / dreamina；缺省按简报或 lightai",
                    },
                },
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        backend, source = resolve_backend(context)
        probe = probe_backend(backend)
        command = probe.command
        try:
            from command_log import record_traced_command
            task_id = await record_traced_command(
                source="director",
                tool="probe_backend",
                command=command,
                cwd=str(context.get("repo_path") or ""),
                status="success" if probe.available else "error",
                ticket_id=str(context.get("ticket_id") or ""),
                requirement_id=str(context.get("requirement_id") or ""),
                project_id=str(context.get("project_id") or ""),
                agent_type=str(context.get("agent_type") or "SkillAgent"),
            )
        except Exception:
            task_id = ""
        data = {
            "backend": probe.backend,
            "source": source,
            "available": probe.available,
            "binary": probe.binary,
            "hint": probe.hint,
            "command": command,
            "task_id": task_id,
            "env_missing": not probe.available,
        }
        if probe.available:
            return ActionResult(success=True, data=data, message=f"后端 {probe.backend} 可用")
        return ActionResult(
            success=False,
            error=probe.hint or f"后端 {probe.backend} 不可用",
            data=data,
        )
