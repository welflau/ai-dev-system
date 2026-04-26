"""
AI 自动开发系统 - 项目 API
"""
import json
import logging
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
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

        logger.info("创建项目: %s, 仓库路径: %s", req.name, repo_path)

        # 判断本地目录是否已有 .git（已有仓库 vs 全新创建）
        git_dir = os.path.join(repo_path, ".git")
        cloned = False
        push_success = False

        if req.git_remote_url and not os.path.isdir(git_dir):
            # 远程仓库 + 本地无 .git：尝试 clone
            # 如果目录非空则不能 clone，先检查
            if os.path.isdir(repo_path) and os.listdir(repo_path):
                # 目录非空但无 .git，init + fetch + reset
                logger.info("目录非空但无 .git，执行 init + fetch + reset")
                await git_manager._run_git(repo_path, "init", "-b", "main")
                git_manager.set_project_path(project_id, repo_path)
                await git_manager.set_remote(project_id, req.git_remote_url)
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
                cloned = await git_manager.clone(req.git_remote_url, repo_path)
                if cloned:
                    logger.info("clone 成功，使用远程仓库内容")
                    git_manager.set_project_path(project_id, repo_path)
                else:
                    logger.warning("clone 失败，回退到本地初始化")
                    os.makedirs(repo_path, exist_ok=True)

        if not cloned:
            # 本地初始化流程（无远程 URL 或 clone 失败）
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

            # git init
            if not os.path.isdir(git_dir):
                rc, out, err = await git_manager._run_git(repo_path, "init", "-b", "main")
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
            try:
                push_success = await git_manager.push(project_id)
            except Exception as e:
                logger.warning("首次推送失败（忽略）: %s", e)

        # v0.17 Phase D：导入时带过来的 traits
        traits_list = list(req.traits or [])
        traits_conf = dict(req.traits_confidence or {})
        if traits_list and not traits_conf:
            # 用户从探测结果直接采纳 → 默认 source=file_detected
            traits_conf = {
                t: {"score": 0.9, "source": "file_detected", "evidence": "imported via detect-local"}
                for t in traits_list
            }

        data = {
            "id": project_id,
            "name": req.name,
            "description": req.description or "",
            "status": "active",
            "tech_stack": req.tech_stack or "",
            "config": "{}",
            "git_repo_path": repo_path,
            "git_remote_url": req.git_remote_url or "",
            "traits": json.dumps(traits_list, ensure_ascii=False),
            "traits_confidence": json.dumps(traits_conf, ensure_ascii=False),
            "preset_id": req.preset_id,
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


@router.post("/analyze-docs")
async def analyze_docs(files: List[UploadFile] = File(...)):
    """读取上传的文档，用 LLM 提取项目信息"""
    import chardet

    MAX_TOTAL_CHARS = 60000   # 送给 LLM 的最大字符数
    SUPPORTED_EXT = {".txt", ".md", ".markdown", ".rst", ".csv",
                     ".json", ".yaml", ".yml", ".toml", ".xml",
                     ".html", ".htm", ".log", ".conf", ".ini"}

    texts = []
    for f in files:
        raw = await f.read()
        if not raw:
            continue
        # 只处理文本文件
        ext = ("." + f.filename.rsplit(".", 1)[-1].lower()) if "." in f.filename else ""
        # 如果不在白名单则跳过（防止二进制文件乱码）
        # 但也允许无扩展名或未知扩展名的纯文本，用 chardet 探测
        detected = chardet.detect(raw[:4096]) if ext not in SUPPORTED_EXT else None
        if detected and (detected.get("encoding") is None or detected.get("confidence", 0) < 0.5):
            continue
        encoding = detected["encoding"] if detected and detected.get("encoding") else "utf-8"
        try:
            text = raw.decode(encoding, errors="replace")
        except Exception:
            try:
                text = raw.decode("utf-8", errors="replace")
            except Exception:
                continue
        texts.append(f"=== {f.filename} ===\n{text[:20000]}")

    if not texts:
        raise HTTPException(400, "未能读取任何有效文档，请上传文本格式文件（.md/.txt/.json 等）")

    combined = "\n\n".join(texts)[:MAX_TOTAL_CHARS]

    from llm_client import llm_client

    prompt = f"""请根据以下文档内容，提取并生成一个软件项目的基础信息。

文档内容：
{combined}

请以纯 JSON 格式返回，包含以下字段（如文档未提及则留空字符串）：
{{
  "name": "项目名称（简短有力，建议英文或中文均可）",
  "description": "项目描述（100-300字，说明项目目标、核心功能、应用场景）",
  "tech_stack": "技术栈（逗号分隔，如 Python, FastAPI, React, PostgreSQL）",
  "core_features": ["核心功能点1", "核心功能点2", "核心功能点3"],
  "target_users": "目标用户群体",
  "project_type": "项目类型（如 Web应用/移动端/API服务/桌面应用/数据分析/其他）"
}}"""

    try:
        result = await llm_client.chat_json(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2048,
        )
    except Exception as e:
        logger.error("LLM 分析文档失败: %s", e)
        raise HTTPException(500, f"AI 分析失败: {str(e)}")

    if not isinstance(result, dict):
        raise HTTPException(500, "AI 返回格式异常，请重试")

    return {
        "name": result.get("name", ""),
        "description": result.get("description", ""),
        "tech_stack": result.get("tech_stack", ""),
        "core_features": result.get("core_features", []),
        "target_users": result.get("target_users", ""),
        "project_type": result.get("project_type", ""),
        "doc_count": len(files),
    }



@router.post("/{project_id}/upload-docs")
async def upload_docs_to_project(project_id: str, files: List[UploadFile] = File(...)):
    """将文档写入项目仓库 docs/Design/ 目录并提交"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    _ensure_git_path(project)

    saved = {}
    for f in files:
        raw = await f.read()
        if not raw:
            continue
        # 以 UTF-8 解码（文本文件），失败则 latin-1 兜底
        try:
            content = raw.decode("utf-8", errors="replace")
        except Exception:
            content = raw.decode("latin-1", errors="replace")
        # 写入 docs/Design/{原始文件名}
        dest_path = f"docs/Design/{f.filename}"
        saved[dest_path] = content

    if not saved:
        raise HTTPException(400, "没有可写入的文件")

    # 写入 Git 仓库
    await git_manager.write_files(project_id, saved)

    # Git commit
    file_names = ", ".join(f.filename for f in files if f.filename)
    commit_hash = await git_manager.commit(
        project_id,
        message=f"docs: 导入设计文档到 docs/Design/ ({file_names})",
        author="AI Dev System",
    )

    # 尝试推送（失败不影响主流程）
    push_ok = False
    try:
        push_ok = await git_manager.push(project_id)
    except Exception as e:
        logger.warning("上传文档后推送失败: %s", e)

    return {
        "saved": list(saved.keys()),
        "commit": commit_hash,
        "push_success": push_ok,
        "count": len(saved),
    }


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

    try:
        # 级联删除关联数据（单事务，按外键依赖顺序，由子到父）
        delete_sqls = [
            "DELETE FROM chat_messages WHERE project_id = ?",
            "DELETE FROM ticket_commands WHERE project_id = ?",
            "DELETE FROM ticket_logs WHERE project_id = ?",
            "DELETE FROM artifacts WHERE project_id = ?",
            "DELETE FROM subtasks WHERE ticket_id IN (SELECT id FROM tickets WHERE project_id = ?)",
            "DELETE FROM llm_conversations WHERE project_id = ?",
            "DELETE FROM tickets WHERE project_id = ?",
            "DELETE FROM requirements WHERE project_id = ?",
            "DELETE FROM milestones WHERE project_id = ?",
            "DELETE FROM ci_builds WHERE project_id = ?",
            "DELETE FROM project_environments WHERE project_id = ?",
            "DELETE FROM projects WHERE id = ?",
        ]
        for sql in delete_sqls:
            await db._db.execute(sql, (project_id,))
        await db._db.commit()
        logger.info("项目 %s 级联删除完成", project_id)
    except Exception as e:
        logger.error("级联删除失败: %s", e, exc_info=True)
        raise HTTPException(500, f"级联删除失败: {e}")

    return {"message": "项目已删除"}


# ==================== Git 仓库 API ====================


@router.get("/{project_id}/git/branches")
async def get_git_branches(project_id: str):
    """获取项目 Git 分支列表"""
    from git_manager import git_manager
    branches = await git_manager.list_branches(project_id)
    current = await git_manager.get_current_branch(project_id)
    return {"branches": branches, "current": current}


@router.get("/{project_id}/git/branches/tree")
async def get_git_branches_tree(project_id: str):
    """v0.19.1：分支树形视图数据（含 upstream / ahead-behind / 最后一次提交 / 推测 parent）

    返回：
      {
        "branches": [ {name, upstream, parent, ahead, behind,
                       last_commit_at, last_commit_sha, last_commit_subject, current}, ... ],
        "current": "<当前分支>"
      }
    前端自行依 parent 字段 build 树。
    """
    from git_manager import git_manager
    branches = await git_manager.list_branches_enriched(project_id)
    current = await git_manager.get_current_branch(project_id)
    return {"branches": branches, "current": current}


@router.post("/{project_id}/git/switch-branch")
async def switch_git_branch(project_id: str, body: dict):
    """切换 Git 分支"""
    from git_manager import git_manager
    branch = body.get("branch", "").strip()
    if not branch:
        raise HTTPException(400, "分支名不能为空")
    ok = await git_manager.switch_branch(project_id, branch)
    if not ok:
        raise HTTPException(400, f"切换分支失败: {branch}")
    return {"current": branch}


@router.post("/{project_id}/git/merge")
async def merge_git_branches(project_id: str, body: dict):
    """手动合并分支（如 develop → master）"""
    from git_manager import git_manager
    source = body.get("source", "develop")
    target = body.get("target", "master")
    message = body.get("message", f"merge: {source} → {target}")

    result = await git_manager.merge_branch(project_id, source, target, message)

    if result["success"]:
        # 记录日志
        from events import event_manager
        await event_manager.publish_to_project(
            project_id,
            "branch_merged",
            {"source": source, "target": target, "commit": result.get("commit")},
        )

    return result


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
    current_branch = await git_manager.get_current_branch(project_id)
    tree["current_branch"] = current_branch
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


@router.get("/{project_id}/git/commit/{sha}")
async def get_git_commit_detail(project_id: str, sha: str):
    """v0.19.1：单次提交详情 + 每文件 patch"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")
    _ensure_git_path(project)
    # 基本合法性校验：sha 只允许 hex
    if not sha or not all(c in "0123456789abcdefABCDEF" for c in sha) or len(sha) > 40:
        raise HTTPException(400, "非法的 commit sha")
    detail = await git_manager.get_commit_detail(project_id, sha)
    if not detail:
        raise HTTPException(404, "commit 不存在")
    return detail


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


