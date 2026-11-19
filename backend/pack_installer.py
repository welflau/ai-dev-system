"""
ConfigPack Installer — 把 CLI 配置 Pack 安装到项目目录或用户主目录

安装范围（scope）：
  project（默认）→ <project_path>/.{cli}/packs/<pack_name>/...  项目级，与用户自己的文件隔离
  user           → Path.home()/.{cli}/...                       用户级，写入各 CLI 原生自扫的顶层目录
                    （如 ~/.codebuddy/skills/<id>/SKILL.md），一次安装对本机所有项目/所有 CLI 后端生效

Pack 目录约定：
  shared/          → 同时安装到 pack.json 声明的所有 CLI
    rules.md       → claude: 追加到 CLAUDE.md；其余: rules/{pack}.md（自动补 frontmatter）
    rules/*.md     → 各 CLI: rules/ 目录直接 copy
    commands/*.md  → 各 CLI: commands/ 目录直接 copy
    skills/*.md    → 各 CLI: skills/ 目录直接 copy
    agents/*.md    → 各 CLI: agents/ 目录直接 copy
    scripts/       → 各 CLI: scripts/ 目录直接 copy
    mcps/*.json    → claude: merge 到 settings.json mcpServers；其余: mcps/ 直接 copy
    hooks/*.json   → claude: merge 到 settings.json hooks；其余: hooks/ 直接 copy
  claude/          → 仅安装到 .claude/（Claude Code 专有格式）
  codebuddy/       → 仅安装到 .codebuddy/（Codebuddy 专有格式）
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pack_installer")

_PACKS_DIR = Path(__file__).parent / "config_packs"

# 支持的 CLI 目标白名单。用户级安装会写入这些 CLI 各自的用户目录，
# 使 ADS 无论用哪个 CLI 后端都能原生扫到同一份 skill。
ALL_CLI_TARGETS = ("claude", "codebuddy", "cursor", "workbuddy")

# 模板变量白名单，只替换这些占位符
_TEMPLATE_VARS = {"project_name", "repo_path", "tech_stack", "git_remote"}

# traits → pack 名称映射
_TRAIT_PACK_MAP: Dict[str, List[str]] = {
    "engine:ue5":       ["ue5-dev", "ue5-prod-skills"],
    "engine:ue4":       ["ue5-dev", "ue5-prod-skills"],
    "engine:godot":     ["godot-dev"],
    "engine:unity":     ["unity-dev"],
    "platform:web":     ["web-dev"],
    "framework:react":  ["web-dev", "typescript-quality"],
    "framework:vue":    ["web-dev", "typescript-quality"],
    "lang:typescript":  ["typescript-quality"],
    "vcs:git":          ["git-workflow", "code-quality", "vibe-workflow"],
    "category:game":    ["game-dev", "git-workflow", "vibe-workflow"],
    "category:app":     ["git-workflow", "vibe-workflow", "ai-workflow"],
    "category:ai":      ["ai-workflow"],
    "category:content": ["content-creation"],
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
    traits = traits or []
    is_video = "category:video" in traits or "pipeline:video" in traits
    seen: set = set()
    result: List[str] = []
    for trait in traits:
        for pack_name in _TRAIT_PACK_MAP.get(trait, []):
            if is_video and pack_name == "web-dev":
                continue
            if pack_name not in seen:
                seen.add(pack_name)
                result.append(pack_name)
    return result


def score_pack(pack_meta: Dict, project_traits: List[str]) -> Dict:
    """计算单个 pack 对项目 traits 的符合率。

    Returns:
        {
            "match_score": 0.0~1.0,   # 命中率
            "matched_traits": [...],   # 命中的 trait 列表
            "is_recommended": bool,    # 是否推荐（score > 0）
        }
    """
    auto_traits: List[str] = pack_meta.get("auto_traits") or []
    if not auto_traits:
        return {"match_score": 0.0, "matched_traits": [], "is_recommended": False}

    project_trait_set = set(project_traits or [])
    matched = [t for t in auto_traits if t in project_trait_set]
    score = round(len(matched) / len(auto_traits), 2)
    return {
        "match_score": score,
        "matched_traits": matched,
        "is_recommended": score > 0,
    }


def _render_template(content: str, ctx: Dict[str, str]) -> str:
    """替换白名单变量，其余占位符原样保留（Codebuddy {{.系统变量}} 不受影响）。"""
    for key in _TEMPLATE_VARS:
        content = content.replace("{{" + key + "}}", ctx.get(key, ""))
    return content


def _detect_cli_targets(project_path: str, pack_targets: List[str]) -> List[str]:
    """按 pack.json targets 字段过滤到受支持的 CLI，目录不存在时自动创建。

    project_path 保留在签名里以兼容既有调用方；目标集合由 pack.json 声明，
    不再按「本机是否存在该 CLI 目录」做探测（用户级安装时目录本来就不存在）。
    """
    return [t for t in pack_targets if t in ALL_CLI_TARGETS]


def _append_to_main_md(dst: Path, pack_name: str, content: str) -> None:
    """将 Pack 规则追加到主记忆文件（CLAUDE.md 或 CODEBUDDY.md），section 幂等。"""
    section = f"\n\n## Pack: {pack_name}\n\n{content.strip()}\n"
    if dst.exists():
        existing = dst.read_text(encoding="utf-8")
        if f"## Pack: {pack_name}" in existing:
            return  # 已安装，跳过
        dst.write_text(existing + section, encoding="utf-8")
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content.strip() + "\n", encoding="utf-8")


# 保留旧名称作为别名，兼容现有调用
_append_to_claude_md = _append_to_main_md


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
    project_path: str = "",
    project_ctx: Optional[Dict[str, str]] = None,
    scope: str = "project",
) -> Dict[str, Any]:
    """
    将指定 Pack 安装到项目目录（scope="project"）或用户主目录（scope="user"）。

    scope="project"：写到 <project_path>/.{cli}/packs/<pack_name>/...，与用户自己的文件隔离。
    scope="user"   ：写到 Path.home()/.{cli}/... 的顶层目录（CLI 原生自扫位置），
                     一次安装对本机所有项目、所有 CLI 后端生效；此时 project_path 被忽略。

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
            "scope": "project" | "user",
            "install_root": str,
            "installed_targets": ["claude", "codebuddy", "cursor", "workbuddy"],
            "copied_files": [...],
            "skipped": [...],
            "errors": [...],
        }
    """
    if scope not in ("project", "user"):
        return {"success": False, "errors": [f"未知安装范围 scope={scope!r}，允许 project / user"]}
    if scope == "project" and not project_path:
        return {"success": False, "errors": ["项目级安装缺少 project_path"]}

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

    declared_targets = meta.get("targets", list(ALL_CLI_TARGETS))
    # 用户级安装的目的是「一次装好、任意 CLI 后端都能用」，因此强制覆盖全部 4 个 CLI，
    # 不受某个 Pack 自身声明不足（如旧 pack.json 只写了 claude/codebuddy）的限制。
    if scope == "user":
        declared_targets = list(ALL_CLI_TARGETS)
    targets = _detect_cli_targets(project_path, declared_targets)
    install_root = str(Path.home()) if scope == "user" else str(Path(project_path))

    installed_targets: List[str] = []
    skipped: List[str] = []
    errors: List[str] = []
    copied_files: List[str] = []  # 记录实际操作的文件，供日志展示

    def _install_files(src_dir: Path, dst_root: Path, target: str, is_shared: bool = False) -> None:
        """将 src_dir 下的文件安装到 dst_root，处理 copy/追加/merge 三种操作。

        shared/ 分发规则：
          rules.md       → claude: 追加到 CLAUDE.md；codebuddy: rules/{pack}.md（自动补 frontmatter）
          rules/*.md     → claude: .claude/rules/；codebuddy: .codebuddy/rules/（直接 copy）
          commands/      → 两端直接 copy
          skills/        → 两端直接 copy
          agents/        → 两端直接 copy
          scripts/       → 两端直接 copy
          mcps/*.json    → claude: merge 到 settings.json；codebuddy: .codebuddy/mcps/ 直接 copy
          hooks/*.json   → claude: merge 到 settings.json hooks 节；codebuddy: .codebuddy/hooks/ 直接 copy
        """
        try:
            dst_root.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(f".{target}/: 创建目录失败 ({e})")
            return
        for src_file in sorted(src_dir.rglob("*")):
            if src_file.is_dir():
                continue
            try:
                content = src_file.read_text(encoding="utf-8")
            except Exception as e:
                errors.append(f"{src_file.name}: 读取失败 ({e})")
                continue

            # 模板变量（{{project_name}} 等）是项目上下文；用户级安装没有项目，
            # 不做替换以免把占位符静默抹成空串，保留原文更可追溯。
            if scope == "project":
                content = _render_template(content, ctx)
            rel = src_file.relative_to(src_dir)
            parts = rel.parts  # e.g. ('mcps', 'ue-mcp.json') or ('rules.md',)

            # ── shared/rules.md（单文件规则） ──────────────────────────
            _prefix = "~/" if scope == "user" else ""
            if is_shared and src_file.name == "rules.md" and len(parts) == 1:
                if target == "claude":
                    dst = dst_root / "CLAUDE.md"
                    _append_to_main_md(dst, pack_name, content)
                    copied_files.append(f"{_prefix}.claude/CLAUDE.md [追加]")
                else:
                    dst = dst_root / "rules" / f"{pack_name}.md"
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if not content.startswith("---"):
                        content = (
                            f"---\nname: {pack_name}\n"
                            f"description: {meta.get('description', pack_name)}\n"
                            f"type: always\n---\n\n"
                        ) + content
                    dst.write_text(content, encoding="utf-8")
                    copied_files.append(f"{_prefix}.{target}/rules/{pack_name}.md")
                continue

            # ── shared/mcps/*.json ─────────────────────────────────────
            if is_shared and len(parts) >= 2 and parts[0] == "mcps" and src_file.suffix == ".json":
                if target == "claude":
                    # Claude Code 通过 settings.json 的 mcpServers 注册 MCP
                    settings_dst = dst_root / "settings.json"
                    try:
                        mcp_data = json.loads(content)
                        _merge_json(settings_dst, {"mcpServers": mcp_data})
                        copied_files.append(f"{_prefix}.claude/settings.json [merge mcpServers.{src_file.stem}]")
                    except Exception as e:
                        errors.append(f"mcps/{src_file.name}: JSON 解析失败 ({e})")
                else:
                    dst = dst_root / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_text(content, encoding="utf-8")
                    copied_files.append(f"{_prefix}.{target}/{rel}")
                continue

            # ── shared/hooks/*.json ────────────────────────────────────
            if is_shared and len(parts) >= 2 and parts[0] == "hooks" and src_file.suffix == ".json":
                if target == "claude":
                    # Claude Code hooks 在 settings.json 的 hooks 节
                    settings_dst = dst_root / "settings.json"
                    try:
                        hook_data = json.loads(content)
                        _merge_json(settings_dst, {"hooks": hook_data})
                        copied_files.append(f"{_prefix}.claude/settings.json [merge hooks]")
                    except Exception as e:
                        errors.append(f"hooks/{src_file.name}: JSON 解析失败 ({e})")
                else:
                    dst = dst_root / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_text(content, encoding="utf-8")
                    copied_files.append(f"{_prefix}.{target}/{rel}")
                continue

            # ── 其余文件（commands / skills / agents / scripts / rules/子目录）
            # project：装到 .{target}/packs/{pack_name}/ 子目录，与用户自己的文件分开
            # user   ：装到 .{target}/ 顶层原生目录（skills/、commands/ ...），
            #          这样 CodeBuddy / Claude / Cursor / WorkBuddy 才会原生自扫到
            if scope == "user":
                dst = dst_root / rel
                display = f"~/.{target}/{rel}"
            else:
                dst = dst_root / "packs" / pack_name / rel
                display = f".{target}/packs/{pack_name}/{rel}"

            if src_file.name in ("CLAUDE.md", "CODEBUDDY.md"):
                _append_to_main_md(dst, pack_name, content)
                copied_files.append(f"{display} [追加]")
            elif src_file.name in ("settings.json", "mcp.json"):
                _merge_json(dst, json.loads(content))
                copied_files.append(f"{display} [merge]")
            else:
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_text(content, encoding="utf-8")
                    copied_files.append(display)
                except Exception as e:
                    errors.append(f"{display}: 写入失败 ({e})")

    base_root = Path(install_root)

    # 1. 安装 shared/（安装到所有目标 CLI）
    shared_dir = pack_dir / "shared"
    if shared_dir.exists():
        for target in targets:
            dst_root = base_root / f".{target}"
            _install_files(shared_dir, dst_root, target, is_shared=True)
            if target not in installed_targets:
                installed_targets.append(target)

    # 2. 安装 CLI 特有目录（claude/ codebuddy/ cursor/ workbuddy/）
    for target in targets:
        src_dir = pack_dir / target
        if not src_dir.exists():
            if not shared_dir.exists():
                skipped.append(f"{target}: Pack 未提供该 CLI 的配置")
            continue
        dst_root = base_root / f".{target}"
        _install_files(src_dir, dst_root, target)
        if target not in installed_targets:
            installed_targets.append(target)

    success = len(installed_targets) > 0
    if errors:
        logger.warning("pack install %s partial errors: %s", pack_name, errors)
    if success:
        logger.info("pack '%s' -> %s  scope=%s targets=%s", pack_name, install_root, scope, installed_targets)

    return {
        "success": success,
        "pack_name": pack_name,
        "scope": scope,
        "install_root": install_root,
        "installed_targets": installed_targets,
        "copied_files": copied_files,
        "skipped": skipped,
        "errors": errors,
    }


def install_packs(
    pack_names: List[str],
    project_path: str = "",
    project_ctx: Optional[Dict[str, str]] = None,
    scope: str = "project",
) -> List[Dict[str, Any]]:
    """批量安装多个 Pack，返回每个 Pack 的安装结果列表。"""
    return [install_pack(name, project_path, project_ctx, scope) for name in pack_names]
