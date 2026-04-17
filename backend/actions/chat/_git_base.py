"""
Git Action 共享工具 —— 所有 GitXxxAction 的仓库探测/恢复逻辑都相同，抽在此处
"""
from typing import Optional, Tuple
from actions.base import ActionResult
from database import db


async def ensure_git_ready(project_id: str) -> Tuple[bool, Optional[ActionResult]]:
    """
    确保项目存在、Git 仓库就绪（含恢复自定义仓库路径）。
    返回 (ready, error_result)：ready=True 时 error_result 是 None。
    """
    from git_manager import git_manager

    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        return False, ActionResult(
            success=False,
            data={"type": "error", "message": "项目不存在"},
        )

    # 恢复自定义仓库路径
    repo_path = project.get("git_repo_path")
    if repo_path and project_id not in git_manager._custom_paths:
        from git_manager import PROJECTS_DIR
        if repo_path != str(PROJECTS_DIR / project_id):
            git_manager.set_project_path(project_id, repo_path)

    if not git_manager.repo_exists(project_id):
        return False, ActionResult(
            success=False,
            data={"type": "error", "message": "仓库不存在"},
        )

    return True, None
