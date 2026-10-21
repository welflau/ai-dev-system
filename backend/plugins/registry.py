"""插件 Action 注册表。

SkillRunner 的 ``builtin_tools``、DevAgent / 自测 / CI 都通过 ``create_action``
取实例，不再各自 ``from actions.xxx import``。

解析顺序：
  1. 公共白名单：``write_file`` / ``read_file`` / ``shell`` / ``gen_image``
     （``gen_image:subdir`` 语法仍有效）
  2. skill 目录内 ``actions/*.py``（跟 SKILL.md 放一起的实现）
  3. ``backend/plugins/<id>/actions/*.py`` 扫描到的 ActionBase 子类

``mcp__...`` 由 executor 层处理，这里返回 None。
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import pkgutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from actions.base import ActionBase

logger = logging.getLogger("plugins.registry")

PLUGIN_ROOT = Path(__file__).resolve().parent

PUBLIC_TOOL_NAMES = frozenset({"write_file", "read_file", "shell", "gen_image"})

_plugin_classes: Dict[str, Type[ActionBase]] = {}
_discovered = False


def reset_discovery() -> None:
    """测试用：清扫描缓存，下次 ``create_action`` 会按当前 PLUGIN_ROOT 重扫。"""
    global _discovered, _plugin_classes
    _discovered = False
    _plugin_classes = {}


def iter_plugin_dirs() -> List[Path]:
    if not PLUGIN_ROOT.is_dir():
        return []
    return [
        d for d in sorted(PLUGIN_ROOT.iterdir())
        if d.is_dir() and not d.name.startswith(("_", "."))
    ]


def iter_plugin_skill_dirs() -> List[Path]:
    """``plugins/<id>/skills/<skill_id>/`` 目录（不一定含 SKILL.md）。"""
    dirs: List[Path] = []
    for plugin_dir in iter_plugin_dirs():
        skills = plugin_dir / "skills"
        if not skills.is_dir():
            continue
        try:
            dirs.extend(d for d in sorted(skills.iterdir()) if d.is_dir())
        except OSError as e:
            logger.warning("扫描插件 skill 目录失败 %s: %s", skills, e)
    return dirs


def _is_concrete_action(obj: Any) -> bool:
    try:
        if not isinstance(obj, type) or obj is ActionBase:
            return False
        if not issubclass(obj, ActionBase):
            return False
    except TypeError:
        return False
    abstracts = getattr(obj, "__abstractmethods__", None)
    return not abstracts


def _classes_from_module(mod: Any) -> Dict[str, Type[ActionBase]]:
    found: Dict[str, Type[ActionBase]] = {}
    for attr in vars(mod).values():
        if not _is_concrete_action(attr):
            continue
        try:
            name = attr().name
        except Exception as e:
            logger.warning("实例化 %s.%s 取 name 失败: %s",
                           getattr(mod, "__name__", "?"), getattr(attr, "__name__", "?"), e)
            continue
        if not name:
            continue
        found[name] = attr
    return found


def _load_actions_from_package(package_name: str) -> Dict[str, Type[ActionBase]]:
    found: Dict[str, Type[ActionBase]] = {}
    try:
        pkg = importlib.import_module(package_name)
    except Exception as e:
        logger.warning("导入插件包 %s 失败: %s", package_name, e)
        return found
    pkg_path = getattr(pkg, "__path__", None)
    if not pkg_path:
        return found
    for _finder, modname, ispkg in pkgutil.iter_modules(pkg_path):
        if ispkg or modname.startswith("_"):
            continue
        full = f"{package_name}.{modname}"
        try:
            mod = importlib.import_module(full)
        except Exception as e:
            logger.warning("导入插件 Action 模块 %s 失败: %s", full, e)
            continue
        for name, cls in _classes_from_module(mod).items():
            if name in found and found[name] is not cls:
                logger.warning("插件 Action 重名 %s: %s 覆盖 %s", name, cls, found[name])
            found[name] = cls
    return found


def _load_actions_from_dir(actions_dir: Path) -> Dict[str, Type[ActionBase]]:
    """加载 skill 目录内 ``actions/*.py``（不要求是 Python 包）。"""
    found: Dict[str, Type[ActionBase]] = {}
    if not actions_dir.is_dir():
        return found
    for py in sorted(actions_dir.glob("*.py")):
        if py.name.startswith("_"):
            continue
        key = str(py.resolve())
        mod_name = "_ads_skill_action_" + key.replace("\\", "/").replace("/", "_").replace(":", "_").replace(".", "_")
        spec = importlib.util.spec_from_file_location(mod_name, py)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            logger.warning("加载 skill 本地 Action %s 失败: %s", py, e)
            sys.modules.pop(mod_name, None)
            continue
        for name, cls in _classes_from_module(mod).items():
            found[name] = cls
    return found


def ensure_discovered() -> Dict[str, Type[ActionBase]]:
    global _discovered, _plugin_classes
    if _discovered:
        return _plugin_classes
    _discovered = True
    merged: Dict[str, Type[ActionBase]] = {}
    for plugin_dir in iter_plugin_dirs():
        if not (plugin_dir / "actions").is_dir():
            continue
        pkg = f"plugins.{plugin_dir.name}.actions"
        for name, cls in _load_actions_from_package(pkg).items():
            if name in merged and merged[name] is not cls:
                logger.warning("插件 Action 重名 %s（%s vs %s）", name, cls, merged[name])
            merged[name] = cls
    _plugin_classes = merged
    if merged:
        logger.info("🔌 插件 Action 已注册: %s", sorted(merged))
    return _plugin_classes


def available_action_names() -> List[str]:
    names = set(PUBLIC_TOOL_NAMES)
    names.update(ensure_discovered())
    return sorted(names)


def get_action_class(tool_name: str) -> Optional[Type[ActionBase]]:
    """按名字取 Action 类（给 Agent.action_classes 用）。公共白名单不在此表。"""
    if not tool_name or str(tool_name).startswith("mcp__"):
        return None
    return ensure_discovered().get(tool_name)


def require_action_class(tool_name: str) -> Type[ActionBase]:
    cls = get_action_class(tool_name)
    if cls is None:
        raise RuntimeError(f"{tool_name} 未注册（插件未加载）")
    return cls


def require_action(tool_name: str, **kwargs) -> ActionBase:
    action = create_action(tool_name, **kwargs)
    if action is None:
        raise RuntimeError(f"{tool_name} 未注册（插件未加载）")
    return action


def create_action(
    tool_name: str,
    *,
    skill_dir: Optional[Path] = None,
    allowed_exts: Any = None,
    write_mode: Optional[str] = None,
    subdir: Optional[str] = None,
) -> Optional[ActionBase]:
    """按 ``builtin_tools`` 名字实例化 Action。未知名字返回 None。"""
    if not tool_name or str(tool_name).startswith("mcp__"):
        return None

    extra_subdir = subdir or ""
    name = tool_name
    if tool_name.startswith("gen_image:"):
        name = "gen_image"
        extra_subdir = tool_name.split(":", 1)[1]

    if name == "write_file":
        from actions.write_file import WriteFileAction
        return WriteFileAction(
            allowed_exts=allowed_exts,
            write_mode=write_mode or "skill",
        )
    if name == "read_file":
        from actions.read_repo_file import ReadRepoFileAction
        return ReadRepoFileAction()
    if name == "shell":
        from actions.chat.shell_exec import ShellAction
        return ShellAction()
    if name == "gen_image":
        from actions.gen_image import GenImageAction
        return GenImageAction(subdir=extra_subdir)

    if skill_dir is not None:
        local = _load_actions_from_dir(Path(skill_dir) / "actions")
        cls = local.get(name)
        if cls is not None:
            return cls()

    cls = ensure_discovered().get(name)
    if cls is not None:
        return cls()
    logger.info("未注册的 builtin_tools 名: %s", tool_name)
    return None


def _read_plugin_manifest(plugin_dir: Path) -> Dict[str, Any]:
    raw: Dict[str, Any] = {}
    manifest = plugin_dir / "plugin.json"
    if manifest.is_file():
        try:
            loaded = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw = loaded
        except Exception as e:
            logger.warning("读 %s 失败: %s", manifest, e)
    rt = raw.get("required_traits")
    if rt is not None and not isinstance(rt, dict):
        rt = None
    return {
        "id": str(raw.get("id") or plugin_dir.name),
        "name": str(raw.get("name") or plugin_dir.name),
        "version": str(raw.get("version") or ""),
        "description": str(raw.get("description") or ""),
        "required_traits": rt,
        "path": str(plugin_dir),
    }


def _plugin_action_items(plugin_id: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for name, cls in sorted(_load_actions_from_package(f"plugins.{plugin_id}.actions").items()):
        try:
            desc = cls().description or ""
        except Exception:
            desc = ""
        items.append({
            "name": name,
            "description": desc,
            "available_for_traits": getattr(cls, "available_for_traits", None),
        })
    return items


def _plugin_skill_items(plugin_dir: Path) -> List[Dict[str, Any]]:
    skills_root = plugin_dir / "skills"
    if not skills_root.is_dir():
        return []
    items: List[Dict[str, Any]] = []
    try:
        from skills.loader import _parse_frontmatter
    except Exception:
        _parse_frontmatter = None
    try:
        dirs = sorted(d for d in skills_root.iterdir() if d.is_dir())
    except OSError:
        return []
    for d in dirs:
        md = d / "SKILL.md"
        if not md.is_file():
            continue
        stage_id = ""
        if _parse_frontmatter is not None:
            try:
                fm, _body = _parse_frontmatter(
                    md.read_text(encoding="utf-8", errors="replace")
                )
                wf = (fm or {}).get("x-workflow") or (fm or {}).get("x_workflow") or {}
                if isinstance(wf, dict):
                    stage_id = str(wf.get("stage_id") or "")
            except Exception:
                pass
        items.append({
            "id": d.name,
            "rel_path": f"skills/{d.name}/SKILL.md",
            "stage_id": stage_id,
        })
    return items


def list_ads_plugins(*, traits: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """扫 ``backend/plugins/*/plugin.json``，给「套件与插件」页用。"""
    from actions.base import _match_traits

    out: List[Dict[str, Any]] = []
    for plugin_dir in iter_plugin_dirs():
        if not (plugin_dir / "plugin.json").is_file():
            continue
        info = _read_plugin_manifest(plugin_dir)
        actions = _plugin_action_items(plugin_dir.name)
        skills = _plugin_skill_items(plugin_dir)
        info["counts"] = {"actions": len(actions), "skills": len(skills)}
        if traits is None:
            info["active"] = None
        else:
            info["active"] = _match_traits(info.get("required_traits"), set(traits))
        out.append(info)
    return out


def get_ads_plugin(plugin_id: str, *, traits: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    plugin_dir = PLUGIN_ROOT / plugin_id
    if not plugin_dir.is_dir() or not (plugin_dir / "plugin.json").is_file():
        return None
    from actions.base import _match_traits

    info = _read_plugin_manifest(plugin_dir)
    info["actions"] = _plugin_action_items(plugin_dir.name)
    info["skills"] = _plugin_skill_items(plugin_dir)
    info["counts"] = {
        "actions": len(info["actions"]),
        "skills": len(info["skills"]),
    }
    if traits is None:
        info["active"] = None
    else:
        info["active"] = _match_traits(info.get("required_traits"), set(traits))
    return info
