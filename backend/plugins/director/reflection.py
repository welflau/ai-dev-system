"""人审打回的反思信号。生成 API 失败不走这里。"""
from __future__ import annotations

from typing import Any, Dict, List

HANDLED_FAILURE_TYPES = frozenset({
    "director_script_rejected",
    "director_visual_rejected",
    "director_prompts_failed",
    "director_brief_rejected",
    "director_clip_trial_rejected",
})


def enrich_fix_context(
    failure_type: str,
    reject_detail: Dict[str, Any],
    context: Dict[str, Any],
) -> None:
    det = reject_detail or {}
    context["director_reject_reason"] = det.get("reason") or det.get("message") or ""
    context["director_work_slug"] = det.get("work_slug") or context.get("work_slug") or ""
    context["director_mode"] = det.get("mode") or ""
    context["director_paths"] = det.get("paths") or []


def build_reflection_signal(
    failure_type: str,
    context: Dict[str, Any],
) -> str:
    reason = str(context.get("director_reject_reason") or "")
    mode = str(context.get("director_mode") or "")
    slug = str(context.get("director_work_slug") or "")
    lines = [
        f"Director 制作阶段被打回（{failure_type}）。不要改代码，只改工作包里的讲稿/Prompt/人物文档。",
    ]
    if mode:
        lines.append(f"当前 Mode：{mode}")
    if slug:
        lines.append(f"作品工作包：works/{slug}/")
    if reason:
        lines.append(f"打回原因：{reason}")
    paths = context.get("director_paths") or []
    if paths:
        lines.append("相关文件：")
        for p in paths[:12]:
            lines.append(f"- {p}")
    lines.append("修正后重新产出同一批文件，不要换 Mode，不要静默换风格。")
    return "\n".join(lines)


def apply_deterministic_fixes(
    failure_type: str,
    repo_path: str,
    compile_errors: List[Dict[str, Any]],
    existing_code: Dict[str, str],
) -> Dict[str, str]:
    return {}
