"""ArtistAgent 的结果处理器。

从 `TicketOrchestrator._handle_agent_result` 原样搬出（重构方案 R2 第 1 步），逻辑未改。
和原文的差别只有三处：`self` 写成 `orch`；共享的局部变量从 `ctx` 取；
`return` 写成 `return HANDLED`，落到函数尾部的路径写成 `return new_status`。
"""
import json
from typing import Optional

from orchestration.result_handlers.context import HANDLED, ResultContext
from utils import generate_id, now_iso


async def handle_artist(ctx: ResultContext) -> Optional[str]:
    """ArtistAgent：资产落地，状态写成 assets_ready。在处理器内收尾。"""
    orch = ctx.orch
    db = ctx.db
    project_id = ctx.project_id
    ticket_id = ctx.ticket_id
    ticket = ctx.ticket
    agent_name = ctx.agent_name
    action = ctx.action
    result = ctx.result
    result_json = ctx.result_json
    current_status = ctx.current_status
    requirement_id = ctx.requirement_id
    git_result = ctx.git_result

    # 美术资产落地（asset_gen fragment）。没有这个分支会落到函数末尾的
    # else: new_status = current_status —— 状态不推进，同一条 rule 反复命中。
    new_status = "assets_ready"
    await db.update("tickets", {
        "status": new_status, "result": result_json, "updated_at": now_iso(),
    }, "id = ?", (ticket_id,))
    _total = result.get("assets_total", 0)
    _sourced = result.get("sourced", 0)
    _ph = result.get("placeholder", 0)
    _skip = result.get("skipped", 0)
    if _total:
        await db.insert("artifacts", {
            "id": generate_id("ART"),
            "project_id": project_id,
            "requirement_id": requirement_id,
            "ticket_id": ticket_id,
            "type": "asset_manifest",
            "name": f"资产落地 - {ticket['title']}",
            "path": None,
            "content": result_json,
            "metadata": json.dumps({
                "total": _total, "sourced": _sourced,
                "placeholder": _ph, "skipped": _skip,
            }, ensure_ascii=False),
            "created_at": now_iso(),
        })
    await orch._log(
        project_id, requirement_id, ticket_id, agent_name,
        action, current_status, new_status,
        f"资产落地完成：{_sourced} 命中资产库 / {_ph} 占位图 / {_skip} 待人工",
        detail_data={
            "total": _total, "sourced": _sourced,
            "placeholder": _ph, "skipped": _skip,
            "media_paths": result.get("media_paths") or [],
            "git_files": (git_result.get("files") if git_result else []) or [],
        },
    )
    # 占位图和待人工项需要美术介入，写进评论让人看得见（顺带把生成的图片路径附在评论后，方便直接预览点开）
    _warn = ""
    if _ph or _skip:
        _warn = (f"\n⚠️ {_ph} 个占位图需替换"
                 + (f"，{_skip} 项需人工提供" if _skip else ""))
    _media_list = result.get("media_paths") or []
    _media_note = ""
    if _media_list:
        _media_note = "\n🖼️ 产出图片：" + ", ".join(f"`{p}`" for p in _media_list[:12])
    await orch._write_phase_comment(
        project_id, ticket_id, agent_name,
        f"✅ 资产落地完成：共 {_total} 项，{_sourced} 个命中资产库。{_warn}{_media_note}",
        phase=new_status,
    )
    return HANDLED
