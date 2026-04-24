r"""
InstantiateUETemplateAction — 拷贝 UE 官方模板并按项目名 rename（v0.18 Phase A.5）

核心思想：UE 自带的 Templates/TP_* 是 Epic 官方验证必编过的 C++ 骨架。
让 LLM 在这个基础上改，比从零写 UE C++ 可靠 10 倍。

实现要点：
- 读模板的 Config/TemplateDefs.ini，按 Epic 官方规则做 folder/filename/content 替换
- 支持的 token：%TEMPLATENAME% / %TEMPLATENAME_UPPERCASE% / %TEMPLATENAME_LOWERCASE%
- 跳过 FoldersToIgnore / FilesToIgnore（Binaries / Build / Intermediate / TemplateDefs.ini 等）
- .uproject 单独处理（改名 + 更新 Modules[].Name）
- 对 cpp/h/ini/cs 文件做内容替换；其他文件（.uasset 等）原样拷贝

输入 context:
    engine_path         : UE 引擎根目录
    template_name       : 模板名（如 "TP_FirstPerson"）。未给则按 traits 从 ue_templates.yaml 挑
    project_traits      : list[str]，用于自动挑模板
    target_dir          : 目标仓库目录（一般 = git_manager._repo_path(project_id)）
    project_name        : 目标项目名（如 "MyFPS"），用于替换。建议用 ProjectName 而非带空格/中文
    allow_overwrite     : 默认 False；目标目录非空时拒绝
    copy_content_assets : 默认 True；拷贝 Content/ 下的 .uasset（模板的 BP/材质/网格）

输出 data:
    {
      "status": "success" | "error",
      "template": str,
      "project_name": str,
      "engine_path": str,
      "target_dir": str,
      "files_created": int,
      "files_skipped": int,
      "files": {rel_path: "(binary)" | "text content"},   # 仅文本文件回传内容
      "uproject_path": str,                                # 新 .uproject 的绝对路径
      "notes": [...],                                      # 用户可读的步骤摘要
    }

降级：找不到模板 / 目标非空 / 替换规则解析失败 → 返 status=error，orchestrator 已有 BLOCKED + 诊断链处理。
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from actions.base import ActionBase, ActionResult
from engines.ue_resolver import get_templates_dir, verify_engine

logger = logging.getLogger("actions.instantiate_ue_template")

_TEMPLATES_YAML = Path(__file__).resolve().parent.parent / "templates" / "ue_templates.yaml"


# ==================== trait → template 映射 ====================


def _match_traits(match_cfg: Optional[Dict], traits: Set[str]) -> bool:
    if not match_cfg:
        return True
    all_of = match_cfg.get("all_of") or []
    any_of = match_cfg.get("any_of") or []
    none_of = match_cfg.get("none_of") or []
    if all_of and not all(t in traits for t in all_of):
        return False
    if any_of and not any(t in traits for t in any_of):
        return False
    if none_of and any(t in traits for t in none_of):
        return False
    return True


def pick_template_by_traits(traits: List[str]) -> Optional[str]:
    """按 ue_templates.yaml 规则挑第一个匹配的模板（priority 降序）"""
    try:
        import yaml
    except ImportError:
        return None
    if not _TEMPLATES_YAML.exists():
        return None
    try:
        data = yaml.safe_load(_TEMPLATES_YAML.read_text(encoding="utf-8")) or {}
    except Exception:
        return None

    traits_set = set(traits or [])
    mappings = data.get("mappings") or []
    mappings_sorted = sorted(
        mappings,
        key=lambda m: int(m.get("priority", 50)),
        reverse=True,
    )
    for m in mappings_sorted:
        if _match_traits(m.get("match"), traits_set):
            return m.get("template")
    return None


# ==================== TemplateDefs.ini 解析 ====================


_RE_FOLDER_RENAME = re.compile(
    r'FolderRenames=\(From="([^"]+)",To="([^"]+)"\)'
)
_RE_FILENAME_REPL = re.compile(
    r'FilenameReplacements=\(Extensions=\(([^)]+)\),From="([^"]+)",To="([^"]+)"(?:,bCaseSensitive=(true|false))?\)'
)
_RE_CONTENT_REPL = re.compile(
    r'ReplacementsInFiles=\(Extensions=\(([^)]+)\),From="([^"]+)",To="([^"]+)"(?:,bCaseSensitive=(true|false))?\)'
)
_RE_SIMPLE_KV = re.compile(r'^([A-Za-z]+)=["]?([^"\r\n]+)["]?$')


def _parse_template_defs(ini_path: Path) -> Dict[str, Any]:
    """解析 TemplateDefs.ini 的 FoldersToIgnore / FilesToIgnore / FolderRenames /
    FilenameReplacements / ReplacementsInFiles。"""
    rules: Dict[str, Any] = {
        "folders_to_ignore": [],
        "files_to_ignore": [],
        "folder_renames": [],     # [(from, to), ...]
        "filename_replacements": [],  # [(exts, from, to, case_sensitive), ...]
        "content_replacements": [],   # 同上
    }
    if not ini_path.is_file():
        return rules

    for line in ini_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith(";") or line.startswith("#") or line.startswith("["):
            continue

        m = _RE_FOLDER_RENAME.match(line)
        if m:
            rules["folder_renames"].append((m.group(1), m.group(2)))
            continue

        m = _RE_FILENAME_REPL.match(line)
        if m:
            exts = tuple(e.strip().strip('"').lower() for e in m.group(1).split(","))
            cs = (m.group(4) or "").lower() == "true"
            rules["filename_replacements"].append((exts, m.group(2), m.group(3), cs))
            continue

        m = _RE_CONTENT_REPL.match(line)
        if m:
            exts = tuple(e.strip().strip('"').lower() for e in m.group(1).split(","))
            cs = (m.group(4) or "").lower() == "true"
            rules["content_replacements"].append((exts, m.group(2), m.group(3), cs))
            continue

        if line.startswith("FoldersToIgnore="):
            val = line.split("=", 1)[1].strip().strip('"')
            rules["folders_to_ignore"].append(val)
            continue

        if line.startswith("FilesToIgnore="):
            val = line.split("=", 1)[1].strip().strip('"')
            rules["files_to_ignore"].append(val)
            continue

    return rules


# ==================== 替换逻辑 ====================


def _compute_tokens(template_name: str, project_name: str) -> Dict[str, str]:
    """根据原模板名 + 目标项目名，算出 UE 官方约定的 3 种 token 替换"""
    return {
        "%TEMPLATENAME%": template_name,
        "%PROJECTNAME%": project_name,
        "%TEMPLATENAME_UPPERCASE%": template_name.upper(),
        "%PROJECTNAME_UPPERCASE%": project_name.upper(),
        "%TEMPLATENAME_LOWERCASE%": template_name.lower(),
        "%PROJECTNAME_LOWERCASE%": project_name.lower(),
    }


def _substitute_tokens(s: str, tokens: Dict[str, str]) -> str:
    """把规则里的 %XXX% 替换成实际值（先 UPPER/LOWER，后原样 —— 避免过早吃掉）"""
    result = s
    # 有序：specific 优先
    for key in (
        "%TEMPLATENAME_UPPERCASE%",
        "%PROJECTNAME_UPPERCASE%",
        "%TEMPLATENAME_LOWERCASE%",
        "%PROJECTNAME_LOWERCASE%",
        "%TEMPLATENAME%",
        "%PROJECTNAME%",
    ):
        result = result.replace(key, tokens.get(key, ""))
    return result


def _apply_filename_replacements(
    name: str, rules: List[tuple], tokens: Dict[str, str]
) -> str:
    """按 FilenameReplacements 规则改文件名或目录名。

    rules 里的 From/To 带 %TEMPLATENAME% / %PROJECTNAME% 等 token，先代入 tokens 算出实值，
    再对 name 做 replace。case_sensitive 控制是否大小写敏感。
    """
    current = name
    for exts, frm, to, cs in rules:
        frm_real = _substitute_tokens(frm, tokens)
        to_real = _substitute_tokens(to, tokens)
        if cs:
            current = current.replace(frm_real, to_real)
        else:
            current = _case_insensitive_replace(current, frm_real, to_real)
    return current


def _case_insensitive_replace(s: str, old: str, new: str) -> str:
    if not old:
        return s
    pattern = re.compile(re.escape(old), re.IGNORECASE)
    return pattern.sub(new, s)


def _apply_folder_renames(
    rel_path: Path, rules: List[Tuple[str, str]], tokens: Dict[str, str]
) -> Path:
    """对相对路径应用 FolderRenames 规则（一般是 Source/%TEMPLATENAME%* → Source/%PROJECTNAME%*）"""
    rel_posix = rel_path.as_posix()
    for frm, to in rules:
        frm_real = _substitute_tokens(frm, tokens)
        to_real = _substitute_tokens(to, tokens)
        # FolderRenames 是前缀匹配
        if rel_posix == frm_real or rel_posix.startswith(frm_real + "/"):
            rel_posix = to_real + rel_posix[len(frm_real):]
    return Path(rel_posix)


def _apply_content_replacements(
    content: str, ext: str, rules: List[tuple], tokens: Dict[str, str]
) -> str:
    """按 ReplacementsInFiles 对文件内容做替换"""
    ext_lc = ext.lstrip(".").lower()
    result = content
    for exts, frm, to, cs in rules:
        if ext_lc not in exts:
            continue
        frm_real = _substitute_tokens(frm, tokens)
        to_real = _substitute_tokens(to, tokens)
        if cs:
            result = result.replace(frm_real, to_real)
        else:
            result = _case_insensitive_replace(result, frm_real, to_real)
    return result


# ==================== 主 Action ====================


class InstantiateUETemplateAction(ActionBase):
    """拷贝 UE 官方模板 + 按项目名 rename，产出可编译骨架"""

    available_for_traits = {"any_of": ["engine:ue5", "engine:ue4"]}

    @property
    def name(self) -> str:
        return "instantiate_ue_template"

    @property
    def description(self) -> str:
        return "把 UE 官方模板拷贝到项目仓库并做项目名替换，产出可编译骨架"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        engine_path = context.get("engine_path") or context.get("ue_engine_path")
        template_name = context.get("template_name")
        target_dir = context.get("target_dir")
        project_name = context.get("project_name")
        allow_overwrite = bool(context.get("allow_overwrite", False))
        copy_content = bool(context.get("copy_content_assets", True))
        traits = context.get("project_traits") or context.get("traits") or []

        if not engine_path:
            return _err("缺 engine_path（用 UEEngineResolver 先解析）")
        engine_info = verify_engine(engine_path)
        if not engine_info.path or not engine_info.has_editor:
            return _err(
                "引擎验证失败或不完整（缺 UnrealEditor.exe）",
                detail={"engine": engine_info.to_dict()},
            )

        # 未指定模板 → 按 traits 自动挑
        if not template_name:
            picked = pick_template_by_traits(traits)
            if not picked:
                return _err(
                    "未指定 template_name 且按 traits 未能匹配到模板",
                    detail={"traits": list(traits)},
                )
            template_name = picked
            logger.info("按 traits %s 挑选模板: %s", traits, template_name)

        if not target_dir:
            return _err("缺 target_dir（项目仓库目录）")
        target = Path(target_dir)

        if not project_name:
            return _err("缺 project_name")
        if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", project_name):
            return _err(
                f"project_name '{project_name}' 非法（首字母 + 字母/数字/下划线）"
            )

        templates_dir = get_templates_dir(engine_path)
        if not templates_dir:
            return _err(f"引擎 {engine_path} 下没有 Templates/ 目录")

        src = templates_dir / template_name
        if not src.is_dir():
            return _err(
                f"模板 {template_name} 不存在: {src}",
                detail={"available": sorted(p.name for p in templates_dir.iterdir()
                                            if p.is_dir())[:30]},
            )

        # 目标目录 empty check
        target.mkdir(parents=True, exist_ok=True)
        existing = [p for p in target.iterdir() if p.name not in (".git",)]
        if existing and not allow_overwrite:
            return _err(
                f"目标目录非空：{target}（包含 {len(existing)} 个文件/目录，加 allow_overwrite=true 强制覆盖）",
                detail={"existing_top": [p.name for p in existing[:10]]},
            )

        # 解析 TemplateDefs.ini
        defs = _parse_template_defs(src / "Config" / "TemplateDefs.ini")
        logger.info(
            "TemplateDefs: ignore_folders=%d ignore_files=%d folder_renames=%d filename_repl=%d content_repl=%d",
            len(defs["folders_to_ignore"]),
            len(defs["files_to_ignore"]),
            len(defs["folder_renames"]),
            len(defs["filename_replacements"]),
            len(defs["content_replacements"]),
        )

        tokens = _compute_tokens(template_name, project_name)
        content_exts = set()
        for exts, *_ in defs["content_replacements"]:
            content_exts.update(exts)

        # 预计算 ignore list 的实际匹配字符串（含 token 代入）
        ignore_files = set()
        for pat in defs["files_to_ignore"]:
            ignore_files.add(_substitute_tokens(pat, tokens).replace("\\", "/"))
        ignore_folders = set(defs["folders_to_ignore"])

        # 扫描并拷贝
        files_created = 0
        files_skipped = 0
        files_map: Dict[str, str] = {}
        notes: List[str] = []

        for root, dirs, files in _walk(src):
            rel_root = Path(root).relative_to(src)

            # 跳过 ignore 的目录（就地 prune）
            dirs[:] = [d for d in dirs if d not in ignore_folders]

            for fname in files:
                src_file = Path(root) / fname
                rel = rel_root / fname
                rel_posix = rel.as_posix()

                # files_to_ignore
                if any(_match_ignore(rel_posix, pat) for pat in ignore_files):
                    files_skipped += 1
                    continue

                # Content/ 资产（.uasset/.umap 等）按 copy_content 开关
                if (not copy_content) and rel_posix.startswith("Content/"):
                    files_skipped += 1
                    continue

                # 算目标相对路径：先 FolderRenames，再 filename rename
                dest_rel = _apply_folder_renames(rel, defs["folder_renames"], tokens)
                ext = dest_rel.suffix.lower().lstrip(".")
                new_name = _apply_filename_replacements(
                    dest_rel.name, defs["filename_replacements"], tokens,
                )
                dest_rel = dest_rel.with_name(new_name)

                dest_abs = target / dest_rel
                dest_abs.parent.mkdir(parents=True, exist_ok=True)

                # 如果是可替换的文本扩展，读 → 替换内容 → 写
                if ext in content_exts or ext in {"cpp", "h", "ini", "cs", "txt", "md"}:
                    try:
                        text = src_file.read_text(encoding="utf-8-sig", errors="replace")
                    except Exception:
                        shutil.copy2(src_file, dest_abs)
                        files_created += 1
                        continue
                    new_text = _apply_content_replacements(
                        text, ext, defs["content_replacements"], tokens,
                    )
                    dest_abs.write_text(new_text, encoding="utf-8")
                    # 回传少量代码文件到 files_map 供后续日志/artifact 使用
                    if ext in ("h", "cpp", "cs") and len(new_text) < 8000:
                        files_map[dest_rel.as_posix()] = new_text
                else:
                    # 二进制 / 大文件原样拷
                    shutil.copy2(src_file, dest_abs)
                files_created += 1

        # 创建 .uproject（模板的 .uproject 在 FilesToIgnore 里，需要自己生成）
        # EngineAssociation 约定：官方 Launcher = "5.3" (Major.Minor)；
        #                         自编译 build = "{GUID}"（从 engine_info 里拿）
        assoc = engine_info.engine_association
        if not assoc:
            # 兜底：裁剪到 Major.Minor
            parts = (engine_info.version or "").split(".")
            assoc = ".".join(parts[:2]) if len(parts) >= 2 else (engine_info.version or "")
        uproject_abs = _write_uproject(target, project_name, assoc)
        notes.append(f"拷贝模板 {template_name} → {files_created} 文件（skip {files_skipped}）")
        notes.append(f"项目名替换: {template_name} → {project_name}")
        notes.append(f".uproject 已生成: {uproject_abs.name}")

        logger.info(
            "✔ 模板实例化完成: %s → %s (%d 文件)",
            template_name, project_name, files_created,
        )

        return ActionResult(
            success=True,
            data={
                "status": "success",
                "template": template_name,
                "project_name": project_name,
                "engine_path": engine_info.path,
                "engine_version": engine_info.version,
                "target_dir": str(target),
                "files_created": files_created,
                "files_skipped": files_skipped,
                "files": files_map,
                "uproject_path": str(uproject_abs),
                "notes": notes,
            },
            message=f"已基于 {template_name} 实例化 {project_name}（{files_created} 文件）",
        )


# ==================== helpers ====================


def _err(msg: str, detail: Optional[Dict] = None) -> ActionResult:
    data = {"status": "error", "message": msg}
    if detail:
        data.update(detail)
    return ActionResult(success=False, data=data, message=msg, error=msg)


def _walk(path: Path):
    """os.walk 的 Path 版"""
    import os
    for root, dirs, files in os.walk(path):
        yield root, dirs, files


def _match_ignore(rel_posix: str, pat: str) -> bool:
    """FilesToIgnore 的匹配：既支持完整路径也支持 basename"""
    pat = pat.replace("\\", "/")
    if rel_posix == pat:
        return True
    # 有的 pattern 是 %TEMPLATENAME%.uproject 这种不含路径
    if "/" not in pat and rel_posix.endswith("/" + pat):
        return True
    if "/" not in pat and rel_posix == pat:
        return True
    return False


def _write_uproject(target: Path, project_name: str, engine_assoc: str) -> Path:
    """写一份最小可工作的 .uproject。EngineAssociation 用引擎的 association 字段（如 "5.3"）"""
    up_abs = target / f"{project_name}.uproject"
    obj = {
        "FileVersion": 3,
        "EngineAssociation": engine_assoc or "",
        "Category": "",
        "Description": "",
        "Modules": [
            {
                "Name": project_name,
                "Type": "Runtime",
                "LoadingPhase": "Default",
                "AdditionalDependencies": ["Engine"],
            }
        ],
    }
    up_abs.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    return up_abs
