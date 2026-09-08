"""
InstallUCPAction — AI 对话中为当前 UE 项目部署 UnrealClientProtocol 插件

当用户说「安装 UCP」「部署 UnrealClientProtocol」「Editor 连不上帮我装插件」时调用。
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.install_ucp")


class InstallUCPAction(ActionBase):

    available_for_traits = {"any_of": ["engine:ue5", "engine:ue4"]}
    expose_for_ue_repo = True  # traits 未标 UE 但目录有 .uproject 时也暴露

    @property
    def name(self) -> str:
        return "install_ucp"

    @property
    def description(self) -> str:
        return "为当前 UE 项目部署 UnrealClientProtocol (UCP) 插件"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "为当前 UE 项目把 ADS 内置的 UnrealClientProtocol (UCP) 插件复制到 "
                "Plugins/UnrealClientProtocol。\n"
                "适用：ue_call / launch_ue_editor 连不上 Editor、用户要求安装 UCP、"
                "或需确认插件是否已部署。\n"
                "部署后需重启 UE Editor 并完成插件编译；Edit → Plugins 中确认已启用。\n"
                "先用 action=status 检查，再用 action=install 安装或更新。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "install"],
                        "description": "status=检查是否已安装；install=复制/更新 UCP 到 Plugins/",
                    },
                },
                "required": ["action"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        action = (context.get("action") or "status").strip().lower()
        project_id = context.get("project_id")

        if not project_id:
            return ActionResult(success=False, error="需要在项目内使用此工具")

        repo_path, traits = await _get_project_repo_and_traits(project_id)
        if not repo_path:
            return ActionResult(success=False, error="项目未配置本地仓库路径")

        from ue_ucp_deploy import deploy_ucp_to_project, is_ucp_installed, is_ue_project_path

        if not is_ue_project_path(repo_path, traits):
            return ActionResult(
                success=False,
                error="当前项目不是 UE 工程（无 engine:ue* trait 且无 .uproject）",
            )

        if action == "status":
            installed = is_ucp_installed(repo_path)
            dest = str(Path(repo_path) / "Plugins" / "UnrealClientProtocol")
            return ActionResult(
                success=True,
                data={
                    "type": "ucp_status",
                    "installed": installed,
                    "path": dest if installed else None,
                    "repo_path": repo_path,
                },
                message=(
                    "UCP 插件已安装在 Plugins/UnrealClientProtocol"
                    if installed
                    else "UCP 插件尚未安装，可调用 action=install 部署"
                ),
            )

        if action == "install":
            was_installed = is_ucp_installed(repo_path)
            result = deploy_ucp_to_project(repo_path)
            data = {
                "type": "ucp_installed",
                "already_installed": was_installed and result.get("installed"),
                **result,
            }
            if result.get("installed"):
                msg = result.get("message") or "UCP 插件已部署"
                if was_installed:
                    msg = "UCP 插件已更新（Plugins/UnrealClientProtocol）。请重启 Editor 完成编译"
                logger.info("project=%s chat-installed UCP: %s", project_id, repo_path)
                return ActionResult(success=True, data=data, message=f"✅ {msg}")
            return ActionResult(
                success=False,
                data=data,
                error=result.get("message") or "UCP 部署失败",
            )

        return ActionResult(success=False, error=f"未知 action: {action}")


async def _get_project_repo_and_traits(project_id: str) -> Tuple[Optional[str], List[str]]:
    try:
        from database import db
        row = await db.fetch_one(
            "SELECT git_repo_path, traits FROM projects WHERE id = ?",
            (project_id,),
        )
        if not row:
            return None, []
        repo_path = (row.get("git_repo_path") or "").strip() or None
        traits_raw = row.get("traits") or "[]"
        if isinstance(traits_raw, str):
            traits = json.loads(traits_raw) or []
        elif isinstance(traits_raw, list):
            traits = list(traits_raw)
        else:
            traits = []
        return repo_path, [str(t) for t in traits]
    except Exception as e:
        logger.warning("_get_project_repo_and_traits failed: %s", e)
        return None, []
