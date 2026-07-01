"""
LoadSkillAction — 按需加载单个 Skill 全文到当前对话上下文

主动触发架构的核心：
  system prompt 只含 Skill 索引（名称+描述），AI 推理时按需调用此工具加载具体内容。
  每次调用对应一条思考日志「📚 加载 Skill: xxx」，完全可追踪。

输入：
  skill_id      Skill ID（来自索引表）
  reason        为什么需要这个 Skill（可选，帮助用户理解）

输出：
  type          "skill_loaded"
  skill_id      加载的 Skill ID
  name          Skill 显示名
  content       Skill 全文（注入到当前对话上下文）
  token_count   大约字符数
"""
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.load_skill")


class LoadSkillAction(ActionBase):

    @property
    def name(self) -> str:
        return "load_skill"

    @property
    def description(self) -> str:
        return "当需要特定领域的深度规范知识时，按需加载对应 Skill 文档到当前对话"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "按需加载 Skill 文档。当用户问题需要特定领域知识（如 UE C++ 规范、Git 工程化、"
                "编辑态控制等）时调用。不确定是否需要时可不调用，直接回答。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "skill_id": {
                        "type": "string",
                        "description": "Skill ID，从可用 Skill 索引表中选择",
                    },
                    "reason": {
                        "type": "string",
                        "description": "为什么需要这个 Skill（简短说明）",
                    },
                },
                "required": ["skill_id"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        from skills import skill_loader

        skill_id = (context.get("skill_id") or "").strip()
        reason = context.get("reason", "")
        project_id = context.get("project_id")

        if not skill_id:
            return ActionResult(success=False, error="skill_id 不能为空")

        # 验证 Skill 是否可用（全局库 + 项目自定义）
        available_ids = await _get_available_skill_ids(project_id)
        if skill_id not in available_ids:
            all_ids = list(skill_loader.skills.keys())
            return ActionResult(
                success=False,
                data={"type": "error", "message": f"Skill `{skill_id}` 不可用，可选：{available_ids}"},
                error=f"Skill `{skill_id}` 不在可用列表中",
            )

        # 加载 Skill 全文
        if skill_id.startswith("custom.") and project_id:
            content, name = await _load_custom_skill(skill_id, project_id)
        elif skill_id.startswith("agent.") and project_id:
            content, name = await _load_agent_skill(skill_id, project_id)
        else:
            content = skill_loader.get_skill_prompt(skill_id)
            cfg = skill_loader.skills.get(skill_id, {})
            name = cfg.get("name", skill_id)

        if not content:
            return ActionResult(
                success=False,
                data={"type": "error", "message": f"Skill `{skill_id}` 内容为空"},
                error="Skill 内容为空",
            )

        logger.info("📚 load_skill: %s (%s) reason=%s project=%s",
                    skill_id, name, reason[:60], project_id)

        return ActionResult(
            success=True,
            data={
                "type": "skill_loaded",
                "skill_id": skill_id,
                "name": name,
                "content": content,
                "token_estimate": len(content) // 4,  # 粗略估算
            },
            message=f"已加载 Skill：{name}",
        )


async def _get_available_skill_ids(project_id: str = None) -> list:
    """四层优先级获取可用 Skill ID 列表。

    Layer 1（基础）：skills.json enabled 字段
    Layer 2（全局覆盖）：global_skill_settings 表
    Layer 3（项目覆盖）：project_skills 表（项目级开关 + 自定义 Skill）
    Layer 4（项目本地）：{project_path}/.Agent/skills/ 目录（agent.* 前缀）
    """
    from skills import skill_loader
    from database import db

    enabled_map: dict = {
        sid: bool(cfg.get("enabled", True))
        for sid, cfg in skill_loader.skills.items()
    }

    try:
        global_rows = await db.fetch_all("SELECT skill_id, enabled FROM global_skill_settings")
        for r in global_rows:
            enabled_map[r["skill_id"]] = bool(r["enabled"])
    except Exception:
        pass

    if project_id:
        try:
            proj_rows = await db.fetch_all(
                "SELECT skill_id, enabled FROM project_skills WHERE project_id=?",
                (project_id,),
            )
            for r in proj_rows:
                enabled_map[r["skill_id"]] = bool(r["enabled"])
        except Exception:
            pass

        # Layer 4: 项目本地 Skill 目录（.ads / .Agent / .codebuddy / .claude）
        seen_names: set = set()
        for agent_dir in await _enum_project_skill_dirs(project_id):
            for skill_dir in agent_dir.iterdir():
                if (skill_dir.is_dir() and (skill_dir / "SKILL.md").exists()
                        and skill_dir.name not in seen_names):
                    seen_names.add(skill_dir.name)
                    enabled_map[f"agent.{skill_dir.name}"] = True

    return [sid for sid, enabled in enabled_map.items() if enabled]


async def _get_project_agent_skills_dir(project_id: str):
    """返回项目 Skills 的「写入」目录路径（install 用）。
    P2: 优先读 .ads/skills/，降级到 .Agent/skills/（向后兼容）。
    仅用于安装写入；「读取/枚举」请用 _enum_project_skill_dirs。
    """
    from pathlib import Path
    from database import db
    try:
        row = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id=?", (project_id,))
        if row and row.get("git_repo_path"):
            repo = Path(row["git_repo_path"])
            # P2: 优先 .ads/skills/
            ads_skills = repo / ".ads" / "skills"
            if ads_skills.exists():
                return ads_skills
            # 向后兼容 .Agent/skills/
            return repo / ".Agent" / "skills"
    except Exception:
        pass
    return Path(__file__).parent.parent.parent / "data" / "project_skills" / project_id / ".Agent" / "skills"


async def _enum_project_skill_dirs(project_id: str) -> list:
    """枚举项目所有 Skill「读取」目录（存在才返回，按优先级去重）。

    覆盖多套 CLI 约定：.ads/skills、.Agent/skills、.codebuddy/skills、.claude/skills。
    这样 .codebuddy/skills/ 里的 Skill（如 ue-py-run）也能被 agent.* 索引与加载。
    同时并入 extra_paths 里的项目路径。
    """
    from pathlib import Path
    from database import db
    import json as _json

    dirs: list = []
    repo_paths: list = []
    try:
        row = await db.fetch_one(
            "SELECT git_repo_path, extra_paths FROM projects WHERE id=?", (project_id,)
        )
        if row:
            if row.get("git_repo_path"):
                repo_paths.append(row["git_repo_path"])
            try:
                extra = _json.loads(row.get("extra_paths") or "[]")
                repo_paths += [
                    p["path"] for p in extra
                    if isinstance(p, dict) and p.get("path")
                ]
            except Exception:
                pass
    except Exception:
        pass

    for rp in repo_paths:
        base = Path(rp)
        for sub in (".ads/skills", ".Agent/skills", ".codebuddy/skills", ".claude/skills"):
            d = base / sub
            if d.exists() and d not in dirs:
                dirs.append(d)

    # 兜底：无仓库路径时的 data 目录
    if not repo_paths:
        fallback = (Path(__file__).parent.parent.parent / "data"
                    / "project_skills" / project_id / ".Agent" / "skills")
        if fallback.exists():
            dirs.append(fallback)
    return dirs


async def _load_agent_skill(skill_id: str, project_id: str):
    """加载项目本地 Skill 的 SKILL.md 内容。返回 (content, name)。

    在所有项目 Skill 目录（.ads / .Agent / .codebuddy / .claude）中按 dir_name 查找。
    """
    dir_name = skill_id.removeprefix("agent.")
    skill_md = None
    for agent_dir in await _enum_project_skill_dirs(project_id):
        candidate = agent_dir / dir_name / "SKILL.md"
        if candidate.exists():
            skill_md = candidate
            break
    if skill_md is None:
        return None, skill_id
    try:
        content = skill_md.read_text(encoding="utf-8").strip()
        # 从 frontmatter 取 name
        import re as _re
        m = _re.match(r"^---\s*\n(.*?)\n---\s*\n", content, _re.DOTALL)
        name = dir_name
        if m:
            try:
                import yaml as _yaml
                fm = _yaml.safe_load(m.group(1)) or {}
                name = fm.get("name", dir_name)
            except Exception:
                pass
        return content, name
    except Exception as e:
        logger.warning("load agent skill %s failed: %s", skill_id, e)
        return None, skill_id


async def _load_custom_skill(skill_id: str, project_id: str):
    """加载项目自定义 Skill 的内容和显示名。返回 (content, name)。"""
    from pathlib import Path
    try:
        from database import db
        row = await db.fetch_one(
            "SELECT custom_path, custom_name FROM project_skills WHERE project_id=? AND skill_id=? AND source='custom'",
            (project_id, skill_id),
        )
        if not row or not row["custom_path"]:
            return None, skill_id

        _BASE = Path(__file__).parent.parent.parent / "data" / "project_skills"
        skill_file = _BASE / row["custom_path"]
        if not skill_file.exists():
            logger.warning("自定义 Skill 文件不存在: %s", skill_file)
            return None, skill_id

        content = skill_file.read_text(encoding="utf-8").strip()
        name = row["custom_name"] or skill_id
        return content, name
    except Exception as e:
        logger.warning("加载自定义 Skill %s 失败: %s", skill_id, e)
        return None, skill_id
