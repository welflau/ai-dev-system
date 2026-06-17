"""
ConfigPack Installer — 把 CLI 配置 Pack 安装到项目目录

支持 Claude Code (.claude/) 和 Codebuddy (.codebuddy/) 两种 CLI。
安装操作：
  - copy:   rules / agents / commands / skills（独立文件直接复制）
  - append: CLAUDE.md（多 Pack section 追加，幂等）
  - merge:  settings.json / mcp.json（只添加新 key，不覆盖已有）
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pack_installer")

_PACKS_DIR = Path(__file__).parent / "config_packs"

# 模板变量白名单，只替换这些占位符
_TEMPLATE_VARS = {"project_name", "repo_path", "tech_stack", "git_remote"}

# traits → pack 名称映射
_TRAIT_PACK_MAP: Dict[str, List[str]] = {
    "engine:ue5":           ["ue5-dev"],
    "engine:ue4":           ["ue5-dev"],
    "platform:web":         ["web-dev"],
    "framework:react":      ["web-dev", "typescript-quality"],
    "framework:vue":        ["web-dev", "typescript-quality"],
    "lang:typescript":      ["typescript-quality"],
    "vcs:git":              ["git-workflow", "code-quality"],
    "category:game":        ["git-workflow"],
    "category:app":         ["git-workflow"],
}


def list_packs() -> List[Dict[str, Any]]:
    """返回所有可用 Pack 的元数据列表。"""
    packs = []
    if not _PACKS_DIR.exists():
        return packs
    for pack_dir in sorted(_PACKS_DIR.iterdir()):
        meta_file = pack_dir / "pack.json"
        if pack_dir.is_dir() and meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                meta["_dir"] = str(pack_dir)
                packs.append(meta)
            except Exception as e:
                logger.warning("读取 pack.json 失败 %s: %s", pack_dir, e)
    return packs


def get_recommended_packs(traits: List[str]) -> List[str]:
    """根据 traits 返回推荐 pack 名称（去重、保序）。"""
    seen: set = set()
    result: List[str] = []
    for trait in (traits or []):
        for pack_name in _TRAIT_PACK_MAP.get(trait, []):
            if pack_name not in seen:
                seen.add(pack_name)
                result.append(pack_name)
    return result


def _render_template(content: str, ctx: Dict[str, str]) -> str:
    """替换白名单变量，其余占位符原样保留（Codebuddy {{.系统变量}} 不受影响）。"""
    for key in _TEMPLATE_VARS:
        content = content.replace("{{" + key + "}}", ctx.get(key, ""))
    return content


def _detect_cli_targets(project_path: str, pack_targets: List[str]) -> List[str]:
    """
    检测项目目录中已有哪些 CLI 配置目录。
    两个都不存在时，按 pack.json targets 字段声明的目标创建目录。
    """
    p = Path(project_path)
    targets = []
    if (p / ".claude").exists():
        targets.append("claude")
    if (p / ".codebuddy").exists():
        targets.append("codebuddy")
    if not targets:
        targets = [t for t in pack_targets if t in ("claude", "codebuddy")]
    return targets


def _append_to_claude_md(dst: Path, pack_name: str, content: str) -> None:
    """将 Pack 规则追加到 CLAUDE.md，section 标题保证幂等。"""
    section = f"\n\n## Pack: {pack_name}\n\n{content.strip()}\n"
    if dst.exists():
        existing = dst.read_text(encoding="utf-8")
        if f"## Pack: {pack_name}" in existing:
            return  # 已安装，跳过
        dst.write_text(existing + section, encoding="utf-8")
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content.strip() + "\n", encoding="utf-8")


def _merge_json(dst: Path, new_data: Dict) -> None:
    """深度 merge JSON：只往里加新 key，已有 key 保留原值。"""
    existing: Dict = {}
    if dst.exists():
        try:
            existing = json.loads(dst.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    def _deep_merge(base: dict, extra: dict) -> dict:
        for k, v in extra.items():
            if k not in base:
                base[k] = v
            elif isinstance(base[k], dict) and isinstance(v, dict):
                _deep_merge(base[k], v)
        return base

    merged = _deep_merge(existing, new_data)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")


def install_pack(
    pack_name: str,
    project_path: str,
    project_ctx: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    将指定 Pack 安装到 project_path 下的 .claude/ 和/或 .codebuddy/。

    project_ctx 示例：
        {
            "project_name": "我的游戏",
            "repo_path": "D:/Projects/MyGame",
            "tech_stack": "UE5 / C++",
            "git_remote": "https://github.com/org/my-game.git",
        }

    Returns:
        {
            "success": bool,
            "pack_name": str,
            "installed_targets": ["claude", "codebuddy"],
            "skipped": [...],
            "errors": [...],
        }
    """
    ctx = project_ctx or {}
    pack_dir = _PACKS_DIR / pack_name

    if not pack_dir.exists():
        return {"success": False, "errors": [f"Pack '{pack_name}' 不存在"]}

    meta_file = pack_dir / "pack.json"
    if not meta_file.exists():
        return {"success": False, "errors": [f"Pack '{pack_name}' 缺少 pack.json"]}

    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception as e:
        return {"success": False, "errors": [f"pack.json 解析失败: {e}"]}

    declared_targets = meta.get("targets", ["claude", "codebuddy"])
    targets = _detect_cli_targets(project_path, declared_targets)

    installed_targets: List[str] = []
    skipped: List[str] = []
    errors: List[str] = []

    for target in targets:
        src_dir = pack_dir / target
        if not src_dir.exists():
            skipped.append(f"{target}: Pack 未提供该 CLI 的配置")
            continue

        dst_root = Path(project_path) / f".{target}"
        dst_root.mkdir(parents=True, exist_ok=True)

        for src_file in sorted(src_dir.rglob("*")):
            if src_file.is_dir():
                continue

            try:
                content = src_file.read_text(encoding="utf-8")
            except Exception as e:
                errors.append(f"{src_file.name}: 读取失败 ({e})")
                continue

            content = _render_template(content, ctx)
            rel = src_file.relative_to(src_dir)
            dst = dst_root / rel

            try:
                if src_file.name == "CLAUDE.md":
                    _append_to_claude_md(dst, pack_name, content)
                elif src_file.name in ("settings.json", "mcp.json"):
                    _merge_json(dst, json.loads(content))
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_text(content, encoding="utf-8")
            except Exception as e:
                errors.append(f"{rel}: 安装失败 ({e})")
                continue

        installed_targets.append(target)

    success = len(installed_targets) > 0
    if errors:
        logger.warning("pack install %s partial errors: %s", pack_name, errors)
    if success:
        logger.info("pack '%s' -> %s  targets=%s", pack_name, project_path, installed_targets)

    return {
        "success": success,
        "pack_name": pack_name,
        "installed_targets": installed_targets,
        "skipped": skipped,
        "errors": errors,
    }


def install_packs(
    pack_names: List[str],
    project_path: str,
    project_ctx: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """批量安装多个 Pack，返回每个 Pack 的安装结果列表。"""
    return [install_pack(name, project_path, project_ctx) for name in pack_names]
