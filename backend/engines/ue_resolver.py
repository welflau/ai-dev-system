r"""
UEEngineResolver — 本机 UE 引擎发现 / 验证 / 为项目解析引擎

数据源优先级：
    1. .uproject 的 EngineAssociation 字段（精确匹配）
    2. HKLM (官方 Launcher 版本)                → HKEY_LOCAL_MACHINE\SOFTWARE\EpicGames\Unreal Engine\{5.x}\InstalledDirectory
    3. HKCU (自编译 Source Build)                → HKEY_CURRENT_USER\SOFTWARE\Epic Games\Unreal Engine\Builds\{GUID}
    4. 引擎目录的 Engine/Build/Build.version     → 权威版本号
    5. InstalledBuild.txt / SourceDistribution.txt → 区分 launcher vs source_build

只支持 Windows。其他平台返回空列表（让前端引导用户手填）。
"""
from __future__ import annotations

import json
import logging
import platform
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("engines.ue_resolver")

# ==================== 数据结构 ====================


@dataclass
class UEEngineInfo:
    path: str                           # 引擎根目录（含 Engine/ 子目录）
    version: str = ""                   # "5.3.2"（Major.Minor.Patch）
    version_full: Dict[str, Any] = field(default_factory=dict)  # Build.version 原文
    type: str = "unknown"               # "launcher" | "source_build" | "unknown"
    engine_association: str = ""        # .uproject 里用来关联的字符串：版本号 or "{GUID}"
    has_ubt: bool = False
    has_editor: bool = False
    warnings: List[str] = field(default_factory=list)
    source_guid: Optional[str] = None   # 自编译时对应 HKCU 里的 GUID

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ==================== 公开 API ====================


def detect_installed_engines() -> List[UEEngineInfo]:
    """扫注册表返回本机所有已知 UE 引擎。

    顺序：HKLM 官方版（按版本号升序） → HKCU 自编译（按 GUID 排序）
    """
    result: List[UEEngineInfo] = []
    if not _is_windows():
        logger.info("当前平台 %s 非 Windows，UE 引擎自动检测不可用", sys.platform)
        return result

    # HKLM 官方 Launcher
    for ver, path in _scan_hklm_engines():
        info = verify_engine(path)
        info.engine_association = ver
        # HKLM 一定是 launcher；若 type 判定失败，强制标记
        if info.type == "unknown":
            info.type = "launcher"
        result.append(info)

    # HKCU 自编译
    for guid, path in _scan_hkcu_engines():
        info = verify_engine(path)
        info.engine_association = "{" + guid + "}"
        info.source_guid = guid
        if info.type == "unknown":
            info.type = "source_build"
        result.append(info)

    logger.info(
        "检测到 %d 个 UE 引擎（HKLM %d + HKCU %d）",
        len(result),
        sum(1 for e in result if e.type == "launcher"),
        sum(1 for e in result if e.type == "source_build"),
    )
    return result


def resolve_project_engine(uproject_path: str | Path) -> Optional[UEEngineInfo]:
    """根据 .uproject 的 EngineAssociation 字段定位到具体引擎。

    返回 None 表示关联失败（前端应让用户从 detect_installed_engines 列表里选）。
    """
    p = Path(uproject_path)
    if not p.exists():
        logger.warning("uproject 不存在: %s", p)
        return None

    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            uproject = json.load(f)
    except Exception as e:
        logger.warning("uproject 解析失败 %s: %s", p, e)
        return None

    assoc = (uproject.get("EngineAssociation") or "").strip()

    # Case 1: 版本号如 "5.3" → HKLM
    if assoc and not assoc.startswith("{"):
        for ver, path in _scan_hklm_engines():
            if ver == assoc:
                info = verify_engine(path)
                info.engine_association = assoc
                if info.type == "unknown":
                    info.type = "launcher"
                return info
        logger.warning("EngineAssociation=%s 在 HKLM 找不到，需要用户手选", assoc)
        return None

    # Case 2: GUID "{...}" → HKCU
    if assoc.startswith("{") and assoc.endswith("}"):
        guid = assoc[1:-1]
        for g, path in _scan_hkcu_engines():
            if g.lower() == guid.lower():
                info = verify_engine(path)
                info.engine_association = assoc
                info.source_guid = g
                if info.type == "unknown":
                    info.type = "source_build"
                return info
        logger.warning("EngineAssociation=%s 在 HKCU 找不到", assoc)
        return None

    # Case 3: 空串 → 扫相对路径（.uproject 同级或上级找 Engine/）
    cur = p.parent
    for _ in range(5):   # 最多往上找 5 层
        candidate = cur / "Engine"
        if candidate.is_dir() and (candidate / "Build").is_dir():
            info = verify_engine(str(cur))
            info.engine_association = ""
            info.warnings.append("EngineAssociation 为空，通过相对路径定位")
            return info
        if cur.parent == cur:
            break
        cur = cur.parent

    logger.warning("uproject %s 的 EngineAssociation 为空且无法从相对路径定位", p)
    return None


