"""
WriteFileAction — 受限写文件工具（供 SkillRunner 里的 LLM 用来落盘产出）。

比让 LLM 用 shell 的 `echo >` 写文件可控得多：
  - 只允许写到 skill 声明的 outputs.root 目录下（context["_skill_output_root"]）
  - 扩展名白名单（默认 .md）
  - 自动去掉 LLM 偶尔加的 ```lang ... ``` 围栏（搬自原 _fill_openspec_4_artifacts 清洗逻辑）
  - 路径越界校验（relative_to）
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.write_file")

_DEFAULT_EXTS = {".md"}


def _strip_fences(md: str) -> str:
    """去掉 LLM 偶尔套的 ```lang ... ``` 围栏。"""
    s = (md or "").strip()
    if s.startswith("```"):
        nl = s.find("\n")
        if nl > 0:
            s = s[nl + 1:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3].rstrip()
    return s


class WriteFileAction(ActionBase):

    def __init__(self, allowed_exts: List[str] = None):
        self._exts = set(allowed_exts) if allowed_exts else set(_DEFAULT_EXTS)

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return ("把内容写入 skill 产出目录下的文件（如 proposal.md）。"
                "path 相对产出目录，只允许写声明的文件类型。")

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "相对产出目录的文件名，如 proposal.md"},
                    "content": {"type": "string", "description": "文件完整内容（纯文本/Markdown）"},
                },
                "required": ["path", "content"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        root_raw = context.get("_skill_output_root")
        if not root_raw:
            return ActionResult(success=False, error="缺少产出目录（_skill_output_root）")
        rel = (context.get("path") or "").strip().replace("\\", "/").lstrip("/")
        content = context.get("content")
        if not rel:
            return ActionResult(success=False, error="path 不能为空")
        if content is None:
            return ActionResult(success=False, error="content 不能为空")

        root = Path(root_raw).resolve()
        target = (root / rel).resolve()
        # 越界校验
        try:
            target.relative_to(root)
        except ValueError:
            return ActionResult(success=False, error=f"path 越界，只能写产出目录内: {rel}")
        # 扩展名白名单
        if target.suffix.lower() not in self._exts:
            return ActionResult(success=False,
                                error=f"不允许的文件类型 {target.suffix}，仅 {sorted(self._exts)}")

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            cleaned = _strip_fences(str(content))
            target.write_text(cleaned, encoding="utf-8")
            logger.info("[write_file] %s (%d 字节)", rel, len(cleaned))
            return ActionResult(
                success=True,
                data={"type": "write_file", "path": rel, "bytes": len(cleaned)},
                files={rel: cleaned},
                message=f"已写入 {rel}（{len(cleaned)} 字节）",
            )
        except Exception as e:
            logger.error("[write_file] 写 %s 失败: %s", rel, e)
            return ActionResult(success=False, error=f"写文件失败: {e}")
