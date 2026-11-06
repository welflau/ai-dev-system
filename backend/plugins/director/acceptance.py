"""产品验收：以工作包清单和本地文件为准，不因读不到 mp4 像素判 0 分。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def _load_package(context: Dict[str, Any]) -> Dict[str, Any]:
    repo = str(context.get("repo_path") or "")
    slug = str(context.get("work_slug") or "")
    if not repo:
        return {}
    root = Path(repo) / "works"
    if slug:
        pkg = root / slug / "video_package.json"
        if pkg.is_file():
            try:
                return json.loads(pkg.read_text(encoding="utf-8"))
            except Exception:
                return {"path": str(pkg), "unreadable": True}
    if not root.is_dir():
        return {}
    for pkg in sorted(root.glob("*/video_package.json"), reverse=True):
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            data.setdefault("path", str(pkg))
            return data
        except Exception:
            continue
    return {}


async def build_acceptance_evidence(context: Dict[str, Any]) -> Dict[str, Any]:
    pkg = _load_package(context)
    clips: List[Dict[str, Any]] = []
    if isinstance(pkg.get("clips"), list):
        clips = pkg["clips"]
    missing = []
    existing = []
    for clip in clips:
        path = Path(str(clip.get("path") or ""))
        if not path.is_file() or path.stat().st_size <= 0:
            missing.append(str(clip.get("path") or clip.get("filename") or "?"))
        else:
            existing.append(f"{path.name} ({path.stat().st_size} bytes)")

    lines = [
        "## Director 视频制片验收证据",
        f"- Mode：{pkg.get('mode') or '（未写）'}",
        f"- style：{pkg.get('style') or '（未写）'}",
        f"- 后端：{pkg.get('backend') or '（未写）'}",
        f"- 工作包：{pkg.get('work_slug') or pkg.get('path') or '（未找到 video_package.json）'}",
        f"- 已落盘片段：{len(existing)}",
        f"- 缺失/空文件：{len(missing)}",
    ]
    if existing:
        lines.append("已有文件：")
        lines.extend(f"- {x}" for x in existing[:30])
    if missing:
        lines.append("缺失：")
        lines.extend(f"- {x}" for x in missing[:30])

    failed = list(missing)
    if not clips:
        failed.append("没有 video_package.json 或 clips 清单为空")

    return {
        "evidence_markdown": "\n".join(lines),
        "extra_check_items": [
            "video_brief 已锁定 Mode 与 style",
            "讲稿或剧情拆解已经人审",
            "片段 1 已人审（画面 + 音色）",
            "current-assets-manifest 与实际节点输入一致",
            "全部计划片段已下载且非空",
            "正式片段分辨率未违反成本锁（默认 720p）",
        ],
        "failed_items": failed,
        "acceptance_rules": (
            "以工作包清单和本地文件为准，不得因 ProductAgent 读不到 mp4 像素内容判 0 分。"
            "缺文件、空文件、任务未成功才不通过。自动剪辑不是验收项。"
        ),
    }
