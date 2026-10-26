"""Unity 插件贡献的仓库页根目录：Hub 里对应版本的编辑器安装位置。

版本来自项目 ``ProjectSettings/ProjectVersion.txt`` 的 ``m_EditorVersion``。
安装位置先查 Unity Hub 的 editors 清单，再按常见 Hub Editor 目录对版本号。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List


def workspace_roots(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    repo = Path(str((project or {}).get("git_repo_path") or "").strip() or ".")
    version = _editor_version(repo) if repo.is_dir() else ""
    path = _find_editor(version) if version else ""
    if path:
        return [{
            "id": "editor",
            "label": f"Unity {version}",
            "path": path,
            "kind": "engine",
            "available": True,
            "message": "",
        }]
    if version:
        message = f"ProjectVersion.txt 需要 Unity {version}，本机没有找到这个版本的编辑器目录。"
    elif repo.is_dir():
        message = "没有读到 ProjectSettings/ProjectVersion.txt，无法定位 Unity 编辑器目录。"
    else:
        message = "项目仓库路径无效，无法定位 Unity 编辑器目录。"
    return [{
        "id": "editor",
        "label": "Unity 编辑器",
        "path": "",
        "kind": "engine",
        "available": False,
        "message": message,
    }]


def _editor_version(repo: Path) -> str:
    pv = repo / "ProjectSettings" / "ProjectVersion.txt"
    try:
        if not pv.is_file():
            return ""
        text = pv.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        if line.startswith("m_EditorVersion:"):
            return line.split(":", 1)[1].strip()
    return ""


def _find_editor(version: str) -> str:
    if not version:
        return ""
    for exe in _hub_exes_for_version(version):
        root = _editor_root_from_exe(exe)
        if root:
            return root
    for hub in _hub_editor_dirs():
        cand = hub / version
        if (cand / "Editor" / "Unity.exe").is_file():
            return str(cand)
    return ""


def _editor_root_from_exe(exe: str) -> str:
    path = Path(exe)
    # .../<version>/Editor/Unity.exe
    if path.name.lower() == "unity.exe" and path.parent.name.lower() == "editor":
        root = path.parent.parent
        if root.is_dir():
            return str(root)
    return ""


def _hub_exes_for_version(version: str) -> List[str]:
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return []
    hub = Path(appdata) / "UnityHub"
    found: List[str] = []
    for name in ("editors.json", "editors-v2.json"):
        found.extend(_exes_for_version(hub / name, version))
    return found


def _exes_for_version(path: Path, version: str) -> List[str]:
    try:
        if not path.is_file():
            return []
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    exes: List[str] = []
    if isinstance(data, dict):
        if version in data:
            exes.extend(_exe_strings(data[version]))
        for key, value in data.items():
            if key == version:
                continue
            if version in str(key) or version in json.dumps(value, ensure_ascii=False):
                exes.extend(_exe_strings(value))
    elif isinstance(data, list):
        for value in data:
            if version in json.dumps(value, ensure_ascii=False):
                exes.extend(_exe_strings(value))
    return exes


def _exe_strings(value: Any) -> List[str]:
    out: List[str] = []
    if isinstance(value, str) and value.lower().endswith("unity.exe"):
        out.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            out.extend(_exe_strings(item))
    elif isinstance(value, list):
        for item in value:
            out.extend(_exe_strings(item))
    return out


def _hub_editor_dirs() -> List[Path]:
    roots: List[Path] = []
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(key, "")
        if base:
            roots.append(Path(base) / "Unity" / "Hub" / "Editor")
    for extra in (r"D:\Program Files", r"E:\Program Files", r"D:\Unity", r"E:\Unity"):
        roots.append(Path(extra) / "Hub" / "Editor" if extra.endswith("Unity")
                     else Path(extra) / "Unity" / "Hub" / "Editor")
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        sec = Path(appdata) / "UnityHub" / "secondaryInstallPath.json"
        custom = _secondary_install_path(sec)
        if custom:
            roots.append(Path(custom) / "Editor" if Path(custom).name.lower() != "editor"
                         else Path(custom))
            # Hub 的 secondary 路径有时直接就是 Hub 根，编辑器在其 Editor/<version>
            roots.append(Path(custom) / "Editor")
    # 去重，保持顺序
    seen = set()
    unique: List[Path] = []
    for root in roots:
        key = str(root).replace("\\", "/").rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def _secondary_install_path(path: Path) -> str:
    try:
        if not path.is_file():
            return ""
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return ""
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, dict):
        for key in ("path", "secondaryInstallPath", "installPath"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""
