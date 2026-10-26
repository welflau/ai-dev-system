"""UE 插件贡献的仓库页根目录：本机引擎安装位置。

宿主只按 traits 调用 ``workspace_roots``。引擎路径优先用项目上已保存的
``ue_engine_path``，没有再按 ``.uproject`` 的 EngineAssociation 解析。
解析不到时仍返回一条不可用记录，让 Tab 出现并说明原因。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def workspace_roots(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    path, version, message = _resolve(project or {})
    short = _short_version(version)
    label = f"UE 引擎 {short}" if short else "UE 引擎"
    if path:
        return [{
            "id": "engine",
            "label": label,
            "path": path,
            "kind": "engine",
            "available": True,
            "message": "",
        }]
    return [{
        "id": "engine",
        "label": "UE 引擎",
        "path": "",
        "kind": "engine",
        "available": False,
        "message": message or "没有定位到 UE 引擎目录",
    }]


def _resolve(project: Dict[str, Any]) -> Tuple[str, str, str]:
    stored = str(project.get("ue_engine_path") or "").strip()
    version = str(project.get("ue_engine_version") or "").strip()
    if stored and _is_engine_root(stored):
        return stored, _version_of(stored) or version, ""

    repo = str(project.get("git_repo_path") or "").strip()
    uproject = _find_uproject(repo)
    if uproject:
        try:
            from engines.ue_resolver import resolve_project_engine
            info = resolve_project_engine(uproject)
        except Exception as e:
            info = None
            version = version or ""
            fallback = f"读取 .uproject 关联的引擎失败: {e}"
        else:
            fallback = ""
            if info is not None and _is_engine_root(getattr(info, "path", "")):
                found = str(info.path)
                return found, (getattr(info, "version", "") or _version_of(found) or version), ""
            if info is not None and getattr(info, "warnings", None):
                fallback = "；".join(str(w) for w in info.warnings[:2])
        if stored:
            return "", version, f"项目里配置的引擎路径不是有效的引擎根: {stored}"
        return "", version, fallback or "没有从 .uproject 的 EngineAssociation 解析到本机引擎"

    if stored:
        return "", version, f"项目里配置的引擎路径不是有效的引擎根: {stored}"
    return "", version, "项目没有 ue_engine_path，仓库根下也没有 .uproject"


def _is_engine_root(path: str) -> bool:
    if not path:
        return False
    try:
        return (Path(path) / "Engine").is_dir()
    except OSError:
        return False


def _short_version(version: str) -> str:
    parts = [p for p in (version or "").split(".") if p != ""]
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0]}.{parts[1]}"
    return version or ""


def _version_of(engine_root: str) -> str:
    try:
        from engines.ue_resolver import verify_engine
        info = verify_engine(engine_root)
    except Exception:
        return ""
    return str(getattr(info, "version", "") or "")


def _find_uproject(repo: str) -> Optional[Path]:
    if not repo:
        return None
    root = Path(repo)
    try:
        if not root.is_dir():
            return None
        found = sorted(p for p in root.glob("*.uproject") if p.is_file())
    except OSError:
        return None
    return found[0] if found else None
