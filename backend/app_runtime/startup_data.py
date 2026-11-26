"""启动时恢复项目设置、补录索引并同步资源。"""
import json
import logging

from config import settings

logger = logging.getLogger("main")


async def restore_project_repositories(db):
    from git_manager import PROJECTS_DIR, git_manager
    logger.info("Git 项目仓库目录: %s", PROJECTS_DIR)

    # 从数据库恢复自定义 git_repo_path 映射 + push remote 配置
    projects = await db.fetch_all(
        "SELECT id, git_repo_path, git_remote_url, git_remotes, git_push_remote FROM projects"
    )
    restored = 0
    for p in projects:
        repo_path = p.get("git_repo_path") or ""
        if repo_path:
            default_path = str(PROJECTS_DIR / p["id"])
            if repo_path != default_path:
                git_manager.set_project_path(p["id"], repo_path)
                restored += 1

        # 恢复 push remote 配置
        push_remote = p.get("git_push_remote") or "origin"
        git_manager.set_push_remote(p["id"], push_remote)

        # 补全旧数据：git_remotes 空但 git_remote_url 有值 → 自动迁移
        git_remotes_raw = p.get("git_remotes") or "[]"
        if (git_remotes_raw == "[]" or not git_remotes_raw) and p.get("git_remote_url"):
            await db.update("projects", {
                "git_remotes": json.dumps([{"name": "origin", "url": p["git_remote_url"]}])
            }, "id = ?", (p["id"],))

    if restored:
        logger.info("已恢复 %d 个项目的自定义仓库路径映射", restored)


async def reset_stale_environments(db):
    # 清理僵尸环境记录：预览服务是 subprocess，随后端进程退出而死，
    # 但 project_environments.status 仍停留在 'running'，前端会显示"运行中"
    # 并给出一个点进去 404 的链接。启动时统一重置。
    # 状态值与 api/projects.py 的自愈逻辑保持一致（inactive，不是 stopped）。
    try:
        stale = await db.fetch_all(
            "SELECT id FROM project_environments WHERE status = 'running'"
        )
        if stale:
            await db.execute(
                "UPDATE project_environments SET status = 'inactive' WHERE status = 'running'"
            )
            logger.info("已重置 %d 条僵尸环境记录（上次退出时未清理的 running）", len(stale))
    except Exception as e:
        logger.warning("清理僵尸环境记录失败（非致命）: %s", e)


async def index_knowledge_documents(db):
    # 补录现有 docs 文件到 knowledge_index（首次启动迁移）
    try:
        from api.knowledge import _upsert_knowledge_index, GLOBAL_DOCS_DIR, PROJECTS_DIR as K_PROJECTS_DIR
        from config import BASE_DIR as _BDIR
        SYSTEM_ROOT = _BDIR.parent  # F:\A_Works\ai-dev-system
        indexed = 0

        # 1. 系统自身的 docs/ 和 dev-notes/（全局知识，filename 带前缀区分）
        for sys_dir, prefix in [
            (SYSTEM_ROOT / "docs",      "sys_docs__"),
            (SYSTEM_ROOT / "dev-notes", "sys_devnotes__"),
        ]:
            if sys_dir.is_dir():
                for md in sorted(sys_dir.glob("*.md")):
                    fname = prefix + md.name
                    await _upsert_knowledge_index(None, fname, md.read_text(encoding="utf-8", errors="replace"))
                    indexed += 1

        # 2. 用户在全局知识库 Tab 手动写入的文档
        for md in GLOBAL_DOCS_DIR.glob("*.md"):
            await _upsert_knowledge_index(None, md.name, md.read_text(encoding="utf-8", errors="replace"))
            indexed += 1

        # 3. 各项目的 docs/
        for pid_dir in K_PROJECTS_DIR.iterdir():
            docs_dir = pid_dir / "docs"
            if docs_dir.is_dir():
                for md in docs_dir.glob("*.md"):
                    await _upsert_knowledge_index(pid_dir.name, md.name, md.read_text(encoding="utf-8", errors="replace"))
                    indexed += 1
        # 强制 rebuild（确保 tokenizer 变更后旧数据被重建）
        # 先 integrity-check 刷新 FTS5 schema 缓存，再 rebuild
        await db.execute("INSERT INTO knowledge_fts(knowledge_fts) VALUES('integrity-check')")
        await db.execute("INSERT INTO knowledge_fts(knowledge_fts) VALUES('rebuild')")
        if indexed:
            logger.info("知识库 FTS5 索引：补录 %d 个文档", indexed)
    except Exception as e:
        logger.warning("知识库 FTS5 补录失败（忽略）: %s", e)


async def index_finished_tickets(db):
    # 补录已完成工单到 tickets_fts（首次启动迁移）
    try:
        from api.knowledge import _upsert_tickets_fts
        done_tickets = await db.fetch_all("""
            SELECT t.id, t.project_id, t.title, t.description,
                   (SELECT tl.detail FROM ticket_logs tl
                    WHERE tl.ticket_id = t.id AND tl.action = 'reflection'
                    ORDER BY tl.created_at DESC LIMIT 1) AS reflection_detail
            FROM tickets t
            WHERE t.status IN ('acceptance_passed', 'testing_done', 'deployed', 'development_done')
        """)
        fts_indexed = 0
        for t in done_tickets:
            text = f"{t['title']} {t['description'] or ''}"
            if t["reflection_detail"]:
                try:
                    ref = json.loads(t["reflection_detail"])
                    root_cause = ref.get("reflection", {}).get("root_cause", "")
                    if root_cause:
                        text += f" {root_cause}"
                except Exception:
                    pass
            await _upsert_tickets_fts(t["id"], t["project_id"], text)
            fts_indexed += 1
        if fts_indexed:
            logger.info("工单历史 FTS5 索引：补录 %d 个工单", fts_indexed)
    except Exception as e:
        logger.warning("工单历史 FTS5 补录失败（忽略）: %s", e)
    # tickets_fts 无需 rebuild（internal content，INSERT 后直接可搜）


async def sync_art_assets():
    # 同步美术资产库（G_ArtRes → art_assets 表）
    try:
        from scripts.sync_art_assets import sync_art_assets_from_manifest
        art_path = settings.ART_ASSETS_LOCAL_PATH
        if art_path:
            n = await sync_art_assets_from_manifest(art_path)
            if n:
                logger.info("美术资产库同步完成: %d 条", n)
        else:
            logger.debug("ART_ASSETS_LOCAL_PATH 未配置，跳过美术资产库同步")
    except Exception as e:
        logger.warning("美术资产库同步失败（忽略）: %s", e)


async def sync_design_library():
    # 同步策划知识库（G_DesignKnowledge → planning_knowledge 等表）
    try:
        from scripts.sync_design_knowledge import sync_design_knowledge
        kb_path = settings.GLOBAL_KNOWLEDGE_LOCAL_PATH
        if kb_path:
            n = await sync_design_knowledge(kb_path)
            if n:
                logger.info("策划知识库同步完成: %d 篇", n)
        else:
            logger.debug("GLOBAL_KNOWLEDGE_LOCAL_PATH 未配置，跳过知识库同步")
    except Exception as e:
        logger.warning("策划知识库同步失败（忽略）: %s", e)
