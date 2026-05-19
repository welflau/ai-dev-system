"""
Skills API
  GET    /api/skills                                          — 全局 Skill 列表（含 DB 覆盖后的状态）
  POST   /api/skills/{skill_id}/enable                        — 全局开启某 Skill
  POST   /api/skills/{skill_id}/disable                       — 全局关闭某 Skill
  DELETE /api/skills/{skill_id}/override                      — 删除全局覆盖，恢复 skills.json 默认值
  GET    /api/projects/{project_id}/skills                    — 项目可用 Skill 列表（全局 + 自定义，含启用状态）
  POST   /api/projects/{project_id}/skills/{skill_id}/enable  — 项目级启用
  POST   /api/projects/{project_id}/skills/{skill_id}/disable — 项目级禁用
  DELETE /api/projects/{project_id}/skills/{skill_id}         — 删除项目覆盖，恢复全局默认
  POST   /api/projects/{project_id}/skills/upload             — 上传自定义 Skill (.md)
  DELETE /api/projects/{project_id}/skills/custom/{skill_id}  — 删除自定义 Skill
"""
import logging
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from database import db
from utils import generate_id, now_iso

_CUSTOM_SKILLS_DIR = Path(__file__).parent.parent / "data" / "project_skills"

logger = logging.getLogger("api.skills")

router = APIRouter(tags=["skills"])


# ── 全局 Skill 配置 ──────────────────────────────────────────────────────────

@router.get("/api/skills/ping")
async def skills_ping():
    return {"pong": True, "has_marketplace": True}

@router.get("/api/skills")
async def list_global_skills():
    """返回所有 Skill 的状态（skills.json + global_skill_settings DB 覆盖后的最终值）"""
    from skills import skill_loader

    # 读取 global_skill_settings 覆盖
    global_overrides: dict = {}
    try:
        rows = await db.fetch_all("SELECT skill_id, enabled FROM global_skill_settings")
        global_overrides = {r["skill_id"]: bool(r["enabled"]) for r in rows}
    except Exception:
        pass  # 表不存在时忽略

    status = skill_loader.get_all_skills_status()
    skills = []
    for sid, info in status.items():
        # scan_dir 聚合条目不出现在全局配置里（它的子项已展开为 marketplace_item）
        if info.get("source") != "marketplace" and sid in [
            k for k, v in skill_loader.skills.items() if v.get("type") == "scan_dir"
        ]:
            continue
        enabled_default = info["enabled"]
        enabled_global = global_overrides.get(sid, enabled_default)
        skills.append({
            "id": sid,
            "name": info["name"],
            "description": info["description"],
            "enabled": enabled_global,
            "enabled_default": enabled_default,  # skills.json 原始值
            "overridden": sid in global_overrides,
            "source": info.get("source", "builtin"),
            "inject_to": info["inject_to"],
            "priority": info["priority"],
            "prompt_exists": info["prompt_exists"],
            "traits_match": info["traits_match"],
            "group": info["group"],
        })
    return {"skills": skills, "total": len(skills)}


@router.post("/api/skills/{skill_id}/enable")
async def global_enable_skill(skill_id: str):
    """全局开启某 Skill（写 global_skill_settings，覆盖 skills.json 默认值）"""
    await db.execute(
        """INSERT INTO global_skill_settings (skill_id, enabled, updated_at)
           VALUES (?, 1, ?)
           ON CONFLICT(skill_id) DO UPDATE SET enabled=1, updated_at=excluded.updated_at""",
        (skill_id, now_iso()),
    )
    logger.info("global skill=%s → enabled", skill_id)
    return {"ok": True, "skill_id": skill_id, "enabled": True}


@router.post("/api/skills/{skill_id}/disable")
async def global_disable_skill(skill_id: str):
    """全局关闭某 Skill"""
    await db.execute(
        """INSERT INTO global_skill_settings (skill_id, enabled, updated_at)
           VALUES (?, 0, ?)
           ON CONFLICT(skill_id) DO UPDATE SET enabled=0, updated_at=excluded.updated_at""",
        (skill_id, now_iso()),
    )
    logger.info("global skill=%s → disabled", skill_id)
    return {"ok": True, "skill_id": skill_id, "enabled": False}


