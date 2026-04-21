"""
SessionLogger — 每个需求一个会话目录，落可读 transcript + 结构化 jsonl

对标 MagicAI src/agents/game_agent/utils/transcript.py + subagent_tracker.py。
本项目没有 SDK hook，但 `orchestrator._log()` 和 `llm_client._save_conversation()`
是天然的两个 chokepoint，覆盖全部 Agent / Action / LLM 活动。

目录结构：
  backend/logs/session_<requirement_id>/
    transcript.txt        # 人读：顺序事件
    tool_calls.jsonl      # 结构化：每行一个 JSON

详见 docs/20260420_03_Session_Transcript实现方案.md
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("session_logger")

# 日志根目录（相对 backend/）
_LOGS_ROOT = Path(__file__).parent / "logs"

# 事件类型 → emoji
_EMOJI = {
    "log": "ℹ️",
    "llm": "🧠",
    "reflection": "🔍",
    "reject": "❌",
    "accept": "✅",
    "complete": "🎉",
    "start": "🤖",
    "error": "💥",
    "info": "ℹ️",
    "warn": "⚠️",
}


def _sanitize_req_id(req_id: str) -> str:
    """防路径注入 + Windows 文件名兼容：只保留字母数字 _ - ."""
    if not req_id:
        return "unknown"
    safe = "".join(c for c in str(req_id) if c.isalnum() or c in "_-.")
    return safe[:80] or "unknown"


def _now_parts():
    now = datetime.now(timezone.utc)
    return now.isoformat(timespec="seconds"), now.strftime("%H:%M:%S")


def _pick_emoji(kind: str, action: Optional[str]) -> str:
    """优先按 action 选，比如 'reject'/'accept'/'complete'；兜底 kind"""
    if action and action in _EMOJI:
        return _EMOJI[action]
    return _EMOJI.get(kind, "•")


class SessionLogger:
    """每个 requirement 一个异步锁；文件追加写"""

    def __init__(self, root: Path = _LOGS_ROOT):
        self.root = root
        self._locks: Dict[str, asyncio.Lock] = {}
        self._started: set = set()  # 已写过 banner 的 req_id

    def _get_lock(self, req_id: str) -> asyncio.Lock:
        lock = self._locks.get(req_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[req_id] = lock
        return lock

    def _session_dir(self, req_id: str) -> Path:
        return self.root / f"session_{_sanitize_req_id(req_id)}"

    async def _ensure_header(self, req_id: str, session_dir: Path, transcript_path: Path):
        """首次写入时创建目录 + banner"""
        if req_id in self._started:
            return
        session_dir.mkdir(parents=True, exist_ok=True)
        if not transcript_path.exists():
            iso, _ = _now_parts()
            banner = (
                "=" * 80 + "\n"
                f"Session: requirement {req_id}\n"
                f"Started: {iso}\n"
                + "=" * 80 + "\n\n"
            )
            transcript_path.write_text(banner, encoding="utf-8")
        self._started.add(req_id)

    async def log_event(
        self,
        *,
        requirement_id: Optional[str],
        kind: str = "log",
        agent: Optional[str] = None,
        action: Optional[str] = None,
        ticket_id: Optional[str] = None,
        from_status: Optional[str] = None,
        to_status: Optional[str] = None,
        message: str = "",
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        """镜像一条 ticket_log 事件到 transcript.txt + tool_calls.jsonl"""
        if not requirement_id:
            return  # 没有 req 就没有 session
        req_id = _sanitize_req_id(requirement_id)
        session_dir = self._session_dir(req_id)
        transcript_path = session_dir / "transcript.txt"
        jsonl_path = session_dir / "tool_calls.jsonl"

        lock = self._get_lock(req_id)
        async with lock:
            try:
                await self._ensure_header(req_id, session_dir, transcript_path)

                iso, hm = _now_parts()
                emoji = _pick_emoji(kind, action)

                # 人读行
                parts = [f"[{hm}] {emoji}"]
                if agent:
                    tag = f"{agent}.{action}" if action else agent
                    parts.append(tag)
                if ticket_id:
                    parts.append(f"· ticket {ticket_id[:12]}")
                if from_status and to_status and from_status != to_status:
                    parts.append(f"· {from_status} → {to_status}")
                if message:
                    parts.append(f"· {message}")
                line_text = " ".join(parts) + "\n"

                with transcript_path.open("a", encoding="utf-8") as f:
                    f.write(line_text)

                # 结构化行
                record = {
                    "ts": iso,
                    "kind": kind,
                    "agent": agent,
                    "action": action,
                    "ticket_id": ticket_id,
                    "from": from_status,
                    "to": to_status,
                    "message": message,
                }
                if detail:
                    # detail 可能很大，保留但不截断（jsonl 只给工具用）
                    record["detail"] = detail
                with jsonl_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.warning("SessionLogger.log_event 写入失败 (req=%s): %s", req_id, e)

    async def log_llm(
        self,
        *,
        requirement_id: Optional[str],
        agent: Optional[str] = None,
        action: Optional[str] = None,
        ticket_id: Optional[str] = None,
        model: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        duration_ms: Optional[int] = None,
        status: str = "success",
    ) -> None:
        """镜像一次 LLM 调用。不写 messages/response 内容（太大，已在 llm_conversations 表里）"""
        if not requirement_id:
            return
        req_id = _sanitize_req_id(requirement_id)
        session_dir = self._session_dir(req_id)
        transcript_path = session_dir / "transcript.txt"
        jsonl_path = session_dir / "tool_calls.jsonl"

        lock = self._get_lock(req_id)
        async with lock:
            try:
                await self._ensure_header(req_id, session_dir, transcript_path)

                iso, hm = _now_parts()

                # 可读行
                tok = ""
                if input_tokens is not None and output_tokens is not None:
                    tok = f"({input_tokens}/{output_tokens} tokens"
                    if duration_ms is not None:
                        tok += f", {duration_ms / 1000:.1f}s"
                    tok += ")"
                tag = f"{agent}.{action}" if (agent and action) else (agent or "LLM")
                line = f"[{hm}] 🧠 {tag} → LLM call {tok}"
                if status != "success":
                    line += f" [{status}]"
                line += "\n"

                with transcript_path.open("a", encoding="utf-8") as f:
                    f.write(line)

                record = {
                    "ts": iso,
                    "kind": "llm",
                    "agent": agent,
                    "action": action,
                    "ticket_id": ticket_id,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "duration_ms": duration_ms,
                    "status": status,
                }
                with jsonl_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.warning("SessionLogger.log_llm 写入失败 (req=%s): %s", req_id, e)


# 单例
session_logger = SessionLogger()
