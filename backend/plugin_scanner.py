"""
PluginScanner — 扫描各 AgentClient 已安装的 Plugin，把内容纳入 ADS

## Plugin 是什么

各 Client（WorkBuddy / CodeBuddy / Claude Code）的插件就是一个**版本化的分发容器**，
里面按约定目录放 skills / commands / agents / rules / hooks / mcp.json，
客户端启动时挂载。开关记在各自 settings.json 的 `enabledPlugins`。

和 ADS 自己的 ConfigPack（见 pack_installer.py）是同类东西 —— 都是内容容器，
但作用域不同：

  ConfigPack  项目级，安装进 <repo>/.codebuddy/packs/<name>/，ADS 可装可卸
  Plugin      机器级，留在用户主目录的 cache 里，ADS 只读

所以本模块**只扫描不安装**，更不去碰 Client 的凭证保险库
（~/.workbuddy/connectors/*/.credentials.v3.json 那套是 Client 的身份能力，
ADS 要接企业 MCP 应当自己走一遍 OAuth，而不是借用户给别人的授权）。

## 三种目录布局

各家不统一，`_iter_plugin_dirs` 逐一探测：

  WorkBuddy  ~/.workbuddy/plugins/cache/<marketplace>/<plugin>/<version>/
  CodeBuddy  ~/.codebuddy/plugins/marketplaces/<marketplace>/plugins/<plugin>/
             ~/.codebuddy/plugins/marketplaces/<marketplace>/<plugin>/        ← 无 plugins/ 层
  Claude     ~/.claude/plugins/marketplaces/<marketplace>/plugins/<plugin>/
             ~/.claude/plugins/marketplaces/<marketplace>/external_plugins/<plugin>/

manifest 文件名也三套：.codebuddy-plugin/ .workbuddy-plugin/ .claude-plugin/ 下的
plugin.json，且**允许为空**（tapd-woa 的 plugin.json 就是 0 字节，靠 mcp.json 工作）。
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("plugin_scanner")

# 各 Client 的插件根目录（相对用户主目录）+ 该层下是否还有 marketplace 一级
_PLUGIN_ROOTS = [
    (".workbuddy/plugins/cache",         "workbuddy"),
    (".codebuddy/plugins/marketplaces",  "codebuddy"),
    (".claude/plugins/marketplaces",     "claude"),
]

# manifest 目录名（按 Client 习惯排列，逐一探测）
_MANIFEST_DIRS = (".codebuddy-plugin", ".workbuddy-plugin", ".claude-plugin")

# 跳过的目录名前缀：download_* 是下载中转（CodeBuddy 那边有几百个），. 开头是元数据
_SKIP_PREFIXES = ("download_", ".")

# 非插件的辅助目录，不当 plugin 也不当 marketplace
_SKIP_NAMES = {"dist", "node_modules", "__pycache__"}

# 插件可能提供的内容目录 → ADS 里对应的内容类型
_CONTENT_DIRS = {
    "skills":    "skills",
    "commands":  "commands",
    "agents":    "agents",
    "rules":     "rules",
    "fragments": "fragments",   # interactionmode-* 用这个注入提示词分片
}


def _is_skipped(name: str) -> bool:
    return name.startswith(_SKIP_PREFIXES) or name in _SKIP_NAMES


def iter_skill_files(skills_dir: Path) -> List[Path]:
    """列出一个 skills/ 目录里真正可挂载的 skill 入口文件。

    只认两种形态：`skills/<name>/SKILL.md` 和平铺的 `skills/<name>.md`。

    刻意**不**递归。ardot 的 skills/ardot-design-core/ 下面还有
    func-rule/*/SKILL.md 和 references/*.md —— 前者是 SKILL.md 正文引用的
    子文档，后者是附属资料，各 Client 的 skill 发现也只看一层。递归会把
    ardot 的 7 个数成 10 个、sheetagent 的 2 个数成 10 个。

    统一出口，避免扫描/计数/明细三处各写一遍 glob 而算出不同的数。
    """
    if not skills_dir.is_dir():
        return []
    out: List[Path] = []
    try:
        for entry in sorted(skills_dir.iterdir()):
            if _is_skipped(entry.name):
                continue
            if entry.is_dir():
                f = entry / "SKILL.md"
                if f.exists():
                    out.append(f)
            elif entry.suffix == ".md" and entry.name != "SKILL.md":
                out.append(entry)
    except (PermissionError, OSError):
        pass
    return out


def _read_manifest(plugin_dir: Path) -> Dict[str, Any]:
    """读 plugin.json。三种 manifest 目录名都试，允许文件为空或损坏。"""
    for md in _MANIFEST_DIRS:
        f = plugin_dir / md / "plugin.json"
        if not f.exists():
            continue
        try:
            text = f.read_text(encoding="utf-8").strip()
            if not text:
                return {}        # 空 manifest 合法（tapd-woa）
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.debug("plugin.json 解析失败 %s: %s", f, e)
            return {}
    return {}


def _has_manifest(d: Path) -> bool:
    return any((d / md / "plugin.json").exists() for md in _MANIFEST_DIRS)


def _looks_like_plugin(d: Path) -> bool:
    """判定一个目录是不是插件本体（而非 marketplace 容器 / 版本中间层）。"""
    if _has_manifest(d):
        return True
    if (d / "mcp.json").exists() or (d / "SKILL.md").exists():
        return True
    return any((d / sub).is_dir() for sub in _CONTENT_DIRS)


def _pick_version(plugin_dir: Path) -> Optional[Path]:
    """WorkBuddy 的 <plugin>/<version>/ 布局里挑一个版本目录。

    优先取 .in_use/ 里有 pid 的（Client 正在用的那个），否则取名字排序最大的。
    interactionmode-* 那种 4 个版本全无 .in_use 的情况就落到后者。
    """
    versions = [d for d in plugin_dir.iterdir()
                if d.is_dir() and not _is_skipped(d.name)]
    if not versions:
        return None
    in_use = [d for d in versions
              if (d / ".in_use").is_dir() and any((d / ".in_use").iterdir())]
    pool = in_use or versions
    return sorted(pool, key=lambda d: d.name)[-1]


def _iter_plugin_dirs(mp_root: Path):
    """在一个 marketplace 根下找出所有 (plugin_name, plugin_dir, version)。

    三种布局混在同一个 marketplace 根下也能处理 —— 逐个候选目录判定，
    而不是先认定布局再套用。
    """
    try:
        candidates = sorted(mp_root.iterdir())
    except (PermissionError, OSError):
        return

    for cand in candidates:
        if not cand.is_dir() or _is_skipped(cand.name):
            continue

        # 布局 A：<mp>/plugins/<plugin>/ 或 <mp>/external_plugins/<plugin>/
        if cand.name in ("plugins", "external_plugins"):
            try:
                inner = sorted(cand.iterdir())
            except (PermissionError, OSError):
                continue
            for p in inner:
                if p.is_dir() and not _is_skipped(p.name) and _looks_like_plugin(p):
                    yield p.name, p, _read_manifest(p).get("version") or ""
            continue

        # 布局 B：<mp>/<plugin>/<version>/ —— 自己不像插件，但子目录像
        if not _looks_like_plugin(cand):
            vdir = _pick_version(cand)
            if vdir and _looks_like_plugin(vdir):
                yield cand.name, vdir, vdir.name
            continue

        # 布局 C：<mp>/<plugin>/ 扁平（CodeBuddy 的 tencent-internal 是这样）
        yield cand.name, cand, _read_manifest(cand).get("version") or ""


def _load_enabled_map(home: Path) -> Dict[str, Dict[str, bool]]:
    """读各 Client settings.json 的 enabledPlugins。

    返回 {cli: {"<plugin>@<marketplace>": bool}}。按 cli 分开存很关键 ——
    同名插件在不同 Client 里的启用状态是独立的（agent-browser 在 WorkBuddy
    开着、在 CodeBuddy 没装），合成一张表会互相污染。

    某个 Client 完全没有 enabledPlugins 键时返回 {}，调用方据此判定
    「该 Client 一个都没装」而不是「全都装了」。
    """
    per_cli: Dict[str, Dict[str, bool]] = {}
    for rel, cli in _PLUGIN_ROOTS:
        # ".workbuddy/plugins/cache" → ".workbuddy/settings.json"
        settings = home / rel.split("/")[0] / "settings.json"
        table: Dict[str, bool] = {}
        if settings.exists():
            try:
                data = json.loads(settings.read_text(encoding="utf-8"))
                ep = data.get("enabledPlugins")
                if isinstance(ep, dict):
                    table = {k: bool(v) for k, v in ep.items()}
            except Exception as e:
                logger.debug("读取 %s 失败: %s", settings, e)
        per_cli[cli] = table
    return per_cli


def _count_content(plugin_dir: Path) -> Dict[str, int]:
    """统计插件贡献了多少各类内容 —— 供「套件与插件」页展示。"""
    counts: Dict[str, int] = {}

    for sub, kind in _CONTENT_DIRS.items():
        d = plugin_dir / sub
        if not d.is_dir():
            continue
        try:
            n = len(iter_skill_files(d)) if kind == "skills" else len(list(d.rglob("*.md")))
        except (PermissionError, OSError):
            continue
        if n:
            counts[kind] = n

    # 插件根目录直挂 SKILL.md（agent-browser 是这样）
    if (plugin_dir / "SKILL.md").exists():
        counts["skills"] = counts.get("skills", 0) + 1

    # mcp.json 里的 server 数
    mcp_file = plugin_dir / "mcp.json"
    if mcp_file.exists():
        try:
            data = json.loads(mcp_file.read_text(encoding="utf-8"))
            servers = data.get("mcpServers") or {}
            if servers:
                counts["mcp"] = len(servers)
        except Exception:
            pass

    # hooks/hooks.json 里的事件绑定数
    hooks_dir = plugin_dir / "hooks"
    if hooks_dir.is_dir():
        n = 0
        try:
            for hf in hooks_dir.glob("*.json"):
                data = json.loads(hf.read_text(encoding="utf-8"))
                hooks_obj = data.get("hooks", data)
                if isinstance(hooks_obj, dict):
                    for bindings in hooks_obj.values():
                        if isinstance(bindings, list):
                            n += sum(len(b.get("hooks") or [])
                                     for b in bindings if isinstance(b, dict))
        except Exception:
            pass
        if n:
            counts["hooks"] = n

    return counts


def _display_name(manifest: Dict[str, Any], fallback: str) -> str:
    """取展示名。WorkBuddy 把中英文名塞在 extensions["ai.workbuddy"].display 里。"""
    ext = (manifest.get("extensions") or {}).get("ai.workbuddy") or {}
    disp = ext.get("display") or {}
    for key in ("name_zh", "name", "name_en"):
        val = disp.get(key)
        if val:
            return str(val)
    return str(manifest.get("name") or fallback)


def _description(manifest: Dict[str, Any]) -> str:
    ext = (manifest.get("extensions") or {}).get("ai.workbuddy") or {}
    disp = ext.get("display") or {}
    for key in ("description_zh", "description"):
        val = disp.get(key) or manifest.get(key)
        if val:
            return str(val)[:300]
    return str(manifest.get("description") or "")[:300]


def scan_plugins(home: Optional[Path] = None) -> List[Dict[str, Any]]:
    """扫描所有 Client 已安装的 Plugin。

    Returns:
        每条形如：
        {
            "name": "ardot", "display_name": "Ardot",
            "marketplace": "workbuddy-builtin", "cli": "workbuddy",
            "version": "5.7.0-wb...",
            "enabled": True,      # enabledPlugins 里记着 true
            "installed": True,    # enabledPlugins 里登记过（无论 true/false）
            "key": "ardot@workbuddy-builtin",
            "path": "C:/Users/.../ardot/5.7.0-.../",
            "description": "...", "counts": {"skills": 13, "mcp": 1},
        }

    注意 installed=False 的条目占大多数 —— marketplace 是整仓克隆，
    里面绝大部分插件用户从未安装，只是「市场里可见」。
    """
    home = home or Path.home()
    enabled_map = _load_enabled_map(home)
    results: List[Dict[str, Any]] = []
    seen: set = set()

    for rel, cli in _PLUGIN_ROOTS:
        root = home / rel
        if not root.is_dir():
            continue
        try:
            marketplaces = sorted(root.iterdir())
        except (PermissionError, OSError):
            continue

        for mp in marketplaces:
            if not mp.is_dir() or _is_skipped(mp.name):
                continue
            for pname, pdir, version in _iter_plugin_dirs(mp):
                key = f"{pname}@{mp.name}"
                dedup = (cli, key)
                if dedup in seen:
                    continue
                seen.add(dedup)

                manifest = _read_manifest(pdir)
                # 三态：True 已启用 / False 已禁用 / None 未登记
                #
                # 「未登记」不等于「已启用」。marketplace 目录是整个仓库克隆下来的
                # 目录树（Claude 官方市场 42 个、CodeBuddy 官方 206 个），绝大多数
                # 用户从未装过 —— 只有 enabledPlugins 里记了名字的才是真装了。
                # 本机实测：扫到 344 个，enabledPlugins 里只有 23 个。
                table = enabled_map.get(cli) or {}
                state = table.get(key)
                results.append({
                    "name": pname,
                    "display_name": _display_name(manifest, pname),
                    "marketplace": mp.name,
                    "cli": cli,
                    "version": str(manifest.get("version") or version or ""),
                    "enabled": bool(state),
                    # 可浏览但未安装 —— 前端据此把「市场里有」和「我装了」分开
                    "installed": state is not None,
                    "key": key,
                    "path": str(pdir).replace("\\", "/"),
                    "description": _description(manifest),
                    "counts": _count_content(pdir),
                })

    results.sort(key=lambda p: (p["cli"], p["marketplace"], p["name"]))
    logger.debug("扫描到 %d 个 Plugin", len(results))
    return results


def iter_active_plugins(home: Optional[Path] = None) -> List[Dict[str, Any]]:
    """只返回「真装了且开着」的插件 —— 各内容类型扫描的统一入口。

    scan_plugins 返回的是整个 marketplace 目录树（本机 344 个），绝大多数是
    别人仓库里的目录而非用户的选择。把内容纳入 ADS 时必须过掉这些，否则
    Skills 面板会凭空多出几百条用户根本没装的东西。
    """
    return [p for p in scan_plugins(home)
            if p.get("installed") and p.get("enabled")]


def load_plugin_mcp_servers(home: Optional[Path] = None,
                            enabled_only: bool = True) -> Dict[str, Any]:
    """收集 Plugin 提供的 MCP server 配置，供 mcp_client 合并。

    返回 {server_name: cfg}，cfg 带 `_source`（形如 "plugin:tapd-woa"）
    和 `_plugin` / `_marketplace` 供前端标来源。

    注意：企业 connector（tapd / iwiki / tencent-docs …）的端点虽然扫得到，
    但鉴权凭证在 Client 自己的加密保险库里，ADS 连上去多半是 401 —— 这是预期的，
    `_needs_auth` 标出来让前端能提示，而不是伪装成可用。
    """
    home = home or Path.home()
    result: Dict[str, Any] = {}

    for plugin in scan_plugins(home):
        # 未安装的（marketplace 里可见但用户没装）一律不接 —— 那是别人仓库里的
        # 目录，不是用户的选择
        if not plugin["installed"]:
            continue
        if enabled_only and not plugin["enabled"]:
            continue
        mcp_file = Path(plugin["path"]) / "mcp.json"
        if not mcp_file.exists():
            continue
        try:
            data = json.loads(mcp_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.debug("plugin mcp.json 解析失败 %s: %s", mcp_file, e)
            continue

        for name, cfg in (data.get("mcpServers") or {}).items():
            if not isinstance(cfg, dict) or name.startswith("_"):
                continue
            # 远端 server 且插件没自带 headers → 鉴权靠 Client 的凭证保险库，
            # ADS 没有那份授权，连上去就是 401。
            #
            # 这类一律 enabled=False：不是"用户关掉了"，而是 ADS 连不上，
            # 每次 warmup 花 20s 超时重试毫无意义。`_needs_auth` 传给前端，
            # 让面板显示真实原因（需在 Client 侧授权），而不是假装没启用。
            needs_auth = bool(cfg.get("url")) and not cfg.get("headers")
            result[name] = {
                **cfg,
                "enabled": not needs_auth,
                "_source": f"plugin:{plugin['name']}",
                "_plugin": plugin["name"],
                "_marketplace": plugin["marketplace"],
                "_needs_auth": needs_auth,
            }
    return result
