"""作品工作包路径与 slug。"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Optional

_SLUG_RE = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)


def slugify(title: str) -> str:
    raw = (title or "").strip()
    slug = _SLUG_RE.sub("-", raw).strip("-")
    slug = slug[:48] or "untitled"
    return slug


def works_root(repo_path: str) -> Path:
    return Path(repo_path).resolve() / "works"


def package_dir(repo_path: str, slug: str) -> Path:
    return works_root(repo_path) / slug


def unique_slug(repo_path: str, title: str) -> str:
    base = slugify(title)
    root = works_root(repo_path)
    if not (root / base).exists():
        return base
    stamped = f"{base}-{date.today().isoformat()}"
    if not (root / stamped).exists():
        return stamped
    n = 2
    while (root / f"{stamped}-{n}").exists():
        n += 1
    return f"{stamped}-{n}"


def current_slug_file(repo_path: str) -> Path:
    return works_root(repo_path) / ".current-slug"


def write_current_slug(repo_path: str, slug: str) -> None:
    root = works_root(repo_path)
    root.mkdir(parents=True, exist_ok=True)
    current_slug_file(repo_path).write_text(slug, encoding="utf-8")


def read_current_slug(repo_path: str) -> Optional[str]:
    p = current_slug_file(repo_path)
    if not p.is_file():
        return None
    slug = p.read_text(encoding="utf-8").strip()
    return slug or None


def find_existing_slug(repo_path: str, slug: Optional[str] = None) -> Optional[str]:
    if slug:
        d = package_dir(repo_path, slug)
        if d.is_dir():
            return slug
    marked = read_current_slug(repo_path)
    if marked and package_dir(repo_path, marked).is_dir():
        return marked
    root = works_root(repo_path)
    if not root.is_dir():
        return None
    dirs = sorted(p for p in root.iterdir() if p.is_dir())
    return dirs[-1].name if dirs else None


def archive_paths(repo_path: str, slug: str, rel_paths: list) -> list:
    """把打回的文件移到 archive/，不覆盖正在用的工作副本。"""
    from datetime import datetime
    import shutil

    moved = []
    dest_root = package_dir(repo_path, slug) / "archive" / datetime.now().strftime("%Y%m%d-%H%M%S")
    repo = Path(repo_path).resolve()
    for raw in rel_paths or []:
        rel = str(raw or "").replace("\\", "/").lstrip("/")
        if not rel or ".." in rel.split("/"):
            continue
        src = (repo / rel).resolve()
        try:
            src.relative_to(repo)
        except ValueError:
            continue
        if not src.is_file():
            continue
        dest_root.mkdir(parents=True, exist_ok=True)
        dest = dest_root / src.name
        n = 2
        while dest.exists():
            dest = dest_root / f"{src.stem}-{n}{src.suffix}"
            n += 1
        shutil.move(str(src), str(dest))
        moved.append(str(dest.relative_to(repo)).replace("\\", "/"))
    return moved
