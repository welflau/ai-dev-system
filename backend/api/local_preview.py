"""全局助手预览本地文件。

项目里的文件走仓库接口。全局助手没有当前项目，气泡里经常是相对路径
或带环境变量的路径，这里负责对上磁盘上的文件并读出正文。
凭证类文件始终拒绝。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

_BLOCKED_NAMES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "credentials", "secrets", "id_rsa", "id_ed25519",
}
_BLOCKED_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".cer"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".ico"}
_TEXT_LIMIT = 400_000
_ENV_ROOTS = ("SIBOOT_WORKSPACE_PATH", "WORKSPACE_PATH")
_NOISE = ".,;:)]}）】>\"'`"
_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "Intermediate", "Binaries", "Saved", "DerivedDataCache",
    "Cache", "Code Cache", "GPUCache", "blob_storage", "sessions",
}
_GENERIC_SEGMENTS = {"agent", "agents", "skill", "skills", "src", "docs", "app", "lib"}

_PCT_ENV = re.compile(r"%([^%\\/]+)%")
_DOLLAR_ENV = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


def blocked_reason(path: Path) -> str:
    name = path.name.lower()
    if name in _BLOCKED_NAMES or name.startswith(".env"):
        return f"不预览凭证文件: {path.name}"
    if path.suffix.lower() in _BLOCKED_SUFFIXES:
        return f"不预览密钥文件: {path.suffix}"
    if any(k in name for k in ("password", "secret", "token", "credential")):
        return f"文件名包含敏感词: {path.name}"
    return ""


def expand_env(text: str) -> str:
    def pct(m):
        return os.environ.get(m.group(1), m.group(0))

    def dollar(m):
        return os.environ.get(m.group(1), m.group(0))

    return _DOLLAR_ENV.sub(dollar, _PCT_ENV.sub(pct, text or ""))


def _clean(text: str) -> str:
    s = expand_env(str(text or "")).strip().strip('"').strip("'")
    while s and s[-1] in _NOISE:
        s = s[:-1]
    s = s.replace("/", "\\") if os.name == "nt" else s
    return s


def _default_roots() -> List[Path]:
    """siboot 没把工作区写进环境变量时，仍从它的本机目录里找。"""
    found: List[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        found.append(Path(appdata) / "siboot" / "workspace")
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if home:
        found.append(Path(home) / ".siboot")
    for key in _ENV_ROOTS:
        val = os.environ.get(key)
        if val:
            found.append(Path(val))
    roots: List[Path] = []
    seen = set()
    for root in found:
        try:
            if not root.is_dir():
                continue
            key = str(root.resolve()).casefold()
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        roots.append(root)
    return roots


def _segments(text: str) -> List[str]:
    parts = re.split(r"[\\/]+", text.replace("\\", "/"))
    out = []
    for part in parts:
        part = part.strip().strip('"').strip("'")
        while part and part[-1] in _NOISE:
            part = part[:-1]
        if len(part) < 3 or part.casefold() in _GENERIC_SEGMENTS:
            continue
        if part.startswith("$") or part.startswith("%") or ":" in part:
            continue
        out.append(part)
    return out


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _prefer_tokens(raw_rel: str, hints: List[str]) -> List[str]:
    tokens: List[str] = []
    seen = set()
    for text in [raw_rel, *hints]:
        for seg in _segments(text):
            key = seg.casefold()
            if key in seen:
                continue
            seen.add(key)
            tokens.append(seg)
    return tokens


def _search_named(roots: List[Path], filename: str, tokens: List[str], suffixes: List[str]) -> Optional[Path]:
    """在已知根目录下按文件名找。多个同名文件时，优先路径里含对话提到的目录。"""
    want = filename.casefold()
    token_cf = [t.casefold() for t in tokens if t.casefold() != want]
    suffix_cf = [s.replace("\\", "/").strip("/").casefold() for s in suffixes if s]
    best: Optional[Path] = None
    best_score = -1
    zero_score = 0
    seen_dirs = 0
    for root in roots:
        stack = [(root, 0)]
        while stack and seen_dirs < 4000:
            cur, depth = stack.pop()
            seen_dirs += 1
            try:
                entries = list(cur.iterdir())
            except OSError:
                continue
            for entry in entries:
                try:
                    is_file = entry.is_file()
                    is_dir = entry.is_dir()
                except OSError:
                    continue
                if is_file and entry.name.casefold() == want:
                    path_cf = str(entry).replace("\\", "/").casefold()
                    score = sum(2 for t in token_cf if t and t in path_cf)
                    score += sum(5 for s in suffix_cf if s and path_cf.endswith("/" + s))
                    if score == 0:
                        zero_score += 1
                    if score > best_score:
                        best = entry
                        best_score = score
                elif is_dir and depth < 6 and entry.name not in _SKIP_DIRS:
                    stack.append((entry, depth + 1))
    if best is None:
        return None
    if best_score <= 0 and zero_score > 1:
        return None
    return best


def resolve_local_file(raw: str, hints: Optional[List[str]] = None) -> Optional[Path]:
    """把气泡里的路径对到一个真实文件。对不上返回 None。"""
    cleaned = _clean(raw)
    if not cleaned:
        return None
    direct = Path(cleaned)
    if direct.is_absolute() and _is_file(direct):
        return direct

    rel = cleaned.replace("\\", "/").lstrip("./").lstrip("/")
    if not rel:
        return None
    rel_cf = rel.casefold()
    rel_path = Path(*[p for p in rel.split("/") if p and p != "."])
    hint_list = [h for h in (hints or []) if str(h).strip()]
    tokens = _prefer_tokens(rel, hint_list)

    bases: List[Path] = []
    for hint in hint_list:
        h = _clean(hint)
        if not h:
            continue
        hp = Path(h)
        if hp.is_absolute() and _is_file(hp):
            norm = str(hp).replace("\\", "/").casefold()
            if norm == rel_cf or norm.endswith("/" + rel_cf):
                return hp
            bases.append(hp.parent)
        elif hp.is_absolute():
            bases.append(hp if _is_dir(hp) else hp.parent)
        else:
            # 对话里的相对目录，例如 agent/siboot-smallrpg
            rel_hint = h.replace("\\", "/").strip("/")
            if rel_hint and rel_hint.casefold() != rel_cf:
                tokens.extend(seg for seg in _segments(rel_hint) if seg.casefold() not in {t.casefold() for t in tokens})

    roots = _default_roots()
    search_roots: List[Path] = []
    seen = set()

    def add_root(path: Path) -> None:
        try:
            if not path.is_dir():
                return
            key = str(path.resolve()).casefold()
        except OSError:
            return
        if key in seen:
            return
        seen.add(key)
        search_roots.append(path)

    for base in bases:
        cursor = base
        for _ in range(10):
            cand = cursor / rel_path
            if _is_file(cand):
                return cand
            add_root(cursor)
            if cursor.parent == cursor:
                break
            cursor = cursor.parent
    for root in roots:
        cand = root / rel_path
        if _is_file(cand):
            return cand
        # 相对目录提示挂到工作区根上：agent/siboot-smallrpg + SKILL.md
        for hint in hint_list:
            h = _clean(hint)
            if not h or Path(h).is_absolute():
                continue
            hint_rel = Path(*[p for p in h.replace("\\", "/").split("/") if p and p != "."])
            cand = root / hint_rel / rel_path
            if _is_file(cand):
                return cand
            cand = root / hint_rel
            if _is_file(cand) and cand.name.casefold() == rel_path.name.casefold():
                return cand
        add_root(root)

    suffixes = [rel]
    for hint in hint_list:
        h = _clean(hint)
        if not h or Path(h).is_absolute():
            continue
        hint_rel = "/".join(p for p in h.replace("\\", "/").split("/") if p and p != ".")
        if hint_rel:
            suffixes.append(f"{hint_rel}/{rel_path.name}")
    return _search_named(search_roots, rel_path.name, tokens, suffixes)


def read_local_preview(path: Path) -> dict:
    reason = blocked_reason(path)
    if reason:
        raise PermissionError(reason)
    if not _is_file(path):
        raise FileNotFoundError(str(path))
    ext = path.suffix.lower()
    if ext in _IMAGE_EXTS:
        return {
            "path": str(path),
            "filename": path.name,
            "kind": "image",
            "content": "",
            "truncated": False,
        }
    size = path.stat().st_size
    if size > 2_000_000:
        return {
            "path": str(path),
            "filename": path.name,
            "kind": "binary",
            "content": "",
            "truncated": False,
            "message": "文件超过 2MB，不在这里展开",
        }
    data = path.read_bytes()
    if b"\x00" in data[:8192]:
        return {
            "path": str(path),
            "filename": path.name,
            "kind": "binary",
            "content": "",
            "truncated": False,
            "message": "这是二进制文件，不能按文本打开",
        }
    text = data.decode("utf-8", "replace")
    truncated = len(text) > _TEXT_LIMIT
    if truncated:
        text = text[:_TEXT_LIMIT]
    return {
        "path": str(path),
        "filename": path.name,
        "kind": "text",
        "content": text,
        "truncated": truncated,
    }
