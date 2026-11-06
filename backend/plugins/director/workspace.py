"""仓库页贡献 works/ 作为作品工作包根。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def workspace_roots(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    repo = str(project.get("git_repo_path") or "").strip()
    if not repo:
        return [{
            "id": "works",
            "label": "作品工作包",
            "path": "",
            "kind": "content",
            "available": False,
            "message": "项目没有仓库路径，无法定位 works/",
        }]
    works = Path(repo) / "works"
    if works.is_dir():
        return [{
            "id": "works",
            "label": "作品工作包",
            "path": str(works),
            "kind": "content",
            "available": True,
            "message": "",
        }]
    return [{
        "id": "works",
        "label": "作品工作包",
        "path": str(works),
        "kind": "content",
        "available": False,
        "message": "还没有 works/，先跑 init_work_package",
    }]
