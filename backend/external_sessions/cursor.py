"""
Cursor 会话 provider —— 只读。

存储模型（扫描阶段已经确认）：
  %APPDATA%\\Cursor\\User\\
  ├── workspaceStorage\\<hash>\\workspace.json  — {"folder": "file:///i%3A/..."}
  └── globalStorage\\state.vscdb                 — composerHeaders + cursorDiskKV
          composerHeaders(composerId, workspaceId, createdAt, lastUpdatedAt, value JSON)
          cursorDiskKV(key, value)
              composerData:<cid>   → 元数据 + fullConversationHeadersOnly 消息顺序
              bubbleId:<cid>:<bid> → 单条消息；type=1 user，type=2 assistant
              agentKv:blob:<hash>  → 二进制 blob，这次忽略

关键：Cursor 开着时文件被锁。sqlite3 开 URI 用 ?mode=ro&immutable=1
跳过 WAL/锁协商，纯快照读。
"""
from __future__ import annotations

import difflib
import json
import logging
import os
import re
import sqlite3
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar, List, Optional

from .base import ExternalMessage, ExternalSessionDetail, ExternalSessionSummary

logger = logging.getLogger("external_sessions.cursor")


# ---------- 路径辅助 ----------


def _default_cursor_user_dir() -> Optional[Path]:
    """默认 %APPDATA%\\Cursor\\User；env CURSOR_USER_DIR 可覆盖（Insiders / 便携版）。"""
    env = os.environ.get("CURSOR_USER_DIR")
    if env:
        p = Path(env)
        return p if p.is_dir() else None
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    p = Path(appdata) / "Cursor" / "User"
    return p if p.is_dir() else None


def _ro_connect(path: Path) -> sqlite3.Connection:
    """
    只读 + immutable 打开 SQLite。
    - mode=ro：不建 journal/wal
    - immutable=1：声明文件不会变，SQLite 直接跳过锁协商（Cursor 独占锁打开的 db 才能被我们读）
    """
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def _norm(p: str) -> str:
    """path 归一化：正斜杠、去尾部 sep、lower（Windows 文件系统不敏感）。"""
    return p.replace("\\", "/").rstrip("/").lower()


def _uri_to_path(uri: str) -> Optional[str]:
    """
    `file:///i%3A/A_Works/OG2/P4/UE5` → `i:/A_Works/OG2/P4/UE5`
    不是 file:// 开头或解码失败就 None。
    """
    if not uri or not uri.lower().startswith("file:///"):
        return None
    tail = uri[len("file:///"):]
    try:
        return urllib.parse.unquote(tail)
    except Exception:
        return None


def _path_matches_any(path: str, norm_roots: List[str]) -> bool:
    """path 已经是原始形态；roots 必须预先 _norm 过。"""
    pn = _norm(path)
    for r in norm_roots:
        if not r:
            continue
        if pn == r or pn.startswith(r + "/"):
            return True
    return False


_IMAGE_ID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")


def _sniff_image_mime(path: Path) -> str:
    """按 magic bytes 猜 content-type —— Cursor 粘贴图存的文件名统一是 .png 后缀，
    但实际字节经常是 JPEG（截图压缩导致），不能信扩展名。"""
    try:
        with path.open("rb") as f:
            head = f.read(12)
    except Exception:
        return "application/octet-stream"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _ms_to_iso(ms: Optional[int]) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return ""


# ---------- Provider ----------


