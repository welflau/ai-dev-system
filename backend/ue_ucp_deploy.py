"""
将 ADS 内置 UnrealClientProtocol (UCP) 插件部署到 UE 工程 Plugins/ 目录。

供 CreateProjectAction、projects API、instantiate_ue_template 等路径复用。
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ue_ucp_deploy")

_UCP_SRC = Path(__file__).parent / "ue_plugins" / "UnrealClientProtocol"
_UCP_REL = Path("Plugins") / "UnrealClientProtocol"
_UCP_MARKER = _UCP_REL / "UnrealClientProtocol.uplugin"


def is_ucp_installed(repo_path: str) -> bool:
    """工程 Plugins/ 下是否已有 UCP 插件。"""
    return (Path(repo_path) / _UCP_MARKER).is_file()


def is_ue_project_path(repo_path: str, traits: Optional[List[str]] = None) -> bool:
    """traits 含 engine:ue*，或目录中存在 *.uproject（根目录或一级子目录）。"""
    if traits:
        if any(str(t).startswith("engine:ue") for t in traits):
            return True
    root = Path(repo_path)
    if not root.is_dir():
        return False
    if list(root.glob("*.uproject")):
        return True
    for child in root.iterdir():
        if child.is_dir() and list(child.glob("*.uproject")):
            return True
    return False


def deploy_ucp_to_project(repo_path: str) -> Dict[str, Any]:
    """
    复制 UCP 到 {repo_path}/Plugins/UnrealClientProtocol。
    已存在时使用 dirs_exist_ok 合并更新（与 instantiate_ue_template 一致）。
    """
    repo = Path(repo_path)
    if not repo.is_dir():
        return {
            "installed": False,
            "skipped": True,
            "reason": "repo_not_found",
            "path": None,
            "message": f"仓库路径不存在: {repo_path}",
        }

    if not _UCP_SRC.is_dir():
        logger.warning("UCP 源目录不存在: %s", _UCP_SRC)
        return {
            "installed": False,
            "skipped": True,
            "reason": "source_missing",
            "path": None,
            "message": "ADS 内置 UCP 插件快照不存在，跳过部署",
        }

    ucp_dst = repo / _UCP_REL
    try:
        ucp_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(_UCP_SRC), str(ucp_dst), dirs_exist_ok=True)
        msg = "UCP 插件已复制到 Plugins/UnrealClientProtocol（请重启 Editor 完成编译）"
        logger.info("UCP deployed: %s", ucp_dst)
        return {
            "installed": True,
            "skipped": False,
            "path": str(ucp_dst),
            "message": msg,
        }
    except Exception as e:
        logger.warning("UCP deploy failed for %s: %s", repo_path, e)
        return {
            "installed": False,
            "skipped": False,
            "reason": "copy_failed",
            "path": str(ucp_dst),
            "message": f"UCP 插件部署失败: {e}",
            "error": str(e),
        }
