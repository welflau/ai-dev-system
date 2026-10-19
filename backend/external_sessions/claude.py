"""
Claude Code 会话 provider —— 只读。

存储模型：
  %USERPROFILE%\\.claude\\projects\\<slug>\\<sessionId>.jsonl
  slug = 路径（':'→'-'，'\\'→'-'），如 F--A-Works-ai-dev-system
  sessionId == 文件名（uuid）。

jsonl 每行一个事件（type 区分）：
  - user:       message.content 为 str 或 [text / tool_result / ...]
  - assistant:  message.content 为 [{type:text / tool_use / thinking, ...}]
  - summary:    压缩摘要（跳过）
  - attachment / queue-operation / last-prompt / file-history-snapshot: 跳过
每条带 timestamp（ISO 字符串，含 Z）、cwd、sessionId。

标题：history.jsonl（command history：{display, project, sessionId, timestamp}）
  按 sessionId 取最早一条 display 当标题；没有则回退到转写首条用户消息。
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

logger = logging.getLogger("external_sessions.claude")

_TEXT_BLOCK_TYPES = {"text", "input_text", "output_text"}


def _default_claude_user_dir() -> Optional[Path]:
    """默认 %USERPROFILE%\\.claude；env CLAUDE_USER_DIR 可覆盖。"""
    env = os.environ.get("CLAUDE_USER_DIR")
    if env:
        p = Path(env)
        return p if p.is_dir() else None
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if not home:
        return None
    p = Path(home) / ".claude"
    return p if p.is_dir() else None


def _to_iso(ts) -> str:
    """timestamp 可能是 ISO 字符串或毫秒整数，统一成 ISO 字符串。"""
    if ts is None:
        return ""
    if isinstance(ts, (int, float)):
        return _ms_to_iso(int(ts))
    return str(ts)


def _trim_title(s: str, max_chars: int = 60) -> str:
    s = (s or "").strip()
    return s[:max_chars] + "…" if len(s) > max_chars else s


def _iter_session_files(user_dir: Path):
    projects = user_dir / "projects"
    if not projects.is_dir():
        return
    yield from projects.glob("*/*.jsonl")


def _load_titles(user_dir: Path) -> dict:
    """history.jsonl → {sessionId: 最早一条 display}（当会话标题）。"""
    titles: dict = {}
    hist = user_dir / "history.jsonl"
    if not hist.is_file():
        return titles
    try:
        with hist.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                sid = e.get("sessionId")
                d = (e.get("display") or "").strip()
                if sid and d:
                    titles.setdefault(sid, d)  # 保留最早一条
    except Exception as e:
        logger.debug("load history.jsonl failed: %s", e)
    return titles


def _assistant_search_text(e: dict) -> str:
    parts: List[str] = []
    for b in (e.get("message") or {}).get("content") or []:
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt == "text":
            parts.append(b.get("text") or "")
        elif bt == "thinking":
            parts.append(b.get("thinking") or b.get("text") or "")
        elif bt == "tool_use":
            parts.append(b.get("name") or "")
            inp = b.get("input")
            if isinstance(inp, str):
                parts.append(inp)
            elif inp is not None:
                try:
                    parts.append(json.dumps(inp, ensure_ascii=False))
                except Exception:
                    pass
        elif bt == "tool_result":
            content = b.get("content")
            if isinstance(content, str):
                parts.append(content)
    return "\n".join(p for p in parts if p)


def _scan_session(path: Path, norm_roots: List[str], query: str = "") -> Optional[dict]:
    """扫一个 jsonl，返回会话元数据；cwd 不命中任一项目根则返回 None。"""
    cwd = None
    matched = False
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
                if t == "user":
                    msg_count += 1
                    if not first_user_text:
                        first_user_text = _user_text(e)
                    if q and not snippet:
                        snippet = match_snippet(_user_text(e), q)
                elif t == "assistant":
                    msg_count += 1
                    if q and not snippet:
                        snippet = match_snippet(_assistant_search_text(e), q)
                ts = e.get("timestamp")
                # timestamp 是 ISO 字符串，直接按字符串比大小（同格式可比）
                if ts:
                    ts_first = ts if ts_first is None or str(ts) < str(ts_first) else ts_first
                    ts_last = ts if ts_last is None or str(ts) > str(ts_last) else ts_last
    except Exception as e:
        logger.debug("scan session failed %s: %s", path, e)
        return None

    if not matched or msg_count == 0:
        return None
    return {
        "cwd": cwd,
        "first_user_text": first_user_text,
        "ts_first": ts_first,
        "ts_last": ts_last,
        "msg_count": msg_count,
        "match_snippet": snippet,
    }


def _user_text(e: dict) -> str:
    """user 事件的 message.content（str 或 blocks）→ 纯文本。"""
    msg = e.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return " ".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") in _TEXT_BLOCK_TYPES
        ).strip()
    return ""


class ClaudeProvider:
    name: ClassVar[str] = "claude"

    def __init__(self, user_dir: Optional[Path] = None):
        self.user_dir = user_dir if user_dir is not None else _default_claude_user_dir()

    @property
    def available(self) -> bool:
        if not self.user_dir:
            return False
        return (self.user_dir / "projects").is_dir()

    def _find_session_file(self, session_id: str) -> Optional[Path]:
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

        titles = _load_titles(self.user_dir)
        sessions: List[ExternalSessionSummary] = []
        for path in _iter_session_files(self.user_dir):
            meta = _scan_session(path, norm_roots, query=q)
            if not meta:
                continue
            sid = path.stem
            title = _trim_title(titles.get(sid, "") or meta["first_user_text"], 40) or "(未命名)"
            subtitle = meta["cwd"] or ""
            snippet = meta.get("match_snippet") or ""
            raw_title = titles.get(sid, "") or ""
            if q and not (
                contains_query(title, q)
                or contains_query(raw_title, q)
                or contains_query(subtitle, q)
                or snippet
            ):
                continue
            extra = {"subtitle": subtitle or None}
            if snippet and q:
                extra["match_snippet"] = snippet
            extra = {k: v for k, v in extra.items() if v is not None}
            sessions.append(ExternalSessionSummary(
                id=sid,
                title=title,
                created_at=_to_iso(meta["ts_first"]),
                updated_at=_to_iso(meta["ts_last"]),
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

        titles = _load_titles(self.user_dir)
        messages: List[ExternalMessage] = []
        cwd = ""
        first_user_text = ""
        ts_first = None
        ts_last = None

        def _mk_id(e: dict) -> str:
            return e.get("uuid") or e.get("id") or uuid.uuid4().hex

        def _created(e: dict) -> Optional[str]:
            return _to_iso(e.get("timestamp")) or None

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

                    if t == "user":
                        text = _user_text(e)
                        if not first_user_text and text:
                            first_user_text = text
                        if text:
                            messages.append(ExternalMessage(
                                id=_mk_id(e), role="user", kind="text",
                                content=text, created_at=_created(e),
                            ))
                        continue
                    if t == "assistant":
                        for b in (e.get("message") or {}).get("content") or []:
                            if not isinstance(b, dict):
                                continue
                            bt = b.get("type")
                            if bt == "text":
                                text = (b.get("text") or "").strip()
                                if text:
                                    messages.append(ExternalMessage(
                                        id=_mk_id(e), role="assistant", kind="text",
                                        content=text, created_at=_created(e),
                                    ))
                            elif bt == "tool_use":
                                name = b.get("name") or "tool"
                                messages.append(ExternalMessage(
                                    id=_mk_id(e), role="assistant", kind="tool_call",
                                    content=f"🔧 `{name}`",
                                    tool_calls=[{"kind": "tool_call", "data": {
                                        "name": name, "id": b.get("id"),
                                        "input": b.get("input"),
                                    }}],
                                    created_at=_created(e),
                                ))
                            elif bt == "thinking":
                                text = (b.get("thinking") or b.get("text") or "").strip()
                                if text:
                                    messages.append(ExternalMessage(
                                        id=_mk_id(e), role="assistant", kind="thinking",
                                        content=text, created_at=_created(e),
                                    ))
                        continue
                    # summary / attachment / queue-operation / last-prompt / file-history-snapshot 跳过

                    ts = e.get("timestamp")
                    if ts:
                        ts_first = ts if ts_first is None or str(ts) < str(ts_first) else ts_first
                        ts_last = ts if ts_last is None or str(ts) > str(ts_last) else ts_last
        except Exception as e:
            logger.warning("read session %s failed: %s", session_id, e)
            return None

        title = _trim_title(titles.get(session_id, "") or first_user_text, 40) or "(未命名)"
        extra = {"subtitle": cwd or None}
        extra = {k: v for k, v in extra.items() if v is not None}
        summary = ExternalSessionSummary(
            id=path.stem,
            title=title,
            created_at=_to_iso(ts_first),
            updated_at=_to_iso(ts_last),
            message_count=len(messages),
            is_archived=False,
            provider=self.name,
            extra=extra or None,
        )
        detail = ExternalSessionDetail(**summary.model_dump(), messages=messages)
        detail.message_count = len(messages)
        return detail
