"""
Plugin 只读 API —— 暴露各 AgentClient 已安装的插件给「套件与插件」页

Plugin 和 ConfigPack 是同类东西（都是内容容器），但作用域不同：
ConfigPack 是项目级、ADS 可装可卸；Plugin 是机器级、ADS 只读。所以这个
router 不挂在 /api/projects/{id} 下 —— 插件跟看哪个项目无关。

端点：
- GET /api/plugins              列表（默认只给已安装的，?all=true 带上市场里可浏览的）
- GET /api/plugins/detail       单个插件的内容明细（skills/commands/agents/rules/hooks/mcp）

**只读**：没有 install / enable 端点，也永远不会有。插件的开关记在各 Client
自己的 settings.json 里，ADS 去改它等于替用户操作别人的客户端配置。
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from plugin_scanner import scan_plugins, iter_skill_files, _CONTENT_DIRS

router = APIRouter(prefix="/api/plugins", tags=["plugins"])
logger = logging.getLogger("api.plugins")

_CLI_LABELS = {
    "workbuddy": "WorkBuddy",
    "codebuddy": "CodeBuddy",
    "claude": "Claude Code",
}


@router.get("")
async def list_plugins(all: bool = False, cli: str = ""):
    """列出插件，按 Client → marketplace 分组。

    Args:
        all: 默认 False，只返回 enabledPlugins 里登记过的（本机 23 个）。
             True 则带上 marketplace 里可浏览但用户没装的（本机 344 个）——
             marketplace 是整仓克隆，那几百个目录不是用户的选择，默认不展示。
        cli: 只看某个 Client（workbuddy / codebuddy / claude）。
    """
    try:
        plugins = scan_plugins()
    except Exception as e:
        logger.warning("扫描 Plugin 失败: %s", e)
        raise HTTPException(500, f"扫描插件失败: {e}")

    if cli:
        plugins = [p for p in plugins if p["cli"] == cli]

    total_scanned = len(plugins)
    if not all:
        plugins = [p for p in plugins if p["installed"]]

    # 按 (cli, marketplace) 分组，保持 scan_plugins 已排好的顺序
    groups: List[Dict[str, Any]] = []
    index: Dict[tuple, Dict[str, Any]] = {}
    for p in plugins:
        key = (p["cli"], p["marketplace"])
        g = index.get(key)
        if g is None:
            g = {
                "cli": p["cli"],
                "cli_label": _CLI_LABELS.get(p["cli"], p["cli"]),
                "marketplace": p["marketplace"],
                "plugins": [],
            }
            index[key] = g
            groups.append(g)
        g["plugins"].append(p)

    for g in groups:
        g["count"] = len(g["plugins"])
        g["enabled_count"] = sum(1 for p in g["plugins"] if p["enabled"])

    installed = [p for p in plugins if p["installed"]]
    return {
        "groups": groups,
        "plugins": plugins,
        "counts": {
            # scanned 只在 all=true 时等于全量；默认视图下它是"过滤前"的数
            "scanned": total_scanned,
            "installed": len(installed),
            "enabled": sum(1 for p in installed if p["enabled"]),
            "shown": len(plugins),
        },
    }


def _list_md(d: Path, kind: str, limit: int = 200) -> List[Dict[str, str]]:
    """列一个内容目录下的条目（名字 + 相对路径），不读正文。

    skills 走 iter_skill_files —— 和 plugin_scanner 的计数用同一个判定，
    否则列表长度会和卡片上的数字对不上。
    """
    if not d.is_dir():
        return []
    out = []
    try:
        files = iter_skill_files(d) if kind == "skills" else sorted(d.rglob("*.md"))
        for f in files[:limit]:
            rel = f.relative_to(d)
            # <name>/SKILL.md 的展示名取目录名，平铺的 <name>.md 取文件名
            name = rel.parts[-2] if f.name == "SKILL.md" and len(rel.parts) > 1 else f.stem
            out.append({"name": name, "rel_path": str(rel).replace("\\", "/")})
    except (PermissionError, OSError):
        pass
    return out


@router.get("/detail")
async def plugin_detail(key: str, cli: str = ""):
    """单个插件的内容明细。

    Args:
        key: "<plugin>@<marketplace>"，即 scan_plugins 返回的 key。
        cli: 同名插件可能装在多个 Client 里（sheetagent 在 WorkBuddy 和
             CodeBuddy 各有一份），给了就精确到一个。
    """
    match = None
    for p in scan_plugins():
        if p["key"] != key:
            continue
        if cli and p["cli"] != cli:
            continue
        match = p
        break
    if not match:
        raise HTTPException(404, f"插件不存在: {key}")

    pdir = Path(match["path"])
    contents: Dict[str, List[Dict[str, str]]] = {}
    for sub, kind in _CONTENT_DIRS.items():
        items = _list_md(pdir / sub, kind)
        if items:
            contents.setdefault(kind, []).extend(items)
    if (pdir / "SKILL.md").exists():
        contents.setdefault("skills", []).append(
            {"name": match["name"], "rel_path": "SKILL.md"})

    # MCP：只给 server 名和 transport，**不返回 url / headers / env**
    # —— 那里面有企业内网地址和可能的 token
    mcp_servers = []
    mcp_file = pdir / "mcp.json"
    if mcp_file.exists():
        try:
            data = json.loads(mcp_file.read_text(encoding="utf-8"))
            from mcp_client import _detect_transport
            for name, cfg in (data.get("mcpServers") or {}).items():
                if not isinstance(cfg, dict) or name.startswith("_"):
                    continue
                transport = _detect_transport(cfg)
                mcp_servers.append({
                    "name": name,
                    "transport": transport,
                    # 远端且插件没自带 headers → 鉴权在 Client 的凭证保险库里，
                    # ADS 没有那份授权。前端据此提示"需在 Client 侧授权"
                    "needs_auth": bool(cfg.get("url")) and not cfg.get("headers"),
                })
        except Exception as e:
            logger.debug("解析 %s 失败: %s", mcp_file, e)

    # hook 事件名。sheetagent 的 hooks.json 里 SessionStart / UserPromptSubmit
    # 都是空数组 —— 声明了事件但没绑命令，列出来会让人以为挂了 3 个钩子。
    # 只收真有 binding 的。
    hooks = []
    hdir = pdir / "hooks"
    if hdir.is_dir():
        try:
            for hf in sorted(hdir.glob("*.json")):
                data = json.loads(hf.read_text(encoding="utf-8"))
                obj = data.get("hooks", data)
                if not isinstance(obj, dict):
                    continue
                for event, bindings in sorted(obj.items()):
                    # lintbot 的 hooks/ 下有 3 个 json，事件名重复，去重
                    if event in hooks:
                        continue
                    if isinstance(bindings, list) and any(
                            isinstance(b, dict) and b.get("hooks") for b in bindings):
                        hooks.append(event)
        except Exception:
            pass

    return {
        **match,
        "cli_label": _CLI_LABELS.get(match["cli"], match["cli"]),
        "contents": contents,
        "mcp_servers": mcp_servers,
        "hook_events": hooks,
    }