@router.delete("/api/skills/{skill_id}/override")
async def reset_global_skill(skill_id: str):
    """删除全局覆盖，恢复 skills.json 默认值"""
    await db.execute("DELETE FROM global_skill_settings WHERE skill_id=?", (skill_id,))
    return {"ok": True, "skill_id": skill_id, "reset": True}


# ── Marketplace API ──────────────────────────────────────────────────────────

_MARKETPLACE_DIR = Path(__file__).parent.parent / "skills" / "marketplace"
_USE_SKILLS_DIR  = Path(__file__).parent.parent / "skills" / "use_skills"


_SKIP_DIR_PREFIXES = ("download_", ".")  # 过滤临时下载目录和隐藏目录


def _iter_marketplace_skills(base_dir: Path):
    """递归扫描 marketplace 目录，返回所有包含 SKILL.md 的目录。
    自动跳过 download_* 等临时目录。
    """
    for skill_md in sorted(base_dir.rglob("SKILL.md")):
        # 跳过路径中含临时目录的 Skill
        parts = skill_md.relative_to(base_dir).parts
        if any(p.startswith(_SKIP_DIR_PREFIXES) for p in parts):
            continue
        yield skill_md.parent


def _find_marketplace_skill(dir_name: str) -> Path | None:
    """在 marketplace 目录中递归查找指定 dir_name 的 Skill 目录。"""
    for skill_dir in _iter_marketplace_skills(_MARKETPLACE_DIR):
        if skill_dir.name == dir_name:
            return skill_dir
    return None


def _get_skill_category(skill_dir: Path, base_dir: Path) -> str:
    """从目录结构推导 Skill 分类。
    规则：
    - {base}/cb_teams_marketplace/plugins/{plugin}/skills/{skill} → 分类 = plugin
    - {base}/{category}/{skill} → 分类 = category
    - {base}/{skill} → 分类 = "通用"
    """
    try:
        parts = skill_dir.relative_to(base_dir).parts
        if len(parts) >= 4 and "plugins" in parts:
            idx = list(parts).index("plugins")
            if idx + 1 < len(parts):
                return parts[idx + 1]
        if len(parts) >= 2:
            return parts[0]
    except Exception:
        pass
    return "通用"


def _parse_skill_meta(skill_md: Path) -> dict:
    """从 SKILL.md frontmatter 提取 name / description / category。"""
    try:
        text = skill_md.read_text(encoding="utf-8")
        import re as _re
        m = _re.match(r"^---\s*\n(.*?)\n---\s*\n", text, _re.DOTALL)
        if m:
            import yaml as _yaml
            fm = _yaml.safe_load(m.group(1)) or {}
            return {
                "name": fm.get("name") or skill_md.parent.name,
                "description": (fm.get("description") or "")[:300],
                "category": fm.get("category", ""),
            }
    except Exception:
        pass
    return {"name": skill_md.parent.name, "description": "", "category": ""}


@router.get("/api/skills/marketplace")
async def list_marketplace_skills():
    """列出 marketplace/ 目录下所有可用 Skill，并标记哪些已安装到 use_skills/。"""
    if not _MARKETPLACE_DIR.exists():
        return {"skills": []}

    installed = {p.name for p in _USE_SKILLS_DIR.iterdir() if p.is_dir()} \
        if _USE_SKILLS_DIR.exists() else set()

    skills = []
    for skill_dir in _iter_marketplace_skills(_MARKETPLACE_DIR):
        skill_md = skill_dir / "SKILL.md"
        meta = _parse_skill_meta(skill_md)
        # 优先用目录结构推导分类，frontmatter category 作补充
        category = _get_skill_category(skill_dir, _MARKETPLACE_DIR)
        if not category or category == "通用":
            category = meta.get("category") or "通用"
        skills.append({
            "dir_name": skill_dir.name,
            "name": meta["name"],
            "description": meta["description"],
            "category": category,
            "installed": skill_dir.name in installed,
        })
    return {"skills": skills}


