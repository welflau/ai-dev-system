#!/usr/bin/env python3
"""
aidcs — AI Dev System CLI

常用命令：
  aidcs start              启动后台服务
  aidcs stop               停止后台服务
  aidcs status             查看系统状态（处理中工单/Agent/指标）
  aidcs projects           列出所有项目
  aidcs req <project_id>   列出项目需求
  aidcs req new <project_id> "需求标题"   提交新需求
  aidcs pause <project_id>              批量暂停项目所有进行中需求
  aidcs search <query>     搜索策划知识库
  aidcs assets <query>     搜索美术资产库
  aidcs competitor <url>   触发竞品反拆分析
  aidcs logs <project_id>  查看最近操作日志
"""
import argparse
import io
import json
import os
import sys
import urllib.request
import urllib.error

# Windows 控制台强制 UTF-8 输出
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

API_BASE = os.environ.get("AIDCS_API", "http://localhost:8000/api")


def _get(path: str) -> dict:
    url = f"{API_BASE}{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"错误 {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"请求失败: {e}", file=sys.stderr)
        sys.exit(1)


def _post(path: str, body: dict) -> dict:
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"错误 {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"请求失败: {e}", file=sys.stderr)
        sys.exit(1)


# ── 命令实现 ──────────────────────────────────────────────

def cmd_status(_):
    """查看系统状态"""
    m = _get("/metrics")
    print(f"⚙️  处理中: {m['processing']}  |  🔄 异步任务: {m['asyncio_tasks']}"
          f"  |  💾 内存: {m['mem_mb']}MB  |  🗄️  DB: {m['db_ms']}ms")

    # 处理中的工单
    try:
        d = _get("/orchestrator/status")
        if d.get("processing_tickets"):
            print(f"\n进行中的工单：")
            for tid in d["processing_tickets"][:5]:
                print(f"  🎫 {tid}")
    except Exception:
        pass


def cmd_projects(_):
    """列出项目"""
    d = _get("/projects")
    projects = d.get("projects", [])
    if not projects:
        print("暂无项目")
        return
    print(f"{'ID':25}  {'名称':30}  状态")
    print("-" * 70)
    for p in projects:
        print(f"{p['id']:25}  {p['name'][:30]:30}  {p['status']}")


def cmd_req(args):
    """需求操作"""
    pid = args.project_id
    if not pid:
        print("请提供 project_id", file=sys.stderr)
        sys.exit(1)

    if args.new_title:
        # 提交新需求
        body = {"title": args.new_title, "description": "", "priority": "medium"}
        r = _post(f"/projects/{pid}/requirements", body)
        print(f"✅ 需求已提交: {r.get('id', '')} — {args.new_title}")
    else:
        # 列出需求
        d = _get(f"/projects/{pid}/requirements")
        reqs = d.get("requirements", [])
        if not reqs:
            print("暂无需求")
            return
        print(f"{'ID':25}  {'标题':40}  状态")
        print("-" * 80)
        for r in reqs:
            print(f"{r['id']:25}  {r['title'][:40]:40}  {r['status']}")


def cmd_pause(args):
    """批量暂停项目需求"""
    pid = args.project_id
    r = _post(f"/projects/{pid}/chat", {
        "message": "暂停所有进行中的需求",
        "history": [],
    })
    print(r.get("reply", "操作完成"))


def cmd_search(args):
    """搜索策划知识库"""
    q = " ".join(args.query)
    d = _get(f"/planning-knowledge?q={urllib.parse.quote(q)}&limit=5")
    rows = d.get("results", d.get("items", []))
    if not rows:
        print("未找到相关内容")
        return
    for r in rows:
        print(f"\n📄 {r.get('title', r.get('filename', ''))}")
        print(f"   {r.get('summary', '')[:120]}")


def cmd_assets(args):
    """搜索美术资产库"""
    q = " ".join(args.query)
    d = _get(f"/art-assets?q={urllib.parse.quote(q)}&limit=8")
    assets = d.get("assets", [])
    if not assets:
        print("未找到资产")
        return
    for a in assets:
        tags = ", ".join(a.get("tags", [])[:3]) if isinstance(a.get("tags"), list) else ""
        print(f"  🎨 {a['name'][:40]}  [{a['type']}]  {a['source']}  {tags}")


def cmd_competitor(args):
    """竞品反拆分析"""
    url = args.url
    print(f"🔍 正在分析: {url} ...")
    body = {"url": url, "focus": args.focus or "全面分析"}
    r = _post("/competitor-analysis", body)
    name = r.get("game_name", "竞品")
    print(f"\n✅ 分析完成：{name}")
    if r.get("saved_path"):
        print(f"📄 已保存到：{r['saved_path']}")
    report = r.get("report", "")
    if report:
        # 只打印前 30 行
        lines = report.strip().split("\n")
        print("\n" + "\n".join(lines[:30]))
        if len(lines) > 30:
            print(f"... (共 {len(lines)} 行，完整报告见 G_DesignKnowledge)")


def cmd_logs(args):
    """查看操作日志"""
    pid = args.project_id
    d = _get(f"/projects/{pid}/logs?limit=20")
    logs = d.get("logs", [])
    for l in logs:
        t = l.get("created_at", "")[:16]
        agent = l.get("agent_type", "?")[:15]
        msg = l.get("message", "")[:60]
        level = {"error": "❌", "warn": "⚠️", "info": "✅"}.get(l.get("level", "info"), "·")
        print(f"{t}  {agent:15}  {level} {msg}")


def cmd_start(_):
    """启动后台服务"""
    import subprocess, os
    backend = os.path.join(os.path.dirname(__file__))
    print("🚀 启动 AI Dev System 后台...")
    subprocess.Popen(
        [sys.executable, os.path.join(backend, "main.py")],
        cwd=backend,
        stdout=open(os.path.join(backend, "server.log"), "w"),
        stderr=subprocess.STDOUT,
    )
    print("后台已启动，日志: backend/server.log")
    print("访问: http://localhost:8000/app")


# ── 主入口 ────────────────────────────────────────────────

def main():
    import urllib.parse

    parser = argparse.ArgumentParser(
        prog="aidcs",
        description="AI Dev System CLI",
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("start",   help="启动后台服务")
    sub.add_parser("status",  help="查看系统状态")
    sub.add_parser("projects", help="列出所有项目")

    p_req = sub.add_parser("req", help="需求操作")
    p_req.add_argument("project_id", nargs="?", default="")
    p_req.add_argument("new_title", nargs="?", default="")

    p_pause = sub.add_parser("pause", help="批量暂停项目需求")
    p_pause.add_argument("project_id")

    p_search = sub.add_parser("search", help="搜索策划知识库")
    p_search.add_argument("query", nargs="+")

    p_assets = sub.add_parser("assets", help="搜索美术资产库")
    p_assets.add_argument("query", nargs="+")

    p_comp = sub.add_parser("competitor", help="竞品反拆分析")
    p_comp.add_argument("url")
    p_comp.add_argument("--focus", default="全面分析")

    p_logs = sub.add_parser("logs", help="查看操作日志")
    p_logs.add_argument("project_id")

    args = parser.parse_args()

    CMDS = {
        "start": cmd_start, "status": cmd_status, "projects": cmd_projects,
        "req": cmd_req, "pause": cmd_pause, "search": cmd_search,
        "assets": cmd_assets, "competitor": cmd_competitor, "logs": cmd_logs,
    }

    if not args.cmd or args.cmd not in CMDS:
        parser.print_help()
        return

    CMDS[args.cmd](args)


if __name__ == "__main__":
    main()