class CursorProvider:
    name: ClassVar[str] = "cursor"

    def __init__(self, user_dir: Optional[Path] = None):
        self.user_dir = user_dir if user_dir is not None else _default_cursor_user_dir()

    @property
    def available(self) -> bool:
        """Cursor 没装 / 定位不到 User 目录 → list_sessions 返回空而不是炸。"""
        if not self.user_dir:
            return False
        return (self.user_dir / "globalStorage" / "state.vscdb").is_file()

    def _match_workspaces(self, candidate_roots: List[str]) -> List[str]:
        """遍历 workspaceStorage/*/workspace.json，返回 folder 命中任一候选根的 hash 列表。"""
        if not self.available:
            return []
        assert self.user_dir is not None
        storage_root = self.user_dir / "workspaceStorage"
        if not storage_root.is_dir():
            return []
        norm_roots = [_norm(r) for r in candidate_roots if r]
        if not norm_roots:
            return []
        hashes: List[str] = []
        for sub in storage_root.iterdir():
            if not sub.is_dir():
                continue
            ws_json = sub / "workspace.json"
            if not ws_json.is_file():
                continue
            try:
                with ws_json.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.debug("skip %s: %s", ws_json, e)
                continue
            folder = data.get("folder")
            if not folder:
                continue
            path = _uri_to_path(folder)
            if not path:
                continue
            if _path_matches_any(path, norm_roots):
                hashes.append(sub.name)
        return hashes

    def list_sessions(self, candidate_roots: List[str]) -> List[ExternalSessionSummary]:
        if not self.available:
            return []
        assert self.user_dir is not None
        hashes = self._match_workspaces(candidate_roots)
        if not hashes:
            return []
        db_path = self.user_dir / "globalStorage" / "state.vscdb"
        placeholders = ",".join("?" * len(hashes))
        try:
            with _ro_connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    f"SELECT composerId, workspaceId, createdAt, lastUpdatedAt, value "
                    f"FROM composerHeaders WHERE workspaceId IN ({placeholders}) "
                    f"ORDER BY lastUpdatedAt DESC",
                    hashes,
                ).fetchall()
        except Exception as e:
            logger.warning("read composerHeaders failed: %s", e)
            return []

        sessions: List[ExternalSessionSummary] = []
        for row in rows:
            summary = _row_to_summary(row)
            if summary:
                sessions.append(summary)
        return sessions

    def get_session(self, composer_id: str) -> Optional[ExternalSessionDetail]:
        if not self.available:
            return None
        assert self.user_dir is not None
        db_path = self.user_dir / "globalStorage" / "state.vscdb"
        try:
            with _ro_connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                head = conn.execute(
                    "SELECT composerId, workspaceId, createdAt, lastUpdatedAt, value "
                    "FROM composerHeaders WHERE composerId = ?",
                    (composer_id,),
                ).fetchone()
                if not head:
                    return None
                summary = _row_to_summary(head)
                if not summary:
                    return None
                data_row = conn.execute(
                    "SELECT value FROM cursorDiskKV WHERE key = ?",
                    (f"composerData:{composer_id}",),
                ).fetchone()
                order: List[dict] = []
                if data_row:
                    try:
                        data_json = json.loads(data_row["value"])
                        order = data_json.get("fullConversationHeadersOnly") or []
                    except Exception as e:
                        logger.debug("parse composerData failed: %s", e)

                messages: List[ExternalMessage] = []
                for entry in order:
                    bubble_id = entry.get("bubbleId")
                    if not bubble_id:
                        continue
                    bubble_row = conn.execute(
                        "SELECT value FROM cursorDiskKV WHERE key = ?",
                        (f"bubbleId:{composer_id}:{bubble_id}",),
                    ).fetchone()
                    if not bubble_row:
                        continue
                    try:
                        bubble = json.loads(bubble_row["value"])
                    except Exception:
                        continue
                    msg = _bubble_to_msg(bubble_id, bubble, entry.get("type"))
                    # Cursor 自己会写一些彻底没内容的占位 bubble（text/thinking/toolFormerData/images
                    # 全空，tokenCount 也是 0——像是中断/恢复留下的结构性空当，Cursor 自家 UI 里也不显示），
                    # 不丢给前端渲染成一条干扰视线的"(空消息)"。
                    if msg.kind == "text" and not msg.content and not msg.images and not msg.tool_calls:
                        continue
                    messages.append(msg)

                # 每轮的 edit_file_v2 聚合成「N Files Changed」卡片（Cursor 原生 UI 同款）
                messages = _attach_files_changed(
                    lambda content_id: _fetch_content_blob(conn, content_id), messages
                )
        except Exception as e:
            logger.warning("read session %s failed: %s", composer_id, e)
            return None

        detail = ExternalSessionDetail(**summary.model_dump(), messages=messages)
        detail.message_count = len(messages)
        return detail

    def get_image(self, composer_id: str, image_id: str) -> Optional[Path]:
        """
        粘贴图实测有两种挂法（见 _bubble_to_msg 的注释），对应两套不同的找文件方式：
          1. `workspaceStorage/<workspaceId>/images/<uuid>-<variant>.png` —— glob 一下。
             实测同一个 uuid 下所有 variant 文件内容字节级相同（大概是同一张图在不同引用点
             各写了一份），随便挑第一个命中的就行，不用费劲挑"最对"的那个。
          2. bubble.context.selectedImages 里的 `path` 字段（绝对路径，文件名里嵌的 uuid
             和 JSON 里的 uuid 对不上，没法 glob）—— 只能退回去扫这个 composer 的所有 bubble，
             找 selectedImages.uuid 命中的那条，直接用它的 path。
        """
        if not self.available or not _IMAGE_ID_RE.match(image_id):
            return None
        assert self.user_dir is not None
        found = self._glob_image(composer_id, image_id)
        if found:
            return found
        return self._find_selected_image_path(composer_id, image_id)

    def _glob_image(self, composer_id: str, image_id: str) -> Optional[Path]:
        assert self.user_dir is not None
        db_path = self.user_dir / "globalStorage" / "state.vscdb"
        try:
            with _ro_connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT workspaceId FROM composerHeaders WHERE composerId = ?",
                    (composer_id,),
                ).fetchone()
        except Exception as e:
            logger.warning("read workspaceId for %s failed: %s", composer_id, e)
            return None
        if not row or not row["workspaceId"]:
            return None
        images_dir = self.user_dir / "workspaceStorage" / row["workspaceId"] / "images"
        if not images_dir.is_dir():
            return None
        matches = sorted(images_dir.glob(f"{image_id}-*"))
        return matches[0] if matches else None

    def _find_selected_image_path(self, composer_id: str, image_id: str) -> Optional[Path]:
        assert self.user_dir is not None
        db_path = self.user_dir / "globalStorage" / "state.vscdb"
        try:
            with _ro_connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                data_row = conn.execute(
                    "SELECT value FROM cursorDiskKV WHERE key = ?",
                    (f"composerData:{composer_id}",),
                ).fetchone()
                order: List[dict] = []
                if data_row:
                    try:
                        order = json.loads(data_row["value"]).get("fullConversationHeadersOnly") or []
                    except Exception:
                        order = []
                for entry in order:
                    bubble_id = entry.get("bubbleId")
                    if not bubble_id:
                        continue
                    bubble_row = conn.execute(
                        "SELECT value FROM cursorDiskKV WHERE key = ?",
                        (f"bubbleId:{composer_id}:{bubble_id}",),
                    ).fetchone()
                    if not bubble_row:
                        continue
                    try:
                        bubble = json.loads(bubble_row["value"])
                    except Exception:
                        continue
                    sel = ((bubble.get("context") or {}).get("selectedImages")) or []
                    for img in sel:
                        if isinstance(img, dict) and img.get("uuid") == image_id and img.get("path"):
                            p = Path(img["path"])
                            try:
                                p.relative_to(self.user_dir)
                            except ValueError:
                                continue
                            if p.is_file():
                                return p
        except Exception as e:
            logger.warning("scan selectedImages for %s failed: %s", composer_id, e)
            return None
        return None


