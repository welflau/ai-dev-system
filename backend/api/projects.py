"""
AI 自动开发系统 - 项目 API
"""
import json
import logging
from fastapi import APIRouter, HTTPException
from database import db
from models import ProjectCreate, ProjectUpdate
from utils import generate_id, now_iso
from git_manager import git_manager

logger = logging.getLogger("api.projects")

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _ensure_git_path(project: dict):
    """确保 git_manager 中有项目的自定义路径映射（防止重启后丢失）"""
    repo_path = project.get("git_repo_path")
    if repo_path and project["id"] not in git_manager._custom_paths:
        from git_manager import PROJECTS_DIR
        default_path = str(PROJECTS_DIR / project["id"])
        if repo_path != default_path:
            git_manager.set_project_path(project["id"], repo_path)
            logger.debug("恢复项目 %s 的仓库路径: %s", project["id"], repo_path)


@router.post("")
async def create_project(req: ProjectCreate):
    """创建项目"""
    import os
    import traceback
    from api.milestones import generate_roadmap_for_project
    import asyncio

    try:
        project_id = generate_id("PRJ")
        now = now_iso()

        # 确定本地仓库路径
        if req.local_repo_path:
            repo_path = os.path.abspath(req.local_repo_path)
            git_manager.set_project_path(project_id, repo_path)
        else:
            repo_path = str(git_manager._repo_path(project_id))

        # 创建目录结构
        logger.info("创建项目: %s, 仓库路径: %s", req.name, repo_path)
        os.makedirs(repo_path, exist_ok=True)
        for d in git_manager.REPO_DIRS:
            os.makedirs(os.path.join(repo_path, d), exist_ok=True)

        # 生成 README.md
        readme = f"# {req.name}\n\n{req.description or '由 AI 自动开发系统创建的项目'}\n"
        readme_path = os.path.join(repo_path, "README.md")
        if not os.path.exists(readme_path):
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(readme)

        # 生成 .gitignore
        gitignore = "__pycache__/\n*.py[cod]\n.venv/\nvenv/\n.idea/\n.vscode/\n.DS_Store\nThumbs.db\n.env\n*.log\n"
        gitignore_path = os.path.join(repo_path, ".gitignore")
        if not os.path.exists(gitignore_path):
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.write(gitignore)

        # git init（如果还没有 .git 目录）
        git_dir = os.path.join(repo_path, ".git")
        if not os.path.isdir(git_dir):
            rc, out, err = await git_manager._run_git(repo_path, "init")
            logger.info("git init: rc=%d", rc)

        # 配置远程仓库
        if req.git_remote_url:
            await git_manager.set_remote(project_id, req.git_remote_url)
            logger.info("远程仓库已设置: %s", req.git_remote_url)

        # 初始提交
        await git_manager._run_git(repo_path, "add", ".")
        rc, out, err = await git_manager._run_git(
            repo_path, "commit", "-m",
            f"init: {req.name} - project initialized by AI Dev System",
            "--author", "AI Dev System <ai@dev-system.local>",
        )
        logger.info("git commit: rc=%d", rc)

        # 尝试首次推送（允许失败）
        push_success = False
        try:
            push_success = await git_manager.push(project_id)
        except Exception as e:
            logger.warning("首次推送失败（忽略）: %s", e)

        data = {
            "id": project_id,
            "name": req.name,
            "description": req.description or "",
            "status": "active",
            "tech_stack": req.tech_stack or "",
            "config": "{}",
            "git_repo_path": repo_path,
            "git_remote_url": req.git_remote_url or "",
            "created_at": now,
            "updated_at": now,
        }
        await db.insert("projects", data)

        logger.info("项目创建完成: %s (%s)", req.name, project_id)

        # 异步生成初版 Roadmap（不阻塞创建流程）
        asyncio.create_task(generate_roadmap_for_project(
            project_id, req.name, req.description or ""
        ))

        return {
            "id": project_id,
            **data,
            "push_success": push_success,
        }

    except Exception as e:
        error_detail = traceback.format_exc()
        logger.error("创建项目失败:\n%s", error_detail)
        raise HTTPException(500, detail=f"创建项目失败: {str(e)}")


