"""会话临时素材登记。

文件为主 + DB 索引。新写入落 DATA_DIR/session_materials/{session_id}/，
旧 chat_images / generated-images 只登记不搬家。
不进 ArtifactStore，不进 art_assets，直到用户 promote。
"""
from __future__ import annotations

import json
import logging
import mimetypes
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import BASE_DIR, DATA_DIR
from database import db
from utils import generate_id, now_iso

logger = logging.getLogger("materials.registry")

MATERIALS_ROOT = DATA_DIR / "session_materials"
TTL_DAYS = 14
KEEP_SCRATCH = 50

ORIGINS = frozenset({"upload", "import", "generated", "export", "tool"})
STATUSES = frozenset({"scratch", "pinned", "promoted", "deleted"})
PROMOTE_SINKS = frozenset({"art", "repo", "knowledge", "ticket", "requirement"})

# 只替换操作系统不允许的字符；中文、全角冒号等保留给展示名。
_UNSAFE_FS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_INLINE_DOC_RE = re.compile(
    r"【附件(?:路径)?[:：]([^\]]+)】(?:\r?\n([\s\S]*?))?(?=(?:\r?\n【附件(?:路径)?[:：])|$)"
)


def _display_name(name: str) -> str:
    raw = (name or "file").strip().replace("\\", "/")
    base = Path(raw).name.strip() or "file"
    return base[:200]


def _safe_filename(name: str) -> str:
    base = _display_name(name)
    cleaned = _UNSAFE_FS.sub("_", base).strip(" .") or "file"
    return cleaned[:80]


def _guess_mime(name: str, fallback: str = "") -> str:
    mime, _ = mimetypes.guess_type(name)
    return mime or fallback or "application/octet-stream"


