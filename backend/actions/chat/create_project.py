"""
CreateProjectAction — 真正创建项目（clone/init Git + 写库 + 异步跑 roadmap）

与 ConfirmProjectAction 的区别：
- ConfirmProjectAction 只生成草稿卡片，不碰 Git、不碰数据库
- CreateProjectAction 直接 Git clone/init + INSERT projects + 调度 roadmap 生成

调用来源（P1 迁移期）：
1. 旧 [ACTION:CREATE_PROJECT] 路径（chat.py:_execute_create_project wrapper 调用）
2. P2 新增的 /api/chat/confirm-create-project 端点（用户确认后）

不对 LLM 暴露为 tool —— LLM 只应调用 confirm_project 产草稿让用户审核。
"""
import asyncio
import logging
import os
import re
from typing import Any, Dict, Optional

from actions.base import ActionBase, ActionResult
from database import db
from utils import generate_id, now_iso

logger = logging.getLogger("actions.chat.create_project")


class CreateProjectAction(ActionBase):

    @property
    def name(self) -> str:
        return "create_project"

    @property
    def description(self) -> str:
        return "真正创建项目：Git clone/init + INSERT projects + 异步跑 roadmap 生成"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        # 内部 Action，不对 LLM 暴露；ChatAssistantAgent 只注册 confirm_project。
        # 此 schema 保留只是为了接口一致，P2 接入 tool_use 时会从 action_classes 里排除本项。
        return {
            "name": self.name,
            "description": "（内部用）实际落库创建项目——LLM 不应直接调用，应通过 confirm_project 让用户确认。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "tech_stack": {"type": "string"},
                    "git_remote_url": {"type": "string"},
                    "local_repo_path": {"type": "string"},
                },
                "required": ["name", "git_remote_url"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        import json as _json
        from git_manager import git_manager

        name = (context.get("name") or "").strip()
        description = (context.get("description") or "").strip()
        tech_stack = (context.get("tech_stack") or "").strip()
        git_remote_url = (context.get("git_remote_url") or "").strip()
        local_repo_path = (context.get("local_repo_path") or "").strip()

        # v0.17 traits 字段：
        #   traits: List[str]，可空（向后兼容，但会打 warning）
        #   preset_id: Optional[str]
        #   traits_confidence: Dict，默认记用户来源
        traits = context.get("traits") or []
        if not isinstance(traits, list):
            traits = []
        traits = [str(t).strip() for t in traits if str(t).strip()]
        preset_id = (context.get("preset_id") or "").strip() or None

        # traits_confidence：如果是用户确认的（从 confirm_project 过来），全部 source=user_declared
        traits_confidence = context.get("traits_confidence") or {
            t: {"score": 1.0, "source": "user_declared" if preset_id is None else "preset",
                "evidence": f"preset:{preset_id}" if preset_id else "user confirmed in chat"}
            for t in traits
        }

        if not name:
            return ActionResult(success=False, data={"type": "error", "message": "项目名称不能为空"})
        if not git_remote_url:
            return ActionResult(success=False, data={"type": "error", "message": "Git 远程仓库 URL 不能为空"})
        if not traits:
            logger.warning("创建项目 '%s' 时 traits 为空 — 后续 skill/SOP 匹配会退化为通用流程", name)

        try:
            project_id = generate_id("PRJ")
            now = now_iso()

            # 确定本地仓库路径
            if local_repo_path:
                repo_path = os.path.abspath(local_repo_path)
            else:
                # 使用系统设置的默认项目目录（无则退回 backend/projects/）
                try:
                    from api.system_settings import get_setting
                    default_dir = await get_setting("projects_default_dir")
                except Exception:
                    default_dir = ""
                if default_dir:
                    import pathlib
                    safe_name = re.sub(r'[<>:"/\\|?*]', '-', name).strip()
                    repo_path = str(pathlib.Path(default_dir) / safe_name)
                else:
                    repo_path = str(git_manager._repo_path(project_id))
            git_manager.set_project_path(project_id, repo_path)

            logger.info("AI助手创建项目: %s, 仓库路径: %s", name, repo_path)

            git_dir = os.path.join(repo_path, ".git")
            cloned = False
            push_success = False

            if git_remote_url and not os.path.isdir(git_dir):
                # 远程仓库 + 本地无 .git：尝试 clone
                if os.path.isdir(repo_path) and os.listdir(repo_path):
                    # 目录非空但无 .git，init + fetch + reset
                    logger.info("目录非空但无 .git，执行 init + fetch + reset")
                    await git_manager._run_git(repo_path, "init", "-b", "main")
                    git_manager.set_project_path(project_id, repo_path)
                    await git_manager.set_remote(project_id, git_remote_url)
                    await git_manager._run_git(repo_path, "fetch", "origin")
                    # 检测远程默认分支
                    rc, refs, _ = await git_manager._run_git(repo_path, "ls-remote", "--symref", "origin", "HEAD")
                    remote_branch = "main"
                    if "refs/heads/" in refs:
                        for line in refs.splitlines():
                            if "ref:" in line and "refs/heads/" in line:
                                remote_branch = line.split("refs/heads/")[-1].split()[0]
                                break
                    await git_manager._run_git(repo_path, "reset", "--mixed", f"origin/{remote_branch}")
                    await git_manager._run_git(repo_path, "checkout", ".")
                    cloned = True
                else:
                    # 目录为空或不存在：直接 clone
                    if os.path.isdir(repo_path):
                        try:
                            os.rmdir(repo_path)
                        except OSError:
                            pass
                    cloned = await git_manager.clone(git_remote_url, repo_path)
                    if cloned:
                        logger.info("clone 成功，使用远程仓库内容")
                        git_manager.set_project_path(project_id, repo_path)
                    else:
                        logger.warning("clone 失败，回退到本地初始化")
                        os.makedirs(repo_path, exist_ok=True)

            if not cloned:
                # 本地初始化流程
                os.makedirs(repo_path, exist_ok=True)
                for d in git_manager.REPO_DIRS:
                    os.makedirs(os.path.join(repo_path, d), exist_ok=True)

                readme = f"# {name}\n\n{description or '由 AI 自动开发系统创建的项目'}\n"
                readme_path = os.path.join(repo_path, "README.md")
                if not os.path.exists(readme_path):
                    with open(readme_path, "w", encoding="utf-8") as f:
                        f.write(readme)

                gitignore = "__pycache__/\n*.py[cod]\n.venv/\nvenv/\n.idea/\n.vscode/\n.DS_Store\nThumbs.db\n.env\n*.log\n"
                gitignore_path = os.path.join(repo_path, ".gitignore")
                if not os.path.exists(gitignore_path):
                    with open(gitignore_path, "w", encoding="utf-8") as f:
                        f.write(gitignore)

                if not os.path.isdir(git_dir):
                    await git_manager._run_git(repo_path, "init", "-b", "main")

                if git_remote_url:
                    await git_manager.set_remote(project_id, git_remote_url)

                await git_manager._run_git(repo_path, "add", ".")
                await git_manager._run_git(
                    repo_path, "commit", "-m",
                    f"init: {name} - project initialized by AI Dev System",
                    "--author", "AI Dev System <ai@dev-system.local>",
                )

                try:
                    push_success = await git_manager.push(project_id)
                except Exception as e:
                    logger.warning("AI助手创建项目首次推送失败: %s", e)

            # 写入数据库
            proj_data = {
                "id": project_id,
                "name": name,
                "description": description,
                "status": "active",
                "tech_stack": tech_stack,
                "config": "{}",
                "git_repo_path": repo_path,
                "git_remote_url": git_remote_url,
                "traits": _json.dumps(traits, ensure_ascii=False),
                "traits_confidence": _json.dumps(traits_confidence, ensure_ascii=False),
                "preset_id": preset_id,
                "created_at": now,
                "updated_at": now,
            }
            await db.insert("projects", proj_data)

            logger.info("AI助手创建项目完成: %s (%s)", name, project_id)

            # 异步生成初版 Roadmap（fire-and-forget）
            from api.milestones import generate_roadmap_for_project
            asyncio.create_task(generate_roadmap_for_project(project_id, name, description))

            # 自动安装 marketplace Skill（基于 traits 规则匹配，fire-and-forget）
            asyncio.create_task(_auto_install_skills(project_id, traits))

            # v0.19.1 对话一键流：UE 项目自动弹 propose 方案卡，持久化到项目聊天
            # 前端跳转到项目详情后，loadChatHistory 自然能拿到这条消息，无需前端再串 API。
            auto_next: Optional[Dict[str, Any]] = None
            is_ue_project = any(t.startswith("engine:ue") for t in traits)
            if is_ue_project:
                try:
                    from actions.chat.propose_ue_framework import ProposeUEFrameworkAction
                    from api.chat import _save_chat_message

                    propose_result = await ProposeUEFrameworkAction().run({
                        "project_id": project_id,
                    })
                    if propose_result.success:
                        intro = (
                            "✨ 检测到这是 UE 项目，已自动为你生成了框架方案。"
                            "请在下方卡片里确认引擎和模板后点「确认生成」。"
                        )
                        await _save_chat_message(
                            project_id=project_id,
                            role="assistant",
                            content=intro,
                            action=propose_result.data,
                        )
                        auto_next = {
                            "type": "propose_ue_framework",
                            "project_id": project_id,
                            "persisted": True,
                            "reason": "UE 项目 onboarding：propose 卡片已持久化到项目聊天",
                        }
                    else:
                        logger.warning(
                            "UE auto-propose failed for %s: %s",
                            project_id, propose_result.error or "unknown",
                        )
                except Exception as e:
                    logger.warning("UE auto-propose 异常: %s", e)

            data = {
                "type": "project_created",
                "project_id": project_id,
                "name": name,
                "description": description,
                "tech_stack": tech_stack,
                "git_remote_url": git_remote_url,
                "traits": traits,
                "preset_id": preset_id,
                "push_success": push_success,
                "message": f"项目「{name}」已创建成功" + ("，并已推送到远程仓库" if push_success else "（首次推送失败，请检查远程仓库权限）"),
            }
            if auto_next:
                data["auto_next"] = auto_next

            return ActionResult(success=True, data=data)

        except Exception as e:
            logger.error("AI助手创建项目失败: %s", e)
            return ActionResult(
                success=False,
                data={"type": "error", "message": f"创建项目失败: {str(e)}"},
            )


# traits → marketplace skill 映射规则
_TRAIT_SKILL_MAP = {
    "engine:ue5":        ["unreal-cpp-dev", "unreal-editor-control"],
    "engine:ue4":        ["unreal-cpp-dev"],
    "framework:react":   ["react-dev"],
    "framework:fastapi": ["fastapi-dev"],
    "platform:web":      ["multi-search-engine"],
    "platform:wechat":   ["multi-search-engine"],
    "vcs:git":           ["git-workflow"],
}


async def _auto_install_skills(project_id: str, traits: list) -> None:
    """根据 traits 自动把匹配的 marketplace Skill 安装到项目 .Agent/skills/。"""
    import shutil
    from pathlib import Path

    marketplace_dir = Path(__file__).parent.parent.parent / "skills" / "marketplace"
    if not marketplace_dir.exists():
        return

    # 收集需要安装的 skill dir_names（去重）
    to_install: set = set()
    for trait in (traits or []):
        for skill_name in _TRAIT_SKILL_MAP.get(trait, []):
            src = marketplace_dir / skill_name
            if src.exists() and (src / "SKILL.md").exists():
                to_install.add(skill_name)

    if not to_install:
        return

    try:
        from actions.chat.load_skill import _get_project_agent_skills_dir
        agent_dir = await _get_project_agent_skills_dir(project_id)
        agent_dir.mkdir(parents=True, exist_ok=True)

        installed = []
        for skill_name in sorted(to_install):
            dst = agent_dir / skill_name
            if dst.exists():
                continue
            # 支持子文件夹：递归查找
            src = None
            for skill_md in marketplace_dir.rglob("SKILL.md"):
                if skill_md.parent.name == skill_name:
                    src = skill_md.parent
                    break
            if not src:
                logger.warning("auto-install: skill not found in marketplace: %s", skill_name)
                continue
            try:
                shutil.copytree(str(src), str(dst))
                installed.append(skill_name)
            except Exception as e:
                logger.warning("auto-install skill %s failed: %s", skill_name, e)

        if installed:
            logger.info("project=%s auto-installed skills: %s", project_id, installed)
    except Exception as e:
        logger.warning("_auto_install_skills failed for %s: %s", project_id, e)