@router.post("/api/skills/marketplace/{dir_name}/install")
async def install_marketplace_skill(dir_name: str):
    """将 marketplace/{dir_name} 复制到 use_skills/，并热重载 SkillLoader。"""
    # 安全：只允许字母数字、连字符、下划线
    if not re.match(r'^[\w\-]+$', dir_name):
        raise HTTPException(400, "非法目录名")

    src = _find_marketplace_skill(dir_name)
    if not src:
        raise HTTPException(404, f"marketplace 中不存在 Skill: {dir_name}")

    _USE_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    dst = _USE_SKILLS_DIR / dir_name
    if dst.exists():
        return {"ok": True, "dir_name": dir_name, "already_installed": True}

    import shutil
    shutil.copytree(str(src), str(dst))

    # 热重载
    from skills import skill_loader
    skill_loader.reload()
    logger.info("marketplace skill installed: %s", dir_name)
    return {"ok": True, "dir_name": dir_name, "installed": True}


@router.delete("/api/skills/use/{dir_name}")
async def uninstall_use_skill(dir_name: str):
    """从 use_skills/ 删除已安装的 Skill，并热重载。"""
    if not re.match(r'^[\w\-]+$', dir_name):
        raise HTTPException(400, "非法目录名")

    dst = _USE_SKILLS_DIR / dir_name
    if not dst.exists():
        raise HTTPException(404, f"use_skills 中不存在: {dir_name}")

    import shutil
    shutil.rmtree(str(dst))

    from skills import skill_loader
    skill_loader.reload()
    logger.info("use_skill uninstalled: %s", dir_name)
    return {"ok": True, "dir_name": dir_name, "uninstalled": True}


# ── 项目 .Agent/skills 目录助手 ─────────────────────────────────────────────

async def _get_project_agent_skills_dir(project_id: str) -> Path:
    """返回项目 Skills 目录路径。
    P2: 优先 .ads/skills/，降级 .Agent/skills/（向后兼容）。
    """
    row = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id=?", (project_id,))
    if row and row.get("git_repo_path"):
        base = Path(row["git_repo_path"])
        ads_skills = base / ".ads" / "skills"
        if ads_skills.exists():
            return ads_skills
        return base / ".Agent" / "skills"
    fallback = Path(__file__).parent.parent / "data" / "project_skills" / project_id / ".Agent" / "skills"
    return fallback


@router.get("/api/projects/{project_id}/skills/marketplace")
async def list_project_marketplace_skills(project_id: str):
    """列出 marketplace/ 的所有 Skill，标记哪些已安装到该项目的 .Agent/skills/。"""
    if not _MARKETPLACE_DIR.exists():
        return {"skills": []}

    agent_skills_dir = await _get_project_agent_skills_dir(project_id)
    installed = {p.name for p in agent_skills_dir.iterdir() if p.is_dir()} \
        if agent_skills_dir.exists() else set()

    skills = []
    for skill_dir in _iter_marketplace_skills(_MARKETPLACE_DIR):
        skill_md = skill_dir / "SKILL.md"
        meta = _parse_skill_meta(skill_md)
        category = _get_skill_category(skill_dir, _MARKETPLACE_DIR)
        if not category or category == "通用":
            category = meta.get("category") or "通用"
        skills.append({
            "dir_name": skill_dir.name,
            "name": meta["name"],
            "description": meta["description"],
            "category": category,
            "installed": skill_dir.name in installed,
        })
    return {"skills": skills, "project_id": project_id}


@router.post("/api/projects/{project_id}/skills/marketplace/{dir_name}/install")
async def install_project_skill(project_id: str, dir_name: str):
    """将 marketplace/{dir_name} 复制到项目 .Agent/skills/。"""
    if not re.match(r'^[\w\-]+$', dir_name):
        raise HTTPException(400, "非法目录名")

    src = _find_marketplace_skill(dir_name)
    if not src:
        raise HTTPException(404, f"marketplace 中不存在 Skill: {dir_name}")

    agent_skills_dir = await _get_project_agent_skills_dir(project_id)
    agent_skills_dir.mkdir(parents=True, exist_ok=True)
    dst = agent_skills_dir / dir_name
    if dst.exists():
        return {"ok": True, "dir_name": dir_name, "already_installed": True}

    import shutil
    shutil.copytree(str(src), str(dst))
    logger.info("project=%s skill installed: %s → %s", project_id, dir_name, dst)
    return {"ok": True, "dir_name": dir_name, "installed": True, "path": str(dst)}


