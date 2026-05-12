"""
BrowseMarketplaceAction — AI 助手浏览和安装 Marketplace Skill

支持系统级（安装到 use_skills/）和项目级（安装到 .Agent/skills/）两个作用域。
- 无 project_id：系统级，全局聊天可用
- 有 project_id：项目级
"""
import logging
import shutil
from pathlib import Path
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.browse_marketplace")

_MARKETPLACE_DIR = Path(__file__).parent.parent.parent / "skills" / "marketplace"
_USE_SKILLS_DIR  = Path(__file__).parent.parent.parent / "skills" / "use_skills"

_SKIP_PREFIXES = ("download_", ".")


def _iter_skills(base: Path):
    for skill_md in sorted(base.rglob("SKILL.md")):
        parts = skill_md.relative_to(base).parts
        if any(p.startswith(_SKIP_PREFIXES) for p in parts):
            continue
        yield skill_md.parent


def _find_skill(dir_name: str) -> Path | None:
    for sd in _iter_skills(_MARKETPLACE_DIR):
        if sd.name == dir_name:
            return sd
    return None


def _parse_meta(skill_md: Path) -> dict:
    try:
        import re as _re, yaml as _yaml
        text = skill_md.read_text(encoding="utf-8")
        m = _re.match(r"^---\s*\n(.*?)\n---\s*\n", text, _re.DOTALL)
        if m:
            fm = _yaml.safe_load(m.group(1)) or {}
            return {"name": fm.get("name") or skill_md.parent.name,
                    "description": (fm.get("description") or "")[:200]}
    except Exception:
        pass
    return {"name": skill_md.parent.name, "description": ""}


class BrowseMarketplaceAction(ActionBase):

    @property
    def name(self) -> str:
        return "browse_marketplace"

    @property
    def description(self) -> str:
        return "浏览/安装/卸载 Marketplace Skill（系统级或项目级）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "浏览 Skill 市场、安装或卸载 Skill。\n"
                "• action=list：列出市场中所有可用 Skill 及安装状态\n"
                "• action=install：安装指定 Skill（有项目则装到项目，否则装到系统）\n"
                "• action=uninstall：卸载已安装的 Skill\n"
                "用户说「看看有什么 Skill」「帮我安装 xxx」「卸载 yyy」时调用。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "install", "uninstall"],
                        "description": "list=浏览，install=安装，uninstall=卸载",
                    },
                    "dir_name": {
                        "type": "string",
                        "description": "Skill 目录名，action=install/uninstall 时必填",
                    },
                    "filter": {
                        "type": "string",
                        "description": "list 时的关键词过滤（可选）",
                    },
                },
                "required": ["action"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        action   = context.get("action", "list")
        dir_name = (context.get("dir_name") or "").strip()
        keyword  = (context.get("filter") or "").lower()
        project_id = context.get("project_id")

        if action == "list":
            return await self._list(project_id, keyword)
        elif action == "install":
            if not dir_name:
                return ActionResult(success=False, error="请指定要安装的 Skill 目录名（dir_name）")
            return await self._install(project_id, dir_name)
        elif action == "uninstall":
            if not dir_name:
                return ActionResult(success=False, error="请指定要卸载的 Skill 目录名（dir_name）")
            return await self._uninstall(project_id, dir_name)
        return ActionResult(success=False, error=f"未知 action: {action}")

    # ── list ──────────────────────────────────────────────

    async def _list(self, project_id, keyword) -> ActionResult:
        if not _MARKETPLACE_DIR.exists():
            return ActionResult(success=True, data={"type": "marketplace_list", "skills": []},
                                message="marketplace 目录不存在，请先把 Skill 文件夹放入 backend/skills/marketplace/")

        installed = await self._get_installed(project_id)

        skills = []
        for sd in _iter_skills(_MARKETPLACE_DIR):
            meta = _parse_meta(sd / "SKILL.md")
            name = meta["name"]
            desc = meta["description"]
            if keyword and keyword not in name.lower() and keyword not in desc.lower() and keyword not in sd.name.lower():
                continue
            skills.append({
                "dir_name": sd.name,
                "name": name,
                "description": desc[:120],
                "installed": sd.name in installed,
            })

        scope = "项目" if project_id else "系统"
        installed_cnt = sum(1 for s in skills if s["installed"])
        return ActionResult(
            success=True,
            data={"type": "marketplace_list", "skills": skills, "scope": scope},
            message=f"市场共 {len(skills)} 个 Skill，{scope}已安装 {installed_cnt} 个",
        )

    # ── install ───────────────────────────────────────────

    async def _install(self, project_id, dir_name) -> ActionResult:
        src = _find_skill(dir_name)
        if not src:
            return ActionResult(success=False, error=f"marketplace 中找不到 Skill: {dir_name}")

        dst_dir = await self._get_install_dir(project_id)
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / dir_name

        if dst.exists():
            scope = "项目" if project_id else "系统"
            skill_content = ""
            try:
                skill_content = (dst / "SKILL.md").read_text(encoding="utf-8").strip()
            except Exception:
                pass
            return ActionResult(
                success=True,
                data={"type": "skill_installed", "dir_name": dir_name, "already_installed": True,
                      "skill_content": skill_content},
                message=f"Skill「{dir_name}」已在{scope}中安装。以下是使用文档：",
            )

        shutil.copytree(str(src), str(dst))

        # 系统级安装需热重载
        if not project_id:
            from skills import skill_loader
            skill_loader.reload()

        # 安装后立即读取 SKILL.md 内容，让 AI 能马上使用
        skill_content = ""
        try:
            skill_content = (dst / "SKILL.md").read_text(encoding="utf-8").strip()
        except Exception:
            pass

        scope = "项目" if project_id else "系统"
        logger.info("browse_marketplace install: %s → %s (%s)", dir_name, dst, scope)
        msg = f"✅ 已安装 Skill「{dir_name}」到{scope}。以下是使用文档，请按文档说明操作："
        return ActionResult(
            success=True,
            data={"type": "skill_installed", "dir_name": dir_name, "scope": scope,
                  "skill_content": skill_content},
            message=msg,
        )

    # ── uninstall ─────────────────────────────────────────

    async def _uninstall(self, project_id, dir_name) -> ActionResult:
        dst_dir = await self._get_install_dir(project_id)
        dst = dst_dir / dir_name
        if not dst.exists():
            scope = "项目" if project_id else "系统"
            return ActionResult(success=False, error=f"{scope}中未安装 Skill: {dir_name}")

        shutil.rmtree(str(dst))

        if not project_id:
            from skills import skill_loader
            skill_loader.reload()

        scope = "项目" if project_id else "系统"
        logger.info("browse_marketplace uninstall: %s (%s)", dir_name, scope)
        return ActionResult(
            success=True,
            data={"type": "skill_uninstalled", "dir_name": dir_name, "scope": scope},
            message=f"已从{scope}移除 Skill「{dir_name}」",
        )

    # ── helpers ───────────────────────────────────────────

    async def _get_install_dir(self, project_id) -> Path:
        if not project_id:
            return _USE_SKILLS_DIR
        from actions.chat.load_skill import _get_project_agent_skills_dir
        return await _get_project_agent_skills_dir(project_id)

    async def _get_installed(self, project_id) -> set:
        install_dir = await self._get_install_dir(project_id)
        if install_dir.exists():
            return {p.name for p in install_dir.iterdir() if p.is_dir()}
        return set()