@router.get("")
async def list_projects():
    """获取项目列表"""
    projects = await db.fetch_all(
        "SELECT * FROM projects ORDER BY created_at DESC"
    )
    return {"projects": projects, "total": len(projects)}


@router.get("/{project_id}")
async def get_project(project_id: str):
    """获取项目详情"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    _ensure_git_path(project)

    # 附带统计信息
    req_count = await db.fetch_one(
        "SELECT COUNT(*) as count FROM requirements WHERE project_id = ?",
        (project_id,),
    )
    ticket_count = await db.fetch_one(
        "SELECT COUNT(*) as count FROM tickets WHERE project_id = ?",
        (project_id,),
    )
    ticket_stats = await db.fetch_all(
        "SELECT status, COUNT(*) as count FROM tickets WHERE project_id = ? GROUP BY status",
        (project_id,),
    )

    return {
        **project,
        "stats": {
            "requirements": req_count["count"] if req_count else 0,
            "tickets": ticket_count["count"] if ticket_count else 0,
            "ticket_by_status": {row["status"]: row["count"] for row in ticket_stats},
        },
        "git_repo_exists": git_manager.repo_exists(project_id),
    }





@router.put("/{project_id}")
async def update_project(project_id: str, req: ProjectUpdate):
    """更新项目"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    update_data = {k: v for k, v in req.dict(exclude_unset=True).items() if v is not None}
    if update_data:
        update_data["updated_at"] = now_iso()
        await db.update("projects", update_data, "id = ?", (project_id,))

        # 如果更新了 git_remote_url，同步到 GitManager
        if "git_remote_url" in update_data and git_manager.repo_exists(project_id):
            try:
                await git_manager.set_remote(project_id, update_data["git_remote_url"])
            except Exception as e:
                logger.warning("同步 git remote 失败: %s", e)

    return await get_project(project_id)


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    """删除项目及所有关联数据"""
    logger.info("开始删除项目: %s", project_id)
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    logger.info("找到项目: %s, 开始级联删除...", project['name'])

    # 级联删除关联数据（按外键依赖顺序，由子到父）
    await db.execute("DELETE FROM chat_messages WHERE project_id = ?", (project_id,))
    await db.execute("DELETE FROM ticket_commands WHERE project_id = ?", (project_id,))
    await db.execute("DELETE FROM ticket_logs WHERE project_id = ?", (project_id,))
    await db.execute("DELETE FROM artifacts WHERE project_id = ?", (project_id,))
    await db.execute("DELETE FROM subtasks WHERE ticket_id IN (SELECT id FROM tickets WHERE project_id = ?)", (project_id,))
    await db.execute("DELETE FROM llm_conversations WHERE project_id = ?", (project_id,))
    await db.execute("DELETE FROM tickets WHERE project_id = ?", (project_id,))
    await db.execute("DELETE FROM requirements WHERE project_id = ?", (project_id,))
    await db.execute("DELETE FROM milestones WHERE project_id = ?", (project_id,))

    cursor = await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    logger.info("DELETE projects rowcount: %d", cursor.rowcount)

    # 验证删除结果
    check = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if check:
        logger.error("验证失败！项目仍然存在: %s", project_id)
        raise HTTPException(500, "删除失败：数据库未能成功删除项目")
    else:
        logger.info("验证通过，项目已从数据库移除")

    return {"message": "项目已删除"}


# ==================== Git 仓库 API ====================


@router.post("/{project_id}/git/remote")
async def set_git_remote(project_id: str, body: dict):
    """设置项目 Git 远程仓库"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    _ensure_git_path(project)

    url = body.get("url", "")
    if not url:
        raise HTTPException(400, "远程仓库 URL 不能为空")

    # 确保仓库已初始化
    if not git_manager.repo_exists(project_id):
        await git_manager.init_repo(project_id, project["name"], project.get("description", ""))

    await git_manager.set_remote(project_id, url)
    await db.update("projects", {
        "git_remote_url": url,
        "updated_at": now_iso(),
    }, "id = ?", (project_id,))

    return {"status": "ok", "remote_url": url}


@router.get("/{project_id}/git/tree")
async def get_git_tree(project_id: str):
    """获取项目仓库文件树"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    _ensure_git_path(project)
    tree = await git_manager.get_file_tree(project_id)
    return tree


