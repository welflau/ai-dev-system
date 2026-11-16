"""确定性 Web 脚手架 Action（不经 LLM）。

给「初始化项目脚手架与技术栈」类工单产出一套真实可运行的
Vite + TypeScript + Three.js 骨架，绕开 LLM 结构化输出不稳定与
write_code._fallback 的增量硬失败循环。

对齐 2026-09-20「防假成功六道闸门」的约束：
- notes 用 "[Scaffold]" 前缀，不是 "[降级]"；
- 产出 >= 7 个真实文件，不是 console.log 空壳；
- 只写模板列出的骨架文件，不碰仓库其它内容；
- 失败返回 success=False + _scaffold_failed，由 dev.py 走 blocked，不空转。

产物是覆盖式写入（脚手架工单是依赖图根节点、业务功能在后续工单里做），
重复执行幂等；第一轮降级留下的空壳 index.html 会被替换成真实入口。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.scaffold_web")

_TEMPLATE_DIR = Path(__file__).resolve().parent / "scaffold_templates" / "vite-three"
_NAME_TOKEN = "{{PROJECT_NAME}}"
_TITLE_TOKEN = "{{PROJECT_TITLE}}"


class ScaffoldWebAction(ActionBase):
    @property
    def name(self) -> str:
        return "scaffold_web"

    @property
    def description(self) -> str:
        return "确定性生成 Vite + TypeScript + Three.js 项目骨架（不经 LLM）"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        repo_path = context.get("repo_path")
        if not repo_path:
            return self._err("缺 repo_path，无法落地脚手架")
        if not _TEMPLATE_DIR.is_dir():
            return self._err(f"脚手架模板不存在: {_TEMPLATE_DIR}")

        project_name = str(
            context.get("project_name") or context.get("name") or
            Path(repo_path).name or "web-app"
        )
        title = project_name.replace("-", " ").replace("_", " ").strip() or project_name
        target = Path(repo_path)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return self._err(f"创建仓库目录失败: {e}")

        files: Dict[str, str] = {}
        for src in sorted(_TEMPLATE_DIR.rglob("*")):
            if not src.is_file():
                continue
            rel = src.relative_to(_TEMPLATE_DIR).as_posix()
            try:
                text = src.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                return self._err(f"读取模板文件失败 {rel}: {e}")
            text = (text.replace(_NAME_TOKEN, project_name.lower())
                        .replace(_TITLE_TOKEN, title))
            dest = target / rel
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
            except OSError as e:
                return self._err(f"写入骨架文件失败 {rel}: {e}")
            files[rel] = text

        if len(files) < 7:
            return self._err(f"骨架文件不足（{len(files)}），拒绝伪成功")

        logger.info("🧩 脚手架已落地 %s（%d 文件）", target, len(files))
        return ActionResult(
            success=True,
            files=files,
            data={
                "dev_result": {
                    "files": files,
                    "notes": "[Scaffold] Vite + TypeScript + Three.js 确定性骨架（无需 LLM）",
                },
                "estimated_hours": 2,
                "scaffold_files": len(files),
            },
            message=f"已落地 {len(files)} 个骨架文件（Vite + TypeScript + Three.js）",
        )

    @staticmethod
    def _err(msg: str) -> ActionResult:
        return ActionResult(
            success=False,
            data={"status": "error",
                  "dev_result": {"files": {}, "notes": msg},
                  "_scaffold_failed": True},
            message=msg,
            error=msg,
        )
