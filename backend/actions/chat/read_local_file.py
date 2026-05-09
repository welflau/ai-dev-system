"""
ReadLocalFileAction — 读取本地文件内容

供 ChatAssistant 动态加载 Skill 文档（SKILL.md）、项目配置等。
安全约束：只允许读白名单目录，禁止读凭证类文件。
"""
import logging
from pathlib import Path
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.read_local_file")

MAX_CONTENT_CHARS = 12000

# 文件名黑名单（不区分大小写）
_BLOCKED_NAMES = {
    ".env", ".env.local", ".env.production",
    "credentials", "secrets", "id_rsa", "id_ed25519",
}
_BLOCKED_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".cer"}

# 白名单目录（相对于 backend/ 或绝对路径前缀）
# 运行时动态构建，避免硬编码绝对路径
def _build_allowed_roots() -> list[Path]:
    backend_dir = Path(__file__).resolve().parent.parent.parent  # backend/
    return [
        backend_dir / "ue_plugins",
        backend_dir / "skills",
        backend_dir / "docs",
        backend_dir / "sop",
        backend_dir.parent / "docs",   # 项目 docs/
    ]


def _is_safe_path(path: Path) -> tuple[bool, str]:
    """返回 (是否安全, 拒绝原因)"""
    # 文件名黑名单
    name_lower = path.name.lower()
    if name_lower in _BLOCKED_NAMES:
        return False, f"禁止读取凭证/配置文件: {path.name}"
    if path.suffix.lower() in _BLOCKED_SUFFIXES:
        return False, f"禁止读取密钥文件类型: {path.suffix}"
    if "password" in name_lower or "secret" in name_lower or "token" in name_lower:
        return False, f"文件名包含敏感关键词: {path.name}"

    # 路径穿越检查
    try:
        resolved = path.resolve()
    except Exception:
        return False, "无效路径"

    allowed_roots = _build_allowed_roots()
    for root in allowed_roots:
        try:
            resolved.relative_to(root.resolve())
            return True, ""
        except ValueError:
            continue

    return False, f"路径不在允许的目录范围内（允许: ue_plugins/, skills/, docs/, sop/）"


class ReadLocalFileAction(ActionBase):

    @property
    def name(self) -> str:
        return "read_local_file"

    @property
    def description(self) -> str:
        return "读取本地文件内容（Skill 文档、配置文件等），超过限制会截断"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "读取本地文件内容。主要用于加载 Skill 文档（SKILL.md）让 AI 理解如何操作某个工具或系统。\n"
                "用户说『用这个 skill』或给出一个本地文件路径时调用。\n"
                "只能读取允许目录内的文件（ue_plugins、skills、docs 等），不能读取凭证或配置文件。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件的绝对路径，例如 F:\\...\\Skills\\unreal-actor-editing\\SKILL.md",
                    },
                },
                "required": ["path"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        raw_path = (context.get("path") or "").strip()
        if not raw_path:
            return ActionResult(success=False, error="path 不能为空")

        path = Path(raw_path)

        safe, reason = _is_safe_path(path)
        if not safe:
            return ActionResult(success=False, error=reason)

        if not path.exists():
            return ActionResult(success=False, error=f"文件不存在: {path}")

        if not path.is_file():
            return ActionResult(success=False, error=f"路径不是文件: {path}")

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning("读取文件失败: %s → %s", path, e)
            return ActionResult(success=False, error=f"读取失败: {e}")

        truncated = False
        if len(content) > MAX_CONTENT_CHARS:
            content = content[:MAX_CONTENT_CHARS] + f"\n\n[内容过长，已截断至 {MAX_CONTENT_CHARS} 字符]"
            truncated = True

        logger.info("read_local_file: %s (%d 字符%s)", path.name, len(content), ", 已截断" if truncated else "")
        return ActionResult(
            success=True,
            data={
                "path": str(path),
                "filename": path.name,
                "content": content,
                "truncated": truncated,
            },
            message=f"已读取 {path.name}（{len(content)} 字符）",
        )
