"""
CodeBuddy 会话 provider —— 只读。

存储模型：
  %USERPROFILE%\\.codebuddy\\projects\\<slug>\\<sessionId>.jsonl
  slug = 盘符小写 + '-' + 路径（'\\' 换成 '-'），如 f-A_Works-ai-dev-system
  sessionId == 文件名（uuid）。

jsonl 每行一个事件（type 字段区分）：
  - message:  role=user/assistant, content=[{type:input_text|output_text, text}]
  - reasoning: 思考过程（rawContent 里 reasoning_text）
  - function_call / function_call_result: 工具调用（name/callId/status/output）
  - ai-title:  会话标题（aiTitle）
  - summary:   首条用户消息的压缩（initial-user-message），跳过避免重复
  - file-history-snapshot: 文件改动快照，暂不聚合
每条带 timestamp(ms)、cwd(项目绝对路径)、sessionId。

图片：本项目 CodeBuddy 会话里图片多以文件路径 + Read 工具读入（blob 落
~/.codebuddy/blobs），不做内联 image block，v1 不解析图片。
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import ClassVar, List, Optional

from .base import (
    ExternalMessage,
    ExternalSessionDetail,
    ExternalSessionSummary,
    contains_query,
    match_snippet,
)
from .cursor import _ms_to_iso, _norm, _path_matches_any

logger = logging.getLogger("external_sessions.codebuddy")

_SKIP_TYPES = {"file-history-snapshot", "queue-operation"}
_TEXT_BLOCK_TYPES = {"input_text", "output_text", "text"}


def _default_codebuddy_user_dir() -> Optional[Path]:
    """默认 %USERPROFILE%\\.codebuddy；env CODEBUDDY_USER_DIR 可覆盖。"""
    env = os.environ.get("CODEBUDDY_USER_DIR")
    if env:
        p = Path(env)
        return p if p.is_dir() else None
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if not home:
        return None
    p = Path(home) / ".codebuddy"
    return p if p.is_dir() else None


def _iter_session_files(user_dir: Path):
    projects = user_dir / "projects"
    if not projects.is_dir():
        return
    yield from projects.glob("*/*.jsonl")


def _trim_title(s: str, max_chars: int = 60) -> str:
    s = (s or "").strip()
    return s[:max_chars] + "…" if len(s) > max_chars else s


def _block_text(blocks, types) -> str:
    if not isinstance(blocks, list):
        return ""
    return " ".join(
        b.get("text", "")
        for b in blocks
        if isinstance(b, dict) and b.get("type") in types
    ).strip()


def _event_search_text(e: dict) -> str:
    """一条 jsonl 事件里能被搜到的文字。"""
    t = e.get("type")
    if t == "ai-title":
        return e.get("aiTitle") or ""
    if t == "message":
        return _block_text(e.get("content"), _TEXT_BLOCK_TYPES)
    if t == "reasoning":
        return _block_text(e.get("rawContent"), {"reasoning_text"})
    if t in ("function_call", "function_call_result"):
        parts = [e.get("name") or "", e.get("status") or ""]
        for key in ("arguments", "output"):
            val = e.get(key)
            if isinstance(val, str):
                parts.append(val)
            elif val is not None:
                try:
                    parts.append(json.dumps(val, ensure_ascii=False))
                except Exception:
                    pass
        return "\n".join(p for p in parts if p)
    return ""


def _scan_session(path: Path, norm_roots: List[str], query: str = "") -> Optional[dict]:
    """扫一个 jsonl，返回会话元数据；cwd 不命中任一项目根则返回 None。"""
    cwd = None
    matched = False
    title = ""
    first_user_text = ""
    ts_first = None
    ts_last = None
    msg_count = 0
    snippet = ""
    q = (query or "").strip()
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if cwd is None:
                    c = e.get("cwd")
                    if c:
                        cwd = c
                        matched = _path_matches_any(c, norm_roots)
                        if not matched:
                            return None
                t = e.get("type")
                if t == "ai-title":
                    title = e.get("aiTitle") or title
                elif t == "message":
                    if e.get("role") in ("user", "assistant"):
                        msg_count += 1
                        if e.get("role") == "user" and not first_user_text:
                            first_user_text = _block_text(e.get("content"), _TEXT_BLOCK_TYPES)
                if q and not snippet:
                    snippet = match_snippet(_event_search_text(e), q)
                ts = e.get("timestamp")
                if ts:
                    ts_first = ts if ts_first is None or ts < ts_first else ts_first
                    ts_last = ts if ts_last is None or ts > ts_last else ts_last
    except Exception as e:
        logger.debug("scan session failed %s: %s", path, e)
        return None

    if not matched or msg_count == 0:
        return None
    return {
        "cwd": cwd,
        "title": title,
        "first_user_text": first_user_text,
        "ts_first": ts_first,
        "ts_last": ts_last,
        "msg_count": msg_count,
        "match_snippet": snippet,
    }


class CodeBuddyProvider:
    name: ClassVar[str] = "codebuddy"

    def __init__(self, user_dir: Optional[Path] = None):
        self.user_dir = user_dir if user_dir is not None else _default_codebuddy_user_dir()

    @property
    def available(self) -> bool:
        if not self.user_dir:
            return False
        return (self.user_dir / "projects").is_dir()

    def _find_session_file(self, session_id: str) -> Optional[Path]:
        """按文件名（sessionId == uuid）定位 jsonl。session_id 走 Path().name 防穿越。"""
        name = Path(session_id).name
        if not name:
            return None
        projects = self.user_dir / "projects"
        if not projects.is_dir():
            return None
        hits = list(projects.glob(f"*/{name}.jsonl"))
        return hits[0] if hits else None

    def list_sessions(self, candidate_roots: List[str], query: str = "") -> List[ExternalSessionSummary]:
        if not self.available:
            return []
        norm_roots = [_norm(r) for r in candidate_roots if r]
        if not norm_roots:
            return []
        q = (query or "").strip()

        sessions: List[ExternalSessionSummary] = []
        for path in _iter_session_files(self.user_dir):
            meta = _scan_session(path, norm_roots, query=q)
            if not meta:
                continue
            title = (meta["title"] or "").strip()
            if not title:
                title = _trim_title(meta["first_user_text"], 40) or "(未命名)"
            else:
                title = _trim_title(title)
            subtitle = meta["cwd"] or ""
            snippet = meta.get("match_snippet") or ""
            if q and not (
                contains_query(title, q)
                or contains_query(subtitle, q)
                or snippet
            ):
                continue
            extra = {"subtitle": subtitle or None}
            if snippet and q:
                extra["match_snippet"] = snippet
            extra = {k: v for k, v in extra.items() if v is not None}
            sessions.append(ExternalSessionSummary(
                id=path.stem,
                title=title,
                created_at=_ms_to_iso(meta["ts_first"]),
                updated_at=_ms_to_iso(meta["ts_last"]),
                message_count=meta["msg_count"],
                is_archived=False,
                provider=self.name,
                extra=extra or None,
            ))
        sessions.sort(key=lambda s: s.updated_at or "", reverse=True)
        return sessions

    def get_session(self, session_id: str) -> Optional[ExternalSessionDetail]:
        if not self.available:
            return None
        path = self._find_session_file(session_id)
        if not path:
            return None

        messages: List[ExternalMessage] = []
        title = ""
        first_user_text = ""
        cwd = ""
        ts_first = None
        ts_last = None

        def _mk_id(e: dict) -> str:
            return e.get("id") or uuid.uuid4().hex

        def _created(e: dict) -> Optional[str]:
            return _ms_to_iso(e.get("timestamp"))

        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    t = e.get("type")

                    if not cwd and e.get("cwd"):
                        cwd = e["cwd"]

                    if t == "ai-title":
                        title = e.get("aiTitle") or title
                        continue
                    if t == "summary":
                        # initial-user-message 压缩，和原始 message 重复，跳过
                        continue
                    if t == "message":
                        role = e.get("role")
                        if role not in ("user", "assistant"):
                            continue
                        text = " ".join(
                            b.get("text", "")
                            for b in (e.get("content") or [])
                            if isinstance(b, dict) and b.get("type") in _TEXT_BLOCK_TYPES
                        ).strip()
                        if not text:
                            continue
                        if role == "user" and not first_user_text:
                            first_user_text = text
                        messages.append(ExternalMessage(
                            id=_mk_id(e), role=role, kind="text",
                            content=text, created_at=_created(e),
                        ))
                        continue
                    if t == "reasoning":
                        text = " ".join(
                            b.get("text", "")
                            for b in (e.get("rawContent") or [])
                            if isinstance(b, dict) and b.get("type") == "reasoning_text"
                        ).strip()
                        if not text:
                            continue
                        messages.append(ExternalMessage(
                            id=_mk_id(e), role="assistant", kind="thinking",
                            content=text, created_at=_created(e),
                        ))
                        continue
                    if t == "function_call":
                        name = e.get("name") or "tool"
                        messages.append(ExternalMessage(
                            id=_mk_id(e), role="assistant", kind="tool_call",
                            content=f"🔧 `{name}`",
                            tool_calls=[{"kind": "tool_call", "data": {
                                "name": name, "callId": e.get("callId"),
                                "arguments": e.get("arguments"),
                            }}],
                            created_at=_created(e),
                        ))
                        continue
                    if t == "function_call_result":
                        name = e.get("name") or "tool"
                        status = e.get("status") or ""
                        messages.append(ExternalMessage(
                            id=_mk_id(e), role="assistant", kind="tool_call",
                            content=f"🔧 `{name}`" + (f" · {status}" if status else ""),
                            tool_calls=[{"kind": "tool_call", "data": {
                                "name": name, "callId": e.get("callId"),
                                "status": status, "output": e.get("output"),
                            }}],
                            created_at=_created(e),
                        ))
                        continue

                    ts = e.get("timestamp")
                    if ts:
                        ts_first = ts if ts_first is None or ts < ts_first else ts_first
                        ts_last = ts if ts_last is None or ts > ts_last else ts_last
        except Exception as e:
            logger.warning("read session %s failed: %s", session_id, e)
            return None

        title = title.strip() or _trim_title(first_user_text, 40) or "(未命名)"
        title = _trim_title(title)
        extra = {"subtitle": cwd or None}
        extra = {k: v for k, v in extra.items() if v is not None}
        summary = ExternalSessionSummary(
            id=path.stem,
            title=title,
            created_at=_ms_to_iso(ts_first),
            updated_at=_ms_to_iso(ts_last),
            message_count=len(messages),
            is_archived=False,
            provider=self.name,
            extra=extra or None,
        )
        detail = ExternalSessionDetail(**summary.model_dump(), messages=messages)
        detail.message_count = len(messages)
        return detail