@router.get("/{project_id}/git/log")
async def get_git_log(project_id: str, limit: int = 20):
    """获取项目 Git 提交日志"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    _ensure_git_path(project)
    logs = await git_manager.get_log(project_id, limit)
    return {"commits": logs, "total": len(logs)}


@router.get("/{project_id}/git/file")
async def get_git_file(project_id: str, path: str):
    """读取仓库中的文件内容"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    _ensure_git_path(project)
    content = await git_manager.get_file_content(project_id, path)
    if content is None:
        raise HTTPException(404, "文件不存在")

    return {"path": path, "content": content}


@router.get("/{project_id}/git/diff")
async def get_git_diff(project_id: str, commit: str = None):
    """获取 Git diff"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    _ensure_git_path(project)
    diff = await git_manager.get_diff(project_id, commit)
    return {"diff": diff}


@router.post("/detect-local")
async def detect_local_project(body: dict):
    """检测本地 Git 仓库信息"""
    import os

    local_path = body.get("local_path", "").strip()
    if not local_path:
        raise HTTPException(400, "本地路径不能为空")

    # 转换为绝对路径
    local_path = os.path.abspath(local_path)

    # 检查路径是否存在
    if not os.path.exists(local_path):
        raise HTTPException(404, f"路径不存在: {local_path}")

    # 检查是否是目录
    if not os.path.isdir(local_path):
        raise HTTPException(400, "路径必须是目录")

    result = {}

    # 提取项目名称（从路径最后一级目录）
    result["project_name"] = os.path.basename(local_path).replace("-", " ").replace("_", " ").title()

    # 检查是否是 Git 仓库
    git_dir = os.path.join(local_path, ".git")
    is_git_repo = os.path.isdir(git_dir)
    result["is_git_repo"] = is_git_repo

    if is_git_repo:
        # 尝试获取远程仓库 URL
        rc, out, err = await git_manager._run_git(local_path, "remote", "-v")
        if rc == 0 and out:
            # 解析远程 URL（第一行，第二列）
            lines = out.strip().split("\n")
            if lines:
                parts = lines[0].split()
                if len(parts) >= 2:
                    result["git_remote_url"] = parts[1]

        # 尝试获取项目描述（从 README.md）
        readme_files = ["README.md", "README.txt", "readme.md", "readme.txt"]
        for readme_name in readme_files:
            readme_path = os.path.join(local_path, readme_name)
            if os.path.exists(readme_path):
                try:
                    with open(readme_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        # 获取前100行作为描述
                        description_lines = []
                        for line in lines[:100]:
                            line = line.strip()
                            if line and not line.startswith("#"):
                                description_lines.append(line)
                        if description_lines:
                            result["description"] = "\n".join(description_lines[:10]) + "..."
                        break
                except Exception as e:
                    logger.warning("读取 README 失败: %s", e)
                break

        # 尝试检测技术栈（从文件结构）
        tech_stack = []
        # 检查 Python
        if os.path.exists(os.path.join(local_path, "requirements.txt")) or \
           os.path.exists(os.path.join(local_path, "pyproject.toml")) or \
           os.path.exists(os.path.join(local_path, "setup.py")):
            tech_stack.append("Python")
        # 检查 Node.js
        if os.path.exists(os.path.join(local_path, "package.json")):
            tech_stack.append("Node.js")
        # 检查 Java
        if os.path.exists(os.path.join(local_path, "pom.xml")) or \
           os.path.exists(os.path.join(local_path, "build.gradle")):
            tech_stack.append("Java")
        # 检查 Go
        if os.path.exists(os.path.join(local_path, "go.mod")):
            tech_stack.append("Go")
        # 检查 Rust
        if os.path.exists(os.path.join(local_path, "Cargo.toml")):
            tech_stack.append("Rust")

        if tech_stack:
            result["tech_stack"] = ", ".join(tech_stack)

    return result
