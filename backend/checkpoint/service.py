"""
Checkpoint 服务：写前快照 / 还原 / 列表。

P0：ticket_start 标记 + before_write 增量；取消还原到 ticket_start 之后的差集。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from database import db
from utils import generate_id, now_iso

from checkpoint import store as blob_store
from checkpoint.context import get_checkpoint_context, set_checkpoint_context

logger = logging.getLogger("checkpoint.service")

_WRITE_TOOL_NAMES = {
    "Write", "Edit", "write_file", "edit_file", "create_file",
    "mcp__filesystem__write_file", "mcp__filesystem__edit_file",
}
_PATH_KEYS = ("path", "file_path", "filePath", "file", "filename")


class CheckpointService:

    async def maybe_capture_for_tool(
        self,
        tool_name: str,
        tool_input: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """QueryEngine / CLI 写工具入口：有 ticket 上下文时写前拍快照。

        CLI 原生 Write 为尽力而为（tool_start 时磁盘可能已改）；API 路径在 execute 前调用则可靠。
        """
        short = (tool_name or "").split("__")[-1] if tool_name else ""
        if tool_name not in _WRITE_TOOL_NAMES and short not in ("Write", "Edit", "write_file", "edit_file", "create_file"):
            return None
        ctx = dict(context or {})
        cv = get_checkpoint_context()
        project_id = ctx.get("project_id") or cv.get("project_id") or ""
        ticket_id = ctx.get("ticket_id") or cv.get("ticket_id") or ""
        if not project_id or not ticket_id:
            return None
        path = ""
        if isinstance(tool_input, dict):
            for k in _PATH_KEYS:
                if tool_input.get(k):
                    path = str(tool_input[k]).strip()
                    break
        if not path:
            return None
        # 去掉仓库绝对前缀，归一相对路径
        repo_path = ctx.get("repo_path") or cv.get("repo_path") or ""
        rel = path.replace("\\", "/")
        if repo_path:
            rp = str(repo_path).replace("\\", "/").rstrip("/")
            if rel.lower().startswith(rp.lower() + "/"):
                rel = rel[len(rp) + 1:]
            elif rel.lower().startswith(rp.lower()):
                rel = rel[len(rp):].lstrip("/")
        rel = blob_store.normalize_rel_path(rel)
        if not rel:
            return None
        try:
            set_checkpoint_context(
                project_id=project_id, ticket_id=ticket_id,
                agent_type=ctx.get("agent_type") or cv.get("agent_type") or "",
                action=ctx.get("action") or tool_name,
                repo_path=repo_path,
            )
            return await self.capture_before_write(
                project_id, ticket_id, [rel],
                repo_path=repo_path or None,
                agent_type=ctx.get("agent_type") or cv.get("agent_type") or "",
                action=ctx.get("action") or tool_name,
            )
        except Exception as e:
            logger.debug("maybe_capture_for_tool 跳过: %s", e)
            return None

    async def gc_expired(self, *, ttl_days: int = 14, keep_active_writes: int = 50) -> Dict[str, Any]:
        """清理终态工单过期 Checkpoint + 进行中工单过多的 before_write；并扫孤儿 blob。"""
        from datetime import datetime, timedelta, timezone
        stats = {"checkpoints_deleted": 0, "files_deleted": 0, "blobs_deleted": 0, "errors": []}
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).strftime("%Y-%m-%dT%H:%M:%S")
            # 终态工单的旧快照
            expired = await db.fetch_all(
                """
                SELECT c.id FROM checkpoints c
                JOIN tickets t ON t.id = c.ticket_id
                WHERE t.status IN ('cancelled', 'deployed')
                  AND c.created_at < ?
                """,
                (cutoff,),
            )
            for row in expired or []:
                n = await self._delete_checkpoint(row["id"])
                stats["checkpoints_deleted"] += 1
                stats["files_deleted"] += n

            # 进行中：每个 ticket 只保留最近 N 条 before_write
            active_tickets = await db.fetch_all(
                """
                SELECT DISTINCT ticket_id FROM checkpoints
                WHERE trigger='before_write'
                """
            )
            for trow in active_tickets or []:
                tid = trow["ticket_id"]
                rows = await db.fetch_all(
                    "SELECT id FROM checkpoints WHERE ticket_id=? AND trigger='before_write' "
                    "ORDER BY created_at DESC",
                    (tid,),
                )
                for old in (rows or [])[keep_active_writes:]:
                    n = await self._delete_checkpoint(old["id"])
                    stats["checkpoints_deleted"] += 1
                    stats["files_deleted"] += n

            stats["blobs_deleted"] = await self._gc_orphan_blobs()
        except Exception as e:
            logger.warning("checkpoint GC 失败: %s", e, exc_info=True)
            stats["errors"].append(str(e))
        return stats

    async def _delete_checkpoint(self, checkpoint_id: str) -> int:
        files = await db.fetch_all(
            "SELECT id FROM checkpoint_files WHERE checkpoint_id=?",
            (checkpoint_id,),
        )
        await db.execute("DELETE FROM checkpoint_files WHERE checkpoint_id=?", (checkpoint_id,))
        await db.execute("DELETE FROM checkpoints WHERE id=?", (checkpoint_id,))
        return len(files or [])

    async def _gc_orphan_blobs(self) -> int:
        """删除未被任何 checkpoint_files 引用的 blob 文件。"""
        from checkpoint.store import BLOBS_ROOT
        if not BLOBS_ROOT.exists():
            return 0
        referenced = set()
        rows = await db.fetch_all(
            "SELECT DISTINCT before_hash FROM checkpoint_files WHERE before_hash IS NOT NULL"
        )
        for r in rows or []:
            if r.get("before_hash"):
                referenced.add(r["before_hash"])
        deleted = 0
        for hh_dir in BLOBS_ROOT.iterdir():
            if not hh_dir.is_dir():
                continue
            for blob in hh_dir.iterdir():
                if blob.is_file() and blob.name not in referenced:
                    try:
                        blob.unlink()
                        deleted += 1
                    except Exception:
                        pass
        return deleted

    async def ensure_ticket_start(
        self,
        project_id: str,
        ticket_id: str,
        *,
        agent_type: str = "Orchestrator",
        action: str = "process_ticket",
    ) -> Optional[str]:
        """工单首次进入处理时写 ticket_start 锚点（已有则复用）。"""
        if not project_id or not ticket_id:
            return None
        existing = await db.fetch_one(
            "SELECT id FROM checkpoints WHERE ticket_id=? AND trigger='ticket_start' "
            "ORDER BY created_at ASC LIMIT 1",
            (ticket_id,),
        )
        if existing:
            return existing["id"]
        cp_id = await self._insert_checkpoint(
            project_id, ticket_id,
            trigger="ticket_start",
            agent_type=agent_type,
            action=action,
            files=[],
            note="工单处理起点",
            emit_timeline=True,
        )
        return cp_id

    async def create_phase_boundary(
        self,
        project_id: str,
        ticket_id: str,
        *,
        agent_type: str = "",
        action: str = "",
        note: str = "",
    ) -> Optional[str]:
        """阶段完成后的可还原锚点（时间轴主展示）。"""
        if not project_id or not ticket_id:
            return None
        return await self._insert_checkpoint(
            project_id, ticket_id,
            trigger="phase_boundary",
            agent_type=agent_type,
            action=action,
            files=[],
            note=note or f"阶段边界 {agent_type}.{action}",
            emit_timeline=True,
        )

    async def capture_before_write(
        self,
        project_id: str,
        ticket_id: str,
        paths: List[str],
        *,
        repo_path: Optional[str] = None,
        agent_type: str = "",
        action: str = "",
    ) -> Optional[str]:
        """写盘前对即将改动的路径拍增量快照。"""
        if not project_id or not ticket_id or not paths:
            return None
        # 确保有锚点
        await self.ensure_ticket_start(project_id, ticket_id, agent_type=agent_type or "Agent", action=action or "write")

        repo = await self._resolve_repo_async(project_id, repo_path)
        if not repo:
            logger.debug("checkpoint skip: 无 repo_path project=%s", project_id[:12])
            return None

        file_rows = []
        seen: Set[str] = set()
        for raw in paths:
            rel = blob_store.normalize_rel_path(raw)
            if not rel or rel in seen:
                continue
            seen.add(rel)
            if blob_store.is_binary_ext(rel):
                file_rows.append({
                    "path": rel, "kind": "skipped", "before_hash": None,
                    "byte_size": 0, "skipped_reason": "binary_ext",
                })
                continue
            abs_p = repo.joinpath(*rel.split("/"))
            kind, before_hash, size, skip = blob_store.read_file_for_snapshot(abs_p)
            if kind == "skipped":
                file_rows.append({
                    "path": rel, "kind": "skipped", "before_hash": None,
                    "byte_size": size, "skipped_reason": skip,
                })
            elif kind == "created":
                file_rows.append({
                    "path": rel, "kind": "created", "before_hash": None,
                    "byte_size": 0, "skipped_reason": None,
                })
            else:
                file_rows.append({
                    "path": rel, "kind": "modified", "before_hash": before_hash,
                    "byte_size": size, "skipped_reason": None,
                })

        # 全是 skipped 也落一条，便于审计；无有效 path 则跳过
        useful = [f for f in file_rows if f["kind"] in ("created", "modified")]
        if not useful and not file_rows:
            return None

        return await self._insert_checkpoint(
            project_id, ticket_id,
            trigger="before_write",
            agent_type=agent_type,
            action=action,
            files=file_rows,
            note=f"写前快照 {len(useful)} 路径",
        )

    async def capture_from_active_context(self, paths: List[str]) -> Optional[str]:
        """供 git_manager 钩子：从 contextvars 取 ticket 再拍快照。"""
        ctx = get_checkpoint_context()
        pid = ctx.get("project_id") or ""
        tid = ctx.get("ticket_id") or ""
        if not pid or not tid:
            return None
        try:
            return await self.capture_before_write(
                pid, tid, paths,
                repo_path=ctx.get("repo_path") or None,
                agent_type=ctx.get("agent_type") or "",
                action=ctx.get("action") or "",
            )
        except Exception as e:
            logger.warning("capture_from_active_context 失败: %s", e, exc_info=True)
            return None

    async def list_checkpoints(self, ticket_id: str) -> List[Dict[str, Any]]:
        rows = await db.fetch_all(
            "SELECT * FROM checkpoints WHERE ticket_id=? ORDER BY created_at ASC",
            (ticket_id,),
        )
        out = []
        for r in rows or []:
            item = dict(r)
            files = await db.fetch_all(
                "SELECT path, kind, before_hash, byte_size, skipped_reason "
                "FROM checkpoint_files WHERE checkpoint_id=?",
                (r["id"],),
            )
            item["files"] = [dict(f) for f in (files or [])]
            item["file_count"] = len([f for f in item["files"] if f["kind"] in ("created", "modified")])
            out.append(item)
        return out

    async def get_checkpoint(self, checkpoint_id: str, ticket_id: str = "") -> Optional[Dict[str, Any]]:
        if ticket_id:
            row = await db.fetch_one(
                "SELECT * FROM checkpoints WHERE id=? AND ticket_id=?",
                (checkpoint_id, ticket_id),
            )
        else:
            row = await db.fetch_one("SELECT * FROM checkpoints WHERE id=?", (checkpoint_id,))
        if not row:
            return None
        item = dict(row)
        files = await db.fetch_all(
            "SELECT * FROM checkpoint_files WHERE checkpoint_id=?",
            (checkpoint_id,),
        )
        item["files"] = [dict(f) for f in (files or [])]
        return item

    async def preview_restore_to_start(self, ticket_id: str) -> Dict[str, Any]:
        """取消预览：相对 ticket_start 之后需还原的路径。"""
        start = await db.fetch_one(
            "SELECT id, created_at FROM checkpoints WHERE ticket_id=? AND trigger='ticket_start' "
            "ORDER BY created_at ASC LIMIT 1",
            (ticket_id,),
        )
        if not start:
            return {
                "strategy": "none",
                "has_checkpoint": False,
                "checkpoint_id": None,
                "files": [],
                "file_count": 0,
                "to_restore": [],
                "to_delete": [],
            }
        plan = await self._diff_plan_after(ticket_id, start["created_at"])
        plan["strategy"] = "checkpoint" if (plan["to_restore"] or plan["to_delete"]) else "checkpoint"
        plan["has_checkpoint"] = True
        plan["checkpoint_id"] = start["id"]
        plan["files"] = sorted(set(plan["to_restore"] + plan["to_delete"]))
        plan["file_count"] = len(plan["files"])
        return plan

    async def restore_to_ticket_start(
        self,
        project_id: str,
        ticket_id: str,
        *,
        commit: bool = True,
        message: str = "",
    ) -> Dict[str, Any]:
        start = await db.fetch_one(
            "SELECT id, created_at FROM checkpoints WHERE ticket_id=? AND trigger='ticket_start' "
            "ORDER BY created_at ASC LIMIT 1",
            (ticket_id,),
        )
        if not start:
            return {"ok": False, "error": "无 ticket_start checkpoint", "strategy": "none"}
        return await self.restore_after_checkpoint(
            project_id, ticket_id, start["id"],
            commit=commit, message=message or f"[Operator] restore checkpoint (cancel) {ticket_id[-8:]}",
        )

    async def restore_after_checkpoint(
        self,
        project_id: str,
        ticket_id: str,
        checkpoint_id: str,
        *,
        commit: bool = True,
        message: str = "",
    ) -> Dict[str, Any]:
        """还原到指定 checkpoint 时刻：撤销其后所有 before_write 对文件的影响。"""
        cp = await self.get_checkpoint(checkpoint_id, ticket_id)
        if not cp:
            return {"ok": False, "error": "checkpoint 不存在"}

        plan = await self._diff_plan_after(ticket_id, cp["created_at"])
        repo = await self._resolve_repo_async(project_id, None)
        if not repo:
            return {"ok": False, "error": "仓库路径不可用", **plan}

        restored, deleted, skipped, errors = [], [], [], []
        # path -> earliest before state after cp
        for path, meta in plan["path_meta"].items():
            kind = meta["kind"]
            before_hash = meta.get("before_hash")
            abs_p = repo.joinpath(*path.split("/"))
            try:
                if kind == "created" or before_hash is None:
                    # 拍快照时不存在 → 删除现今文件/目录
                    if abs_p.exists():
                        if abs_p.is_dir():
                            import shutil
                            shutil.rmtree(abs_p)
                        else:
                            abs_p.unlink()
                        deleted.append(path)
                    else:
                        skipped.append(path)
                else:
                    data = blob_store.get_bytes(before_hash)
                    if data is None:
                        errors.append(f"{path}: blob 缺失 {before_hash[:12]}")
                        continue
                    abs_p.parent.mkdir(parents=True, exist_ok=True)
                    abs_p.write_bytes(data)
                    restored.append(path)
            except Exception as e:
                errors.append(f"{path}: {e}")

        commit_hash = None
        if commit and (restored or deleted):
            try:
                from git_manager import git_manager
                # 让 git 跟踪变更
                repo_dir = str(repo)
                for p in restored + deleted:
                    await git_manager._run_git(repo_dir, "add", "--", p)
                    if p in deleted:
                        await git_manager._run_git(repo_dir, "rm", "-rf", "--ignore-unmatch", "--", p)
                commit_hash = await git_manager.commit(
                    project_id,
                    message or f"[Operator] restore checkpoint {checkpoint_id[-8:]}",
                    author="Operator",
                )
            except Exception as e:
                errors.append(f"commit: {e}")

        ok = not errors or bool(restored or deleted)
        return {
            "ok": ok,
            "strategy": "checkpoint",
            "checkpoint_id": checkpoint_id,
            "restored": restored,
            "deleted": deleted,
            "skipped": skipped,
            "errors": errors,
            "commit_hash": commit_hash,
            "files": sorted(set(restored + deleted)),
            "file_count": len(set(restored + deleted)),
        }

    async def _diff_plan_after(self, ticket_id: str, after_ts: str) -> Dict[str, Any]:
        """ticket_start 之后各 path 的「第一次改动前」状态。"""
        cps = await db.fetch_all(
            "SELECT id, created_at FROM checkpoints WHERE ticket_id=? AND created_at>? "
            "AND trigger='before_write' ORDER BY created_at ASC",
            (ticket_id, after_ts),
        )
        path_meta: Dict[str, Dict[str, Any]] = {}
        for c in cps or []:
            files = await db.fetch_all(
                "SELECT path, kind, before_hash FROM checkpoint_files WHERE checkpoint_id=?",
                (c["id"],),
            )
            for f in files or []:
                if f["kind"] == "skipped":
                    continue
                p = f["path"]
                if p not in path_meta:
                    path_meta[p] = {
                        "kind": f["kind"],
                        "before_hash": f["before_hash"],
                    }
        to_delete = [p for p, m in path_meta.items() if m["kind"] == "created" or m["before_hash"] is None]
        to_restore = [p for p, m in path_meta.items() if m["kind"] == "modified" and m["before_hash"]]
        return {
            "to_restore": to_restore,
            "to_delete": to_delete,
            "path_meta": path_meta,
        }

    def _resolve_repo(self, project_id: str, repo_path: Optional[str]) -> Optional[Path]:
        if repo_path:
            p = Path(repo_path)
            if p.is_dir():
                return p.resolve()
        try:
            from git_manager import git_manager
            rp = git_manager._repo_path(project_id)
            if rp.exists():
                return rp.resolve()
        except Exception:
            pass
        return None

    async def _resolve_repo_async(self, project_id: str, repo_path: Optional[str] = None) -> Optional[Path]:
        p = self._resolve_repo(project_id, repo_path)
        if p:
            return p
        try:
            row = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id=?", (project_id,))
            if row and row.get("git_repo_path"):
                from git_manager import git_manager, PROJECTS_DIR
                custom = row["git_repo_path"]
                default_path = str(PROJECTS_DIR / project_id)
                if custom != default_path:
                    git_manager.set_project_path(project_id, custom)
                return self._resolve_repo(project_id, custom)
        except Exception:
            pass
        return None

    async def _insert_checkpoint(
        self,
        project_id: str,
        ticket_id: str,
        *,
        trigger: str,
        agent_type: str,
        action: str,
        files: List[Dict[str, Any]],
        note: str = "",
        emit_timeline: bool = False,
    ) -> str:
        cp_id = generate_id("CP")
        created = now_iso()
        await db.insert("checkpoints", {
            "id": cp_id,
            "project_id": project_id,
            "ticket_id": ticket_id,
            "trigger": trigger,
            "parent_id": None,
            "agent_type": agent_type or None,
            "action": action or None,
            "note": note or None,
            "created_at": created,
        })
        for f in files:
            await db.insert("checkpoint_files", {
                "id": generate_id("CPF"),
                "checkpoint_id": cp_id,
                "path": f["path"],
                "kind": f["kind"],
                "before_hash": f.get("before_hash"),
                "byte_size": f.get("byte_size") or 0,
                "skipped_reason": f.get("skipped_reason"),
            })
        if emit_timeline:
            await self._emit_timeline_log(
                project_id, ticket_id, cp_id, trigger, note,
                agent_type=agent_type, action=action,
                file_count=len([f for f in files if f.get("kind") in ("created", "modified")]),
                created_at=created,
            )
        return cp_id

    async def _emit_timeline_log(
        self,
        project_id: str,
        ticket_id: str,
        checkpoint_id: str,
        trigger: str,
        note: str,
        *,
        agent_type: str = "",
        action: str = "",
        file_count: int = 0,
        created_at: str = "",
    ) -> None:
        """把可还原锚点写入 ticket_logs，供进展时间轴展示。"""
        try:
            import json as _json
            req = await db.fetch_one("SELECT requirement_id FROM tickets WHERE id=?", (ticket_id,))
            trigger_label = {
                "ticket_start": "工单起点",
                "phase_boundary": "阶段边界",
                "before_write": "写前快照",
            }.get(trigger, trigger)
            msg = note or trigger_label
            if file_count:
                msg = f"{msg}（{file_count} 个文件）"
            await db.insert("ticket_logs", {
                "id": generate_id("LOG"),
                "ticket_id": ticket_id,
                "requirement_id": (req or {}).get("requirement_id"),
                "project_id": project_id,
                "agent_type": agent_type or "Orchestrator",
                "action": "checkpoint",
                "detail": _json.dumps({
                    "message": f"💾 Checkpoint · {trigger_label} — {msg}",
                    "checkpoint_id": checkpoint_id,
                    "trigger": trigger,
                    "restorable": trigger in ("ticket_start", "phase_boundary"),
                    "file_count": file_count,
                    "agent_type": agent_type,
                    "action": action,
                }, ensure_ascii=False),
                "level": "info",
                "layer": "harness",
                "created_at": created_at or now_iso(),
            })
        except Exception as e:
            logger.debug("checkpoint timeline log 跳过: %s", e)


checkpoint_service = CheckpointService()
