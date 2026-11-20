"""ADS 系统公共云端生视频能力（不属于任何 Plugin）。

定位（docs/20261019_01_Action成套插件与公共工具边界方案.md:87-101）：
「任何项目的工单循环或聊天都要用的留在公共模块」——云端生视频不绑定某条
内容流水线，director / videoclaw / 未来插件都应从这里取，而不是各自实现。

依赖方向（单向 DAG，公共层零 plugins.* import）：
    plugins/* ──▶ backend/cloud_video/ ──▶ backend/config.py (settings) + 标准库

本层只做 HTTP transport + 协议编排，抛分层异常：
    CloudVideoUnavailable  未启用 / 缺卡密钥 / 网络不通 / 超时  → 调用方 env_missing → blocked
    CloudVideoError        上游返回失败 / 参数错误 / 协议异常    → 调用方普通失败
**不返回 ActionResult、不写时间轴、不判 env_missing** —— 那些是 Action/Plugin 层职责
（docs/20261023_01_插件套件准入规范与五道约束.md:90-109）。

⚠️ 当前唯一 provider 是第三方「鼠鼠工具」卡密中转（runlive.top，X-Card-Key），
承载 MiniMax H3 模型，**不是 MiniMax 官方 API**（无 Bearer / 无 GroupID）。
官方 key 需另接 provider，不能复用本实现。
"""
from cloud_video.client import (
    ALLOWED_PROVIDERS,
    CloudVideoError,
    CloudVideoUnavailable,
    CloudVideoFile,
    PROVIDERS,
    file_url,
    generate_video,
    generate_video_with_provider,
    get_queue,
    normalize_provider,
    ping,
    probe_provider,
    query,
    queue_stats,
    set_queue,
    submit,
)
from cloud_video.queue import CloudVideoQueue, QueueStats, build_queue_from_settings

__all__ = [
    "CloudVideoError",
    "CloudVideoUnavailable",
    "CloudVideoFile",
    "PROVIDERS",
    "ALLOWED_PROVIDERS",
    "normalize_provider",
    "probe_provider",
    "submit",
    "query",
    "file_url",
    "ping",
    "generate_video",
    "generate_video_with_provider",
    # 生成任务排队
    "CloudVideoQueue",
    "QueueStats",
    "build_queue_from_settings",
    "get_queue",
    "set_queue",
    "queue_stats",
]
