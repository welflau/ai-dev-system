"""视频项目破冰不能推荐网页 MVP。"""
import asyncio
from pathlib import Path

from actions.chat.confirm_requirement import ConfirmRequirementAction
from actions.chat.propose_project_icebreak import build_icebreak_payload
from actions.chat.video_identity import looks_like_web_product, video_chat_routing_section
from pack_installer import get_recommended_packs


def test_video_icebreak_is_director_not_web():
    payload = build_icebreak_payload(
        "TombRaiderComic",
        "古墓丽影 AI 漫剧",
        ["platform:web", "category:video", "pipeline:video"],
    )
    prompts = " ".join(o["prompt"] for o in payload["options"])
    labels = " ".join(o["label"] for o in payload["options"])
    assert "网页 MVP" not in prompts
    assert "Next.js" not in prompts
    assert "试片" in labels or "分镜" in labels or "简报" in labels
    assert "导演制片" in payload["analysis"]


def test_video_icebreak_ignores_leftover_web_docs(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "PRD.md").write_text("# 网页 MVP Next.js", encoding="utf-8")
    (tmp_path / "works").mkdir()
    (tmp_path / "works" / "shot_prompts.md").write_text("分镜", encoding="utf-8")
    payload = build_icebreak_payload(
        "TombRaiderComic",
        "古墓丽影 AI 漫剧",
        ["category:video", "pipeline:video"],
        repo_path=str(tmp_path),
    )
    labels = " ".join(o["label"] for o in payload["options"])
    assert payload.get("is_existing") is not True
    assert "试片" in labels
    assert "网页 MVP" not in " ".join(o["prompt"] for o in payload["options"])


def test_video_packs_skip_web_dev():
    packs = get_recommended_packs(["platform:web", "category:video", "pipeline:video"])
    assert "web-dev" not in packs


def test_looks_like_web_product():
    assert looks_like_web_product(
        "TombRaiderComic 网页 MVP：核心页面与主流程",
        "Next.js 首页 / 章节详情 / 播放页",
    )
    assert not looks_like_web_product("第一集试片：龙三角的呼唤", "出分镜并试生成一个镜头")


def test_confirm_requirement_rejects_web_mvp_for_video():
    result = asyncio.run(ConfirmRequirementAction().run({
        "title": "TombRaiderComic 网页 MVP：核心页面与主流程",
        "description": "首页 / 章节详情 / 播放页，Next.js + mock",
        "project_traits": ["category:video", "pipeline:video"],
    }))
    assert not result.success
    assert "导演制片" in (result.error or "")


def test_confirm_requirement_allows_pilot_for_video():
    result = asyncio.run(ConfirmRequirementAction().run({
        "title": "第一集试片：龙三角的呼唤",
        "description": "选定第一章，出视频简报和分镜，先跑通 1 个镜头试生成。",
        "project_traits": ["category:video", "pipeline:video"],
    }))
    assert result.success
    assert result.data["title"].startswith("第一集试片")


def test_video_chat_routing_mentions_pilot():
    text = video_chat_routing_section()
    assert "第一集试片" in text
    assert "网页 MVP" in text