def rel_to_base(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(BASE_DIR.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def abs_from_rel(rel_path: str) -> Path:
    p = Path(rel_path)
    if p.is_absolute():
        return p
    return (BASE_DIR / rel_path).resolve()


def _expires_at(days: int = TTL_DAYS) -> str:
    return (datetime.now() + timedelta(days=days)).isoformat()


def _row_to_dict(row: Any) -> Dict[str, Any]:
    d = dict(row)
    raw = d.get("metadata")
    if isinstance(raw, str) and raw:
        try:
            d["metadata"] = json.loads(raw)
        except Exception:
            d["metadata"] = {}
    elif not raw:
        d["metadata"] = {}
    d["file_url"] = d.get("public_url") or _file_api_url(d)
    return d


def _file_api_url(d: Dict[str, Any]) -> str:
    sid = d.get("session_id") or ""
    mid = d.get("id") or ""
    pid = d.get("project_id")
    if pid and pid != "__global__":
        return f"/api/projects/{pid}/chat/sessions/{sid}/materials/{mid}/file"
    return f"/api/chat/sessions/{sid}/materials/{mid}/file"


class MaterialRegistry:
    async def attach(
        self,
        *,
        session_id: str,
        project_id: Optional[str] = None,
        name: str,
        origin: str = "upload",
        src_path: Optional[str] = None,
        content: Optional[bytes] = None,
        mime: str = "",
        message_id: Optional[str] = None,
        public_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status: str = "scratch",
        promoted_sink: Optional[str] = None,
        promoted_id: Optional[str] = None,
        copy_into_session_dir: bool = False,
    ) -> Dict[str, Any]:
        if not session_id:
            raise ValueError("session_id 必填")
        if origin not in ORIGINS:
            origin = "upload"
        if status not in STATUSES:
            status = "scratch"
        if content is None and not src_path:
            raise ValueError("attach 需要 src_path 或 content")

        pid = None if (not project_id or project_id == "__global__") else project_id
        mid = generate_id("SM")
        display = _display_name(name)
        safe = _safe_filename(display)
        now = now_iso()
        mime = mime or _guess_mime(display) or _guess_mime(safe)

        if content is not None:
            dest = MATERIALS_ROOT / session_id / f"{mid}_{safe}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            rel_path = rel_to_base(dest)
            size = dest.stat().st_size
        else:
            src = Path(src_path)
            if not src.is_file():
                raise FileNotFoundError(str(src))
            if copy_into_session_dir:
                dest = MATERIALS_ROOT / session_id / f"{mid}_{safe}"
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                rel_path = rel_to_base(dest)
                size = dest.stat().st_size
            else:
                rel_path = rel_to_base(src)
                size = src.stat().st_size

        row = {
            "id": mid,
            "session_id": session_id,
            "project_id": pid,
            "message_id": message_id,
            "name": display,
            "mime": mime,
            "size_bytes": size,
            "rel_path": rel_path,
            "public_url": public_url,
            "origin": origin,
            "status": status,
            "expires_at": _expires_at() if status == "scratch" else None,
            "promoted_sink": promoted_sink,
            "promoted_id": promoted_id,
            "metadata": json.dumps(metadata or {}, ensure_ascii=False),
            "created_at": now,
            "updated_at": now,
        }
        await db.insert("session_materials", row)
        if status == "scratch":
            await self._trim_session(session_id)
        return await self.get(mid)

    async def attach_urls(
        self,
        *,
        session_id: str,
        project_id: Optional[str],
        urls: List[str],
        origin: str,
        message_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for url in urls or []:
            if not url:
                continue
            existing = await db.fetch_one(
                "SELECT id FROM session_materials WHERE session_id=? AND public_url=? AND status!='deleted'",
                (session_id, url),
            )
            if existing:
                rec = await self.get(existing["id"])
                if rec:
                    out.append(rec)
                continue
            src = self._url_to_path(url)
            if not src or not src.is_file():
                logger.debug("跳过无法解析的素材 URL: %s", url)
                continue
            rec = await self.attach(
                session_id=session_id,
                project_id=project_id,
                name=src.name,
                origin=origin,
                src_path=str(src),
                mime=_guess_mime(src.name),
                message_id=message_id,
                public_url=url,
                metadata=metadata,
            )
            out.append(rec)
        return out

    async def attach_inline_docs(
        self,
        *,
        session_id: str,
        project_id: Optional[str] = None,
        content: str,
        message_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """把用户消息里的【附件：文件名】正文登记为本会话素材。幂等：同会话同名跳过。"""
        out: List[Dict[str, Any]] = []
        text = content or ""
        if "【附件" not in text:
            return out
        for match in _INLINE_DOC_RE.finditer(text):
            raw_name = (match.group(1) or "").strip()
            body = (match.group(2) or "").strip()
            if not raw_name or not body:
                continue
            display = _display_name(raw_name)
            existing = await db.fetch_one(
                "SELECT id FROM session_materials WHERE session_id=? AND name=? AND status!='deleted'",
                (session_id, display),
            )
            if existing:
                rec = await self.get(existing["id"])
                if rec:
                    out.append(rec)
                continue
            lower = display.lower()
            fallback = "text/markdown" if lower.endswith((".md", ".markdown")) else "text/plain"
            rec = await self.attach(
                session_id=session_id,
                project_id=project_id,
                name=display,
                origin="upload",
                content=body.encode("utf-8"),
                mime=_guess_mime(display, fallback),
                message_id=message_id,
                metadata={"source": "chat_attachment", "label": raw_name},
            )
            out.append(rec)
        return out

    async def sync_inline_docs_from_session(
        self,
        session_id: str,
        project_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """补登已经落在 chat_messages 里、但没进素材表的聊天附件。"""
        out: List[Dict[str, Any]] = []
        try:
            rows = await db.fetch_all(
                "SELECT id, content FROM chat_messages "
                "WHERE session_id=? AND role='user' AND content LIKE '%【附件%'",
                (session_id,),
            )
        except Exception as e:
            logger.debug("扫描会话附件失败: %s", e)
            return out
        for row in rows or []:
            try:
                attached = await self.attach_inline_docs(
                    session_id=session_id,
                    project_id=project_id,
                    content=row["content"] or "",
                    message_id=row["id"],
                )
                out.extend(attached)
            except Exception as e:
                logger.debug("补登会话附件失败 %s: %s", row["id"], e)
        return out

    def _url_to_path(self, url: str) -> Optional[Path]:
        u = (url or "").split("?", 1)[0]
        if u.startswith("/chat-images/"):
            return BASE_DIR / "chat_images" / u[len("/chat-images/"):]
        if u.startswith("/generated-images/"):
            return BASE_DIR / "generated-images" / u[len("/generated-images/"):]
        return None

    async def get(self, material_id: str) -> Optional[Dict[str, Any]]:
        row = await db.fetch_one("SELECT * FROM session_materials WHERE id=?", (material_id,))
        return _row_to_dict(row) if row else None

    async def list(
        self,
        session_id: str,
        *,
        include_deleted: bool = False,
    ) -> List[Dict[str, Any]]:
        if include_deleted:
            rows = await db.fetch_all(
                "SELECT * FROM session_materials WHERE session_id=? ORDER BY created_at DESC",
                (session_id,),
            )
        else:
            rows = await db.fetch_all(
                "SELECT * FROM session_materials WHERE session_id=? AND status!='deleted' "
                "ORDER BY created_at DESC",
                (session_id,),
            )
        return [_row_to_dict(r) for r in (rows or [])]

    async def pin(self, material_id: str, pinned: bool = True) -> Dict[str, Any]:
        rec = await self.get(material_id)
        if not rec or rec["status"] == "deleted":
            raise FileNotFoundError(material_id)
        if rec["status"] == "promoted":
            return rec
        status = "pinned" if pinned else "scratch"
        await db.update(
            "session_materials",
            {
                "status": status,
                "expires_at": None if pinned else _expires_at(),
                "updated_at": now_iso(),
            },
            "id = ?",
            (material_id,),
        )
        return await self.get(material_id)

    async def markdown_links(self, material_ids: List[str]) -> str:
        parts: List[str] = []
        for i, mid in enumerate(material_ids or [], 1):
            rec = await self.get(mid)
            if not rec or rec["status"] == "deleted":
                continue
            url = rec.get("file_url") or rec.get("public_url") or rec.get("rel_path")
            name = rec.get("name") or f"素材{i}"
            if (rec.get("mime") or "").startswith("image/"):
                parts.append(f"![{name}]({url})")
            else:
                parts.append(f"[{name}]({url})")
        return ("\n\n" + "\n\n".join(parts)) if parts else ""

    async def mark_promoted(
        self,
        material_ids: List[str],
        sink: str,
        promoted_id: str = "",
    ) -> None:
        if sink not in PROMOTE_SINKS:
            return
        now = now_iso()
        for mid in material_ids or []:
            rec = await self.get(mid)
            if not rec or rec["status"] == "deleted":
                continue
            await db.update(
                "session_materials",
                {
                    "status": "promoted",
                    "promoted_sink": sink,
                    "promoted_id": promoted_id or rec.get("promoted_id"),
                    "expires_at": None,
                    "updated_at": now,
                },
                "id = ?",
                (mid,),
            )

    async def promote(
        self,
        material_id: str,
        sink: str,
        *,
        ticket_id: Optional[str] = None,
        scope: str = "project",
    ) -> Dict[str, Any]:
        rec = await self.get(material_id)
        if not rec or rec["status"] == "deleted":
            raise FileNotFoundError(material_id)
        if sink not in PROMOTE_SINKS:
            raise ValueError(f"未知提升目标: {sink}")
        src = abs_from_rel(rec["rel_path"])
        if not src.is_file() and sink in {"art", "repo", "knowledge"}:
            raise FileNotFoundError(rec["rel_path"])

        if sink == "art":
            promoted_id = await self._promote_art(rec, src, scope)
        elif sink == "repo":
            promoted_id = await self._promote_repo(rec, src)
        elif sink == "knowledge":
            promoted_id = await self._promote_knowledge(rec, src)
        elif sink == "ticket":
            if not ticket_id:
                raise ValueError("提升到工单需要 ticket_id")
            await self._append_to_ticket(ticket_id, rec)
            promoted_id = ticket_id
        else:
            raise ValueError(f"未知提升目标: {sink}")

        await self.mark_promoted([material_id], sink, promoted_id)
        out = await self.get(material_id)
        out["promoted_id"] = promoted_id
        return out

    async def _promote_art(self, rec: Dict[str, Any], src: Path, scope: str) -> str:
        from config import settings
        art_root = Path(settings.ART_ASSETS_LOCAL_PATH) if settings.ART_ASSETS_LOCAL_PATH else None
        if not art_root or not art_root.exists():
            raise RuntimeError("未配置 ART_ASSETS_LOCAL_PATH，无法入库")
        dest_dir = art_root / "2d" / "generated"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{rec['id']}_{rec['name']}"
        shutil.copy2(src, dest)
        rel = dest.relative_to(art_root).as_posix()
        ext = dest.suffix.lstrip(".") or "png"
        asset_id = rec["id"].replace("SM-", "IMG-", 1) if rec["id"].startswith("SM-") else rec["id"]
        pid = rec.get("project_id") or ""
        project_scope = "global" if scope == "global" or not pid else pid
        await db.execute(
            """
            INSERT INTO art_assets
            (id, name, description, tags, type, style, format, width, height,
             file_path, source, source_ref, source_url, project_scope, used_count, added_at)
            VALUES (?,?,?,?,?,?,?,0,0,?,?,?,?,?,0,?)
            ON CONFLICT(id) DO UPDATE SET file_path=excluded.file_path
            """,
            (
                asset_id, rec["name"], rec["name"],
                json.dumps(["session", rec.get("origin") or "upload"], ensure_ascii=False),
                "illustration", "ai_generated" if rec.get("origin") == "generated" else "manual",
                ext, rel, "session_material", rec["id"], rec.get("public_url") or "",
                project_scope, now_iso(),
            ),
        )
        return asset_id

    async def _promote_repo(self, rec: Dict[str, Any], src: Path) -> str:
        pid = rec.get("project_id")
        if not pid:
            raise RuntimeError("全局会话不能提升到项目仓库")
        text = src.read_text(encoding="utf-8", errors="replace")
        if not rec["name"].endswith(".md"):
            filename = f"docs/{Path(rec['name']).stem}.md"
        else:
            filename = f"docs/{rec['name']}"
        from git_manager import git_manager
        project = await db.fetch_one("SELECT * FROM projects WHERE id=?", (pid,))
        if not project:
            raise RuntimeError("项目不存在")
        if not git_manager.repo_exists(pid):
            await git_manager.init_repo(pid, project["name"])
        await git_manager.write_file(pid, filename, text)
        mode = (project.get("mode") or "auto")
        if mode != "manual":
            await git_manager.commit(pid, f"[Doc] 会话素材: {filename}", author="ChatAssistant")
        return filename

    async def _promote_knowledge(self, rec: Dict[str, Any], src: Path) -> str:
        text = src.read_text(encoding="utf-8", errors="replace")
        fname = rec["name"] if rec["name"].endswith(".md") else f"{Path(rec['name']).stem}.md"
        from api.knowledge import _get_docs_dir, _safe_filename, _upsert_knowledge_index
        pid = rec.get("project_id")
        safe = _safe_filename(fname)
        path = _get_docs_dir(pid) / safe
        path.write_text(text, encoding="utf-8")
        await _upsert_knowledge_index(pid, safe, text)
        return safe

    async def _append_to_ticket(self, ticket_id: str, rec: Dict[str, Any]) -> None:
        ticket = await db.fetch_one("SELECT id, description FROM tickets WHERE id=?", (ticket_id,))
        if not ticket:
            raise FileNotFoundError(ticket_id)
        md = await self.markdown_links([rec["id"]])
        if not md:
            return
        desc = (ticket.get("description") or "") + md
        await db.update("tickets", {"description": desc, "updated_at": now_iso()}, "id = ?", (ticket_id,))

    async def delete_session(self, session_id: str) -> Dict[str, int]:
        rows = await db.fetch_all(
            "SELECT * FROM session_materials WHERE session_id=?", (session_id,)
        )
        files = 0
        for row in rows or []:
            rec = _row_to_dict(row)
            if rec["status"] != "promoted":
                path = abs_from_rel(rec["rel_path"])
                if path.is_file() and self._owned_file(path):
                    try:
                        path.unlink()
                        files += 1
                    except Exception as e:
                        logger.debug("删素材文件失败 %s: %s", path, e)
            await db.execute("DELETE FROM session_materials WHERE id=?", (rec["id"],))
        return {"rows": len(rows or []), "files": files}

    def _owned_file(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(MATERIALS_ROOT.resolve())
            return True
        except ValueError:
            return False

    async def _trim_session(self, session_id: str) -> None:
        rows = await db.fetch_all(
            "SELECT id FROM session_materials WHERE session_id=? AND status='scratch' "
            "ORDER BY created_at DESC",
            (session_id,),
        )
        for old in (rows or [])[KEEP_SCRATCH:]:
            await self._delete_scratch(old["id"])

    async def _delete_scratch(self, material_id: str) -> None:
        rec = await self.get(material_id)
        if not rec or rec["status"] != "scratch":
            return
        path = abs_from_rel(rec["rel_path"])
        if path.is_file() and self._owned_file(path):
            try:
                path.unlink()
            except Exception:
                pass
        await db.execute("DELETE FROM session_materials WHERE id=?", (material_id,))

    def resolve_file(self, rec: Dict[str, Any]) -> Path:
        return abs_from_rel(rec["rel_path"])


material_registry = MaterialRegistry()
