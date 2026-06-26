"""
VCS 检测器
检测任意文件/目录属于哪种版本控制系统（git / p4 / none），
并提供写前检查 ensure_writable()。
手动挡模式下 AI 修改文件前调用此模块。
"""
import asyncio
import logging
import os
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("vcs_detector")


class VCSType(str, Enum):
    GIT = "git"
    P4 = "p4"
    NONE = "none"
    UNKNOWN = "unknown"


# ── 缓存：路径 → VCS 类型（避免重复检测）──────────────────────
_vcs_cache: dict[str, VCSType] = {}


def _find_git_root(path: str) -> Optional[str]:
    """向上查找 .git 目录，返回 git 根路径，找不到返回 None"""
    p = Path(path).resolve()
    if p.is_file():
        p = p.parent
    while True:
        if (p / ".git").exists():
            return str(p)
        parent = p.parent
        if parent == p:
            return None
        p = parent


def _find_p4config(path: str) -> Optional[str]:
    """向上查找 .p4config 文件，返回所在目录，找不到返回 None"""
    p = Path(path).resolve()
    if p.is_file():
        p = p.parent
    # 同时检查环境变量指定的 P4CONFIG 文件名
    p4config_name = os.environ.get("P4CONFIG", ".p4config")
    while True:
        if (p / p4config_name).exists():
            return str(p)
        parent = p.parent
        if parent == p:
            return None
        p = parent


async def detect_vcs(path: str) -> VCSType:
    """
    检测 path（文件或目录）所属的 VCS 类型。
    优先级：git > p4 > none
    结果会被缓存（按规范化路径）。
    """
    normalized = str(Path(path).resolve())

    # 先查缓存
    if normalized in _vcs_cache:
        return _vcs_cache[normalized]

    # 1. 检测 git
    git_root = _find_git_root(normalized)
    if git_root:
        result = VCSType.GIT
        logger.debug("🔍 VCS detect: %s → git (root: %s)", path, git_root)
        _vcs_cache[normalized] = result
        return result

    # 2. 检测 P4：先找 .p4config，再用 p4 where 确认
    p4config_dir = _find_p4config(normalized)
    if p4config_dir:
        result = VCSType.P4
        logger.debug("🔍 VCS detect: %s → p4 (.p4config at: %s)", path, p4config_dir)
        _vcs_cache[normalized] = result
        return result

    # 3. 用 p4 where 尝试确认（无 .p4config 但有全局 P4 配置的情况）
    try:
        from p4_manager import p4_manager
        file_to_check = normalized if os.path.isfile(normalized) else normalized + "/..."
        depot_path = await asyncio.wait_for(
            p4_manager.p4_where(file_to_check), timeout=5
        )
        if depot_path:
            result = VCSType.P4
            logger.debug("🔍 VCS detect: %s → p4 (p4 where)", path)
            _vcs_cache[normalized] = result
            return result
    except Exception:
        pass

    result = VCSType.NONE
    _vcs_cache[normalized] = result
    logger.debug("🔍 VCS detect: %s → none", path)
    return result


def clear_vcs_cache():
    """清空 VCS 检测缓存（项目路径变更时调用）"""
    _vcs_cache.clear()


# ── 写前检查 ──────────────────────────────────────────────────

class WriteBlockedError(Exception):
    """文件不可写（只读路径且用户未确认）"""
    pass


async def ensure_writable(
    file_path: str,
    readonly_paths: Optional[list[str]] = None,
) -> dict:
    """
    写文件前检查并处理 VCS 状态。
    返回 {"ok": bool, "action": str, "message": str}

    action 可能值：
      "direct"      - 直接可写（git 路径或无管理）
      "p4_edit"     - 已执行 p4 edit checkout
      "p4_already"  - 文件已在 P4 opened 状态，无需再 checkout
      "readonly"    - 只读路径，需用户确认（调用方处理）
      "error"       - 操作失败
    """
    readonly_paths = readonly_paths or []
    normalized = str(Path(file_path).resolve())

    # 检查是否在只读路径列表中
    for ro_path in readonly_paths:
        try:
            Path(normalized).relative_to(Path(ro_path).resolve())
            # 在只读路径中
            return {
                "ok": False,
                "action": "readonly",
                "message": f"文件位于只读路径 {ro_path}，需用户确认才能修改",
                "file_path": normalized,
            }
        except ValueError:
            continue

    vcs = await detect_vcs(normalized)

    if vcs == VCSType.GIT or vcs == VCSType.NONE:
        # git 路径直接写（手动挡不 commit），无管理也直接写
        return {"ok": True, "action": "direct", "message": "", "vcs": vcs.value}

    if vcs == VCSType.P4:
        from p4_manager import p4_manager

        # 先判断是否已 checkout
        if await p4_manager.is_checked_out(normalized):
            return {
                "ok": True,
                "action": "p4_already",
                "message": f"文件已在 P4 opened 状态",
                "vcs": "p4",
            }

        # 新文件（不存在）→ p4 add；已有文件 → p4 edit
        if not os.path.exists(normalized):
            success, msg = await p4_manager.p4_add(normalized)
        else:
            success, msg = await p4_manager.p4_edit(normalized)

        if success:
            return {
                "ok": True,
                "action": "p4_edit",
                "message": msg,
                "vcs": "p4",
            }
        else:
            return {
                "ok": False,
                "action": "error",
                "message": f"P4 checkout 失败: {msg}",
                "vcs": "p4",
            }

    return {"ok": True, "action": "direct", "message": "", "vcs": "unknown"}


# ── 目录扫描：识别项目根路径下的 VCS 结构 ──────────────────────

async def scan_project_paths(root_path: str) -> list[dict]:
    """
    扫描项目根路径，识别子目录的 VCS 类型。
    返回 [{"path": str, "vcs": str, "auto_detected": bool}, ...]
    用于「打开目录」时自动填充多路径配置。
    """
    root = Path(root_path).resolve()
    if not root.exists():
        return []

    results = []

    # 根目录本身
    root_vcs = await detect_vcs(str(root))
    results.append({
        "path": str(root),
        "vcs": root_vcs.value,
        "auto_detected": False,  # 用户主动配置的路径
        "writable": True,
    })

    # 检测常见子目录（UE 项目结构等）
    common_subdirs = ["Source", "Content", "Config", "Plugins"]
    for subdir in common_subdirs:
        sub_path = root / subdir
        if sub_path.exists():
            sub_vcs = await detect_vcs(str(sub_path))
            # 如果子目录 VCS 类型和根目录不同，单独记录
            if sub_vcs != root_vcs:
                results.append({
                    "path": str(sub_path),
                    "vcs": sub_vcs.value,
                    "auto_detected": True,
                    "writable": True,
                })

    return results
