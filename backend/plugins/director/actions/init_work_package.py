"""创建 works/<slug>/ 作品工作包。幂等。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from actions.base import ActionBase, ActionResult
from plugins.director.work_package import package_dir, unique_slug, write_current_slug

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE = _PLUGIN_ROOT / "templates" / "work-package"

_DIRS = (
    "prompts",
    "refs/characters",
    "refs/scenes",
    "refs/continuity",
    "voices",
    "video",
    "archive",
)


class InitWorkPackageAction(ActionBase):
    available_for_traits = {"any_of": ["category:video", "pipeline:video"]}

    @property
    def name(self) -> str:
        return "init_work_package"

    @property
    def description(self) -> str:
        return "为当前片子创建 works/<slug>/ 工作包。已存在且非空则返回现有 slug，不覆盖。"

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "作品标题，用于生成 slug"},
                    "slug": {"type": "string", "description": "可选：指定 slug；已存在则复用"},
                },
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        repo = context.get("repo_path") or ""
        if not repo:
            return ActionResult(success=False, error="缺少 repo_path")
        title = str(context.get("title") or context.get("ticket_title") or "untitled")
        given = str(context.get("slug") or "").strip()
        slug = given or unique_slug(repo, title)
        dest = package_dir(repo, slug)
        created: List[str] = []
        dest.mkdir(parents=True, exist_ok=True)
        for rel in _DIRS:
            d = dest / rel
            d.mkdir(parents=True, exist_ok=True)
            keep = d / ".gitkeep"
            if not keep.exists():
                keep.write_text("", encoding="utf-8")
                created.append(str(keep.relative_to(Path(repo))))

        gitignore = dest / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(
                "video/*.mp4\narchive/**\n.ads-waiting-human.json\n.ads-image-blocked.json\n",
                encoding="utf-8",
            )
            created.append(f"works/{slug}/.gitignore")

        for name, body in (
            ("current-assets-manifest.md", "# 当前素材清单\n\n正式生成前只认本清单。\n"),
            ("generation-lock.md", "# 项目级生成锁\n\n- 分辨率：720p\n- 单片段最长：15 秒\n- 字幕：默认关闭\n"),
        ):
            p = dest / name
            if not p.exists():
                p.write_text(body, encoding="utf-8")
                created.append(f"works/{slug}/{name}")

        if _TEMPLATE.is_dir():
            for src in _TEMPLATE.rglob("*"):
                if not src.is_file():
                    continue
                rel = src.relative_to(_TEMPLATE)
                target = dest / rel
                if target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(src.read_bytes())
                created.append(f"works/{slug}/{rel.as_posix()}")

        write_current_slug(repo, slug)
        return ActionResult(
            success=True,
            data={
                "type": "init_work_package",
                "slug": slug,
                "path": str(dest),
                "created": created,
            },
            message=f"工作包就绪：works/{slug}/",
        )