# ---------- 行解析（剥离到模块级，方便单测，不依赖 Provider 实例） ----------


def _row_to_summary(row) -> Optional[ExternalSessionSummary]:
    """composerHeaders 一行 → Summary。空 draft 过滤掉。"""
    try:
        value = json.loads(row["value"])
    except Exception:
        value = {}
    # 空 draft（isDraft=True + isArchived=True）是"新建会话但没发出一句话"的 UI 占位，不列出
    if value.get("isDraft") and value.get("isArchived"):
        return None
    name = (value.get("name") or "").strip()
    subtitle = (value.get("subtitle") or "").strip()
    title = name or subtitle[:60] or "(未命名)"
    extra = {
        "subtitle": subtitle or None,
        "forceMode": value.get("forceMode"),
        "unifiedMode": value.get("unifiedMode"),
        "contextUsagePercent": value.get("contextUsagePercent"),
        "totalLinesAdded": value.get("totalLinesAdded"),
        "totalLinesRemoved": value.get("totalLinesRemoved"),
        "filesChangedCount": value.get("filesChangedCount"),
    }
    extra = {k: v for k, v in extra.items() if v is not None}
    return ExternalSessionSummary(
        id=row["composerId"],
        title=title,
        created_at=_ms_to_iso(row["createdAt"]),
        updated_at=_ms_to_iso(row["lastUpdatedAt"]),
        message_count=0,   # list 阶段不逐一 fetch bubble headers（太贵），detail 里再回填
        is_archived=bool(value.get("isArchived")),
        provider="cursor",
        extra=extra or None,
    )