@router.delete("/api/projects/{project_id}/skills/use/{dir_name}")
async def uninstall_project_skill(project_id: str, dir_name: str):
    """从项目 .Agent/skills/ 删除已安装的 Skill。"""
    if not re.match(r'^[\w\-]+$', dir_name):
        raise HTTPException(400, "非法目录名")

    agent_skills_dir = await _get_project_agent_skills_dir(project_id)
    dst = agent_skills_dir / dir_name
    if not dst.exists():
        raise HTTPException(404, f"项目 Skills 中不存在: {dir_name}")

    import shutil
    shutil.rmtree(str(dst))
    logger.info("project=%s skill uninstalled: %s", project_id, dir_name)
    return {"ok": True, "dir_name": dir_name, "uninstalled": True}


# ── 项目级 Skill 管理 ────────────────────────────────────────────────────────

@router.get("/api/projects/{project_id}/skills")
async def list_project_skills(project_id: str):
    """
    返回该项目可用的 Skill 列表，含每个 Skill 的启用状态。
    全局 Skill（来自 skills.json）+ 项目自定义 Skill 合并返回。
    """
    from skills import skill_loader

    # 全局 Skill 基础列表
    global_status = skill_loader.get_all_skills_status()

    # 读取项目覆盖配置
    rows = await db.fetch_all(
        "SELECT skill_id, source, enabled, custom_name, custom_path FROM project_skills WHERE project_id=?",
        (project_id,),
    )
    project_map = {r["skill_id"]: r for r in rows}

    # 读取全局 DB 覆盖（用于计算 enabled_global）
    global_overrides: dict = {}
    try:
        global_rows = await db.fetch_all("SELECT skill_id, enabled FROM global_skill_settings")
        global_overrides = {r["skill_id"]: bool(r["enabled"]) for r in global_rows}
    except Exception:
        pass

    result = []
    # 全局 Skill
    for sid, info in global_status.items():
        override = project_map.get(sid)
        # 全局默认值（skills.json + global_skill_settings）
        enabled_global = global_overrides.get(sid, info["enabled"])
        # 项目级最终值
        enabled = bool(override["enabled"]) if override else enabled_global
        result.append({
            "id": sid,
            "name": info["name"],
            "description": info["description"],
            "source": "global",
            "enabled": enabled,
            "enabled_global": enabled_global,   # 全局默认（供「全局默认开/关」标签使用）
            "priority": info["priority"],
            "inject_to": info["inject_to"],
            "traits_match": info["traits_match"],
            "prompt_exists": info["prompt_exists"],
            "overridden": override is not None,
        })

    # 项目自定义 Skill（source='custom'）
    for row in rows:
        if row["source"] == "custom":
            result.append({
                "id": row["skill_id"],
                "name": row["custom_name"] or row["skill_id"],
                "description": "",
                "source": "custom",
                "enabled": bool(row["enabled"]),
                "priority": "medium",
                "inject_to": ["ChatAssistant"],
                "traits_match": {},
                "prompt_exists": True,
                "overridden": False,
            })

    return {"skills": result, "project_id": project_id}


@router.post("/api/projects/{project_id}/skills/{skill_id}/enable")
async def enable_project_skill(project_id: str, skill_id: str):
    """为该项目启用某个 Skill（覆盖全局默认）"""
    await _upsert_skill_enabled(project_id, skill_id, True)
    logger.info("project=%s skill=%s → enabled", project_id, skill_id)
    return {"ok": True, "project_id": project_id, "skill_id": skill_id, "enabled": True}


@router.post("/api/projects/{project_id}/skills/{skill_id}/disable")
async def disable_project_skill(project_id: str, skill_id: str):
    """为该项目禁用某个 Skill"""
    await _upsert_skill_enabled(project_id, skill_id, False)
    logger.info("project=%s skill=%s → disabled", project_id, skill_id)
    return {"ok": True, "project_id": project_id, "skill_id": skill_id, "enabled": False}


@router.delete("/api/projects/{project_id}/skills/{skill_id}")
async def reset_project_skill(project_id: str, skill_id: str):
    """删除项目对该 Skill 的覆盖配置，恢复为全局默认"""
    await db.execute(
        "DELETE FROM project_skills WHERE project_id=? AND skill_id=? AND source='global'",
        (project_id, skill_id),
    )
    return {"ok": True, "project_id": project_id, "skill_id": skill_id, "reset": True}


