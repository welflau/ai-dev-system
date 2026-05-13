"""
ManageSkillAction — AI 助手直接启用/禁用全局或项目 Skill

支持操作：
  enable  — 启用（写 global_skill_settings 或 project_skills）
  disable — 禁用
  status  — 查看当前开关状态（支持模糊匹配 skill_id 前缀）
"""
import json
import logging
from typing import Any, Dict, List

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.manage_skill")


class ManageSkillAction(ActionBase):

    @property
    def name(self) -> str:
        return "manage_skill"

    @property
    def description(self) -> str:
        return "启用或禁用 Skill（支持全局和项目级别）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "启用/禁用全局或项目 Skill，或查询当前开关状态。\n"
                "skill_ids 支持完整 ID 或前缀（如 'unreal-' 可批量操作所有 UE Skills）。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["enable", "disable", "status"],
                        "description": "操作类型：enable=开启 / disable=关闭 / status=查询状态",
                    },
                    "skill_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要操作的 skill_id 列表。支持前缀匹配（如 ['unreal-']）。",
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["global", "project"],
                        "description": "作用范围：global=全局（默认）/ project=当前项目",
                    },
                },
                "required": ["action"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        action  = (context.get("action") or "status").strip().lower()
        skill_ids: List[str] = context.get("skill_ids") or []
        scope   = (context.get("scope") or "global").strip().lower()
        project_id = context.get("project_id")

        from database import db
        from utils import now_iso
        from skills import skill_loader

        # ── 获取所有可用 skill_id ──────────────────────────────────────────
        all_info = skill_loader.get_all_skills_info()
        all_ids = list(all_info.keys())

        # ── 展开前缀匹配 ─────────────────────────────────────────────────
        def _expand(patterns):
            if not patterns:
                return []
            result = []
            for pat in patterns:
                matched = [sid for sid in all_ids if sid.startswith(pat) or sid == pat]
                result.extend(matched if matched else [pat])
            return list(dict.fromkeys(result))  # 去重保序

        # ── status 查询 ───────────────────────────────────────────────────
        if action == "status":
            targets = _expand(skill_ids) if skill_ids else all_ids
            # 读取全局覆盖
            rows = await db.fetch_all(
                "SELECT skill_id, enabled FROM global_skill_settings"
            )
            global_overrides = {r["skill_id"]: bool(r["enabled"]) for r in rows}

            results = []
            for sid in targets:
                info = all_info.get(sid, {})
                enabled_default = info.get("enabled", True)
                enabled_global = global_overrides.get(sid, enabled_default)

                if scope == "project" and project_id:
                    proj_row = await db.fetch_one(
                        "SELECT enabled FROM project_skills WHERE project_id=? AND skill_id=?",
                        (project_id, sid),
                    )
                    enabled_final = bool(proj_row["enabled"]) if proj_row else enabled_global
                else:
                    enabled_final = enabled_global

                results.append({
                    "skill_id": sid,
                    "name": info.get("name", sid),
                    "enabled": enabled_final,
                })

            enabled_list  = [r for r in results if r["enabled"]]
            disabled_list = [r for r in results if not r["enabled"]]

            lines = [f"共 {len(results)} 个 Skill（{scope} 级别）："]
            lines.append(f"✅ 已开启 {len(enabled_list)} 个：" + ", ".join(r["skill_id"] for r in enabled_list[:20]))
            if disabled_list:
                lines.append(f"❌ 已禁用 {len(disabled_list)} 个：" + ", ".join(r["skill_id"] for r in disabled_list[:20]))

            return ActionResult(
                success=True,
                message="\n".join(lines),
                data={"type": "skill_status", "skills": results, "scope": scope},
            )

        # ── enable / disable ─────────────────────────────────────────────
        if not skill_ids:
            return ActionResult(success=False, error="请提供要操作的 skill_ids 列表")

        targets = _expand(skill_ids)
        if not targets:
            return ActionResult(success=False, error=f"未找到匹配的 Skill：{skill_ids}")

        enabled_val = 1 if action == "enable" else 0
        now = now_iso()
        changed = []

        for sid in targets:
            try:
                if scope == "project" and project_id:
                    # 项目级：upsert project_skills
                    existing = await db.fetch_one(
                        "SELECT id FROM project_skills WHERE project_id=? AND skill_id=?",
                        (project_id, sid),
                    )
                    if existing:
                        await db.execute(
                            "UPDATE project_skills SET enabled=? WHERE project_id=? AND skill_id=?",
                            (enabled_val, project_id, sid),
                        )
                    else:
                        import uuid
                        await db.execute(
                            "INSERT INTO project_skills (id, project_id, skill_id, source, enabled, created_at) "
                            "VALUES (?, ?, ?, 'global', ?, ?)",
                            (str(uuid.uuid4()), project_id, sid, enabled_val, now),
                        )
                else:
                    # 全局：upsert global_skill_settings
                    await db.execute(
                        "INSERT INTO global_skill_settings (skill_id, enabled, updated_at) VALUES (?,?,?) "
                        "ON CONFLICT(skill_id) DO UPDATE SET enabled=?, updated_at=?",
                        (sid, enabled_val, now, enabled_val, now),
                    )
                changed.append(sid)
            except Exception as e:
                logger.warning("manage_skill %s %s 失败: %s", action, sid, e)

        verb = "开启" if action == "enable" else "禁用"
        scope_label = f"项目({project_id[:8]})" if scope == "project" and project_id else "全局"
        msg = f"已{verb} {len(changed)} 个 Skill（{scope_label}）：{', '.join(changed)}"
        logger.info("manage_skill: %s", msg)

        return ActionResult(
            success=True,
            message=msg,
            data={"type": "skill_managed", "action": action, "changed": changed, "scope": scope},
        )
