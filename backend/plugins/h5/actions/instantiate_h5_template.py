"""把插件内的 Phaser + Vite 脚手架拷到项目仓库。

不跑 npm install，不启 Vite。目标非空且未允许覆盖时拒绝。
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.instantiate_h5_template")

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE_DIR = _PLUGIN_ROOT / "templates" / "phaser-vite"
_SKIP_DIRS = {".git", "node_modules", "__pycache__"}
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def _err(msg: str, detail: Dict[str, Any] | None = None) -> ActionResult:
    data: Dict[str, Any] = {"status": "error", "message": msg}
    if detail:
        data.update(detail)
    return ActionResult(success=False, data=data, message=msg, error=msg)


def _tokens(project_name: str) -> Dict[str, str]:
    title = project_name.replace("-", " ").replace("_", " ").strip() or project_name
    return {
        "{{PROJECT_NAME}}": project_name.lower(),
        "{{PROJECT_TITLE}}": title,
    }


def _replace_tokens(text: str, tokens: Dict[str, str]) -> str:
    for key, val in tokens.items():
        text = text.replace(key, val)
    return text


class InstantiateH5TemplateAction(ActionBase):
    available_for_traits = {"any_of": ["framework:phaser"]}

    @property
    def name(self) -> str:
        return "instantiate_h5_template"

    @property
    def description(self) -> str:
        return "把 Phaser 3 + Vite + TypeScript 脚手架拷到仓库，替换项目名"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        target_dir = context.get("target_dir") or context.get("repo_path")
        project_name = (
            context.get("project_name")
            or context.get("name")
            or ""
        )
        allow_overwrite = bool(context.get("allow_overwrite", False))
        template_name = str(context.get("template_name") or "phaser-vite")

        if not target_dir:
            return _err("缺 target_dir / repo_path")
        target = Path(target_dir)
        if not project_name:
            project_name = target.name or "h5-game"
        if not _NAME_RE.match(project_name):
            return _err(
                f"project_name '{project_name}' 非法（首字母 + 字母/数字/_/-）"
            )

        src = _PLUGIN_ROOT / "templates" / template_name
        if not src.is_dir():
            return _err(
                f"模板 {template_name} 不存在: {src}",
                detail={"expected": str(_TEMPLATE_DIR)},
            )

        target.mkdir(parents=True, exist_ok=True)
        existing = [p for p in target.iterdir() if p.name not in (".git",)]
        if existing and not allow_overwrite:
            return _err(
                f"目标目录非空：{target}（{len(existing)} 项，加 allow_overwrite=true 强制覆盖）",
                detail={"existing_top": [p.name for p in existing[:10]]},
            )

        tokens = _tokens(project_name)
        files_created = 0
        files_map: Dict[str, str] = {}
        notes: List[str] = []

        for path in src.rglob("*"):
            if not path.is_file():
                continue
            if any(part in _SKIP_DIRS for part in path.relative_to(src).parts):
                continue
            rel = path.relative_to(src)
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                shutil.copy2(path, dest)
                files_created += 1
                continue
            new_text = _replace_tokens(text, tokens)
            dest.write_text(new_text, encoding="utf-8")
            if rel.suffix in {".ts", ".json", ".html", ".md"} and len(new_text) < 8000:
                files_map[rel.as_posix()] = new_text
            files_created += 1

        notes.append(f"拷贝模板 {template_name} → {files_created} 文件")
        notes.append("未执行 npm install；本地预览需自行安装依赖")
        logger.info("H5 脚手架已落地: %s → %s (%d 文件)", template_name, target, files_created)
        return ActionResult(
            success=True,
            data={
                "status": "success",
                "template": template_name,
                "project_name": project_name,
                "target_dir": str(target),
                "files_created": files_created,
                "files": files_map,
                "notes": notes,
            },
            message=f"已基于 {template_name} 实例化 {project_name}（{files_created} 文件）",
        )