def _bubble_to_msg(bubble_id: str, bubble: dict, order_type: Optional[int]) -> ExternalMessage:
    """
    bubble JSON → ExternalMessage。

    Cursor assistant bubble 分三种形态（通过 capabilityType / 是否有特定字段区分）：
      - **文本回复**（capabilityType=None）：`text` 字段有内容。
      - **思考**（capabilityType=30）：`text` 为空，内容在 `thinking` 字段里（JSON 字符串，含 text）。
      - **工具调用**（capabilityType=15）：`text` 为空，内容在 `toolFormerData` 字段里
        （含 name/status/rawArgs/result 等）。
    用户 bubble（type=1）就一种，`text` 字段。
    `kind` 字段把这三种形态暴露给前端，前端按 kind 分支渲染。
    """
    t = bubble.get("type", order_type)
    if t == 1:
        role = "user"
    elif t == 2:
        role = "assistant"
    else:
        role = "system"

    text = (bubble.get("text") or "").strip()
    thinking_raw = bubble.get("thinking")
    tfd = bubble.get("toolFormerData")

    kind: str = "text"
    content: str = text
    tool_calls: Optional[List[dict]] = None

    # 思考 bubble（优先级最高：assistant 的 thinking 字段非空、且 text 空）
    if thinking_raw and not text:
        kind = "thinking"
        try:
            th = json.loads(thinking_raw) if isinstance(thinking_raw, str) else thinking_raw
            content = (th.get("text") or "").strip() if isinstance(th, dict) else ""
        except Exception:
            content = ""

    # 工具调用 bubble
    elif tfd and not text:
        kind = "tool_call"
        name = (tfd.get("name") if isinstance(tfd, dict) else None) or "tool"
        status = (tfd.get("status") if isinstance(tfd, dict) else None) or ""
        # content 给前端"折叠标题"用：工具名 + 状态，前端默认折叠时能一眼看是什么
        content = f"🔧 `{name}`" + (f" · {status}" if status else "")
        tool_calls = [{"kind": "tool_call", "data": tfd}]

    # 其它可能的附加（diff / 解释器结果等），不排斥 text 气泡，一并挂上来
    for key in ("toolResults", "assistantSuggestedDiffs", "interpreterResults"):
        val = bubble.get(key)
        if val:
            tool_calls = tool_calls or []
            tool_calls.append({"kind": key, "data": val})

    # 用户粘贴/拖进来的图：实测 Cursor 有两种挂法，都要认——
    #   - 顶层 bubble.images：只给 uuid + 尺寸，没有二进制也没有 variant 文件名后缀，
    #     真正的字节要靠 CursorProvider.get_image 现查现读（workspaceStorage 里 glob）。
    #   - bubble.context.selectedImages：多给了一个 path 字段（绝对路径），但这个 uuid
    #     和文件名里嵌的 uuid 对不上，所以这种只能靠 get_image 二次扫描 bubble 拿 path。
    images: Optional[List[dict]] = None
    images_raw = bubble.get("images")
    selected_images_raw = ((bubble.get("context") or {}).get("selectedImages")) if isinstance(bubble.get("context"), dict) else None
    seen_uids: set = set()
    for src in (images_raw, selected_images_raw):
        if not isinstance(src, list):
            continue
        for img in src:
            if not isinstance(img, dict):
                continue
            uid = img.get("uuid")
            if not uid or uid in seen_uids:
                continue
            seen_uids.add(uid)
            dim = img.get("dimension") or {}
            images = images or []
            images.append({"uuid": uid, "width": dim.get("width"), "height": dim.get("height")})

    raw = {k: v for k, v in bubble.items() if k not in ("text", "type", "thinking", "toolFormerData", "images")}

    return ExternalMessage(
        id=bubble_id,
        role=role,  # type: ignore[arg-type]
        kind=kind,  # type: ignore[arg-type]
        content=content,
        created_at=bubble.get("createdAt"),  # ISO 8601 UTC（如 2026-08-03T02:15:12.462Z）
        tool_calls=tool_calls,
        images=images,
        raw=raw or None,
    )


# ---------- 「N Files Changed」聚合 ----------

# 会改文件的工具调用（实测见过 edit_file_v2；旧版名字一并兼容）
_EDIT_TOOL_NAMES = ("edit_file_v2", "edit_file", "create_file_v2", "create_file")