def verify_engine(engine_path: str | Path) -> UEEngineInfo:
    """给定引擎根目录，做完整验证（版本号 + 类型 + 工具链存在性）。"""
    p = Path(engine_path)
    info = UEEngineInfo(path=str(p))

    if not p.is_dir():
        info.warnings.append(f"路径不存在或不是目录: {p}")
        return info

    engine_dir = p / "Engine"
    if not engine_dir.is_dir():
        info.warnings.append("缺 Engine/ 子目录，不像是 UE 引擎根")
        return info

    # 版本号
    bv = engine_dir / "Build" / "Build.version"
    if bv.is_file():
        try:
            with open(bv, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            info.version_full = data
            mj, mn, pt = data.get("MajorVersion"), data.get("MinorVersion"), data.get("PatchVersion")
            if mj is not None and mn is not None:
                info.version = f"{mj}.{mn}" + (f".{pt}" if pt not in (None, 0) else f".{pt or 0}")
        except Exception as e:
            info.warnings.append(f"Build.version 解析失败: {e}")
    else:
        info.warnings.append("缺 Engine/Build/Build.version，无法确认版本")

    # 类型判定
    if (engine_dir / "Build" / "InstalledBuild.txt").is_file():
        info.type = "launcher"
    elif (engine_dir / "Build" / "SourceDistribution.txt").is_file():
        info.type = "source_build"
    # else 保持 "unknown"，由调用方根据来源（HKLM/HKCU）填

    # 工具链存在性（UE4 老路径 vs UE5 子目录路径）
    ubt_candidates = [
        engine_dir / "Binaries" / "DotNET" / "UnrealBuildTool" / "UnrealBuildTool.exe",   # UE5
        engine_dir / "Binaries" / "DotNET" / "UnrealBuildTool.exe",                        # UE4
    ]
    info.has_ubt = any(p.is_file() for p in ubt_candidates)
    if not info.has_ubt:
        info.warnings.append(
            "缺 UnrealBuildTool.exe；若是自编译 build，需先 GenerateProjectFiles.bat + 编引擎"
        )

    info.has_editor = (
        engine_dir / "Binaries" / "Win64" / "UnrealEditor.exe"
    ).is_file() or (
        engine_dir / "Binaries" / "Win64" / "UE4Editor.exe"
    ).is_file()

    return info


def get_ubt_path(engine_path: str | Path) -> Optional[Path]:
    """拿到 UBT 的可执行文件路径（不存在返回 None）。UE5 优先，老版 UE4 作 fallback。"""
    base = Path(engine_path) / "Engine" / "Binaries" / "DotNET"
    for rel in ("UnrealBuildTool/UnrealBuildTool.exe", "UnrealBuildTool.exe"):
        p = base / rel
        if p.is_file():
            return p
    return None


def get_templates_dir(engine_path: str | Path) -> Optional[Path]:
    """拿到引擎 Templates/ 目录（供 A.5 模板实例化用）"""
    p = Path(engine_path) / "Templates"
    return p if p.is_dir() else None


# ==================== 内部实现：注册表扫描 ====================


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _scan_hklm_engines() -> List[tuple]:
    """返回 [(version_str, install_dir), ...]"""
    if not _is_windows():
        return []
    try:
        import winreg
    except ImportError:
        return []

    result: List[tuple] = []
    try:
        hkey = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\EpicGames\Unreal Engine",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        )
    except OSError:
        logger.debug("HKLM 无 UE 注册表项")
        return []

    try:
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(hkey, i)
            except OSError:
                break
            i += 1
            try:
                sk = winreg.OpenKey(hkey, sub, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
                try:
                    path, _ = winreg.QueryValueEx(sk, "InstalledDirectory")
                    result.append((sub, str(path)))
                finally:
                    winreg.CloseKey(sk)
            except OSError:
                continue
    finally:
        winreg.CloseKey(hkey)

    # 按版本号升序（"4.24" < "5.3" < "5.7"）
    def _key(t):
        parts = t[0].split(".")
        try:
            return tuple(int(x) for x in parts)
        except ValueError:
            return (0,)
    result.sort(key=_key)
    return result


def _scan_hkcu_engines() -> List[tuple]:
    """返回 [(guid, path), ...]（无大括号的纯 GUID）"""
    if not _is_windows():
        return []
    try:
        import winreg
    except ImportError:
        return []

    result: List[tuple] = []
    try:
        hkey = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Epic Games\Unreal Engine\Builds",
            0,
            winreg.KEY_READ,
        )
    except OSError:
        logger.debug("HKCU 无 UE Builds 注册表项")
        return []

    try:
        i = 0
        while True:
            try:
                name, value, _ = winreg.EnumValue(hkey, i)
            except OSError:
                break
            i += 1
            # name 可能带 {}，统一剥掉
            guid = name.strip("{}")
            result.append((guid, str(value)))
    finally:
        winreg.CloseKey(hkey)

    result.sort(key=lambda t: t[0])
    return result
