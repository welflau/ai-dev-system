"""兼容 shim：LightAI 视频实现已上提到系统公共层 `backend/cloud_video/lightai.py`。

本文件保留 `plugins.director.lightai_video` 这个 import 路径，让：
  - gen_video.py:148 / :291 的既有 import 不变
  - download_video.py:51 / :66 的既有 import 不变
  - tests/plugins/test_director_plugin.py 的 monkeypatch 目标不变
行为与原实现逐行一致（公共层的 lightai.py 就是从这里搬过去的）。

新代码请直接 `from cloud_video import lightai`。
"""
from __future__ import annotations

from cloud_video.lightai import (  # noqa: F401
    _as_list,
    _build_payload,
    _create_task,
    _extract_video_url,
    _is_http,
    _poll_task,
    _upload_cos_sync,
    create_and_poll_video,
    download_url,
    resolve_media_url,
)

__all__ = [
    "_as_list",
    "_build_payload",
    "_create_task",
    "_extract_video_url",
    "_is_http",
    "_poll_task",
    "_upload_cos_sync",
    "create_and_poll_video",
    "download_url",
    "resolve_media_url",
]