def _fetch_content_blob(conn, content_id: Optional[str]) -> Optional[str]:
    """
    composer.content.<sha256> → 原始文件全文。
    Cursor 把每次编辑前后的完整内容按 sha256 内容寻址存进 cursorDiskKV（实测 sha256(内容) == 键后缀），
    edit_file_v2 的 result 里给 before/after 两个 contentId，diff 一下就是该次编辑的 +/- 行数。
    """
    if not content_id:
        return None
    try:
        row = conn.execute(
            "SELECT value FROM cursorDiskKV WHERE key = ?", (content_id,)
        ).fetchone()
    except Exception:
        return None
    if not row or row["value"] is None:
        return None
    v = row["value"]
    if isinstance(v, bytes):
        try:
            v = v.decode("utf-8", errors="replace")
        except Exception:
            return None
    return v


def _diff_line_counts(before: str, after: str) -> tuple:
    """两版全文 → (新增行数, 删除行数)。unified diff 数 +/- 行（n=0 只出变更行，快）。"""
    added = removed = 0
    if before == after:
        return 0, 0
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def _attach_files_changed(blob_fetch, messages: List[ExternalMessage]) -> List[ExternalMessage]:
    """
    按轮（两次用户消息之间）聚合 edit_file_v2 调用，轮尾插入一条 kind=files_changed 的合成消息。
    同一文件一轮内多次编辑要链起来：取第一次的 before、最后一次的 after，diff 出净变化——
    逐次 diff 相加会把中间态重复计算。
    """
    out: List[ExternalMessage] = []
    turn_chains: dict = {}       # path -> {before, after}（contentId 链）
    turn_has_edit = False
    turn_last_msg: Optional[ExternalMessage] = None

    def flush() -> None:
        nonlocal turn_chains, turn_has_edit, turn_last_msg
        if turn_has_edit and turn_chains:
            files = []
            for path, ch in turn_chains.items():
                after = blob_fetch(ch["after"]) if ch["after"] else None
                if after is None:
                    continue
                before = blob_fetch(ch["before"]) if ch["before"] else ""
                if before is None:
                    before = ""
                added, removed = _diff_line_counts(before, after)
                # 统一 diff 文本（n=3 上下文），前端 files_changed 卡片展开渲染用。
                # 过长截断，避免一次会话几百次编辑把响应撑爆。
                diff_text = "\n".join(difflib.unified_diff(
                    before.splitlines(), after.splitlines(),
                    fromfile="a/" + path.replace("\\", "/"),
                    tofile="b/" + path.replace("\\", "/"),
                    lineterm="", n=3,
                ))
                if len(diff_text) > 16384:
                    diff_text = diff_text[:16384] + "\n…（diff 过长已截断）"
                files.append({
                    "path": path,
                    "file": path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1],
                    "added": added,
                    "removed": removed,
                    "is_new": before == "",
                    "after_lines": len(after.splitlines()),
                    "diff": diff_text,
                })
            if files:
                out.append(ExternalMessage(
                    id=f"files-changed-{len(out)}",
                    role="assistant",
                    kind="files_changed",
                    content="",
                    created_at=(turn_last_msg.created_at if turn_last_msg else None),
                    tool_calls=[{"kind": "files_changed", "data": {"files": files}}],
                ))
        turn_chains = {}
        turn_has_edit = False
        turn_last_msg = None

    for msg in messages:
        if msg.role == "user":
            flush()
            out.append(msg)
            continue

        if msg.kind == "tool_call" and msg.tool_calls:
            for tc in msg.tool_calls:
                data = tc.get("data") if isinstance(tc, dict) else None
                if not isinstance(data, dict):
                    continue
                if (data.get("name") or "") not in _EDIT_TOOL_NAMES:
                    continue
                if data.get("status") != "completed":
                    continue
                try:
                    params = json.loads(data.get("params") or "{}")
                    result = json.loads(data.get("result") or "{}")
                except Exception:
                    continue
                path = params.get("relativeWorkspacePath") or ""
                if not path:
                    try:
                        path = json.loads(data.get("rawArgs") or "{}").get("path") or ""
                    except Exception:
                        path = ""
                if not path:
                    continue
                turn_has_edit = True
                ch = turn_chains.get(path)
                if ch is None:
                    turn_chains[path] = {
                        "before": result.get("beforeContentId") or "",
                        "after": result.get("afterContentId") or "",
                    }
                elif result.get("afterContentId"):
                    ch["after"] = result["afterContentId"]

        out.append(msg)
        turn_last_msg = msg

    flush()
    return out
