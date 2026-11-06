"""发出人审确认卡并让 skill 停等。"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("plugins.director.confirm_video_gate")


def pick_chat_session(requested: str, latest_project_session: str | None) -> str:
    """人审卡要进用户正在看的项目会话，不能掉进 session_id=default。"""
    sid = (requested or "").strip()
    if sid and sid != "default" and not sid.startswith("default"):
        return sid
    latest = (latest_project_session or "").strip()
    if latest and latest != "default" and not latest.startswith("default"):
        return latest
    return sid or "default"


class ConfirmVideoGateAction(ActionBase):
    available_for_traits = {"any_of": ["category:video", "pipeline:video"]}

    @property
    def name(self) -> str:
        return "confirm_video_gate"

    @property
    def description(self) -> str:
        return (
            "制作产物已落盘后调用。发出确认卡并暂停流水线，等待用户确认或打回。"
            "调用后不要再写文件，直接 done。"
        )

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "确认卡标题"},
                    "summary": {"type": "string", "description": "给用户看的摘要"},
                    "preview_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "工作包内相对路径，如 works/slug/旁白.md",
                    },
                    "work_slug": {"type": "string"},
                    "mode": {"type": "string"},
                    "gate": {
                        "type": "string",
                        "description": "brief / script / visual / clip。指定后先做资产自检，不齐则不进人审",
                    },
                },
                "required": ["title"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        title = str(context.get("title") or "确认当前制作产物").strip()
        summary = str(context.get("summary") or "").strip()
        slug = str(context.get("work_slug") or context.get("slug") or "").strip()
        mode = str(context.get("mode") or "").strip()
        gate = str(context.get("gate") or "").strip().lower()
        if not gate:
            skill_id = str(context.get("skill_id") or "").strip()
            gate = {
                "director-brief": "brief",
                "director-script": "script",
                "director-visual": "visual",
                "director-clip-trial": "clip",
            }.get(skill_id, "")
        repo = str(context.get("repo_path") or "")
        try:
            from actions.gen_image import IMAGE_BLOCK_STOP, read_image_blocked_marker
            from pathlib import Path as _P
            for raw in (
                context.get("_skill_output_root"),
                str(_P(repo) / "works") if repo else "",
            ):
                hit = read_image_blocked_marker(_P(raw) if raw else None)
                if hit:
                    return ActionResult(
                        success=False,
                        error=IMAGE_BLOCK_STOP,
                        data={"image_blocked": True, "waiting_human": False},
                    )
        except Exception:
            pass
        if gate and gate not in ("none", "-"):
            from plugins.director.mode_check import check_gate
            report = check_gate(gate, repo, slug, mode)
            if not report.get("ok"):
                gaps = report.get("gaps") or []
                lines = "；".join(g.get("message") or g.get("code") for g in gaps[:8])
                return ActionResult(
                    success=False,
                    error=f"资产未齐，不能发出确认卡：{lines}",
                    data={
                        "waiting_human": False,
                        "gate": gate,
                        "gaps": gaps,
                        "mode": report.get("mode") or mode,
                        "work_slug": report.get("slug") or slug,
                    },
                )
            mode = str(report.get("mode") or mode)
            slug = str(report.get("slug") or slug)
        raw_paths = context.get("preview_paths") or []
        if isinstance(raw_paths, str):
            paths: List[str] = [raw_paths]
        else:
            paths = [str(p) for p in raw_paths if p]

        project_id = str(context.get("project_id") or "")
        ticket_id = str(context.get("ticket_id") or "")
        public_url = ""
        preview_urls = []
        for rel in paths:
            lower = rel.lower()
            if project_id and lower.endswith(
                (".mp4", ".webm", ".png", ".jpg", ".jpeg", ".webp", ".wav", ".mp3")
            ):
                from urllib.parse import quote
                url = f"/api/projects/{project_id}/git/file-raw?path={quote(rel)}"
                preview_urls.append({"path": rel, "url": url})
                if not public_url:
                    public_url = url
            else:
                preview_urls.append({"path": rel, "url": ""})
        if not public_url:
            public_url = str(context.get("public_url") or "")

        payload = {
            "type": "confirm_video_gate",
            "waiting_human": True,
            "title": title,
            "summary": summary,
            "preview_paths": paths,
            "preview_urls": preview_urls,
            "public_url": public_url,
            "work_slug": slug,
            "mode": mode,
            "ticket_id": ticket_id,
            "project_id": project_id,
        }

        if project_id:
            try:
                from database import db
                from utils import generate_id, now_iso
                latest = await db.fetch_one(
                    """SELECT session_id FROM chat_messages
                       WHERE project_id = ?
                         AND session_id IS NOT NULL AND session_id != ''
                         AND session_id NOT LIKE 'default%'
                       ORDER BY created_at DESC LIMIT 1""",
                    (project_id,),
                )
                session_id = pick_chat_session(
                    str(context.get("session_id") or ""),
                    (latest or {}).get("session_id"),
                )
                msg_id = generate_id("MSG")
                payload["_message_id"] = msg_id
                payload["session_id"] = session_id
                await db.insert("chat_messages", {
                    "id": msg_id,
                    "project_id": project_id,
                    "role": "assistant",
                    "content": f"请确认：{title}",
                    "action_type": "confirm_video_gate",
                    "action_data": json.dumps(payload, ensure_ascii=False),
                    "action_state": "pending",
                    "session_id": session_id,
                    "created_at": now_iso(),
                })
                try:
                    from events import event_manager
                    await event_manager.publish_to_project(
                        project_id, "chat_mcp_action",
                        {"action": payload, "msg_id": msg_id, "session_id": session_id},
                    )
                except Exception:
                    pass
            except Exception as e:
                logger.warning("写入 confirm_video_gate 消息失败: %s", e)

        if repo and slug:
            try:
                from plugins.director.work_package import package_dir
                marker = package_dir(repo, slug) / ".ads-waiting-human.json"
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                logger.warning("写入 waiting_human 标记失败: %s", e)

        return ActionResult(
            success=True,
            data=payload,
            message=f"已发出确认卡「{title}」，等待用户确认。",
        )