# ── 自定义 Skill 上传 / 删除 ─────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/skills/upload")
async def upload_custom_skill(project_id: str, file: UploadFile = File(...)):
    """
    上传自定义 Skill .md 文件，自动注册到 project_skills 表。
    skill_id 由文件名（去掉 .md 后缀）生成，与全局 Skill ID 空间独立（加 `custom.` 前缀）。
    """
    if not (file.filename or "").lower().endswith(".md"):
        raise HTTPException(400, "只支持 .md 文件")

    raw_content = await file.read()
    try:
        content = raw_content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "文件编码必须是 UTF-8")

    if not content.strip():
        raise HTTPException(400, "文件内容不能为空")

    # 文件名 → skill_id（去后缀 + 安全化）
    stem = Path(file.filename).stem
    safe_stem = re.sub(r"[^\w\-]", "-", stem).strip("-") or "custom"
    skill_id = f"custom.{safe_stem}"

    # 存文件
    skill_dir = _CUSTOM_SKILLS_DIR / project_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / f"{safe_stem}.md"
    skill_file.write_text(content, encoding="utf-8")
    relative_path = f"{project_id}/{safe_stem}.md"

    # 提取文件第一行非空文本作为 custom_name（若 frontmatter 有 name 字段则用之）
    custom_name = _extract_skill_name(content) or safe_stem

    # 写入 project_skills 表
    existing = await db.fetch_one(
        "SELECT id FROM project_skills WHERE project_id=? AND skill_id=?",
        (project_id, skill_id),
    )
    if existing:
        await db.execute(
            "UPDATE project_skills SET enabled=1, custom_name=?, custom_path=? WHERE project_id=? AND skill_id=?",
            (custom_name, relative_path, project_id, skill_id),
        )
    else:
        await db.execute(
            """INSERT INTO project_skills (id, project_id, skill_id, source, enabled, custom_name, custom_path, created_at)
               VALUES (?, ?, ?, 'custom', 1, ?, ?, ?)""",
            (generate_id("psk"), project_id, skill_id, custom_name, relative_path, now_iso()),
        )

    logger.info("自定义 Skill 上传: project=%s skill_id=%s file=%s", project_id, skill_id, relative_path)
    return {
        "ok": True,
        "skill_id": skill_id,
        "name": custom_name,
        "path": relative_path,
        "project_id": project_id,
    }


@router.delete("/api/projects/{project_id}/skills/custom/{skill_id:path}")
async def delete_custom_skill(project_id: str, skill_id: str):
    """删除项目自定义 Skill（文件 + 数据库记录）"""
    row = await db.fetch_one(
        "SELECT custom_path FROM project_skills WHERE project_id=? AND skill_id=? AND source='custom'",
        (project_id, skill_id),
    )
    if not row:
        raise HTTPException(404, f"自定义 Skill `{skill_id}` 不存在")

    # 删文件
    if row["custom_path"]:
        skill_file = _CUSTOM_SKILLS_DIR / row["custom_path"]
        if skill_file.exists():
            skill_file.unlink()

    # 删数据库记录
    await db.execute(
        "DELETE FROM project_skills WHERE project_id=? AND skill_id=? AND source='custom'",
        (project_id, skill_id),
    )
    logger.info("自定义 Skill 删除: project=%s skill_id=%s", project_id, skill_id)
    return {"ok": True, "skill_id": skill_id, "project_id": project_id}


# ── helper ───────────────────────────────────────────────────────────────────

def _extract_skill_name(content: str) -> str:
    """从 .md 内容提取 Skill 显示名：优先 frontmatter name 字段，其次第一个 # 标题"""
    # frontmatter
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).splitlines():
            m = re.match(r"^\s*name\s*:\s*(.+)", line)
            if m:
                return m.group(1).strip().strip('"\'')
    # 第一个 # 标题
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


async def _upsert_skill_enabled(project_id: str, skill_id: str, enabled: bool) -> None:
    existing = await db.fetch_one(
        "SELECT id FROM project_skills WHERE project_id=? AND skill_id=?",
        (project_id, skill_id),
    )
    if existing:
        await db.execute(
            "UPDATE project_skills SET enabled=? WHERE project_id=? AND skill_id=?",
            (1 if enabled else 0, project_id, skill_id),
        )
    else:
        await db.execute(
            """INSERT INTO project_skills (id, project_id, skill_id, source, enabled, created_at)
               VALUES (?, ?, ?, 'global', ?, ?)""",
            (generate_id("psk"), project_id, skill_id, 1 if enabled else 0, now_iso()),
        )
