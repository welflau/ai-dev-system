"""共享的文本读取原语（P1 拆环）。

原先 ``safe_read_text`` 定义在 ``memory_record_io``，而 ``memory_record_index``
顶层 import 它、``memory_record_io`` 又在 ``refresh_index_if_exists`` 里延迟
import ``memory_update_index``，形成 IO ↔ IDX 双向环。

把这个无状态叶子函数抽到本模块后：
  IO  -> memory_text_io（re-export，6 个下游导入方不变）
  IDX -> memory_text_io
  IO  -> IDX 保留（refresh_index_if_exists，单向，不再成环）
"""
from __future__ import annotations

import time
from pathlib import Path


def safe_read_text(
    path: Path,
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
    max_attempts: int = 20,
    delay_seconds: float = 0.005,
) -> str:
    """Read ``path`` tolerating brief writer-replace contention.

    On Windows, when a writer is in the middle of ``os.replace`` of an
    atomic-write tmp file onto ``path``, a concurrent reader can observe:

    * ``PermissionError`` -- the writer holds the destination handle without
      ``FILE_SHARE_DELETE`` for the duration of the replace syscall.
    * ``FileNotFoundError`` -- the source tmp was renamed but, in rare
      cases (junctions, antivirus filters), the destination momentarily
      lacks a directory entry.

    Both windows are tiny (sub-millisecond on a healthy filesystem). This
    helper bounded-retries the read so callers never spuriously see
    "file vanished" / "access denied" in normal multi-agent operation.
    Other ``OSError`` subclasses propagate unchanged.
    """
    last_exc: OSError | None = None
    for _ in range(max(1, max_attempts)):
        try:
            return path.read_text(encoding=encoding, errors=errors)
        except (PermissionError, FileNotFoundError) as exc:
            last_exc = exc
            time.sleep(delay_seconds)
    assert last_exc is not None
    raise last_exc