@router.get("/{project_id}/git/file-raw")
async def get_git_file_raw(project_id: str, path: str):
    """读取仓库中的二进制文件（图片等）"""
    from fastapi.responses import FileResponse as FR
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")
    _ensure_git_path(project)
    from pathlib import Path as P
    file_path = git_manager._repo_path(project_id) / path
    if not file_path.exists():
        raise HTTPException(404, "文件不存在")
    return FR(str(file_path))


@router.get("/{project_id}/git/diff")
async def get_git_diff(project_id: str, commit: str = None):
    """获取 Git diff"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    _ensure_git_path(project)
    diff = await git_manager.get_diff(project_id, commit)
    return {"diff": diff}


# ==================== 环境管理 API ====================


@router.get("/{project_id}/environments")
async def get_project_environments(project_id: str):
    """获取项目三个环境的状态"""
    from agents.deploy import DeployAgent

    project = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    envs = await db.fetch_all(
        "SELECT * FROM project_environments WHERE project_id = ? ORDER BY env_type",
        (project_id,),
    )
    env_map = {e["env_type"]: dict(e) for e in envs}

    # 实时维持"UI 显示的分支 = 目录 HEAD"：
    # - dev：共享主仓库，HEAD 是 source of truth → DB.branch 跟着 HEAD 走
    # - test/prod：独立目录，DB.branch（develop/main）是 source of truth → 目录被动过就 checkout 回去
    from git_manager import git_manager
    from pathlib import Path as _Path

    async def _is_working_tree_clean(path: str) -> bool:
        """判断是否无 uncommitted / untracked 文件（切分支前的安全护栏）"""
        try:
            rc, out, _ = await git_manager._run_git(path, "status", "--porcelain")
            return rc == 0 and not out.strip()
        except Exception:
            return False

    result = []
    for env_type in ("dev", "test", "prod"):
        env = env_map.get(env_type, {})
        # 检查进程是否真的还在运行
        key = (project_id, env_type)
        actually_running = key in DeployAgent._preview_servers
        status = "running" if actually_running else "inactive"
        if env.get("status") == "running" and not actually_running:
            await db.execute(
                "UPDATE project_environments SET status = 'inactive' WHERE project_id = ? AND env_type = ?",
                (project_id, env_type),
            )

        deploy_path = env.get("deploy_path", "")
        db_branch = env.get("branch", "")
        actual_branch = ""
        sync_note = ""   # 同步动作备忘（供前端 toast / 日志）

        if deploy_path and _Path(deploy_path).exists():
            try:
                actual_branch = await git_manager.get_branch_at_path(deploy_path)
            except Exception:
                actual_branch = ""

            # --- 一致性维持 ---
            if env_type == "dev":
                # dev 共享主仓库：DB 跟着 HEAD 走
                if actual_branch and actual_branch != db_branch:
                    await db.execute(
                        "UPDATE project_environments SET branch = ? WHERE project_id = ? AND env_type = ?",
                        (actual_branch, project_id, env_type),
                    )
                    sync_note = f"DB 分支已更新为当前 HEAD: {actual_branch}"
                    db_branch = actual_branch

            elif env_type in ("test", "prod"):
                # test/prod 独立目录：DB 是权威（develop/main），目录偏了就切回来
                if db_branch and actual_branch and actual_branch != db_branch:
                    if await _is_working_tree_clean(deploy_path):
                        try:
                            rc, _, err = await git_manager._run_git(
                                deploy_path, "checkout", db_branch,
                            )
                            if rc == 0:
                                actual_branch = db_branch
                                sync_note = f"目录已自动切回 {db_branch}"
                                logger.info("环境 %s 自动对齐分支 → %s (path=%s)",
                                            env_type, db_branch, deploy_path)
                            else:
                                sync_note = f"自动切换失败: {err[:100]}"
                                logger.warning("环境 %s checkout 失败: %s", env_type, err)
                        except Exception as e:
                            sync_note = f"切换异常: {e}"
                    else:
                        sync_note = f"目录有未提交改动，跳过自动切换（当前: {actual_branch}，应为: {db_branch}）"

        result.append({
            "env_type": env_type,
            "branch": db_branch,                    # 经过一致性维持后的分支（UI 显示这个）
            "current_branch": actual_branch,        # 目录当前 HEAD（前端对比用）
            "deploy_path": deploy_path,
            "port": env.get("port"),
            "status": status,
            "url": env.get("url", ""),
            "last_commit": env.get("last_commit", ""),
            "last_deployed_at": env.get("last_deployed_at", ""),
            "branch_sync_note": sync_note,
        })

    return {"environments": result}


@router.post("/{project_id}/environments/{env_type}/deploy")
async def deploy_environment(project_id: str, env_type: str):
    """手动触发环境部署"""
    from agents.deploy import DeployAgent

    if env_type not in ("dev", "test", "prod"):
        raise HTTPException(400, "环境类型无效，可选: dev, test, prod")

    project = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    _ensure_git_path(project)
    url = await DeployAgent.deploy_env(project_id, env_type)
    if url:
        return {"status": "ok", "url": url, "env_type": env_type}
    raise HTTPException(500, f"{env_type} 环境部署失败")


@router.post("/{project_id}/environments/{env_type}/stop")
async def stop_environment(project_id: str, env_type: str):
    """停止环境"""
    from agents.deploy import DeployAgent

    if env_type not in ("dev", "test", "prod"):
        raise HTTPException(400, "环境类型无效")

    await DeployAgent.stop_env(project_id, env_type)
    return {"status": "ok", "env_type": env_type}


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

    # v0.17 Phase D：用 ProjectTypeDetectorAction 探测 traits
    try:
        from actions.chat.detect_project_type import ProjectTypeDetectorAction
        detector_result = await ProjectTypeDetectorAction().run({"repo_path": local_path})
        if detector_result.success:
            d = detector_result.data
            result["detected_traits"] = [
                {
                    "trait": c["trait"],
                    "confidence": c["confidence"],
                    "evidence": c["evidence"],
                }
                for c in (d.get("candidates") or [])
            ]
            result["suggested_preset"] = d.get("suggested_preset")
            result["preset_match_score"] = d.get("preset_match_score", 0)
            result["trait_warnings"] = d.get("warnings") or []
    except Exception as e:
        logger.warning("trait 探测失败（忽略）: %s", e)

    return result


# ==================== v0.17 Phase E：项目特征编辑 API ====================

class UpdateTraitsRequest(BaseModel):
    traits: List[str] = Field(default_factory=list, description="新的 traits 列表（完整覆盖）")
    preset_id: Optional[str] = Field(default=None, description="preset 名，可选")
    traits_confidence: Optional[Dict[str, Any]] = Field(default=None, description="每个 trait 的置信度（可选，不提供则按 source=manual_edit 补）")


def _load_valid_traits() -> set:
    """从 trait_taxonomy.yaml 加载所有合法的 trait 值"""
    try:
        import os as _os
        import yaml
        tax_path = _os.path.join(_os.path.dirname(__file__), "..", "skills", "rules", "trait_taxonomy.yaml")
        tax_path = _os.path.abspath(tax_path)
        if not _os.path.exists(tax_path):
            return set()
        with open(tax_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        valid = set()
        for dim_name, dim in data.items():
            if not isinstance(dim, dict) or "values" not in dim:
                continue
            for v in dim["values"]:
                valid.add(f"{dim_name}:{v}")
        return valid
    except Exception as e:
        logger.warning("加载 trait_taxonomy 失败: %s", e)
        return set()


def _normalize_trait(t: str) -> str:
    """容错：`multiplayer` → `multiplayer:true`，`genre:fps` 保持原样（由上层校验）"""
    t = t.strip()
    if ":" not in t:
        # 无 value 的 trait，猜测是 features 类型，补 :true
        return f"{t}:true"
    return t


@router.patch("/{project_id}/traits")
async def update_project_traits(project_id: str, req: UpdateTraitsRequest):
    """更新项目 traits + preset_id。

    v0.17 Phase E 的核心编辑端点。
    - 合法性校验：不在 taxonomy 里的 trait → warning 但允许（允许未来维度扩展的 heads-up）
    - 自动 normalize：`multiplayer` → `multiplayer:true`
    - 写库后自动失效 orchestrator 的 rules cache
    """
    project = await db.fetch_one("SELECT id, traits FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    # normalize
    normalized = [_normalize_trait(t) for t in req.traits if t.strip()]
    normalized = list(dict.fromkeys(normalized))  # 去重保序

    # 校验合法性
    valid_set = _load_valid_traits()
    unknowns = [t for t in normalized if valid_set and t not in valid_set]

    # traits_confidence：用户提供 → 用户的；否则补 source=manual_edit
    if req.traits_confidence:
        new_conf = dict(req.traits_confidence)
    else:
        import json as _json
        prev_conf = {}
        try:
            prev_raw = await db.fetch_one("SELECT traits_confidence FROM projects WHERE id = ?", (project_id,))
            if prev_raw and prev_raw.get("traits_confidence"):
                prev_conf = _json.loads(prev_raw["traits_confidence"])
        except Exception:
            pass

        new_conf = {}
        for t in normalized:
            if t in prev_conf:
                new_conf[t] = prev_conf[t]   # 保留原来的 source/evidence
            else:
                new_conf[t] = {
                    "score": 1.0,
                    "source": "manual_edit",
                    "evidence": "用户在项目特征页手动添加",
                }

    import json as _json
    await db.update(
        "projects",
        {
            "traits": _json.dumps(normalized, ensure_ascii=False),
            "traits_confidence": _json.dumps(new_conf, ensure_ascii=False),
            "preset_id": req.preset_id,
            "updated_at": now_iso(),
        },
        "id = ?",
        (project_id,),
    )

    # 关键：失效 orchestrator 的 rules cache，下次工单流转会重算 SOP
    try:
        from orchestrator import orchestrator
        orchestrator.invalidate_project_rules(project_id)
    except Exception as e:
        logger.warning("invalidate orchestrator rules 失败: %s", e)

    return {
        "project_id": project_id,
        "traits": normalized,
        "preset_id": req.preset_id,
        "unknowns": unknowns,  # 不在 taxonomy 里的 trait（警告，不阻塞）
        "traits_confidence": new_conf,
    }


@router.get("/{project_id}/traits")
async def get_project_traits(project_id: str):
    """获取项目当前 traits + preset_id + confidence"""
    row = await db.fetch_one(
        "SELECT id, name, traits, traits_confidence, preset_id FROM projects WHERE id = ?",
        (project_id,),
    )
    if not row:
        raise HTTPException(404, "项目不存在")
    import json as _json
    try:
        traits = _json.loads(row.get("traits") or "[]") or []
    except Exception:
        traits = []
    try:
        traits_confidence = _json.loads(row.get("traits_confidence") or "{}") or {}
    except Exception:
        traits_confidence = {}
    return {
        "project_id": row["id"],
        "project_name": row["name"],
        "traits": traits,
        "preset_id": row.get("preset_id"),
        "traits_confidence": traits_confidence,
    }


# ==================== v0.18 UE 配置 API ====================


class UEConfigRequest(BaseModel):
    ue_engine_path: Optional[str] = None
    ue_engine_version: Optional[str] = None
    ue_engine_type: Optional[str] = None         # "launcher" | "source_build"
    uproject_path: Optional[str] = None
    ue_target_name: Optional[str] = None
    ue_target_platform: Optional[str] = None
    ue_target_config: Optional[str] = None


@router.get("/{project_id}/ue-config")
async def get_project_ue_config(project_id: str):
    """获取项目的 UE 配置字段（Phase B 持久化的字段）。"""
    row = await db.fetch_one(
        """SELECT id, name, traits, ue_engine_path, ue_engine_version, ue_engine_type,
                  uproject_path, ue_target_name, ue_target_platform, ue_target_config
           FROM projects WHERE id = ?""",
        (project_id,),
    )
    if not row:
        raise HTTPException(404, "项目不存在")

    # 判断是不是 UE 项目（有 engine:ue* trait）
    import json as _json
    try:
        traits = _json.loads(row.get("traits") or "[]") or []
    except Exception:
        traits = []
    is_ue = any(t.startswith("engine:ue") for t in traits)

    return {
        "project_id": row["id"],
        "project_name": row["name"],
        "is_ue_project": is_ue,
        "ue_engine_path": row.get("ue_engine_path"),
        "ue_engine_version": row.get("ue_engine_version"),
        "ue_engine_type": row.get("ue_engine_type"),
        "uproject_path": row.get("uproject_path"),
        "ue_target_name": row.get("ue_target_name"),
        "ue_target_platform": row.get("ue_target_platform") or "Win64",
        "ue_target_config": row.get("ue_target_config") or "Development",
    }


@router.patch("/{project_id}/ue-config")
async def update_project_ue_config(project_id: str, req: UEConfigRequest):
    """更新项目的 UE 配置字段（按需更新，None 字段跳过）。"""
    existing = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not existing:
        raise HTTPException(404, "项目不存在")

    # 仅更新非 None 字段
    updates = {
        k: v for k, v in req.model_dump().items()
        if v is not None
    }
    if not updates:
        return {"message": "无变更"}

    updates["updated_at"] = now_iso()
    await db.update("projects", updates, "id = ?", (project_id,))
    return {"message": "UE 配置已更新", "updated_fields": list(updates.keys())}


# ==================== v0.17 Preview Assembly API ====================


class PreviewAssemblyRequest(BaseModel):
    traits: List[str] = Field(default_factory=list, description="项目 traits 列表")
    ticket_type: Optional[str] = Field(default=None, description="工单类型（可选）：feature/bug-fix/...")
    include_rules: bool = Field(default=True, description="是否在 skills 预览里列出 alwaysApply 的 rules")


def _match_traits_cfg(match_cfg, traits_list: List[str]) -> bool:
    """本地复制，避免循环 import"""
    if not match_cfg:
        return True
    traits_set = set(traits_list)
    all_of = match_cfg.get("all_of") or []
    any_of = match_cfg.get("any_of") or []
    none_of = match_cfg.get("none_of") or []
    if all_of and not all(t in traits_set for t in all_of):
        return False
    if any_of and not any(t in traits_set for t in any_of):
        return False
    if none_of and any(t in traits_set for t in none_of):
        return False
    return True


@router.post("/preview-assembly")
async def preview_assembly(req: PreviewAssemblyRequest):
    """v0.17 Trait-First 核心 API：给定 traits → 实时返回将要组装出来的
    SOP + Agents + Skills + MCPs + warnings + suggestions。

    前端 confirm_project 确认卡片渲染前调此端点，让用户在点"确认创建"之前
    看到将用什么流程 / 跑哪些 Agent / 注入哪些 Skill。
    """
    from sop.loader import compose_sop
    from skills import skill_loader
    from orchestrator import orchestrator

    traits = list(req.traits or [])
    ticket_type = req.ticket_type

    # 1. SOP 组装
    sop_composed = compose_sop(traits=traits, ticket_type=ticket_type)
    sop_stages = [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "agent": s.get("agent"),
            "action": s.get("action"),
            "trigger_on": s.get("trigger_on"),
            "success_status": s.get("success_status"),
            "description": s.get("description"),
        }
        for s in sop_composed.get("stages", [])
    ]
    fragments_activated = sop_composed.get("composed_from_fragments") or []

    # 2. Agent 过滤
    all_agents = orchestrator.agents
    active_agents = []
    excluded_agents = []
    for name, agent in all_agents.items():
        cls = type(agent)
        avail = getattr(cls, "available_for_traits", None)
        if _match_traits_cfg(avail, traits):
            active_agents.append(name)
        else:
            excluded_agents.append({
                "agent": name,
                "reason": f"available_for_traits={avail} 跟项目 traits 不匹配",
            })

    # 3. Skill 按 Agent 分组
    skills_by_agent: Dict[str, List[Dict]] = {}
    for agent_name in active_agents:
        skill_ids = skill_loader.get_skills_for_agent(agent_name, traits=traits)
        skills_by_agent[agent_name] = [
            {
                "id": sid,
                "name": skill_loader.skills[sid].get("name", sid),
                "priority": skill_loader.skills[sid].get("priority", "medium"),
                "matched": skill_loader.skills[sid].get("traits_match") or {},
            }
            for sid in skill_ids
        ]

    # Rules（全局，不分 Agent）
    rules_list = []
    if req.include_rules:
        rule_ids = skill_loader.get_rules_for_context(traits=traits)
        rules_list = [
            {
                "id": rid,
                "description": skill_loader.rules[rid].get("description", ""),
                "alwaysApply": skill_loader.rules[rid].get("alwaysApply", False),
            }
            for rid in rule_ids
        ]

    # 4. MCP 列表（若客户端已加载）
    mcps = []
    try:
        from mcp_client import mcp_client
        status = mcp_client.get_status()
        for name, s in (status.get("servers") or {}).items():
            enabled_for_traits = s.get("enabled_for_traits")   # Phase F 会启用
            applicable = _match_traits_cfg(enabled_for_traits, traits) if enabled_for_traits else True
            mcps.append({
                "name": name,
                "enabled": s.get("enabled", False),
                "status": s.get("status"),
                "applicable_to_traits": applicable,
                "tools_count": len(s.get("tools") or []),
            })
    except Exception as e:
        logger.warning("preview: 取 MCP 状态失败: %s", e)

    # 5. Warnings —— 缺必填维度 / 冲突
    warnings = []
    has_platform = any(t.startswith("platform:") for t in traits)
    has_category = any(t.startswith("category:") for t in traits)
    if not has_platform:
        warnings.append("缺 platform:* trait（推荐至少有一个）")
    if not has_category:
        warnings.append("缺 category:* trait（决定主流程方向）")
    has_game = "category:game" in traits
    has_engine = any(t.startswith("engine:") for t in traits)
    if has_game and not has_engine:
        warnings.append("category:game 但缺 engine:*（ue5/godot4/unity/none），SOP 会缺引擎编译阶段")

    if not sop_stages:
        warnings.append("SOP 为空，无可执行阶段")

    # 6. Suggestions —— 基于 traits 推下一步能加什么
    suggestions = []
    if has_game and "multiplayer:true" not in traits and has_engine:
        suggestions.append({
            "hint": "如果项目涉及多人对战，可加 multiplayer:true，SOP 会自动插入多人压测阶段",
            "trait": "multiplayer:true",
        })
    if "platform:web" in traits and "i18n" not in traits:
        suggestions.append({
            "hint": "若需国际化，可加 i18n，SOP 会自动插入 i18n_check 阶段",
            "trait": "i18n",
        })

    return {
        "traits": traits,
        "ticket_type": ticket_type,
        "effective_config": {
            "sop": {
                "stages": sop_stages,
                "fragments_activated": fragments_activated,
            },
            "agents": {
                "active": active_agents,
                "excluded": excluded_agents,
            },
            "skills_by_agent": skills_by_agent,
            "rules": rules_list,
            "mcps": mcps,
        },
        "warnings": warnings,
        "suggestions": suggestions,
    }
