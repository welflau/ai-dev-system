"""
capability_check.py — 三层融合能力检测

检测项目是否具备 Superpowers / OpenSpec 能力，
返回 bool，供 Agent 决定是否启用对应增强。
所有检测均为可选，失败只返回 False，不抛异常。
"""
import shutil
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("capability_check")


async def has_superpowers(project_id: str, repo_path: Optional[str] = None) -> bool:
    """项目是否安装了 Superpowers Pack（.claude/packs/superpowers 或 .codebuddy/packs/superpowers）"""
    if not repo_path:
        repo_path = await _get_repo_path(project_id)
    if not repo_path:
        return False
    try:
        root = Path(repo_path)
        return (
            (root / ".claude" / "packs" / "superpowers").exists()
            or (root / ".codebuddy" / "packs" / "superpowers").exists()
        )
    except Exception:
        return False


async def has_openspec(project_id: str, repo_path: Optional[str] = None) -> bool:
    """项目是否安装并初始化了 OpenSpec（opsx/openspec CLI 可用 + openspec/ 目录存在）"""
    if not repo_path:
        repo_path = await _get_repo_path(project_id)
    if not repo_path:
        return False
    try:
        cli_available = bool(shutil.which("opsx") or shutil.which("openspec-cn") or shutil.which("openspec"))
        spec_dir = Path(repo_path) / "openspec"
        return cli_available and spec_dir.exists()
    except Exception:
        return False


def get_openspec_cli() -> Optional[str]:
    """返回可用的 OpenSpec CLI 命令名，None 表示未安装"""
    for cmd in ("opsx", "openspec-cn", "openspec"):
        if shutil.which(cmd):
            return cmd
    return None


def get_ticket_specs_path(repo_path: str, ticket_id: str) -> Path:
    """返回该工单的 OpenSpec specs 文件路径"""
    return Path(repo_path) / "openspec" / "changes" / ticket_id / "specs.md"


def ticket_has_specs(repo_path: str, ticket_id: str) -> bool:
    """该工单是否已有 OpenSpec specs 文件"""
    try:
        return get_ticket_specs_path(repo_path, ticket_id).exists()
    except Exception:
        return False


def load_superpowers_skills(repo_path: str, skills: list[str]) -> str:
    """从已安装的 Superpowers Pack 读取指定 skill 内容，拼接为字符串"""
    root = Path(repo_path)
    pack_roots = [
        root / ".claude" / "packs" / "superpowers" / "skills",
        root / ".codebuddy" / "packs" / "superpowers" / "skills",
    ]
    pack_root = next((p for p in pack_roots if p.exists()), None)
    if not pack_root:
        return ""

    contents = []
    for skill in skills:
        skill_file = pack_root / skill / "SKILL.md"
        if skill_file.exists():
            try:
                contents.append(skill_file.read_text(encoding="utf-8"))
                logger.debug("Superpowers skill 已加载: %s", skill)
            except Exception as e:
                logger.warning("加载 Superpowers skill 失败 %s: %s", skill, e)

    return "\n\n---\n\n".join(contents) if contents else ""


async def _get_repo_path(project_id: str) -> Optional[str]:
    """从 DB 获取项目 git_repo_path"""
    try:
        from database import db
        row = await db.fetch_one(
            "SELECT git_repo_path FROM projects WHERE id = ?", (project_id,)
        )
        return (row or {}).get("git_repo_path") or None
    except Exception:
        return None
