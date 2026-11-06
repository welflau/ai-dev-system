"""Mode 资产自检。人审前用文件落地情况拦缺口，不靠 LLM 自觉。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from plugins.director.backends import load_video_brief, normalize_mode
from plugins.director.work_package import find_existing_slug, package_dir

_IMG = {".png", ".jpg", ".jpeg", ".webp"}
_AUD = {".wav", ".mp3", ".m4a"}
_NA = ("不适用", "n/a", "N/A")
_STOCK = (
    "Drama 必填",
    "Explainer / Storytime 写",
    "Explainer 无关键人物时写明",
    "有台词的固定角色才建",
    "每一行是一个即将提交",
)


def _text(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _placeholder(text: str, *, min_len: int = 40) -> bool:
    t = (text or "").strip()
    if len(t) < min_len:
        return True
    if any(s in t for s in _STOCK):
        return True
    if any(m in t for m in _NA) and len(t) < 160:
        return True
    return False


def _has_table(text: str) -> bool:
    rows = [ln for ln in (text or "").splitlines() if ln.strip().startswith("|")]
    return len(rows) >= 3


def _media(folder: Path, exts: set) -> List[Path]:
    if not folder.is_dir():
        return []
    out = []
    for p in folder.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts and p.stat().st_size > 0:
            out.append(p)
    return out


def _gap(code: str, message: str, path: str = "") -> Dict[str, str]:
    return {"code": code, "message": message, "path": path}


def check_mode_assets(repo_path: str, slug: str = "", mode: str = "") -> Dict[str, Any]:
    found = find_existing_slug(repo_path, slug) if repo_path else None
    if not found:
        return {
            "ok": False,
            "mode": mode or "",
            "slug": slug,
            "gaps": [_gap("no_package", "找不到 works/<slug>/，先 init_work_package")],
        }
    pkg = package_dir(repo_path, found)
    brief = load_video_brief(repo_path, found)
    mode = normalize_mode(mode or brief.get("mode") or "")
    gaps: List[Dict[str, str]] = []

    brief_path = pkg / "video_brief.json"
    if not brief_path.is_file() or not brief.get("mode"):
        gaps.append(_gap("video_brief", "缺少 video_brief.json 或未锁定 mode", f"works/{found}/video_brief.json"))

    if mode == "cinematic-drama":
        gaps.extend(_check_drama(pkg, found))
    elif mode == "storytime-animation":
        gaps.extend(_check_storytime(pkg, found))
    elif mode == "animated-explainer":
        gaps.extend(_check_explainer(pkg, found))
    elif mode:
        gaps.append(_gap("unknown_mode", f"未支持的 Mode：{mode}，不要套用现有流程"))
    else:
        gaps.append(_gap("mode_missing", "尚未选定 Mode"))

    return {
        "ok": not gaps,
        "mode": mode,
        "slug": found,
        "gaps": gaps,
        "package": str(pkg),
    }


def _check_explainer(pkg: Path, slug: str) -> List[Dict[str, str]]:
    gaps = []
    narration = _text(pkg / "旁白.md")
    if _placeholder(narration):
        gaps.append(_gap("narration", "Explainer 需要定稿旁白", f"works/{slug}/旁白.md"))
    bible = _text(pkg / "character-bible.md")
    if _placeholder(bible, min_len=12):
        gaps.append(_gap(
            "character_bible",
            "需要 character-bible.md（无关键人物也要写明）",
            f"works/{slug}/character-bible.md",
        ))
    return gaps


def _check_storytime(pkg: Path, slug: str) -> List[Dict[str, str]]:
    gaps = _check_explainer(pkg, slug)
    refs = _media(pkg / "refs" / "characters", _IMG)
    bible = _text(pkg / "character-bible.md")
    if "无关键人物" not in bible and not refs:
        gaps.append(_gap(
            "character_ref",
            "Storytime 讲述者默认关键人物，需要至少一张人物参考图",
            f"works/{slug}/refs/characters/",
        ))
    return gaps


def _check_drama(pkg: Path, slug: str) -> List[Dict[str, str]]:
    gaps = []
    table = _text(pkg / "片段表.md")
    if _placeholder(table, min_len=80):
        gaps.append(_gap("drama_breakdown", "Drama 需要片段表（开场/结束/对白/出场）", f"works/{slug}/片段表.md"))
    scene = _text(pkg / "scene-bible.md")
    if _placeholder(scene, min_len=60):
        gaps.append(_gap("scene_bible", "Drama 需要场景卡 scene-bible.md", f"works/{slug}/scene-bible.md"))
    if not _media(pkg / "refs" / "scenes", _IMG):
        gaps.append(_gap("scene_ref", "Drama 需要至少一张已确认场景参考图", f"works/{slug}/refs/scenes/"))
    bible = _text(pkg / "character-bible.md")
    if _placeholder(bible, min_len=60):
        gaps.append(_gap("character_bible", "Drama 需要角色资产表", f"works/{slug}/character-bible.md"))
    if not _media(pkg / "refs" / "characters", _IMG):
        gaps.append(_gap(
            "character_ref",
            "Drama 主角/跨片段配角需要人物参考（建议含三视图）",
            f"works/{slug}/refs/characters/",
        ))
    voice = _text(pkg / "voice-plan.md")
    if _placeholder(voice, min_len=40):
        gaps.append(_gap("voice_plan", "Drama 说话角色需要音色计划", f"works/{slug}/voice-plan.md"))
    matrix = _text(pkg / "continuity-matrix.md")
    if _placeholder(matrix, min_len=60) or not _has_table(matrix):
        gaps.append(_gap(
            "continuity_matrix",
            "Drama 需要片段×可辨识元素矩阵（Markdown 表）",
            f"works/{slug}/continuity-matrix.md",
        ))
    lock = _text(pkg / "generation-lock.md")
    if _placeholder(lock, min_len=20):
        gaps.append(_gap("generation_lock", "缺少项目级生成锁", f"works/{slug}/generation-lock.md"))
    return gaps


def check_gate(
    gate: str,
    repo_path: str,
    slug: str = "",
    mode: str = "",
) -> Dict[str, Any]:
    gate = (gate or "").strip().lower()
    found = find_existing_slug(repo_path, slug) if repo_path else None
    if gate in ("", "none"):
        return {"ok": True, "mode": mode, "slug": found or slug, "gaps": []}
    if not found:
        return {
            "ok": False,
            "mode": mode,
            "slug": slug,
            "gaps": [_gap("no_package", "找不到工作包")],
        }
    pkg = package_dir(repo_path, found)
    brief = load_video_brief(repo_path, found)
    mode = normalize_mode(mode or brief.get("mode") or "")

    if gate == "brief":
        if not (pkg / "video_brief.json").is_file() or not brief.get("mode"):
            return {
                "ok": False, "mode": mode, "slug": found,
                "gaps": [_gap("video_brief", "简报未锁定 Mode", f"works/{found}/video_brief.json")],
            }
        if mode not in ("animated-explainer", "storytime-animation", "cinematic-drama"):
            return {
                "ok": False, "mode": mode, "slug": found,
                "gaps": [_gap("unknown_mode", f"未支持 Mode：{mode}")],
            }
        return {"ok": True, "mode": mode, "slug": found, "gaps": []}

    if gate == "script":
        if mode == "cinematic-drama":
            text = _text(pkg / "片段表.md")
            if _placeholder(text, min_len=80):
                return {
                    "ok": False, "mode": mode, "slug": found,
                    "gaps": [_gap("drama_breakdown", "剧情拆解未完成", f"works/{found}/片段表.md")],
                }
        else:
            text = _text(pkg / "旁白.md")
            if _placeholder(text):
                return {
                    "ok": False, "mode": mode, "slug": found,
                    "gaps": [_gap("narration", "旁白未完成", f"works/{found}/旁白.md")],
                }
        return {"ok": True, "mode": mode, "slug": found, "gaps": []}

    if gate == "visual":
        return check_mode_assets(repo_path, found, mode)

    if gate in ("clip", "clip_trial"):
        clip = pkg / "video" / "片段01.mp4"
        if not clip.is_file() or clip.stat().st_size <= 0:
            return {
                "ok": False, "mode": mode, "slug": found,
                "gaps": [_gap("clip_trial", "片段 1 尚未下载到非空 mp4", f"works/{found}/video/片段01.mp4")],
            }
        return {"ok": True, "mode": mode, "slug": found, "gaps": []}

    return {"ok": True, "mode": mode, "slug": found, "gaps": []}
