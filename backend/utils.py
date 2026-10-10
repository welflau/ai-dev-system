"""
AI 自动开发系统 - 工具函数
"""
import uuid
import time
from datetime import datetime, timedelta, timezone


def generate_id(prefix: str = "") -> str:
    """生成唯一 ID
    格式: {prefix}-{timestamp}-{short_uuid}
    例: REQ-20260324-a1b2c3
    """
    ts = datetime.now().strftime("%Y%m%d")
    short = uuid.uuid4().hex[:6]
    if prefix:
        return f"{prefix}-{ts}-{short}"
    return f"{ts}-{short}"


def now_iso() -> str:
    """返回当前时间的 ISO 格式字符串"""
    return datetime.now().isoformat()


def iso_before(ms: float, base_iso: str = "") -> str:
    """把时间往前推 ms 毫秒，返回 ISO 字符串（base_iso 缺省为当前时间）。

    用来补 started_at：记录都是**跑完之后**才落库的，手里只有 created_at 和
    duration_ms，起点只能倒推。没有起点就画不出时间轴 —— 一次对话里哪两步
    并行、哪一步卡了 40 秒，全看这个字段。
    """
    try:
        base = datetime.fromisoformat(base_iso) if base_iso else datetime.now()
    except (ValueError, TypeError):
        base = datetime.now()
    try:
        delta = max(float(ms or 0), 0.0)
    except (ValueError, TypeError):
        delta = 0.0
    return (base - timedelta(milliseconds=delta)).isoformat()


def timestamp_ms() -> int:
    """返回毫秒级时间戳"""
    return int(time.time() * 1000)
