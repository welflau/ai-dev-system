"""
AI 自动开发系统 - 项目 API
"""
import json
import logging
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from database import db
from models import ProjectCreate, ProjectUpdate, RepoPathUpdate
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
def _auto_init_ads_dir(repo_path: str, project_name: str, traits: list) -> None:
    """新建项目时自动创建 .ads/ 目录结构（不覆盖已有文件）。"""
    import json as _json
    from pathlib import Path
    ads_dir = Path(repo_path) / ".ads"
    (ads_dir / "rules").mkdir(parents=True, exist_ok=True)
    (ads_dir / "skills").mkdir(parents=True, exist_ok=True)

    # config.json（不存在才创建）
    cfg_file = ads_dir / "config.json"
    if not cfg_file.exists():
        cfg_file.write_text(_json.dumps({
            "project_name": project_name,
            "traits": traits,
            "description": ""
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    # rules/project-rules.md 模板（不存在才创建）
    rule_file = ads_dir / "rules" / "project-rules.md"
    if not rule_file.exists():
        rule_file.write_text(
            "---\nalwaysApply: true\npriority: medium\n"
            f"description: {project_name} 项目编码规范\n---\n\n"
            f"# {project_name} 项目规范\n\n<!-- 在这里写项目专属的编码规范 -->\n",
            encoding="utf-8"
        )


def _load_ads_config(repo_path: str) -> dict:
    """读取 {repo}/.ads/config.json，返回配置字典，不存在或解析失败返回 {}。"""
    import json as _json
    from pathlib import Path
    cfg_file = Path(repo_path) / ".ads" / "config.json"
    if not cfg_file.exists():
        return {}
    try:
        return _json.loads(cfg_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


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

        # 整理 git_remotes：优先用请求里的数组，否则从 git_remote_url 构造
        remotes_list = req.git_remotes or []
        if not remotes_list and req.git_remote_url:
            remotes_list = [{"name": "origin", "url": req.git_remote_url}]
        # 把所有 remote 注册到 git（本地 clone 场景已经有 origin，跳过已存在的）
        for r in remotes_list:
            rname, rurl = r.get("name", ""), r.get("url", "")
            if rname and rurl and rname != "origin":  # origin 已由 set_remote/clone 处理
                try:
                    await git_manager.add_remote(project_id, rname, rurl)
                except Exception as e:
                    logger.warning("注册 remote '%s' 失败（忽略）: %s", rname, e)

        # 从 git_remotes 推断 git_remote_url（取 origin，fallback 第一个）
        origin_url = req.git_remote_url or ""
        if not origin_url and remotes_list:
            origin_entry = next((r for r in remotes_list if r.get("name") == "origin"), remotes_list[0])
            origin_url = origin_entry.get("url", "")

        # push_remote 默认 "origin"
        git_manager.set_push_remote(project_id, "origin")

        data = {
            "id": project_id,
            "name": req.name,
            "description": req.description or "",
            "status": "active",
            "tech_stack": req.tech_stack or "",
            "config": "{}",
            "git_repo_path": repo_path,
            "git_remote_url": origin_url,
            "git_remotes": json.dumps(remotes_list, ensure_ascii=False),
            "git_push_remote": "origin",
            "traits": json.dumps(traits_list, ensure_ascii=False),
            "traits_confidence": json.dumps(traits_conf, ensure_ascii=False),
            "preset_id": req.preset_id,
            "created_at": now,
            "updated_at": now,
        }
        await db.insert("projects", data)

        # 自动初始化 .ads/ 目录结构（新建项目时自动创建，不覆盖已有内容）
        try:
            _auto_init_ads_dir(repo_path, req.name, traits_list)
        except Exception as e:
            logger.debug("自动初始化 .ads/ 失败（忽略）: %s", e)

        # P4: 读取 .ads/config.json，覆盖 traits 等配置
        try:
            _ads_cfg = _load_ads_config(repo_path)
            if _ads_cfg:
                updates = {}
                if "traits" in _ads_cfg and isinstance(_ads_cfg["traits"], list):
                    # 合并：保留自动检测的 traits，追加 config 里声明的
                    existing = json.loads(data.get("traits", "[]"))
                    merged = list(dict.fromkeys(existing + _ads_cfg["traits"]))
                    updates["traits"] = json.dumps(merged, ensure_ascii=False)
                if "description" in _ads_cfg and not req.description:
                    updates["description"] = str(_ads_cfg["description"])[:500]
                if updates:
                    updates["updated_at"] = now_iso()
                    await db.update("projects", updates, "id = ?", (project_id,))
                    logger.info("项目 %s 已从 .ads/config.json 更新配置", project_id[:12])
        except Exception as e:
            logger.debug("读取 .ads/config.json 失败（忽略）: %s", e)

        if remotes_list:
            logger.info("项目创建完成: %s (%s)，%d 个 Remote: %s",
                        req.name, project_id, len(remotes_list),
                        ", ".join(r.get("name","?") for r in remotes_list))
        else:
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
        "SELECT * FROM projects WHERE id != '__global__' ORDER BY created_at DESC"
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

        # 如果更新了 git_remote_url，同步到 GitManager 并更新 git_remotes 里的 origin 条目
        if "git_remote_url" in update_data and git_manager.repo_exists(project_id):
            try:
                new_url = update_data["git_remote_url"]
                await git_manager.set_remote(project_id, new_url)
                # 同步更新 git_remotes JSON 里 origin 的 url
                fresh = await db.fetch_one("SELECT git_remotes FROM projects WHERE id = ?", (project_id,))
                remotes = json.loads(fresh.get("git_remotes") or "[]")
                updated = False
                for r in remotes:
                    if r.get("name") == "origin":
                        r["url"] = new_url
                        updated = True
                if not updated:
                    remotes.insert(0, {"name": "origin", "url": new_url})
                await db.update("projects", {"git_remotes": json.dumps(remotes)}, "id = ?", (project_id,))
            except Exception as e:
                logger.warning("同步 git remote 失败: %s", e)

    return await get_project(project_id)


@router.put("/{project_id}/repo-path")
async def update_project_repo_path(project_id: str, req: RepoPathUpdate):
    """修改项目本地仓库路径（敏感操作，独立端点）"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    new_path = req.repo_path.strip()
    if not new_path:
        raise HTTPException(422, "路径不能为空")

    if not os.path.isdir(new_path):
        raise HTTPException(400, f"目录不存在，请确认路径正确：{new_path}")

    warning = None
    if not os.path.isdir(os.path.join(new_path, ".git")):
        warning = "目录存在但不是 Git 仓库"

    await db.update("projects", {
        "git_repo_path": new_path,
        "updated_at": now_iso(),
    }, "id = ?", (project_id,))

    logger.info("项目 %s 本地路径已修改: %s → %s", project_id, project.get("git_repo_path"), new_path)

    result = await get_project(project_id)
    if warning:
        result["warning"] = warning
    return result


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    """删除项目及所有关联数据"""
    logger.info("开始删除项目: %s", project_id)
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    logger.info("找到项目: %s, 开始级联删除...", project['name'])

    # 先通知 Orchestrator 停止处理该项目所有工单（防止删表时并发写入导致 FK 冲突）
    try:
        from orchestrator import orchestrator
        tickets_in_flight = [tid for tid in list(orchestrator._processing)
                             if tid in orchestrator._project_active.get(project_id, set())]
        for tid in tickets_in_flight:
            orchestrator._processing.discard(tid)
        orchestrator._project_active.pop(project_id, None)
        logger.info("已从 Orchestrator 移除项目 %s（%d 个进行中工单终止）",
                    project_id, len(tickets_in_flight))
    except Exception as oe:
        logger.warning("停止 Orchestrator 任务失败（继续删除）: %s", oe)

    try:
        # SQLite: PRAGMA foreign_keys=OFF 只能在事务外生效，先 commit 关闭任何活跃事务
        await db._db.commit()
        await db._db.execute("PRAGMA foreign_keys=OFF")
        await db._db.commit()  # 确保 PRAGMA 生效
        delete_sqls = [
            "DELETE FROM chat_messages WHERE project_id = ?",
            "DELETE FROM ticket_commands WHERE project_id = ?",
            "DELETE FROM ticket_logs WHERE project_id = ?",
            "DELETE FROM artifacts WHERE project_id = ?",
            "DELETE FROM subtasks WHERE ticket_id IN (SELECT id FROM tickets WHERE project_id = ?)",
            "DELETE FROM llm_conversations WHERE project_id = ?",
            "DELETE FROM bugs WHERE project_id = ?",
            "DELETE FROM failure_cases WHERE project_id = ?",
            "DELETE FROM knowledge_index WHERE project_id = ?",
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
    finally:
        # 无论成败都恢复 FK 检查
        try:
            await db._db.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass

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


async def _remotes_response(project_id: str, push_remote: str, db_remotes_raw: str = None) -> dict:
    """从 git 读取 remote 列表；git 为空时从 DB 恢复并写入 git"""
    if git_manager.repo_exists(project_id):
        git_remotes = await git_manager.list_remotes(project_id)
        # git 里没有 remote，但 DB 有记录 → 自动恢复到 git
        if not git_remotes and db_remotes_raw:
            db_list = json.loads(db_remotes_raw or "[]")
            for r in db_list:
                name, url = r.get("name", ""), r.get("url", "")
                if name and url:
                    try:
                        await git_manager.add_remote(project_id, name, url)
                    except Exception:
                        pass
            git_remotes = await git_manager.list_remotes(project_id)
    else:
        git_remotes = []
    remotes = [
        {"name": r["name"], "url": r["url"], "is_push_default": r["name"] == push_remote}
        for r in git_remotes
    ]
    return {"remotes": remotes, "push_remote": push_remote}


@router.get("/{project_id}/git/remotes")
async def list_git_remotes(project_id: str):
    """列出项目所有 Git Remote（含 push 默认标记）"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    _ensure_git_path(project)
    push_remote = project.get("git_push_remote") or "origin"
    return await _remotes_response(project_id, push_remote, project.get("git_remotes"))


@router.post("/{project_id}/git/remotes")
async def add_git_remote(project_id: str, body: dict):
    """添加新 Remote"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip()
    if not name:
        raise HTTPException(400, "Remote 名称不能为空")
    if not url:
        raise HTTPException(400, "Remote URL 不能为空")
    if not name.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "Remote 名称只能包含字母、数字、-、_")

    _ensure_git_path(project)

    if not git_manager.repo_exists(project_id):
        await git_manager.init_repo(project_id, project["name"], project.get("description", ""))

    ok = await git_manager.add_remote(project_id, name, url)
    if not ok:
        raise HTTPException(500, f"添加 Remote '{name}' 失败")

    # 同步到 DB git_remotes
    remotes = json.loads(project.get("git_remotes") or "[]")
    remotes = [r for r in remotes if r.get("name") != name]  # 去旧
    remotes.append({"name": name, "url": url})
    updates: dict = {"git_remotes": json.dumps(remotes), "updated_at": now_iso()}
    # 如果是第一个 remote，同时更新 git_remote_url 兼容旧字段
    if name == "origin":
        updates["git_remote_url"] = url
    await db.update("projects", updates, "id = ?", (project_id,))

    push_remote = project.get("git_push_remote") or "origin"
    return await _remotes_response(project_id, push_remote)


@router.delete("/{project_id}/git/remotes/{remote_name}")
async def delete_git_remote(project_id: str, remote_name: str):
    """删除指定 Remote"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    push_remote = project.get("git_push_remote") or "origin"

    if remote_name == push_remote:
        raise HTTPException(400, "无法删除当前 Push 默认 Remote，请先将其他 Remote 设为默认")

    _ensure_git_path(project)
    # 用 git 实际数量判断（DB 可能滞后）
    git_remotes_list = await git_manager.list_remotes(project_id) if git_manager.repo_exists(project_id) else []
    if len(git_remotes_list) <= 1:
        raise HTTPException(400, "至少保留一个 Remote，无法删除")

    if git_manager.repo_exists(project_id):
        await git_manager.remove_remote(project_id, remote_name)

    remotes_db = json.loads(project.get("git_remotes") or "[]")
    remotes_db = [r for r in remotes_db if r.get("name") != remote_name]
    await db.update("projects", {
        "git_remotes": json.dumps(remotes_db),
        "updated_at": now_iso(),
    }, "id = ?", (project_id,))

    return await _remotes_response(project_id, push_remote)


@router.put("/{project_id}/git/push-remote")
async def set_push_remote(project_id: str, body: dict):
    """设置项目的默认 Push Remote"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    remote_name = (body.get("remote_name") or "").strip()
    if not remote_name:
        raise HTTPException(400, "remote_name 不能为空")

    # 验证 remote 存在
    _ensure_git_path(project)
    if git_manager.repo_exists(project_id):
        git_remotes = await git_manager.list_remotes(project_id)
        names = [r["name"] for r in git_remotes]
        if names and remote_name not in names:
            raise HTTPException(400, f"Remote '{remote_name}' 不存在，可用: {', '.join(names)}")

    await db.update("projects", {
        "git_push_remote": remote_name,
        "updated_at": now_iso(),
    }, "id = ?", (project_id,))
    git_manager.set_push_remote(project_id, remote_name)
    logger.info("项目 %s 默认 push remote 设为: %s", project_id, remote_name)

    remotes = json.loads(project.get("git_remotes") or "[]")
    return await _remotes_response(project_id, remote_name)


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
async def get_git_file(project_id: str, path: str, branch: str = None):
    """读取仓库中的文件内容（branch 参数指定从哪个分支读，不影响工作目录）"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    _ensure_git_path(project)
    content = await git_manager.get_file_content(project_id, path, branch=branch)
    if content is None:
        raise HTTPException(404, "文件不存在")

    return {"path": path, "content": content}


@router.get("/{project_id}/screenshots/{filename}")
async def get_project_screenshot(project_id: str, filename: str):
    """v0.19.x：读取 UE 运行截图（存在项目截图目录，不在 git repo 内）"""
    import re
    from fastapi.responses import FileResponse as FR
    from git_manager import git_manager as _gm

    # 安全校验：只允许文件名，不允许路径穿越
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "非法文件名")
    if not re.match(r"^[\w\-. ]+\.(png|jpg|jpeg|webp|gif)$", filename, re.IGNORECASE):
        raise HTTPException(400, "不支持的文件类型")

    from config import BASE_DIR as _BASE_DIR

    # 优先找 chat_images/ue_screenshots/<pid>/（持久化存储位置）
    base_dir = _BASE_DIR / "chat_images" / "ue_screenshots"
    shot_path = base_dir / project_id / filename

    if not shot_path.is_file():
        # 兜底：repo 目录下的 screenshots/（兼容旧路径）
        repo_path = _gm._repo_path(project_id)
        if repo_path:
            shot_path = Path(repo_path) / "screenshots" / filename
    if not shot_path.is_file():
        raise HTTPException(404, "截图不存在")
    return FR(str(shot_path))


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
        # 读取所有 remote（去重 fetch/push 同名条目）
        rc, out, err = await git_manager._run_git(local_path, "remote", "-v")
        if rc == 0 and out:
            seen: dict = {}
            for line in out.strip().splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    seen[parts[0]] = parts[1]
            remotes = [{"name": n, "url": u} for n, u in seen.items()]
            if remotes:
                result["git_remotes"] = remotes
                result["git_remote_url"] = remotes[0]["url"]  # 兼容旧字段，取第一个

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


@router.get("/{project_id}/flow")
async def get_project_flow(project_id: str):
    """项目流程页：返回组合后的完整 SOP 阶段 + 各阶段工单/需求分布"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    import json
    from sop.loader import build_pipeline_stages, compose_sop

    # 解析 traits
    traits_raw = project.get("traits") or "[]"
    traits = json.loads(traits_raw) if isinstance(traits_raw, str) else (traits_raw or [])

    # 组合 SOP（按项目 traits）
    sop_cfg = compose_sop(traits)
    pipeline = build_pipeline_stages(sop_cfg)

    # 各阶段工单数统计
    ticket_rows = await db.fetch_all(
        "SELECT status, COUNT(*) as cnt FROM tickets WHERE project_id = ? GROUP BY status",
        (project_id,),
    )
    status_count = {r["status"]: r["cnt"] for r in ticket_rows}

    # 需求总数
    req_count = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM requirements WHERE project_id = ?", (project_id,)
    )
    total_requirements = (req_count or {}).get("cnt", 0)

    # 组装返回结构
    stages = []
    for stage_def in pipeline.get("defs", []):
        in_statuses = stage_def.get("in_statuses") or []
        ticket_cnt = sum(status_count.get(s, 0) for s in in_statuses)
        stages.append({
            "key":         stage_def.get("key", ""),
            "name":        stage_def.get("name", ""),
            "icon":        stage_def.get("icon", ""),
            "description": stage_def.get("description", ""),
            "ticket_count": ticket_cnt,
            "in_statuses": in_statuses,
            "sop_stages":  stage_def.get("sop_stages", []),
        })

    # 激活的 fragments（compose_sop 存在 composed_from_fragments 字段）
    fragments = sop_cfg.get("composed_from_fragments") or [] if isinstance(sop_cfg, dict) else []

    return {
        "project_id": project_id,
        "project_name": project.get("name", ""),
        "traits": traits,
        "total_requirements": total_requirements,
        "total_tickets": sum(status_count.values()),
        "stages": stages,
        "active_fragments": fragments,
        "sop_name": sop_cfg.get("name", "") if isinstance(sop_cfg, dict) else "",
    }


# ==================== 记忆管理 API ====================

@router.get("/{project_id}/memory")
async def list_memory(
    project_id: str,
    query: str = "",
    type: str = "",
    limit: int = 50,
):
    """列出项目记忆（支持搜索和类型过滤）"""
    from database import db
    pid = project_id if project_id != "__global__" else "__global__"
    try:
        if query:
            rows = await db.fetch_all(
                """SELECT id, type, title, content, agent_type, created_at
                   FROM agent_memory
                   WHERE (project_id = ? OR project_id = '__global__')
                   AND (title LIKE ? OR content LIKE ?)
                   ORDER BY created_at DESC LIMIT ?""",
                (pid, f"%{query}%", f"%{query}%", limit),
            )
        elif type and type != "all":
            rows = await db.fetch_all(
                """SELECT id, type, title, content, agent_type, created_at
                   FROM agent_memory
                   WHERE (project_id = ? OR project_id = '__global__')
                   AND type = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (pid, type, limit),
            )
        else:
            rows = await db.fetch_all(
                """SELECT id, type, title, content, agent_type, created_at
                   FROM agent_memory
                   WHERE project_id = ? OR project_id = '__global__'
                   ORDER BY created_at DESC LIMIT ?""",
                (pid, limit),
            )
        return {"memories": [dict(r) for r in rows], "total": len(rows)}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{project_id}/memory/{memory_id}")
async def delete_memory(project_id: str, memory_id: str):
    """删除一条记忆"""
    from database import db
    try:
        await db.execute("DELETE FROM agent_memory WHERE id = ?", (memory_id,))
        return {"success": True, "id": memory_id}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 快速打开目录 ====================

@router.post("/scan-directory")
async def scan_directory(body: dict):
    """
    扫描本地目录，识别项目信息（名称、技术栈、git、P4、引擎路径、traits）。
    用于 AI 助手「打开目录」快速创建项目。
    返回可直接用于创建项目的识别结果。
    """
    import os
    from pathlib import Path

    local_path = (body.get("path") or body.get("local_path") or "").strip()
    if not local_path:
        raise HTTPException(400, "路径不能为空")

    local_path = os.path.abspath(local_path)
    if not os.path.exists(local_path):
        raise HTTPException(404, f"路径不存在: {local_path}")
    if not os.path.isdir(local_path):
        raise HTTPException(400, "路径必须是目录")

    # 检查是否已是现有项目
    from database import db as _db
    existing = await _db.fetch_one(
        "SELECT id, name FROM projects WHERE git_repo_path = ?", (local_path,)
    )
    if existing:
        return {
            "already_exists": True,
            "project_id": existing["id"],
            "project_name": existing["name"],
            "path": local_path,
        }

    result = {"already_exists": False, "path": local_path}

    # ── 1. 项目名 ──────────────────────────────────────────
    dir_name = Path(local_path).name
    project_name = dir_name.replace("-", " ").replace("_", " ")

    # 从特征文件读取更好的名称
    for name_file, name_key in [
        ("package.json", "name"),
        ("pyproject.toml", None),
    ]:
        candidate = Path(local_path) / name_file
        if candidate.exists():
            try:
                if name_file == "package.json":
                    import json
                    data = json.loads(candidate.read_text(encoding="utf-8", errors="ignore"))
                    if data.get("name"):
                        project_name = data["name"].replace("-", " ").replace("_", " ").title()
                        break
            except Exception:
                pass

    # 从 .uproject 文件名读取项目名
    uprojects = list(Path(local_path).glob("*.uproject"))
    if uprojects:
        project_name = uprojects[0].stem

    result["project_name"] = project_name

    # ── 2. VCS 检测（根路径）──────────────────────────────
    from vcs_detector import detect_vcs, scan_project_paths, VCSType
    from p4_manager import p4_manager

    root_vcs = await detect_vcs(local_path)
    result["root_vcs"] = root_vcs.value

    # git 信息
    if root_vcs == VCSType.GIT:
        result["git_repo_path"] = local_path
        rc, out, _ = await git_manager._run_git(local_path, "remote", "-v")
        if rc == 0 and out:
            seen = {}
            for line in out.strip().splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    seen[parts[0]] = parts[1]
            remotes = [{"name": n, "url": u} for n, u in seen.items()]
            result["git_remotes"] = remotes
            if remotes:
                result["git_remote_url"] = remotes[0]["url"]
    elif root_vcs == VCSType.P4:
        result["p4_root"] = local_path
        p4_info = await p4_manager.p4_info(cwd=local_path)
        if p4_info:
            result["p4_info"] = {
                "client": p4_info.get("Client name"),
                "server": p4_info.get("Server address"),
                "root": p4_info.get("Client root"),
            }

    # ── 3. 多路径扫描 ─────────────────────────────────────
    extra_paths = await scan_project_paths(local_path)
    result["extra_paths"] = extra_paths

    # ── 4. UE 引擎路径识别 ───────────────────────────────
    engine_path = None
    if uprojects:
        try:
            import json
            uproject_data = json.loads(uprojects[0].read_text(encoding="utf-8", errors="ignore"))
            engine_assoc = uproject_data.get("EngineAssociation", "")
            # 从注册表或默认安装路径查找引擎
            candidate_roots = [
                Path("C:/Program Files/Epic Games"),
                Path("D:/Program Files/Epic Games"),
                Path("E:/UE"),
                Path("D:/UE"),
                Path("F:/UE"),
            ]
            for root in candidate_roots:
                if not root.exists():
                    continue
                for child in root.iterdir():
                    if child.is_dir() and engine_assoc.lower() in child.name.lower():
                        engine_path = str(child)
                        break
                if engine_path:
                    break
            if engine_path:
                result["engine_path"] = engine_path
                result["engine_type"] = "UE5" if "5" in (engine_assoc or "") else "UE4"
                extra_paths.append({
                    "path": engine_path,
                    "vcs": "git",
                    "auto_detected": True,
                    "writable": False,
                    "label": f"UE 引擎 ({engine_assoc})",
                })
            else:
                result["engine_path_warning"] = f"未找到 UE 引擎路径（EngineAssociation={engine_assoc}），请手动配置"
        except Exception:
            pass

    # ── 5. traits 检测 ────────────────────────────────────
    try:
        from actions.chat.detect_project_type import ProjectTypeDetectorAction
        detector = ProjectTypeDetectorAction()
        detection = await detector.run({"repo_path": local_path})
        det_data = detection.data if detection.success else {}
        candidates = det_data.get("candidates", [])
        suggested_traits = [c["trait"] for c in candidates if c.get("confidence", 0) >= 0.7]
        result["traits"] = suggested_traits
        result["suggested_preset"] = det_data.get("suggested_preset")
        result["tech_stack"] = _infer_tech_stack(suggested_traits)
    except Exception as e:
        result["traits"] = []
        result["traits_warning"] = str(e)

    # ── 6. 推荐模式 ──────────────────────────────────────
    # 有现有代码的目录默认推荐手动挡
    has_code = any(
        Path(local_path).glob(pat)
        for pat in ["**/*.py", "**/*.js", "**/*.ts", "**/*.cpp", "**/*.cs"]
    )
    result["suggested_mode"] = "manual" if has_code else "auto"

    return result


def _infer_tech_stack(traits: list) -> str:
    """从 traits 推断 tech_stack 描述"""
    parts = []
    engine_map = {"engine:ue5": "Unreal Engine 5", "engine:unity": "Unity", "engine:godot": "Godot"}
    lang_map = {"lang:cpp": "C++", "lang:python": "Python", "lang:javascript": "JavaScript",
                "lang:typescript": "TypeScript", "lang:csharp": "C#", "lang:rust": "Rust"}
    fw_map = {"framework:react": "React", "framework:fastapi": "FastAPI",
              "framework:django": "Django", "framework:phaser": "Phaser"}
    for t in traits:
        if t in engine_map:
            parts.append(engine_map[t])
        elif t in lang_map:
            parts.append(lang_map[t])
        elif t in fw_map:
            parts.append(fw_map[t])
    return ", ".join(parts) if parts else ""


@router.patch("/{project_id}/mode")
async def update_project_mode(project_id: str, body: dict):
    """切换项目运行模式：auto（自动挡）或 manual（手动挡）"""
    from database import db as _db
    mode = body.get("mode", "auto")
    if mode not in ("auto", "manual"):
        raise HTTPException(400, "mode 必须是 auto 或 manual")
    await _db.update("projects", {"mode": mode}, "id = ?", (project_id,))
    return {"project_id": project_id, "mode": mode}


@router.patch("/{project_id}/extra-paths")
async def update_extra_paths(project_id: str, body: dict):
    """更新项目多路径配置"""
    import json as _json
    from database import db as _db
    extra_paths = body.get("extra_paths", [])
    await _db.update(
        "projects",
        {"extra_paths": _json.dumps(extra_paths, ensure_ascii=False)},
        "id = ?", (project_id,)
    )
    return {"project_id": project_id, "extra_paths": extra_paths}


# ==================== ConfigPack 管理 ====================

@router.get("/packs/{pack_name}/detail")
async def get_pack_detail(pack_name: str):
    """返回指定 Pack 的内容清单：agents / commands / skills / mcps / hooks / rules。"""
    from pack_installer import _PACKS_DIR
    pack_dir = _PACKS_DIR / pack_name
    if not pack_dir.exists():
        raise HTTPException(404, f"Pack '{pack_name}' 不存在")

    meta_file = pack_dir / "pack.json"
    if not meta_file.exists():
        raise HTTPException(404, f"Pack '{pack_name}' 缺少 pack.json")

    import re
    meta = json.loads(meta_file.read_text(encoding="utf-8"))

    CATEGORY_MAP = {
        "agents": "agents",
        "commands": "commands",
        "skills": "skills",
        "mcps": "mcps",
        "hooks": "hooks",
        "rules": "rules",
        "scripts": "scripts",
    }

    categories: dict = {k: [] for k in CATEGORY_MAP}

    def _extract_frontmatter(content: str) -> dict:
        if not content.startswith("---"):
            return {}
        end = content.find("\n---", 3)
        if end == -1:
            return {}
        fm_text = content[3:end].strip()
        result = {}
        for line in fm_text.splitlines():
            m = re.match(r'^(\w+)\s*:\s*(.+)$', line.strip())
            if m:
                result[m.group(1)] = m.group(2).strip().strip('"\'')
        return result

    for src_root_name in ("shared", "claude", "codebuddy"):
        src_root = pack_dir / src_root_name
        if not src_root.exists():
            continue
        scope = "" if src_root_name == "shared" else src_root_name

        for src_file in sorted(src_root.rglob("*")):
            if src_file.is_dir():
                continue
            rel = src_file.relative_to(src_root)
            parts = rel.parts

            if src_root_name == "shared" and src_file.name == "rules.md" and len(parts) == 1:
                try:
                    content = src_file.read_text(encoding="utf-8")
                    categories["rules"].append({
                        "name": f"{pack_name} rules",
                        "file": "rules.md",
                        "scope": "shared",
                        "description": "",
                        "emoji": "",
                        "color": "",
                        "content": content,
                    })
                except Exception:
                    pass
                continue

            if len(parts) < 2:
                continue
            cat_key = parts[0]
            if cat_key not in CATEGORY_MAP:
                continue

            try:
                content = src_file.read_text(encoding="utf-8")
            except Exception:
                content = ""

            fm = _extract_frontmatter(content) if src_file.suffix == ".md" else {}
            categories[cat_key].append({
                "name": fm.get("name") or src_file.stem.replace("-", " ").replace("_", " ").title(),
                "file": str(rel).replace("\\", "/"),
                "path": str(src_file).replace("\\", "/"),
                "scope": scope or "shared",
                "description": fm.get("description", ""),
                "emoji": fm.get("emoji", ""),
                "color": fm.get("color", ""),
                "preview": content[:200],
                "content": content,
            })

    return {
        "pack_name": pack_name,
        "meta": meta,
        "categories": {k: v for k, v in categories.items() if v},
    }


@router.get("/{project_id}/packs")
async def get_project_packs(project_id: str):
    """获取项目已安装的 ConfigPack 列表。"""
    from pack_installer import list_packs
    from skills import skill_loader
    rows = await db.fetch_all(
        "SELECT * FROM project_packs WHERE project_id = ? ORDER BY installed_at DESC",
        (project_id,)
    )
    all_packs = {p["name"]: p for p in list_packs()}

    # 预先汇总每个 pack 贡献哪些内置 rule/skill
    pack_rules: dict = {}
    for rid, rcfg in skill_loader.rules.items():
        pk = rcfg.get("pack") or ""
        if pk:
            pack_rules.setdefault(pk, []).append(rid)
    pack_skills: dict = {}
    for sid, scfg in skill_loader.skills.items():
        pk = scfg.get("pack") or ""
        if pk:
            pack_skills.setdefault(pk, []).append(sid)

    result = []
    for row in rows:
        meta = all_packs.get(row["pack_name"], {})
        result.append({
            "id": row["id"],
            "pack_name": row["pack_name"],
            "display_name": meta.get("display_name", row["pack_name"]),
            "description": meta.get("description", ""),
            "tags": meta.get("tags", []),
            "contains": meta.get("contains", []),
            "targets": json.loads(row.get("targets") or "[]"),
            "installed_at": row["installed_at"],
            "enabled_rules": pack_rules.get(row["pack_name"], []),
            "enabled_skills": pack_skills.get(row["pack_name"], []),
        })
    return {"packs": result}


@router.get("/{project_id}/packs/available")
async def get_available_packs(project_id: str):
    """获取可安装的 Pack 列表（排除已安装的），附带项目符合率。"""
    from pack_installer import list_packs, score_pack
    installed_rows = await db.fetch_all(
        "SELECT pack_name FROM project_packs WHERE project_id = ?", (project_id,)
    )
    installed_names = {r["pack_name"] for r in installed_rows}

    proj = await db.fetch_one(
        "SELECT traits, traits_confidence FROM projects WHERE id = ?", (project_id,)
    )
    project_traits: list = []
    if proj and proj.get("traits"):
        try:
            project_traits = json.loads(proj["traits"])
        except Exception:
            pass

    all_packs = list_packs()
    available = []
    for p in all_packs:
        if p["name"] in installed_names:
            continue
        score_info = score_pack(p, project_traits)
        p["match_score"] = score_info["match_score"]
        p["matched_traits"] = score_info["matched_traits"]
        p["is_recommended"] = score_info["is_recommended"]
        available.append(p)

    # 推荐的排前面，同组内按 match_score 降序
    available.sort(key=lambda x: (-x["match_score"], x.get("display_name") or x.get("name", "")))
    return {"packs": available}



@router.get("/{project_id}/agents/all")
async def get_project_agents_all(project_id: str):
    """合并三个来源的 Agent 列表：内置 / 用户（.claude/.codebuddy）/ Pack（已安装）。
    每个 agent 标注 source、pack_name、override_by。
    """
    import re
    from pack_installer import _PACKS_DIR

    proj = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not proj:
        raise HTTPException(404, "项目不存在")
    repo_path = proj.get("git_repo_path", "")

    def _parse_frontmatter(content: str) -> dict:
        if not content.startswith("---"):
            return {}
        end = content.find("\n---", 3)
        if end == -1:
            return {}
        fm_text = content[3:end].strip()
        result = {}
        for line in fm_text.splitlines():
            m = re.match(r'^(\w[\w-]*)\s*:\s*(.+)$', line.strip())
            if m:
                result[m.group(1)] = m.group(2).strip().strip('"\'')
        return result

    def _scan_agents_dir(agents_dir: Path) -> list:
        items = []
        if not agents_dir.exists():
            return items
        for f in sorted(agents_dir.glob("*.md")):
            try:
                content = f.read_text(encoding="utf-8")
            except Exception:
                continue
            fm = _parse_frontmatter(content)
            # 剥离 frontmatter（--- ... --- 块），取正文
            if content.startswith("---"):
                end = content.find("\n---", 3)
                body = content[end + 4:].strip() if end != -1 else content
            else:
                body = content.strip()
            items.append({
                "name": fm.get("name") or f.stem,
                "file": f.name,
                "path": str(f).replace("\\", "/"),
                "description": fm.get("description", ""),
                "model": fm.get("model", ""),
                "color": fm.get("color", ""),
                "emoji": fm.get("emoji", ""),
                "preview": body[:200],
                "content": content,
            })
        return items

    # ── 1. 内置 Agent（ADS 系统 orchestrator）──────────────────────────────
    builtin_agents = []
    try:
        from orchestrator import orchestrator
        icons = {"ProductAgent":"📝","ArchitectAgent":"🏗️","DevAgent":"💻",
                 "TestAgent":"🧪","ReviewAgent":"🔍","DeployAgent":"🚀","ChatAssistant":"💬"}
        roles = {"ProductAgent":"产品经理 — 需求拆单 + 产品验收",
                 "ArchitectAgent":"架构师 — 增量架构设计",
                 "DevAgent":"开发工程师 — 代码开发 + 自测",
                 "TestAgent":"测试工程师 — 5层质量测试",
                 "ReviewAgent":"代码审查 — 读取实际代码审查",
                 "DeployAgent":"运维工程师 — 三环境部署",
                 "ChatAssistant":"AI 助手 — 聊天 + 工具调用"}
        for name, agent in orchestrator.agents.items():
            builtin_agents.append({
                "name": name,
                "description": roles.get(name, name),
                "emoji": icons.get(name, "🤖"),
                "source": "builtin",
                "pack_name": None,
                "react_mode": agent.react_mode.value if hasattr(agent.react_mode, "value") else "single",
                "actions": agent.list_actions(),
            })
    except Exception:
        pass

    # ── 2. 用户 Agent + Pack Agent（均扫项目目录，通过与 pack 库比对区分来源）────
    user_agents = []
    pack_agents = []
    if repo_path:
        installed_pack_names = [
            r["pack_name"] for r in await db.fetch_all(
                "SELECT pack_name FROM project_packs WHERE project_id = ?", (project_id,)
            )
        ]
        for cli in ("claude", "codebuddy"):
            agents_dir = Path(repo_path) / f".{cli}" / "agents"
            for item in _scan_agents_dir(agents_dir):
                # 检查是否来自某个已安装 pack
                pack_origin = None
                stem = Path(item["file"]).stem
                for pn in installed_pack_names:
                    for sub in ("shared", "claude", "codebuddy"):
                        candidate = _PACKS_DIR / pn / sub / "agents" / f"{stem}.md"
                        if candidate.exists():
                            pack_origin = pn
                            break
                    if pack_origin:
                        break
                item["cli"] = cli
                if pack_origin:
                    item["source"] = "pack"
                    item["pack_name"] = pack_origin
                    pack_agents.append(item)
                else:
                    item["source"] = "user"
                    item["pack_name"] = None
                    user_agents.append(item)

    # ── 4. 覆盖关系检测（同名时：用户 > Pack > 内置）──────────────────────
    all_agents = builtin_agents + pack_agents + user_agents
    # 优先级：builtin=0 pack=1 user=2（数字越大优先级越高）
    priority = {"builtin": 0, "pack": 1, "user": 2}
    name_map: dict = {}
    for ag in all_agents:
        n = ag["name"]
        if n not in name_map:
            name_map[n] = []
        name_map[n].append(ag)

    for n, group in name_map.items():
        if len(group) > 1:
            group.sort(key=lambda x: priority.get(x["source"], 0), reverse=True)
            winner = group[0]["source"]
            for ag in group:
                if ag["source"] == winner and group.index(ag) == 0:
                    ag["override_by"] = None
                    ag["is_active"] = True
                else:
                    ag["override_by"] = winner
                    ag["is_active"] = False
        else:
            group[0]["override_by"] = None
            group[0]["is_active"] = True

    return {
        "builtin": builtin_agents,
        "user": user_agents,
        "pack": pack_agents,
        "all": all_agents,
        "counts": {
            "builtin": len(builtin_agents),
            "user": len(user_agents),
            "pack": len(pack_agents),
            "total": len(all_agents),
        }
    }



@router.get("/{project_id}/skills/all")
async def get_project_skills_all(project_id: str):
    """合并三来源 Skill：内置(global/custom) / 用户(.claude/.codebuddy skills/) / Pack。"""
    from pack_installer import _PACKS_DIR
    import re
    import json as _json

    proj = await db.fetch_one("SELECT git_repo_path, extra_paths FROM projects WHERE id = ?", (project_id,))
    repo_path = (proj or {}).get("git_repo_path", "") if proj else ""
    # 合并所有项目路径（git_repo_path + extra_paths）
    all_repo_paths = [repo_path] if repo_path else []
    try:
        extra = _json.loads((proj or {}).get("extra_paths") or "[]")
        all_repo_paths += [p["path"] for p in extra if isinstance(p, dict) and p.get("path")]
    except Exception:
        pass

    def _parse_skill_md(content: str, stem: str) -> dict:
        fm: dict = {}
        if content.startswith("---"):
            end = content.find("\n---", 3)
            if end != -1:
                for line in content[3:end].splitlines():
                    m = re.match(r'^([\w-]+)\s*:\s*(.+)$', line.strip())
                    if m:
                        fm[m.group(1)] = m.group(2).strip().strip('"\'')
        body = re.sub(r'^---[\s\S]*?---\r?\n?', '', content, count=1).strip()
        return {
            "name": fm.get("name") or stem.replace("-", " ").replace("_", " ").title(),
            "description": fm.get("description", ""),
            "preview": body[:150],
        }

    # 1. 内置 skills（现有接口数据 + prompt 内容 + 文件路径）
    builtin_skills = []
    try:
        from skills import skill_loader
        all_status = skill_loader.get_all_skills_status()
        for sid, info in all_status.items():
            # 读取 prompt 内容
            content = ""
            file_path = ""
            try:
                cfg = skill_loader.skills.get(sid, {})
                if cfg.get("type") == "marketplace_item":
                    fp = cfg.get("file_path", "")
                    file_path = fp
                    content = Path(fp).read_text(encoding="utf-8") if fp and Path(fp).exists() else ""
                else:
                    prompt_rel = cfg.get("prompt_file", "")
                    if prompt_rel:
                        fp = skill_loader.base_dir / prompt_rel
                        file_path = str(fp)
                        content = fp.read_text(encoding="utf-8") if fp.exists() else ""
                if not content:
                    content = skill_loader.get_skill_prompt(sid) or ""
            except Exception:
                pass
            builtin_skills.append({
                "id": sid, "name": info["name"], "description": info["description"],
                "source": "builtin", "pack_name": None,
                "enabled": info["enabled"], "priority": info["priority"],
                "file": file_path, "content": content[:4000], "preview": content[:150],
            })
    except Exception:
        pass

    # ── 通用：扫描某个 skills 目录，返回 skill 条目列表 ──────────────────────
    # pack 来源判断：提前查一次，避免 N+1
    _installed_packs = [r["pack_name"] for r in await db.fetch_all(
        "SELECT pack_name FROM project_packs WHERE project_id = ?", (project_id,)
    )]

    async def _scan_skills_dir(skills_dir: Path, default_source: str, base_path: Path | None = None) -> list:
        result = []
        if not skills_dir.exists():
            return result
        try:
            entries = sorted(skills_dir.iterdir())
        except PermissionError:
            return result
        for skill_dir in entries:
            skill_md = (skill_dir / "SKILL.md" if skill_dir.is_dir()
                        else (skill_dir if skill_dir.suffix == ".md" else None))
            if not skill_md or not skill_md.exists():
                continue
            stem = skill_dir.stem
            pack_origin = None
            for pn in _installed_packs:
                for sub in ("shared", "claude", "codebuddy"):
                    candidate = _PACKS_DIR / pn / sub / "skills" / stem / "SKILL.md"
                    if candidate.exists():
                        pack_origin = pn
                        break
                if pack_origin:
                    break
            try:
                content = skill_md.read_text(encoding="utf-8")
                info = _parse_skill_md(content, stem)
                info["source"] = "pack" if pack_origin else (
                    "openspec" if stem.lower().startswith("openspec") or "openspec" in str(skills_dir).lower()
                    else default_source
                )
                info["pack_name"] = pack_origin
                info["id"] = info["name"]
                info["file"] = str(skill_md)
                info["path"] = str(skill_md).replace("\\", "/")
                info["content"] = content[:4000]   # 截断避免响应过大
                # 相对路径：优先相对 base_path，否则相对 skills_dir 父目录
                try:
                    rel_base = base_path or skills_dir.parent.parent
                    info["rel_path"] = str(skill_md.relative_to(rel_base)).replace("\\", "/")
                except ValueError:
                    info["rel_path"] = str(skill_md).replace("\\", "/")
                result.append(info)
            except Exception:
                pass
        return result

    # 2. 项目 skills（所有项目路径 .claude/skills/ + .codebuddy/skills/）
    project_skills = []
    for rp in all_repo_paths:
        rp_path = Path(rp)
        for cli in ("claude", "codebuddy"):
            project_skills += await _scan_skills_dir(
                rp_path / f".{cli}" / "skills", "project", base_path=rp_path
            )

    # 3. 用户 skills（系统用户主目录 ~/.claude/skills/ + ~/.codebuddy/skills/）
    user_skills = []
    home = Path.home()
    for cli in ("claude", "codebuddy"):
        user_skills += await _scan_skills_dir(
            home / f".{cli}" / "skills", "user", base_path=home
        )

    # 4. Pack + OpenSpec skills — 从 project_skills / user_skills 中分拆
    pack_skills = (
        [s for s in project_skills if s.get("source") == "pack"] +
        [s for s in user_skills    if s.get("source") == "pack"]
    )
    openspec_skills = (
        [s for s in project_skills if s.get("source") == "openspec"] +
        [s for s in user_skills    if s.get("source") == "openspec"]
    )
    project_skills = [s for s in project_skills if s.get("source") not in ("pack", "openspec")]
    user_skills    = [s for s in user_skills    if s.get("source") not in ("pack", "openspec")]

    # 去重：同一文件路径可能因 .claude/.codebuddy 双目录或 extra_paths 重复扫描
    def _dedup(lst: list) -> list:
        seen: set = set()
        out = []
        for s in lst:
            key = s.get("file") or s.get("name")
            if key not in seen:
                seen.add(key)
                out.append(s)
        return out

    project_skills  = _dedup(project_skills)
    user_skills     = _dedup(user_skills)
    pack_skills     = _dedup(pack_skills)
    openspec_skills = _dedup(openspec_skills)

    all_skills = builtin_skills + project_skills + user_skills + pack_skills + openspec_skills
    return {
        "builtin":  builtin_skills,
        "project":  project_skills,
        "user":     user_skills,
        "pack":     pack_skills,
        "openspec": openspec_skills,
        "all":      all_skills,
        "counts": {
            "builtin":  len(builtin_skills),
            "project":  len(project_skills),
            "user":     len(user_skills),
            "pack":     len(pack_skills),
            "openspec": len(openspec_skills),
            "total":    len(all_skills),
        },
    }


@router.get("/{project_id}/commands/all")
async def get_project_commands_all(project_id: str):
    """合并三来源 Command：内置(system) / 用户(.claude/.codebuddy commands/) / Pack。"""
    from pack_installer import _PACKS_DIR
    import re

    proj = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id = ?", (project_id,))
    repo_path = (proj or {}).get("git_repo_path", "") if proj else ""

    def _parse_cmd_md(content: str, stem: str) -> dict:
        fm: dict = {}
        if content.startswith("---"):
            end = content.find("\n---", 3)
            if end != -1:
                for line in content[3:end].splitlines():
                    m = re.match(r'^([\w-]+)\s*:\s*(.+)$', line.strip())
                    if m:
                        fm[m.group(1)] = m.group(2).strip().strip('"\'')
        body = re.sub(r'^---[\s\S]*?---\r?\n?', '', content, count=1).strip()
        return {
            "name": stem,
            "description": fm.get("description", ""),
            "preview": body[:150],
        }

    # 1. 内置 + 用户 commands（现有 get_all_commands，补充 file 和 content）
    builtin_cmds, user_cmds = [], []
    try:
        from api.commands import get_all_commands, _BUILTIN_COMMANDS, _load_disk_commands, _load_project_commands
        from pathlib import Path as _Path

        # 构建 name→文件路径映射（支持子目录，name 用相对路径 subdir/stem）
        _cmd_file_map: dict = {}
        _skills_cmds_dir = _Path(__file__).resolve().parent.parent / "skills" / "commands"
        if _skills_cmds_dir.exists():
            for f in _skills_cmds_dir.glob("*.md"):
                _cmd_file_map[f.stem] = str(f)
        if repo_path:
            for cli_dir in [".claude/commands", ".codebuddy/commands", ".ads/commands"]:
                d = _Path(repo_path) / cli_dir
                if d.exists():
                    for f in d.rglob("*.md"):
                        rel = f.relative_to(d)
                        parts = list(rel.parts)
                        parts[-1] = f.stem
                        name_key = "/".join(parts)
                        _cmd_file_map[name_key] = str(f)

        all_cmds = get_all_commands(repo_path=repo_path)
        builtin_names = set(_BUILTIN_COMMANDS.keys())
        for name, info in all_cmds.items():
            src = info.get("source", "system")
            fp = _cmd_file_map.get(name, "")
            content = ""
            try:
                if fp:
                    content = _Path(fp).read_text(encoding="utf-8")
            except Exception:
                pass
            entry = {"name": name, "description": info.get("description", ""),
                     "pack_name": None, "source": src,
                     "file": fp, "content": content, "preview": content[:150]}
            if src == "openspec":
                entry["source"] = "openspec"
                user_cmds.append(entry)
            elif src in ("claude", "ads", "codebuddy"):
                entry["source"] = "project"
                user_cmds.append(entry)
            elif name not in builtin_names:
                entry["source"] = "user"
                user_cmds.append(entry)
            else:
                entry["source"] = "builtin"
                builtin_cmds.append(entry)
    except Exception:
        pass

    # 2. Pack commands — 从 user_cmds 里识别来自 pack 的（对比 pack 库目录同名文件）
    pack_cmds = []
    if repo_path:
        installed_pack_names = [
            r["pack_name"] for r in await db.fetch_all(
                "SELECT pack_name FROM project_packs WHERE project_id = ?", (project_id,)
            )
        ]
        # 重新分类 user_cmds：若同名文件存在于某个 pack 库目录，则归为 pack 来源
        remaining_user = []
        for entry in user_cmds:
            pack_origin = None
            name = entry["name"]
            for pn in installed_pack_names:
                for sub in ("shared", "claude", "codebuddy"):
                    candidate = _PACKS_DIR / pn / sub / "commands" / f"{name}.md"
                    if candidate.exists():
                        pack_origin = pn
                        break
                if pack_origin:
                    break
            if pack_origin:
                entry["source"] = "pack"
                entry["pack_name"] = pack_origin
                pack_cmds.append(entry)
            else:
                remaining_user.append(entry)
        user_cmds = remaining_user

    project_cmds  = [e for e in user_cmds if e.get("source") == "project"]
    openspec_cmds = [e for e in user_cmds if e.get("source") == "openspec"]
    user_cmds     = [e for e in user_cmds if e.get("source") not in ("project", "openspec")]

    all_cmds_list = builtin_cmds + project_cmds + user_cmds + pack_cmds + openspec_cmds
    return {
        "builtin": builtin_cmds, "project": project_cmds, "user": user_cmds,
        "pack": pack_cmds, "openspec": openspec_cmds, "all": all_cmds_list,
        "counts": {"builtin": len(builtin_cmds), "project": len(project_cmds),
                   "user": len(user_cmds), "pack": len(pack_cmds),
                   "openspec": len(openspec_cmds), "total": len(all_cmds_list)},
    }


@router.get("/{project_id}/mcp/all")
async def get_project_mcp_all(project_id: str):
    """合并三来源 MCP：内置(全局 mcp_servers.json) / 用户(settings.json mcpServers) / Pack。"""
    from pack_installer import _PACKS_DIR

    proj = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id = ?", (project_id,))
    repo_path = (proj or {}).get("git_repo_path", "") if proj else ""

    # 1. 内置 MCP（全局 mcp_client）
    builtin_mcps = []
    try:
        from mcp_client import mcp_client
        status = mcp_client.get_status()
        for name, info in (status.get("servers") or {}).items():
            builtin_mcps.append({
                "name": name, "description": info.get("description", ""),
                "status": info.get("status", "unknown"), "tools": info.get("tools", []),
                "source": "builtin", "pack_name": None,
            })
    except Exception:
        pass

    # 2. 用户 / 项目 MCP —— 复用 mcp_client 的多路解析
    #    （用户级 ~/.codebuddy、~/.claude + 项目 .claude/.codebuddy/.ads）
    #    敏感值（headers/env/token）不返回给前端。
    user_mcps = []
    try:
        from mcp_client import _load_project_mcp_config
        builtin_names = {m["name"] for m in builtin_mcps}
        merged = _load_project_mcp_config(repo_path or "")
        for name, cfg in merged.items():
            if name in builtin_names:
                continue  # 已在内置中
            src = cfg.get("_source", "user")
            transport = (cfg.get("type") or cfg.get("transportType")
                         or ("stdio" if cfg.get("command") else "http"))
            user_mcps.append({
                "name": name,
                "description": cfg.get("description", ""),
                "command": cfg.get("command", ""),      # 命令本身非敏感
                "transport": transport,
                "enabled": bool(cfg.get("enabled", True)),
                "source": "user",
                "cli": "codebuddy" if "codebuddy" in src else ("claude" if "claude" in src else src),
                "config_source": src,                   # user:codebuddy / claude / ads ...
                "pack_name": None,
                # 注意：不返回 headers / env / url token 等敏感字段
            })
    except Exception as e:
        logger.debug("加载用户/项目 MCP 失败: %s", e)

    # 3. Pack MCP（pack 的 shared/mcps/*.json 声明）
    pack_mcps = []
    installed_rows = await db.fetch_all(
        "SELECT pack_name FROM project_packs WHERE project_id = ?", (project_id,)
    )
    for row in installed_rows:
        pn = row["pack_name"]
        for sub in ("shared", "claude", "codebuddy"):
            mcps_dir = _PACKS_DIR / pn / sub / "mcps"
            if not mcps_dir.exists():
                continue
            for f in sorted(mcps_dir.glob("*.json")):
                try:
                    mcp_data = json.loads(f.read_text(encoding="utf-8"))
                    for name, cfg in mcp_data.items():
                        pack_mcps.append({
                            "name": name,
                            "description": cfg.get("description", ""),
                            "command": cfg.get("command", ""),
                            "source": "pack", "pack_name": pn, "scope": sub,
                        })
                except Exception:
                    pass

    all_mcps = builtin_mcps + user_mcps + pack_mcps
    return {
        "builtin": builtin_mcps, "user": user_mcps, "pack": pack_mcps, "all": all_mcps,
        "counts": {"builtin": len(builtin_mcps), "user": len(user_mcps),
                   "pack": len(pack_mcps), "total": len(all_mcps)},
    }


@router.get("/{project_id}/rules/all")
async def get_project_rules_all(project_id: str):
    """合并三来源 Rule：内置(backend/skills/rules/) / 用户(.claude/rules/) / Pack(rules/)。"""
    from pack_installer import _PACKS_DIR
    import re

    proj = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id = ?", (project_id,))
    repo_path = (proj or {}).get("git_repo_path", "") if proj else ""

    def _parse_rule_md(content: str, stem: str) -> dict:
        fm: dict = {}
        if content.startswith("---"):
            end = content.find("\n---", 3)
            if end != -1:
                for line in content[3:end].splitlines():
                    m = re.match(r'^([\w-]+)\s*:\s*(.+)$', line.strip())
                    if m:
                        fm[m.group(1)] = m.group(2).strip().strip('"\'')
        body = re.sub(r'^---[\s\S]*?---\r?\n?', '', content, count=1).strip()
        return {
            "name": fm.get("name") or fm.get("title") or stem.replace("-", " ").replace("_", " ").title(),
            "description": fm.get("description", ""),
            "globs": fm.get("globs", ""),
            "preview": body[:150],
            "content": content,
        }

    def _scan_rules_dir(rules_dir: Path, source: str, pack_name=None, cli=None, scope=None) -> list:
        items = []
        if not rules_dir.exists():
            return items
        for f in sorted(rules_dir.rglob("*.md")):
            try:
                content = f.read_text(encoding="utf-8")
                info = _parse_rule_md(content, f.stem)
                info["file"] = str(f)
                info["source"] = source
                info["pack_name"] = pack_name
                if cli:
                    info["cli"] = cli
                if scope:
                    info["scope"] = scope
                items.append(info)
            except Exception:
                pass
        return items

    # 1. 内置 rules（backend/skills/rules/*.md，排除 yaml）
    builtin_rules = []
    builtin_rules_dir = Path(__file__).resolve().parent.parent / "skills" / "rules"
    for f in sorted(builtin_rules_dir.rglob("*.md")):
        try:
            content = f.read_text(encoding="utf-8")
            info = _parse_rule_md(content, f.stem)
            info["file"] = str(f)
            info["source"] = "builtin"
            info["pack_name"] = None
            builtin_rules.append(info)
        except Exception:
            pass

    # 2. 项目 rules（仓库 .claude/rules/ + .codebuddy/rules/）
    project_rules = []
    if repo_path:
        for cli in ("claude", "codebuddy"):
            project_rules += _scan_rules_dir(
                Path(repo_path) / f".{cli}" / "rules",
                source="project", cli=cli
            )
        # 也扫 CLAUDE.md / CODEBUDDY.md（主记忆文件）
        for cli, fname in [("claude", "CLAUDE.md"), ("codebuddy", "CODEBUDDY.md")]:
            f = Path(repo_path) / f".{cli}" / fname
            if f.exists():
                try:
                    content = f.read_text(encoding="utf-8")
                    project_rules.append({
                        "name": fname, "description": "项目主记忆文件（Pack rules 追加于此）",
                        "file": str(f), "source": "project", "cli": cli, "pack_name": None,
                        "content": content, "preview": content[:150], "globs": "",
                    })
                except Exception:
                    pass

    # 3. Pack rules
    pack_rules = []
    installed_rows = await db.fetch_all(
        "SELECT pack_name FROM project_packs WHERE project_id = ?", (project_id,)
    )
    for row in installed_rows:
        pn = row["pack_name"]
        for sub in ("shared", "claude", "codebuddy"):
            # rules.md 单文件
            rules_md = _PACKS_DIR / pn / sub / "rules.md"
            if rules_md.exists():
                try:
                    content = rules_md.read_text(encoding="utf-8")
                    info = _parse_rule_md(content, f"{pn}-rules")
                    info["file"] = str(rules_md)
                    info["source"] = "pack"
                    info["pack_name"] = pn
                    info["scope"] = sub
                    pack_rules.append(info)
                except Exception:
                    pass
            # rules/ 子目录
            pack_rules += _scan_rules_dir(
                _PACKS_DIR / pn / sub / "rules",
                source="pack", pack_name=pn, scope=sub
            )

    all_rules = builtin_rules + project_rules + pack_rules
    return {
        "builtin": builtin_rules, "project": project_rules, "pack": pack_rules, "all": all_rules,
        "counts": {"builtin": len(builtin_rules), "project": len(project_rules),
                   "pack": len(pack_rules), "total": len(all_rules)},
    }


@router.get("/{project_id}/hooks/all")
async def get_project_hooks_all(project_id: str):
    """合并三来源 Hook 配置：内置(全局 settings.json) / 用户(项目 .claude/.codebuddy settings.json) / Pack。
    每个条目表示一个 hook 事件绑定，字段：event / matcher / command / source / pack_name / file。
    """
    from pack_installer import _PACKS_DIR
    import json as _json

    proj = await db.fetch_one("SELECT git_repo_path, extra_paths FROM projects WHERE id = ?", (project_id,))
    repo_path = (proj or {}).get("git_repo_path", "") if proj else ""
    all_repo_paths = [repo_path] if repo_path else []
    try:
        extra = _json.loads((proj or {}).get("extra_paths") or "[]")
        all_repo_paths += [p["path"] for p in extra if isinstance(p, dict) and p.get("path")]
    except Exception:
        pass

    def _flatten_hooks(hooks_obj: dict, source: str, file: str, pack_name=None) -> list:
        """将 settings.json hooks 对象展开为条目列表。
        格式：{ "EventName": [ { "matcher": "...", "hooks": [ {"type":"command","command":"..."} ] } ] }
        """
        items = []
        if not isinstance(hooks_obj, dict):
            return items
        for event, bindings in hooks_obj.items():
            if not isinstance(bindings, list):
                continue
            for binding in bindings:
                if not isinstance(binding, dict):
                    continue
                matcher = binding.get("matcher") or binding.get("tool_name") or ""
                for h in (binding.get("hooks") or []):
                    cmd = h.get("command", "")
                    items.append({
                        "name": f"{event}" + (f" [{matcher}]" if matcher else ""),
                        "event": event,
                        "matcher": matcher,
                        "command": cmd,
                        "hook_type": h.get("type", "command"),
                        "timeout": h.get("timeout"),
                        "description": cmd[:120] if cmd else "",
                        "source": source,
                        "pack_name": pack_name,
                        "file": file,
                        "rel_path": "",
                        "content": _json.dumps(h, ensure_ascii=False),
                        "preview": cmd[:150],
                    })
        return items

    def _read_settings_hooks(settings_path: Path, source: str, base_path: Path | None = None, pack_name=None) -> list:
        if not settings_path.exists():
            return []
        try:
            data = _json.loads(settings_path.read_text(encoding="utf-8"))
            hooks_obj = data.get("hooks", {})
            items = _flatten_hooks(hooks_obj, source, str(settings_path), pack_name)
            for item in items:
                try:
                    rel = settings_path.relative_to(base_path or settings_path.parent)
                    item["rel_path"] = str(rel).replace("\\", "/")
                except ValueError:
                    item["rel_path"] = str(settings_path).replace("\\", "/")
            return items
        except Exception:
            return []

    # 1. 内置 hooks：系统用户主目录 ~/.claude/settings.json + ~/.codebuddy/settings.json
    home = Path.home()
    builtin_hooks: list = []
    for cli in ("claude", "codebuddy"):
        builtin_hooks += _read_settings_hooks(
            home / f".{cli}" / "settings.json",
            source="builtin", base_path=home,
        )

    # 2. 项目 hooks：项目仓库 .claude/settings.json + .codebuddy/settings.json
    project_hooks: list = []
    seen_files: set = set()
    for rp in all_repo_paths:
        rp_path = Path(rp)
        for cli in ("claude", "codebuddy"):
            sf = rp_path / f".{cli}" / "settings.json"
            if str(sf) in seen_files:
                continue
            seen_files.add(str(sf))
            project_hooks += _read_settings_hooks(sf, source="project", base_path=rp_path)

    # 3. Pack hooks：pack shared/hooks/*.json
    pack_hooks: list = []
    installed_rows = await db.fetch_all(
        "SELECT pack_name FROM project_packs WHERE project_id = ?", (project_id,)
    )
    for row in installed_rows:
        pn = row["pack_name"]
        for sub in ("shared", "claude", "codebuddy"):
            hooks_dir = _PACKS_DIR / pn / sub / "hooks"
            if not hooks_dir.exists():
                continue
            for hf in sorted(hooks_dir.glob("*.json")):
                try:
                    data = _json.loads(hf.read_text(encoding="utf-8"))
                    hooks_obj = data.get("hooks", data)  # 有些直接是 hooks 对象
                    items = _flatten_hooks(hooks_obj, "pack", str(hf), pack_name=pn)
                    for item in items:
                        try:
                            item["rel_path"] = str(hf.relative_to(_PACKS_DIR / pn)).replace("\\", "/")
                        except ValueError:
                            pass
                    pack_hooks += items
                except Exception:
                    pass

    all_hooks = builtin_hooks + project_hooks + pack_hooks
    return {
        "builtin": builtin_hooks,
        "project": project_hooks,
        "pack": pack_hooks,
        "all": all_hooks,
        "counts": {
            "builtin": len(builtin_hooks),
            "project": len(project_hooks),
            "pack": len(pack_hooks),
            "total": len(all_hooks),
        },
    }


@router.post("/{project_id}/packs/{pack_name}/install")
async def install_pack_for_project(project_id: str, pack_name: str):
    """手动安装指定 Pack 到项目。"""
    from pack_installer import install_pack
    from utils import generate_id, now_iso
    from events import event_manager

    proj = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not proj:
        raise HTTPException(404, "项目不存在")

    repo_path = proj.get("git_repo_path", "")
    if not repo_path:
        raise HTTPException(400, "项目缺少本地路径，无法安装 Pack")

    ctx = {
        "project_name": proj.get("name", ""),
        "repo_path": repo_path,
        "tech_stack": proj.get("tech_stack", ""),
        "git_remote": proj.get("git_remote_url", ""),
    }

    async def _push_log(message: str, level: str = "info"):
        log_id = generate_id("LOG")
        created_at = now_iso()
        detail = json.dumps({"message": message}, ensure_ascii=False)
        await db.insert("ticket_logs", {
            "id": log_id,
            "ticket_id": None,
            "subtask_id": None,
            "requirement_id": None,
            "project_id": project_id,
            "agent_type": "ConfigPack",
            "action": "install_pack",
            "from_status": None,
            "to_status": None,
            "detail": detail,
            "level": level,
            "created_at": created_at,
        })
        await event_manager.publish_to_project(project_id, "log_added", {
            "id": log_id,
            "agent_type": "ConfigPack",
            "action": "install_pack",
            "detail": detail,
            "level": level,
            "created_at": created_at,
        })

    # 读取 pack 元信息用于日志
    from pack_installer import _PACKS_DIR
    _pack_meta: dict = {}
    try:
        _pack_meta = json.loads((_PACKS_DIR / pack_name / "pack.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    _version = _pack_meta.get("version", "")
    _declared_targets = _pack_meta.get("targets", [])

    await _push_log(
        f"▶ 开始安装 ConfigPack: {pack_name}"
        + (f" v{_version}" if _version else "")
        + (f"  [声明目标: {', '.join(_declared_targets)}]" if _declared_targets else "")
    )
    # 显示哪些目录已存在、哪些会被新建
    _cli_found = [c for c in _declared_targets if (Path(repo_path) / f".{c}").exists()]
    _cli_new = [c for c in _declared_targets if c not in _cli_found]
    if _cli_found:
        await _push_log(f"  已有 CLI 目录: {', '.join('.'+c for c in _cli_found)}")
    if _cli_new:
        await _push_log(f"  将新建 CLI 目录: {', '.join('.'+c for c in _cli_new)}")

    result = install_pack(pack_name, repo_path, ctx)

    if not result["success"]:
        err_msg = "; ".join(result.get("errors", ["安装失败"]))
        await _push_log(f"✗ 安装失败: {err_msg}", level="error")
        raise HTTPException(400, err_msg)

    # 记录复制的文件
    copied = result.get("copied_files", [])
    for f in copied:
        await _push_log(f"  → {f}")

    targets_str = ", ".join(result.get("installed_targets", []))
    await _push_log(f"✓ 安装完成 [{targets_str}]，共 {len(copied)} 个文件")

    if result.get("skipped"):
        for s in result["skipped"]:
            await _push_log(f"  跳过: {s}", level="warn")
    if result.get("errors"):
        for e in result["errors"]:
            await _push_log(f"  ⚠ {e}", level="warn")

    # 检查是否已有记录（重装场景）
    existing = await db.fetch_one(
        "SELECT id FROM project_packs WHERE project_id = ? AND pack_name = ?",
        (project_id, pack_name)
    )
    now = now_iso()
    if existing:
        await db.update(
            "project_packs",
            {"installed_at": now, "targets": json.dumps(result.get("installed_targets", []))},
            "project_id = ? AND pack_name = ?", (project_id, pack_name)
        )
    else:
        await db.insert("project_packs", {
            "id": generate_id("PKG"),
            "project_id": project_id,
            "pack_name": pack_name,
            "installed_at": now,
            "targets": json.dumps(result.get("installed_targets", []), ensure_ascii=False),
        })

    # 更新 projects.installed_packs 冗余列
    all_packs_rows = await db.fetch_all(
        "SELECT pack_name FROM project_packs WHERE project_id = ?", (project_id,)
    )
    installed_names = [r["pack_name"] for r in all_packs_rows]
    await db.update(
        "projects",
        {"installed_packs": json.dumps(installed_names, ensure_ascii=False), "updated_at": now},
        "id = ?", (project_id,)
    )

    return {
        "success": True,
        "pack_name": pack_name,
        "installed_targets": result.get("installed_targets", []),
        "skipped": result.get("skipped", []),
    }


@router.delete("/{project_id}/packs/{pack_name}")
async def uninstall_pack_record(project_id: str, pack_name: str):
    """从记录中移除 Pack（不删除已 copy 的文件，文件归用户所有）。"""
    from utils import now_iso, generate_id
    from events import event_manager

    await db.delete("project_packs", "project_id = ? AND pack_name = ?", (project_id, pack_name))
    # 更新冗余列
    rows = await db.fetch_all(
        "SELECT pack_name FROM project_packs WHERE project_id = ?", (project_id,)
    )
    installed_names = [r["pack_name"] for r in rows]
    await db.update(
        "projects",
        {"installed_packs": json.dumps(installed_names, ensure_ascii=False), "updated_at": now_iso()},
        "id = ?", (project_id,)
    )
    # 写操作日志
    log_id = generate_id("LOG")
    created_at = now_iso()
    detail = json.dumps({"message": f"✕ 移除 ConfigPack 记录: {pack_name}（已安装的文件不受影响）"}, ensure_ascii=False)
    await db.insert("ticket_logs", {
        "id": log_id, "ticket_id": None, "subtask_id": None, "requirement_id": None,
        "project_id": project_id, "agent_type": "ConfigPack", "action": "remove_pack",
        "from_status": None, "to_status": None, "detail": detail, "level": "info",
        "created_at": created_at,
    })
    await event_manager.publish_to_project(project_id, "log_added", {
        "id": log_id, "agent_type": "ConfigPack", "action": "remove_pack",
        "detail": detail, "level": "info", "created_at": created_at,
    })
    return {"success": True, "note": "记录已移除，已安装的文件不受影响（文件归用户所有）"}
