"""
PluginScanner + /api/plugins + 各内容端点的 plugin 分组：行为测试
    python backend/_test_plugin_scanner.py

用临时目录造三种真实存在的目录布局，不依赖本机装了什么 —— 本机数据会变，
造出来的固定。另外跑一遍真实主目录做冒烟（只断言"不崩、数不倒挂"）。

钉住的关键行为：
  1. 「未登记」≠「已启用」。marketplace 目录是整仓克隆，本机扫到 344 个但
     enabledPlugins 里只有 23 个。默认把 344 当已装是最容易犯的错。
  2. enabledPlugins 必须按 Client 分表。同名插件在不同 Client 的状态独立。
  3. skill 计数只认一层。ardot 的 skills/<name>/func-rule/*/SKILL.md 是子文档，
     递归会把 7 个数成 10 个，而且卡片数字和列表长度会对不上。
  4. 需要 Client 凭证的远端 MCP 一律 enabled=False + needs_auth=True，
     否则 warmup 每个白等 20s 超时。
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import plugin_scanner as PS

_pass = _fail = 0


def check(name, cond, detail=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"[OK] {name}" + (f" -- {detail}" if detail else ""))
    else:
        _fail += 1
        print(f"[FAIL] {name}" + (f" -- {detail}" if detail else ""))


def _write(p: Path, content=""):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def build_fixture(home: Path):
    """造出三种真实布局 + 各种边角情况。"""
    # ── WorkBuddy：<mp>/<plugin>/<version>/ ───────────────────────────
    wb = home / ".workbuddy/plugins/cache/wb-mp"
    # 多版本，其中 2.0.0 带 .in_use（Client 正在用的）
    for v in ("1.0.0", "2.0.0", "3.0.0"):
        d = wb / "verplug" / v
        _write(d / ".workbuddy-plugin/plugin.json",
               json.dumps({"name": "verplug", "version": v}))
        _write(d / "skills/alpha/SKILL.md", "# alpha")
    _write(wb / "verplug/2.0.0/.in_use/12345", "")

    # 内容齐全的插件：验证各内容目录都数得到
    full = wb / "fullplug/9.9.9"
    _write(full / ".workbuddy-plugin/plugin.json", json.dumps({
        "name": "fullplug", "version": "9.9.9",
        "extensions": {"ai.workbuddy": {"display": {
            "name_zh": "全料插件", "description_zh": "样样都有"}}},
    }))
    # skills 里混入子文档和附属资料 —— 只该数 2 个（one / two）
    _write(full / "skills/one/SKILL.md", "# one")
    _write(full / "skills/one/references/notes.md", "# notes")
    _write(full / "skills/one/func-rule/sub/SKILL.md", "# sub doc")
    _write(full / "skills/two.md", "# two")
    _write(full / "commands/do.md", "# do")
    _write(full / "agents/bot.md", "# bot")
    _write(full / "rules/style.md", "# style")
    _write(full / "hooks/hooks.json", json.dumps({"hooks": {
        "PreToolUse": [{"matcher": "Skill", "hooks": [{"type": "command", "command": "node x.mjs"}]}],
        "SessionStart": [],        # 声明了但没绑命令 —— 不该算
    }}))
    _write(full / "mcp.json", json.dumps({"mcpServers": {
        "localsrv": {"command": "node", "args": ["s.js"]},
        "remotesrv": {"type": "streamable-http", "url": "https://x.woa.com/mcp"},
        "authedsrv": {"type": "streamable-http", "url": "https://y.woa.com/mcp",
                      "headers": {"Authorization": "Bearer t"}},
    }}))

    # 根目录直挂 SKILL.md（agent-browser 那种），且有个 README 不该被当 skill
    root_skill = wb / "rootskill/1.0.0"
    _write(root_skill / ".workbuddy-plugin/plugin.json", json.dumps({"name": "rootskill"}))
    _write(root_skill / "SKILL.md", "# root")
    _write(root_skill / "README.md", "# readme")

    # ── CodeBuddy：<mp>/plugins/<plugin>/ 和扁平 <mp>/<plugin>/ ────────
    cb = home / ".codebuddy/plugins/marketplaces"
    _write(cb / "cb-mp/plugins/nested/.codebuddy-plugin/plugin.json",
           json.dumps({"name": "nested", "version": "1.2.3"}))
    _write(cb / "cb-mp/plugins/nested/skills/n/SKILL.md", "# n")
    # 扁平布局
    _write(cb / "flat-mp/flatplug/.codebuddy-plugin/plugin.json", "")  # 0 字节 manifest 也合法
    _write(cb / "flat-mp/flatplug/mcp.json", json.dumps({"mcpServers": {"f": {"url": "https://f/mcp"}}}))
    # download_* 下载中转目录，要跳过
    _write(cb / "cb-mp/plugins/download_tmp123/.codebuddy-plugin/plugin.json", "{}")

    # ── Claude：external_plugins/ ─────────────────────────────────────
    cl = home / ".claude/plugins/marketplaces/cl-mp"
    _write(cl / "external_plugins/extplug/.claude-plugin/plugin.json",
           json.dumps({"name": "extplug", "version": "0.1.0"}))
    _write(cl / "external_plugins/extplug/commands/c.md", "# c")

    # ── settings.json：每个 Client 各自一份 enabledPlugins ────────────
    _write(home / ".workbuddy/settings.json", json.dumps({"enabledPlugins": {
        "fullplug@wb-mp": True,
        "verplug@wb-mp": True,
        "rootskill@wb-mp": False,     # 装了但关了
    }}))
    _write(home / ".codebuddy/settings.json", json.dumps({"enabledPlugins": {
        # nested 同名不同 Client 的对照：这里开着
        "nested@cb-mp": True,
    }}))
    # Claude 完全没有 enabledPlugins 键 —— extplug 应判为「未安装」
    _write(home / ".claude/settings.json", json.dumps({"permissions": {}}))


def test_scan(home: Path):
    plugins = PS.scan_plugins(home)
    by_key = {(p["cli"], p["key"]): p for p in plugins}

    check("三种布局都扫到了", len(plugins) >= 6, f"共 {len(plugins)} 个")
    check("download_* 中转目录被跳过",
          not any("download_" in p["name"] for p in plugins))

    # ── 版本选取 ───────────────────────────────────────────────────
    vp = by_key.get(("workbuddy", "verplug@wb-mp"))
    check("多版本只出现一次", vp is not None and
          sum(1 for p in plugins if p["key"] == "verplug@wb-mp") == 1)
    check("优先取 .in_use 标记的版本（而非名字最大的）",
          vp and vp["version"] == "2.0.0", vp and vp["version"])

    # ── 三态：未登记 ≠ 已启用 ──────────────────────────────────────
    ext = by_key.get(("claude", "extplug@cl-mp"))
    check("扫得到但未登记 → installed=False",
          ext is not None and ext["installed"] is False)
    check("未登记的 enabled=False（不能默认当开着）",
          ext is not None and ext["enabled"] is False)
    rs = by_key.get(("workbuddy", "rootskill@wb-mp"))
    check("登记为 false → installed=True / enabled=False",
          rs and rs["installed"] is True and rs["enabled"] is False)
    fp = by_key.get(("workbuddy", "fullplug@wb-mp"))
    check("登记为 true → 两者都 True",
          fp and fp["installed"] and fp["enabled"])

    # ── 按 Client 分表：同名插件状态独立 ───────────────────────────
    nested_cb = by_key.get(("codebuddy", "nested@cb-mp"))
    check("CodeBuddy 的 nested 已启用", nested_cb and nested_cb["enabled"])
    check("Claude 没写 enabledPlugins 时不被别家的表污染",
          ext is not None and not ext["installed"])

    # ── 内容计数 ───────────────────────────────────────────────────
    c = fp["counts"] if fp else {}
    check("skills 只数一层入口（不递归子文档/附属资料）",
          c.get("skills") == 2, f"skills={c.get('skills')}，期望 2")
    check("commands / agents / rules 都数到", c.get("commands") == 1
          and c.get("agents") == 1 and c.get("rules") == 1, str(c))
    check("mcp 数到 3 个 server", c.get("mcp") == 3, str(c.get("mcp")))
    check("hooks 只数真有 binding 的", c.get("hooks") == 1, str(c.get("hooks")))

    rsk = by_key.get(("workbuddy", "rootskill@wb-mp"))
    check("根目录直挂 SKILL.md 算 1 个 skill",
          rsk and rsk["counts"].get("skills") == 1, str(rsk and rsk["counts"]))

    # ── manifest 边角 ──────────────────────────────────────────────
    flat = by_key.get(("codebuddy", "flatplug@flat-mp"))
    check("0 字节 manifest 不影响识别（tapd-woa 真这样）", flat is not None)
    check("display_name 取中文名",
          fp and fp["display_name"] == "全料插件", fp and fp["display_name"])
    check("description 取中文描述",
          fp and fp["description"] == "样样都有")

    # ── iter_active_plugins ────────────────────────────────────────
    active = PS.iter_active_plugins(home)
    keys = {p["key"] for p in active}
    check("iter_active_plugins 只给 installed 且 enabled 的",
          keys == {"fullplug@wb-mp", "verplug@wb-mp", "nested@cb-mp"}, str(sorted(keys)))


def test_skill_files(home: Path):
    sd = home / ".workbuddy/plugins/cache/wb-mp/fullplug/9.9.9/skills"
    files = PS.iter_skill_files(sd)
    names = sorted(f.parent.name if f.name == "SKILL.md" else f.stem for f in files)
    check("iter_skill_files 只返回入口文件", names == ["one", "two"], str(names))
    check("不存在的目录返回空", PS.iter_skill_files(home / "nope") == [])


def test_mcp(home: Path):
    servers = PS.load_plugin_mcp_servers(home)
    check("只收已安装且已启用插件的 server",
          set(servers) == {"localsrv", "remotesrv", "authedsrv"}, str(sorted(servers)))
    check("stdio server 直接可用",
          servers["localsrv"]["enabled"] is True
          and servers["localsrv"]["_needs_auth"] is False)
    check("远端且无 headers → needs_auth=True 且不启用（免得 warmup 白等超时）",
          servers["remotesrv"]["_needs_auth"] is True
          and servers["remotesrv"]["enabled"] is False)
    check("自带 headers 的远端 server 可用",
          servers["authedsrv"]["_needs_auth"] is False
          and servers["authedsrv"]["enabled"] is True)
    check("带来源标记供前端归组",
          servers["localsrv"]["_source"] == "plugin:fullplug"
          and servers["localsrv"]["_plugin"] == "fullplug"
          and servers["localsrv"]["_marketplace"] == "wb-mp")

    # 未启用的插件（flatplug 在 CodeBuddy 表里没登记）不该贡献 server
    check("未安装插件的 server 不被采纳", "f" not in servers)


def test_transport_detect():
    from mcp_client import _detect_transport
    cases = [
        ({"type": "streamable-http", "url": "u"}, "http", "plugin 写法"),
        ({"type": "streamable_http", "url": "u"}, "http", "下划线变体"),
        ({"type": "http", "url": "u"}, "http", "Claude 写法"),
        ({"type": "sse", "url": "u"}, "sse", "已弃用但仍需支持"),
        ({"transport": "sse", "url": "u"}, "sse", "transport 字段名"),
        ({"type": "STDIO"}, "stdio", "大小写不敏感"),
        ({"command": "node"}, "stdio", "只有 command"),
        ({"url": "u"}, "http", "只有 url → 默认 http 不是 sse"),
        ({}, "stdio", "都没有 → 回落 stdio"),
    ]
    for cfg, want, why in cases:
        got = _detect_transport(cfg)
        check(f"transport 归一化：{why}", got == want, f"{cfg} → {got}，期望 {want}")


def test_describe_exc():
    from mcp_client import _describe_exc
    # http transport 的失败被 anyio TaskGroup 包成 ExceptionGroup，
    # 直接 str() 只会得到「unhandled errors in a TaskGroup」
    inner = ConnectionError("All connection attempts failed")
    grp = BaseExceptionGroup("unhandled errors in a TaskGroup", [inner])
    msg = _describe_exc(grp)
    check("ExceptionGroup 里的真实错误被挖出来",
          "All connection attempts failed" in msg and "TaskGroup" not in msg, msg)
    nested = BaseExceptionGroup("outer", [BaseExceptionGroup("mid", [inner])])
    check("嵌套 ExceptionGroup 也能挖到",
          "All connection attempts failed" in _describe_exc(nested))
    check("普通异常带上类型名", _describe_exc(ValueError("boom")) == "ValueError: boom")
    check("无 message 时只给类型名", _describe_exc(ValueError()) == "ValueError")


async def test_api(home: Path):
    import api.plugins as PL
    # scan_plugins 默认读真实 home，这里换成 fixture
    orig = PL.scan_plugins
    PL.scan_plugins = lambda *a, **k: orig(home)
    try:
        d = await PL.list_plugins()
        c = d["counts"]
        check("默认视图只给已安装的", c["shown"] == c["installed"], str(c))
        check("scanned > installed（市场可见 ≠ 已装）",
              c["scanned"] > c["installed"], str(c))
        check("enabled <= installed", c["enabled"] <= c["installed"], str(c))
        check("默认视图不含未安装的",
              all(p["installed"] for p in d["plugins"]))

        d_all = await PL.list_plugins(all=True)
        check("all=true 带上市场可见的",
              d_all["counts"]["shown"] == d_all["counts"]["scanned"],
              str(d_all["counts"]))
        check("分组带 cli 中文名",
              all(g["cli_label"] for g in d_all["groups"]))
        check("分组计数自洽",
              all(g["count"] == len(g["plugins"]) for g in d_all["groups"]))

        d_cli = await PL.list_plugins(all=True, cli="workbuddy")
        check("cli 过滤生效",
              all(p["cli"] == "workbuddy" for p in d_cli["plugins"])
              and d_cli["plugins"])

        det = await PL.plugin_detail("fullplug@wb-mp", cli="workbuddy")
        check("详情里 skills 列表长度 == 卡片数字",
              len(det["contents"]["skills"]) == det["counts"]["skills"] == 2,
              f'{len(det["contents"]["skills"])} vs {det["counts"]["skills"]}')
        check("详情列出 commands / agents / rules",
              {"commands", "agents", "rules"} <= set(det["contents"]))
        check("详情的 hook 事件只含真有 binding 的",
              det["hook_events"] == ["PreToolUse"], str(det["hook_events"]))
        check("MCP 明细标出 transport 和 needs_auth",
              {m["name"]: (m["transport"], m["needs_auth"]) for m in det["mcp_servers"]}
              == {"localsrv": ("stdio", False), "remotesrv": ("http", True),
                  "authedsrv": ("http", False)},
              str(det["mcp_servers"]))
        # 内网地址 / token 绝不能出前端
        blob = json.dumps(det, ensure_ascii=False)
        check("详情不泄露 url / headers / env",
              "woa.com" not in blob and "Bearer" not in blob
              and not any(k in m for m in det["mcp_servers"]
                          for k in ("url", "headers", "env")))

        try:
            await PL.plugin_detail("nope@nope")
            check("不存在的插件报 404", False, "没抛异常")
        except Exception as e:
            check("不存在的插件报 404", getattr(e, "status_code", None) == 404, repr(e))
    finally:
        PL.scan_plugins = orig


async def test_real_endpoints():
    """真实主目录 + 真实项目的冒烟：不断言具体数字，只要求自洽。"""
    from database import db
    import api.projects as P
    await db.connect()
    try:
        row = await db.fetch_one("SELECT id FROM projects LIMIT 1")
        if not row:
            print("[SKIP] 库里没有项目，跳过端点冒烟")
            return
        await _check_real_endpoints(row["id"], P)
    finally:
        await db.disconnect()   # aiosqlite 的后台线程不断开会吊住进程


async def _check_real_endpoints(pid, P):
    for label, fn in [("skills", P.get_project_skills_all),
                      ("commands", P.get_project_commands_all),
                      ("agents", P.get_project_agents_all),
                      ("rules", P.get_project_rules_all),
                      ("hooks", P.get_project_hooks_all),
                      ("mcp", P.get_project_mcp_all)]:
        r = await fn(pid)
        c = r["counts"]
        check(f"/{label}/all 有 plugin 分组和计数",
              "plugin" in r and "plugin" in c, str(sorted(c)))
        check(f"/{label}/all 的 plugin 计数与列表一致",
              c["plugin"] == len(r["plugin"]), f'{c["plugin"]} vs {len(r["plugin"])}')
        check(f"/{label}/all 的 plugin 条目 source 都是 plugin",
              all(i.get("source") == "plugin" for i in r["plugin"]))
        check(f"/{label}/all 的 plugin 条目都带 plugin_name（前端要按容器分组）",
              all(i.get("plugin_name") for i in r["plugin"]))
        check(f"/{label}/all 的 plugin 条目计入 all",
              all(i in r["all"] for i in r["plugin"]))

    # 真实数据里的一致性：卡片数字 vs 端点条目数
    import api.plugins as PL
    skills = await P.get_project_skills_all(pid)
    per_plugin = {}
    for s in skills["plugin"]:
        per_plugin[s["plugin_name"]] = per_plugin.get(s["plugin_name"], 0) + 1
    lst = await PL.list_plugins()
    bad = [(p["name"], p["counts"].get("skills", 0), per_plugin.get(p["name"], 0))
           for p in lst["plugins"]
           if p["enabled"] and p["counts"].get("skills", 0) != per_plugin.get(p["name"], 0)]
    check("真实数据：插件卡片的 skills 数 == Skills 面板里该插件的条目数",
          not bad, str(bad[:5]))

    mcp = await P.get_project_mcp_all(pid)
    leak = {k for m in mcp["all"] for k in ("headers", "env", "url") if k in m}
    check("真实数据：MCP 端点不返回 headers / env / url", not leak, str(leak))


def main():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        build_fixture(home)
        test_scan(home)
        test_skill_files(home)
        test_mcp(home)
        asyncio.run(test_api(home))
    test_transport_detect()
    test_describe_exc()
    asyncio.run(test_real_endpoints())

    print(f"\n{_pass} passed, {_fail} failed")
    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    main()
