"""
读取 CLI（CodeBuddy / Claude）落在用户目录的项目记忆文件。

路径约定（与 CodeBuddy 一致）：
  ~/.codebuddy/projects/<slug>/memory/*.md
  ~/.claude/projects/<slug>/memory/*.md

slug：F:\\A_Works\\Kinema → f-A_Works-Kinema（盘符小写，其余保持大小写，\\ → -）
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("cli_file_memory")

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_TYPE_MAP = {
    "project": "project_context",
    "user": "user_profile",
    "feedback": "behavior_feedback",
    "ref": "external_ref",
    "external": "external_ref",
    "project_context": "project_context",
    "user_profile": "user_profile",
    "behavior_feedback": "behavior_feedback",
    "external_ref": "external_ref",
}


def repo_path_to_cli_slug(repo_path: str) -> str:
    """把本地仓库路径编码成 CodeBuddy/Claude projects 目录名。"""
    p = os.path.abspath((repo_path or "").strip())
    if len(p) >= 2 and p[1] == ":":
        return p[0].lower() + p[2:].replace("\\", "-").replace("/", "-")
    return p.replace("\\", "-").replace("/", "-").lstrip("-")


def discover_cli_memory_dirs(repo_path: str) -> List[Tuple[str, Path]]:
    """返回 [(source, memory_dir), ...]，source 如 codebuddy / claude。"""
    if not (repo_path or "").strip():
        return []
    slug = repo_path_to_cli_slug(repo_path)
    home = Path.home()
    found: List[Tuple[str, Path]] = []
    for source, base in (
        ("codebuddy", home / ".codebuddy" / "projects" / slug / "memory"),
        ("claude", home / ".claude" / "projects" / slug / "memory"),
    ):
        if base.is_dir():
            found.append((source, base))
    return found


def _parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    m = _FRONTMATTER_RE.match(text.lstrip("\ufeff"))
    if not m:
        return {}, text
    meta: Dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip().strip("\"'")
    return meta, m.group(2).strip()


def _mtime_iso(path: Path) -> str:
    try:
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    except OSError:
        return ""


def _read_one_file(source: str, path: Path) -> Optional[Dict[str, Any]]:
    if path.name.upper() == "MEMORY.MD":
        return None
    if path.suffix.lower() != ".md":
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.debug("读 CLI 记忆失败 %s: %s", path, e)
        return None
    meta, body = _parse_frontmatter(text)
    title = (meta.get("name") or meta.get("title") or path.stem).strip()
    raw_type = (meta.get("type") or "project").strip().lower()
    mem_type = _TYPE_MAP.get(raw_type, "project_context")
    content = body.strip() or (meta.get("description") or "").strip()
    if not title and not content:
        return None
    return {
        "id": f"cli:{source}:{path.stem}",
        "type": mem_type,
        "title": title[:200],
        "content": content[:4000],
        "agent_type": source,
        "created_at": _mtime_iso(path),
        "source": source,
        "source_path": str(path),
        "readonly": True,
    }


def load_cli_file_memories(
    repo_path: str,
    *,
    query: str = "",
    type_filter: str = "",
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """扫描 CLI 项目记忆目录，返回与 agent_memory 行结构兼容的列表。"""
    items: List[Dict[str, Any]] = []
    q = (query or "").strip().lower()
    tf = (type_filter or "").strip()
    if tf in ("", "all"):
        tf = ""

    for source, mem_dir in discover_cli_memory_dirs(repo_path):
        try:
            files = sorted(mem_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            continue
        for path in files:
            item = _read_one_file(source, path)
            if not item:
                continue
            if tf and item["type"] != tf:
                continue
            if q:
                blob = f"{item.get('title','')} {item.get('content','')}".lower()
                if q not in blob:
                    continue
            items.append(item)

    items.sort(key=lambda m: m.get("created_at") or "", reverse=True)
    return items[: max(1, min(limit, 200))]
