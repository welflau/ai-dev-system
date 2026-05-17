"""
SetSessionFlagAction — 運行時 per-session 行為開關

讓用戶在聊天中直接調整 AI 行為，無需重啟服務。
Session 級別，重啟後重置為默認值。

支持的 Flag：
  compaction     on/off   — LLM 壓縮長對話歷史（默認 on）
  nudge          on/off   — AI 回覆後提示未完成需求（默認 on）
  verbose        on/off   — 詳細模式：AI 給出更多解釋（默認 off）
  max_turns      1-100    — 本 session 最大工具調用輪次（默認 50）
  budget_tokens  int      — 本 session token 上限（默認 300000）
"""
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.set_session_flag")

# 全局 session flags 存儲（內存，重啟清零）
# key: session_id → dict of flags
_SESSION_FLAGS: Dict[str, Dict[str, Any]] = {}

# 默認值
_FLAG_DEFAULTS: Dict[str, Any] = {
    "compaction":    True,
    "nudge":         True,
    "verbose":       False,
    "max_turns":     50,
    "budget_tokens": 300_000,
}

# 合法值範圍
_FLAG_VALIDATORS = {
    "compaction":    lambda v: v in (True, False, "on", "off", "true", "false", "1", "0"),
    "nudge":         lambda v: v in (True, False, "on", "off", "true", "false", "1", "0"),
    "verbose":       lambda v: v in (True, False, "on", "off", "true", "false", "1", "0"),
    "max_turns":     lambda v: isinstance(v, (int, str)) and 1 <= int(v) <= 200,
    "budget_tokens": lambda v: isinstance(v, (int, str)) and 10_000 <= int(v) <= 2_000_000,
}


def _parse_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("on", "true", "1", "yes")


def _parse_value(key: str, raw):
    """把字符串值轉為對應類型"""
    if key in ("compaction", "nudge", "verbose"):
        return _parse_bool(raw)
    if key in ("max_turns", "budget_tokens"):
        return int(raw)
    return raw


def get_session_flag(session_id: str, key: str) -> Any:
    """讀取 session flag，不存在時返回默認值"""
    return _SESSION_FLAGS.get(session_id, {}).get(key, _FLAG_DEFAULTS.get(key))


def get_all_session_flags(session_id: str) -> Dict[str, Any]:
    """讀取所有 session flags（含默認值）"""
    base = dict(_FLAG_DEFAULTS)
    base.update(_SESSION_FLAGS.get(session_id, {}))
    return base


class SetSessionFlagAction(ActionBase):

    @property
    def name(self) -> str:
        return "set_session_flag"

    @property
    def description(self) -> str:
        return "設置本會話的 AI 行為開關（compaction / nudge / verbose / max_turns / budget_tokens）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "運行時調整本次對話的 AI 行為，無需重啟。\n"
                "可設置：\n"
                "  compaction on/off  — 是否壓縮長對話歷史（默認 on）\n"
                "  nudge on/off       — AI 回覆後是否提示未完成需求（默認 on）\n"
                "  verbose on/off     — 詳細模式（默認 off）\n"
                "  max_turns 數字     — 本 session 最大工具調用輪次（默認 50）\n"
                "  budget_tokens 數字 — 本 session token 上限（默認 300000）\n"
                "  list               — 查看當前所有設置"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "flag": {
                        "type": "string",
                        "description": "Flag 名稱（compaction/nudge/verbose/max_turns/budget_tokens/list）",
                    },
                    "value": {
                        "type": "string",
                        "description": "Flag 值（on/off 或數字），list 時不填",
                    },
                },
                "required": ["flag"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        flag  = (context.get("flag") or "").strip().lower()
        value = context.get("value")
        sid   = context.get("session_id") or context.get("_session_id") or "default"

        # list：顯示當前所有設置
        if flag == "list":
            flags = get_all_session_flags(sid)
            lines = [f"  {k} = {v}" for k, v in flags.items()]
            return ActionResult(
                success=True,
                message="當前 session 設置：\n" + "\n".join(lines),
                data={"type": "session_flags", "flags": flags},
            )

        # 驗證 flag 名稱
        if flag not in _FLAG_DEFAULTS:
            return ActionResult(
                success=False,
                error=f"未知 flag：{flag}。可用：{', '.join(_FLAG_DEFAULTS.keys())} 或 list",
            )

        # 驗證值
        if value is None:
            return ActionResult(success=False, error=f"請提供 {flag} 的值")

        validator = _FLAG_VALIDATORS.get(flag)
        if validator and not validator(value):
            return ActionResult(success=False, error=f"flag {flag} 的值無效：{value}")

        parsed = _parse_value(flag, value)
        if sid not in _SESSION_FLAGS:
            _SESSION_FLAGS[sid] = {}
        _SESSION_FLAGS[sid][flag] = parsed

        logger.info("Session %s flag 已設置：%s = %s", sid[:12], flag, parsed)
        return ActionResult(
            success=True,
            message=f"✅ 已設置 {flag} = {parsed}（本 session 有效）",
            data={"type": "session_flag_set", "flag": flag, "value": parsed},
        )
