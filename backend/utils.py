"""
AI 自动开发系统 - 工具函数
"""
import uuid
import time
from datetime import datetime, timezone


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


def timestamp_ms() -> int:
    """返回毫秒级时间戳"""
    return int(time.time() * 1000)
