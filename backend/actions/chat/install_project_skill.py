"""
InstallProjectSkillAction — AI 对话中为当前项目安装 / 卸载 Marketplace Skill

供 ChatAssistant 在对话里处理类似
"帮我安装联网搜索 skill"、"把 multi-search-engine 加进来" 的用户意图。
"""
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.install_project_skill")


class InstallProjectSkillAction(ActionBase):

    @property
    def name(self) -> str:
        return "install_project_skill"

    @property
    def description(self) -> str:
        return "为当前项目安装或卸载 Marketplace Skill"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "为当前项目安装或移除 Marketplace Skill。"
                "当用户说「安装/添加 xxx skill」「帮我加上联网搜索」「把 yyy 技能加进来」时调用。\n"
                "先用 action=list 列出可用 Skill，再用 action=install 安装指定 Skill。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "install", "uninstall"],
                        "description": "list=查看可用 Skill；install=安装；uninstall=卸载",
                    },
                    "dir_name": {
                        "type": "string",
                        "description": "Skill 目录名（action=install/uninstall 时必填），如 multi-search-engine",
                    },
                },
                "required": ["action"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        action    = context.get("action", "list")
        dir_name  = (context.get("dir_name") or "").strip()
        project_id = context.get("project_id")

        if not project_id:
            return ActionResult(success=False, error="需要在项目内使用此工具")

        if action == "list":
            return await self._list(project_id)
        elif action == "install":
            if not dir_name:
                return ActionResult(success=False, error="请指定要安装的 Skill 目录名（dir_name）")
            return await self._install(project_id, dir_name)
        elif action == "uninstall":
            if not dir_name:
                return ActionResult(success=False, error="请指定要卸载的 Skill 目录名（dir_name）")
            return await self._uninstall(project_id, dir_name)
        else:
            return ActionResult(success=False, error=f"未知 action: {action}")

    async def _list(self, project_id: str) -> ActionResult:
        from pathlib import Path
        from actions.chat.load_skill import _get_project_agent_skills_dir

        marketplace_dir = Path(__file__).parent.parent.parent / "skills" / "marketplace"
        if not marketplace_dir.exists():
            return ActionResult(success=True, data={"type": "skill_list", "skills": [], "message": "marketplace 目录不存在"})

        agent_dir = await _get_project_agent_skills_dir(project_id)
        installed = {p.name for p in agent_dir.iterdir() if p.is_dir()} if agent_dir.exists() else set()

        skills = []
        for skill_dir in sorted(marketplace_dir.iterdir()):
            if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
                continue
            skills.append({
                "dir_name": skill_dir.name,
                "installed": skill_dir.name in installed,
            })

        return ActionResult(
            success=True,
            data={"type": "skill_list", "skills": skills},
            message=f"marketplace 共 {len(skills)} 个 Skill，已安装 {len(installed)} 个",
        )

    async def _install(self, project_id: str, dir_name: str) -> ActionResult:
        import shutil
        from pathlib import Path
        from actions.chat.load_skill import _get_project_agent_skills_dir

        marketplace_dir = Path(__file__).parent.parent.parent / "skills" / "marketplace"
        src = marketplace_dir / dir_name
        if not src.exists() or not (src / "SKILL.md").exists():
            return ActionResult(success=False, error=f"marketplace 中找不到 Skill: {dir_name}")

        agent_dir = await _get_project_agent_skills_dir(project_id)
        agent_dir.mkdir(parents=True, exist_ok=True)
        dst = agent_dir / dir_name

        if dst.exists():
            return ActionResult(
                success=True,
                data={"type": "skill_installed", "dir_name": dir_name, "already_installed": True},
                message=f"Skill「{dir_name}」已安装",
            )

        shutil.copytree(str(src), str(dst))
        logger.info("project=%s chat-installed skill: %s", project_id, dir_name)
        return ActionResult(
            success=True,
            data={"type": "skill_installed", "dir_name": dir_name},
            message=f"✅ 已为项目安装 Skill「{dir_name}」，AI 助手现在可以使用它了",
        )

    async def _uninstall(self, project_id: str, dir_name: str) -> ActionResult:
        import shutil
        from actions.chat.load_skill import _get_project_agent_skills_dir

        agent_dir = await _get_project_agent_skills_dir(project_id)
        dst = agent_dir / dir_name
        if not dst.exists():
            return ActionResult(success=False, error=f"项目中未安装 Skill: {dir_name}")

        shutil.rmtree(str(dst))
        logger.info("project=%s chat-uninstalled skill: %s", project_id, dir_name)
        return ActionResult(
            success=True,
            data={"type": "skill_uninstalled", "dir_name": dir_name},
            message=f"已移除 Skill「{dir_name}」",
        )
