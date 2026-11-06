"""UE 阶段收尾钩子。

宿主看到片段里的 on_success / on_failure 名字后，从 STAGE_HOOKS 里取函数。
函数只调用宿主已经有的副作用，不自己写工单状态。
回跳时只返回阶段 id，触发状态由宿主到组合后的 SOP 里取。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def err_brief(errors: List[Dict], limit: int = 3) -> str:
    parts = []
    for item in (errors or [])[:limit]:
        if not isinstance(item, dict):
            continue
        fname = str(item.get("file") or "?").replace("\\", "/").split("/")[-1]
        parts.append(
            f"{fname}:{item.get('line', '?')} {item.get('code', '')} "
            f"{str(item.get('msg') or '')[:80]}"
        )
    return "; ".join(parts)


async def resolve_compile_bug(host: Any, ctx: Dict[str, Any]) -> None:
    await host._resolve_compile_bug(ctx["ticket_id"], ctx["project_id"])
    return None


async def create_compile_bug(host: Any, ctx: Dict[str, Any]) -> Dict[str, str]:
    result = ctx.get("result") or {}
    errors = result.get("errors") or []
    await host._create_compile_bug(
        ctx["project_id"],
        ctx.get("requirement_id"),
        ctx["ticket_id"],
        errors,
        err_brief(errors),
    )
    return {"log_note": "，已创建 Bug 记录，DevAgent.fix_issues 将修复"}


async def openspec_verify(host: Any, ctx: Dict[str, Any]) -> None:
    stage = ctx.get("stage") or {}
    await host._maybe_openspec_verify(
        ctx["project_id"],
        ctx["ticket_id"],
        stage_label=str(stage.get("id") or ""),
    )
    return None


async def uproject_heal(host: Any, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    result = ctx.get("result") or {}
    module_errors = result.get("module_load_errors") or []
    if not module_errors:
        return None
    heal = await host._try_uproject_heal(
        ctx["project_id"], ctx["ticket_id"], result,
    )
    if heal.get("healed"):
        added = heal.get("added_plugins") or []
        names = ", ".join(str(item) for item in added) if added else "（列表为空）"
        return {
            "rewind_to_stage": "engine_compile",
            "log_message": f"uproject 自愈：追加插件 {names}，重新编译+测试",
            "detail": {"added_plugins": list(added), "heal_result": heal},
        }
    return {"log_note": "（已尝试 uproject 自愈，无有效插件可补充）"}


STAGE_HOOKS = {
    "resolve_compile_bug": resolve_compile_bug,
    "create_compile_bug": create_compile_bug,
    "openspec_verify": openspec_verify,
    "uproject_heal": uproject_heal,
}
