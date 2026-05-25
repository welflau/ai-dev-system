"""
PendingSkillsManager — 管理 AI 自动提取的 Skill 草案

生命周期：draft → confirmed（写入 skills.json）| rejected
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pending_skills")

_SKILLS_BASE = Path(__file__).parent


class PendingSkillsManager:

    async def ensure_table(self) -> None:
        """建表（首次调用时执行）"""
        from database import db
        await db._db.execute("""
            CREATE TABLE IF NOT EXISTS pending_skills (
                id              TEXT PRIMARY KEY,
                project_id      TEXT,
                ticket_id       TEXT,
                agent_type      TEXT,
                name            TEXT NOT NULL,
                description     TEXT NOT NULL,
                inject_to       TEXT NOT NULL,
                traits_match    TEXT,
                prompt_content  TEXT NOT NULL,
                status          TEXT DEFAULT 'draft',
                source_summary  TEXT,
                created_at      TEXT DEFAULT (datetime('now')),
                confirmed_at    TEXT,
                confirmed_by    TEXT
            )
        """)
        await db._db.commit()

    async def add(
        self,
        ticket_id: str,
        project_id: str,
        agent_type: str,
        skill_draft: Dict[str, Any],
        source_summary: str = "",
    ) -> str:
        """新增草案，返回 skill_id。同名草案已存在时静默跳过。"""
        from database import db
        await self.ensure_table()

        name = skill_draft.get("name", "").strip()
        if not name:
            raise ValueError("skill_draft.name 不能为空")

        # 同名草案已存在（任意状态）→ 跳过
        existing = await db.fetch_one(
            "SELECT id FROM pending_skills WHERE name = ? AND project_id = ?",
            (name, project_id)
        )
        if existing:
            logger.info("Skill 草案已存在，跳过: %s", name)
            return existing["id"]

        skill_id = str(uuid.uuid4())[:8]
        await db._db.execute(
            """INSERT INTO pending_skills
               (id, project_id, ticket_id, agent_type, name, description,
                inject_to, traits_match, prompt_content, source_summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                skill_id, project_id, ticket_id, agent_type,
                name,
                skill_draft.get("description", ""),
                json.dumps(skill_draft.get("inject_to", ["DevAgent"]), ensure_ascii=False),
                json.dumps(skill_draft.get("traits_match")) if skill_draft.get("traits_match") else None,
                skill_draft.get("prompt_content", ""),
                source_summary,
            )
        )
        await db._db.commit()
        logger.info("✨ 新 Skill 草案已保存: %s (%s)", name, skill_id)
        return skill_id

    async def list_drafts(self, project_id: Optional[str] = None) -> List[Dict]:
        """列出草案（status=draft）"""
        from database import db
        await self.ensure_table()
        if project_id:
            rows = await db.fetch_all(
                "SELECT * FROM pending_skills WHERE status='draft' AND project_id=? ORDER BY created_at DESC",
                (project_id,)
            )
        else:
            rows = await db.fetch_all(
                "SELECT * FROM pending_skills WHERE status='draft' ORDER BY created_at DESC"
            )
        return [dict(r) for r in rows]

    async def count_pending(self, project_id: Optional[str] = None) -> int:
        """当前 draft 草案数量"""
        from database import db
        await self.ensure_table()
        if project_id:
            row = await db.fetch_one(
                "SELECT COUNT(*) as n FROM pending_skills WHERE status='draft' AND project_id=?",
                (project_id,)
            )
        else:
            row = await db.fetch_one(
                "SELECT COUNT(*) as n FROM pending_skills WHERE status='draft'"
            )
        return (row["n"] if row else 0)

    async def get(self, skill_id: str) -> Optional[Dict]:
        from database import db
        await self.ensure_table()
        row = await db.fetch_one("SELECT * FROM pending_skills WHERE id=?", (skill_id,))
        return dict(row) if row else None

    async def confirm(self, skill_id: str, confirmed_by: str = "user", edit_content: str = "") -> bool:
        """确认草案 → 写入 skills.json + 热重载"""
        from database import db
        await self.ensure_table()
        row = await db.fetch_one("SELECT * FROM pending_skills WHERE id=?", (skill_id,))
        if not row:
            return False

        prompt_content = edit_content.strip() if edit_content.strip() else row["prompt_content"]
        name = row["name"]

        # 写入 packs/<name>/prompt.md
        pack_dir = _SKILLS_BASE / "packs" / name
        pack_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = pack_dir / "prompt.md"
        prompt_file.write_text(prompt_content, encoding="utf-8")

        # 更新 skills.json
        skills_json_path = _SKILLS_BASE / "skills.json"
        try:
            cfg: Dict = json.loads(skills_json_path.read_text(encoding="utf-8")) if skills_json_path.exists() else {}
        except Exception:
            cfg = {}

        inject_to = json.loads(row["inject_to"]) if row["inject_to"] else ["DevAgent"]
        traits_match = json.loads(row["traits_match"]) if row["traits_match"] else None

        cfg[name] = {
            "name": row["description"],
            "description": row["description"],
            "prompt_file": f"packs/{name}/prompt.md",
            "inject_to": inject_to,
            "traits_match": traits_match,
            "priority": "medium",
            "enabled": True,
            "auto_generated": True,
            "source_ticket": row["ticket_id"],
        }
        skills_json_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

        # 热重载
        try:
            from skills import skill_loader
            skill_loader.reload()
            logger.info("🔄 SkillLoader 热重载完成")
        except Exception as e:
            logger.warning("SkillLoader 热重载失败: %s", e)

        # 更新状态
        await db._db.execute(
            "UPDATE pending_skills SET status='confirmed', confirmed_at=datetime('now'), confirmed_by=? WHERE id=?",
            (confirmed_by, skill_id)
        )
        await db._db.commit()
        logger.info("✅ Skill 草案已确认并写入: %s", name)
        return True

    async def reject(self, skill_id: str) -> bool:
        """拒绝草案"""
        from database import db
        await self.ensure_table()
        await db._db.execute(
            "UPDATE pending_skills SET status='rejected' WHERE id=?", (skill_id,)
        )
        await db._db.commit()
        logger.info("❌ Skill 草案已拒绝: %s", skill_id)
        return True


# 单例
pending_skills_manager = PendingSkillsManager()
