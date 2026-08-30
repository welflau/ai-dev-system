"""Checkpoint blob 存储（content-addressed）。"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

from config import DATA_DIR

logger = logging.getLogger("checkpoint.store")

BLOBS_ROOT = DATA_DIR / "checkpoints" / "blobs"
MAX_BLOB_BYTES = 2 * 1024 * 1024  # 2 MiB

_BINARY_EXTS = {
    ".exe", ".dll", ".pdb", ".so", ".dylib", ".a", ".lib",
    ".uasset", ".umap", ".pak", ".bin", ".dat",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp",
    ".mp3", ".mp4", ".wav", ".avi", ".zip", ".7z", ".rar", ".gz",
    ".pdf", ".woff", ".woff2", ".ttf", ".otf",
}


def normalize_rel_path(path: str) -> str:
    rel = (path or "").replace("\\", "/").strip().lstrip("/")
    if not rel or ".." in rel.split("/"):
        return ""
    return rel


def is_binary_ext(path: str) -> bool:
    p = path.lower()
    for ext in _BINARY_EXTS:
        if p.endswith(ext):
            return True
    return False


def blob_path(sha256: str) -> Path:
    hh = sha256[:2]
    return BLOBS_ROOT / hh / sha256


def put_bytes(data: bytes) -> str:
    """写入 blob，返回 sha256 hex。已存在则跳过写盘。"""
    h = hashlib.sha256(data).hexdigest()
    dest = blob_path(h)
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    return h


def get_bytes(sha256: str) -> Optional[bytes]:
    if not sha256:
        return None
    dest = blob_path(sha256)
    if not dest.is_file():
        return None
    try:
        return dest.read_bytes()
    except Exception as e:
        logger.warning("读 blob 失败 %s: %s", sha256[:12], e)
        return None


def read_file_for_snapshot(abs_path: Path) -> tuple:
    """返回 (kind, before_hash|None, byte_size, skipped_reason|None)。

    kind: created（不存在）| modified | skipped
    """
    if not abs_path.exists():
        return "created", None, 0, None
    if abs_path.is_dir():
        return "skipped", None, 0, "is_directory"
    try:
        data = abs_path.read_bytes()
    except Exception as e:
        return "skipped", None, 0, f"io_error:{e}"
    if len(data) > MAX_BLOB_BYTES:
        return "skipped", None, len(data), "too_large"
    # 粗判二进制
    if b"\x00" in data[:8192]:
        return "skipped", None, len(data), "binary"
    try:
        h = put_bytes(data)
        return "modified", h, len(data), None
    except Exception as e:
        return "skipped", None, len(data), f"store_error:{e}"
