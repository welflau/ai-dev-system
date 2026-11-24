"""系统公共云端生视频的分层异常（叶子模块，零项目内 import）。

单独成文件是为了拆环：`client` 顶层要用 `queue`，`queue` 排队超时要抛
`CloudVideoUnavailable`，`lightai` 要抛 `CloudVideoError`。异常类若留在 `client`，
`queue` / `lightai` 就得反向依赖 `client`，形成
`cloud_video ⇄ cloud_video.client ⇄ cloud_video.queue` 的环（六层 DAG 守卫判 CYCLE）。

对外路径不变：`from cloud_video import CloudVideoError`、
`from cloud_video.client import CloudVideoUnavailable` 仍然可用，且是同一个类对象。
"""
from __future__ import annotations


class CloudVideoUnavailable(RuntimeError):
    """未启用 / 缺卡密钥 / 网络不通 / 超时。调用方应转成 env_missing → blocked。"""


class CloudVideoError(RuntimeError):
    """上游返回失败、参数错误或协议异常。调用方按普通失败处理。"""
