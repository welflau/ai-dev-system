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
from typing import Any, Dict

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
        from git_manager import git_manager

        name = (context.get("name") or "").strip()
        description = (context.get("description") or "").strip()
        tech_stack = (context.get("tech_stack") or "").strip()
        git_remote_url = (context.get("git_remote_url") or "").strip()
        local_repo_path = (context.get("local_repo_path") or "").strip()

        if not name:
            return ActionResult(success=False, data={"type": "error", "message": "项目名称不能为空"})
        if not git_remote_url:
            return ActionResult(success=False, data={"type": "error", "message": "Git 远程仓库 URL 不能为空"})

        try:
            project_id = generate_id("PRJ")
            now = now_iso()

            # 确定本地仓库路径
            if local_repo_path:
                repo_path = os.path.abspath(local_repo_path)
                git_manager.set_project_path(project_id, repo_path)
            else:
                repo_path = str(git_manager._repo_path(project_id))

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
                "created_at": now,
                "updated_at": now,
            }
            await db.insert("projects", proj_data)

            logger.info("AI助手创建项目完成: %s (%s)", name, project_id)

            # 异步生成初版 Roadmap（fire-and-forget）
            from api.milestones import generate_roadmap_for_project
            asyncio.create_task(generate_roadmap_for_project(project_id, name, description))

            return ActionResult(
                success=True,
                data={
                    "type": "project_created",
                    "project_id": project_id,
                    "name": name,
                    "description": description,
                    "tech_stack": tech_stack,
                    "git_remote_url": git_remote_url,
                    "push_success": push_success,
                    "message": f"项目「{name}」已创建成功" + ("，并已推送到远程仓库" if push_success else "（首次推送失败，请检查远程仓库权限）"),
                },
            )

        except Exception as e:
            logger.error("AI助手创建项目失败: %s", e)
            return ActionResult(
                success=False,
                data={"type": "error", "message": f"创建项目失败: {str(e)}"},
            )
