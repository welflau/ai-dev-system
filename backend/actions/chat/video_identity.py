"""AI 视频 / 漫剧项目身份：防止被网页 MVP 带跑。"""
from __future__ import annotations

import json
from typing import Any, Iterable, List, Optional, Sequence

VIDEO_TRAITS = ("category:video", "pipeline:video")

_WEB_PRODUCT_MARKERS = (
    "网页 mvp",
    "网页mvp",
    "next.js",
    "nextjs",
    "tailwind",
    "首页",
    "章节详情",
    "播放页",
    "关于页",
    "mock 数据",
    "mock数据",
    "核心页面",
    "主流程先能走通",
    "页面范围",
)

_VIDEO_PRODUCT_MARKERS = (
    "试片",
    "分镜",
    "视频简报",
    "生图",
    "配音",
    "合成",
    "镜头",
    "导演制片",
)

VIDEO_WEB_REQ_REJECT = (
    "这是 AI 视频/漫剧项目，走导演制片（小说 → 分镜 → 生图 → 配音 → 合成），"
    "不能创建网页 / Next.js / 页面 MVP 需求。"
    "请改为「第一集试片」或「视频简报」或「从小说拆分镜」。"
    "已取消的网页 MVP 是误拆，禁止沿用页面范围和技术方案。"
)

INACTIVE_REQUIREMENT_STATUSES = frozenset({"cancelled", "completed", "closed"})


def parse_traits(raw: Any) -> List[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return [t.strip() for t in raw.replace("，", ",").split(",") if t.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(t).strip() for t in raw if str(t).strip()]
    return []


def is_video_traits(traits: Optional[Iterable[str]]) -> bool:
    cleaned = {str(t).strip() for t in (traits or []) if str(t).strip()}
    return any(t in cleaned for t in VIDEO_TRAITS)


def looks_like_web_product(title: str, description: str = "") -> bool:
    blob = f"{title}\n{description}".lower()
    if any(m in blob for m in _VIDEO_PRODUCT_MARKERS):
        return False
    return any(m in blob for m in _WEB_PRODUCT_MARKERS)


async def load_project_traits(project_id: str) -> List[str]:
    if not project_id:
        return []
    try:
        from database import db
        row = await db.fetch_one("SELECT traits FROM projects WHERE id = ?", (project_id,))
        if not row:
            return []
        return parse_traits(row.get("traits"))
    except Exception:
        return []


async def reject_web_requirement_for_video(
    project_id: str,
    title: str,
    description: str = "",
    traits: Optional[Sequence[str]] = None,
) -> Optional[str]:
    """视频项目若被塞网页需求，返回给 LLM 的错误文案；否则 None。"""
    if traits is None:
        traits = await load_project_traits(project_id)
    if is_video_traits(traits) and looks_like_web_product(title, description):
        return VIDEO_WEB_REQ_REJECT
    return None


def video_chat_routing_section() -> str:
    return """
## 🎬 AI 视频 / 漫剧意图路由（优先级最高，高于对话历史和仓库文档）
本项目是导演制片，不是网站、不是 App。正确流程：小说 → 分镜 → 生图 → 配音 → 合成。

硬性规则：
- 用户说「开始 / 现在能开始了 / 继续 / 开工」→ 立即调用 `confirm_requirement`，标题用「第一集试片」，内容是选定章节、视频简报、分镜、跑通 1 个镜头试生成。**不要做网页。**
- **禁止**创建或重开「网页 MVP / Next.js / 首页 / 章节详情 / 播放页 / 关于页 / mock API / 脚手架」类需求。
- 对话历史和仓库里的网页 PRD、视觉规范、web-dev 套件是**错误路由残留**，一律忽略，不要沿用页面范围和技术方案。
- 已取消的网页需求不要「重跑」；即使用户说重来，也必须改成试片 / 简报 / 分镜。
"""
