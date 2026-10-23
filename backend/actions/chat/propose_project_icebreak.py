"""
新建项目破冰 —— 根据名称 / 描述 / traits 给出可选开发方向

不调 LLM，创建流程不被阻塞。UE 项目仍走 propose_ue_framework，本模块只覆盖其余类型。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("actions.chat.propose_project_icebreak")

_IGNORE_NAMES = {
    ".git", ".ads", ".claude", ".codebuddy", ".cursor", ".vscode", ".idea",
    ".agent", "__pycache__", "node_modules", ".venv", "venv", ".gitignore",
    ".env", ".env.example", "claude.md", "codebuddy.md", ".mcp-migrated",
}
_SCAFFOLD_EMPTY_DIRS = {"src", "docs", "tests"}


def _read_text_safe(p: Path, limit: int = 32000) -> str:
    try:
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        pass
    return ""


def _detect_launch_entries(root: Path) -> Dict[str, Any]:
    """扫描存量仓库的环境启动入口文件与可启动的前后端服务（命令、工作目录、端口、前台访问 URL）。"""
    entry_files: List[str] = []
    launch_entries: List[Dict[str, Any]] = []

    candidate_rel_files = [
        "start.ps1", "start.bat", "start.cmd", "start.sh",
        "run.ps1", "run.bat", "start_server.py", "run.py", "main.py", "app.py", "manage.py",
        "backend/start.ps1", "backend/start.bat", "backend/start_server.py",
        "backend/app/main.py", "backend/main.py", "backend/run.py", "backend/manage.py",
        "frontend/package.json", "web/package.json", "client/package.json", "package.json",
        "docker-compose.yml", "docker-compose.yaml",
    ]
    for rel in candidate_rel_files:
        if (root / rel).is_file():
            entry_files.append(rel)

    root_start_txt = "\n".join(
        _read_text_safe(root / fn)
        for fn in ("start.ps1", "start.bat", "start.cmd", "start.sh", "run.ps1", "backend/start.ps1")
        if (root / fn).is_file()
    )
    readme_txt = _read_text_safe(root / "README.md")
    combined_hints = f"{root_start_txt}\n{readme_txt}"

    # ── 1. 检测后端服务 (Backend) ──
    be_dir: Optional[Path] = None
    for sub in ("backend", "server"):
        d = root / sub
        if d.is_dir() and any((d / f).exists() for f in ("app", "main.py", "requirements.txt", "pyproject.toml", "manage.py")):
            be_dir = d
            break
    if be_dir is None and any((root / f).exists() for f in ("start_server.py", "app/main.py", "main.py", "manage.py", "app.py")):
        be_dir = root

    if be_dir is not None:
        uv_match = re.search(r"uvicorn\s+([\w\.:]+)(?:[^\r\n]*?--port\s+(\d+))?", combined_hints)
        app_target = ""
        be_port = 8000
        be_framework = "FastAPI"
        be_entry_file = "start.ps1" if (root / "start.ps1").is_file() else ""

        if uv_match:
            app_target = uv_match.group(1)
            if uv_match.group(2):
                be_port = int(uv_match.group(2))
            if not be_entry_file:
                if (be_dir / "start.ps1").is_file():
                    be_entry_file = f"{be_dir.name}/start.ps1" if be_dir != root else "start.ps1"
                elif (be_dir / "app" / "main.py").is_file():
                    be_entry_file = f"{be_dir.name}/app/main.py" if be_dir != root else "app/main.py"
        elif (be_dir / "app" / "main.py").is_file() or (be_dir / "main.py").is_file():
            main_py = (be_dir / "app" / "main.py") if (be_dir / "app" / "main.py").is_file() else (be_dir / "main.py")
            main_txt = _read_text_safe(main_py)
            if "FastAPI" in main_txt or "uvicorn" in main_txt:
                app_target = "app.main:app" if main_py.parent.name == "app" else "main:app"
                pm = re.search(r"port\s*=\s*(\d+)", main_txt)
                if pm:
                    be_port = int(pm.group(1))
                be_entry_file = be_entry_file or main_py.relative_to(root).as_posix()

        if app_target:
            py_exe = "python"
            if (be_dir / ".venv" / "Scripts" / "python.exe").is_file():
                py_exe = r'".venv\Scripts\python.exe"'
            elif (root / ".venv" / "Scripts" / "python.exe").is_file():
                py_exe = f'"{root / ".venv" / "Scripts" / "python.exe"}"'
            be_cmd = f"{py_exe} -m uvicorn {app_target} --port {be_port}"
            launch_entries.append({
                "id": "backend",
                "kind": "backend",
                "label": f"后端服务 ({be_framework})",
                "entry_file": be_entry_file or "backend",
                "command": be_cmd,
                "cwd": str(be_dir),
                "port": be_port,
                "url": f"http://localhost:{be_port}",
                "docs_url": f"http://localhost:{be_port}/docs",
            })
        elif (be_dir / "start_server.py").is_file():
            srv_py = be_dir / "start_server.py"
            srv_txt = _read_text_safe(srv_py)
            pm = re.search(r"port\s*=\s*(\d+)", srv_txt)
            be_port = int(pm.group(1)) if pm else 8000
            launch_entries.append({
                "id": "backend",
                "kind": "backend",
                "label": "后端服务 (Python)",
                "entry_file": srv_py.relative_to(root).as_posix(),
                "command": "python start_server.py",
                "cwd": str(be_dir),
                "port": be_port,
                "url": f"http://localhost:{be_port}",
                "docs_url": f"http://localhost:{be_port}/docs" if "uvicorn" in srv_txt or "fastapi" in srv_txt.lower() else "",
            })

    # ── 2. 检测前端服务 (Frontend) ──
    fe_dir: Optional[Path] = None
    for sub in ("frontend", "web", "client"):
        d = root / sub
        if (d / "package.json").is_file():
            fe_dir = d
            break
    if fe_dir is None and (root / "package.json").is_file():
        fe_dir = root

    if fe_dir is not None:
        pkg_path = fe_dir / "package.json"
        try:
            pkg_data = json.loads(_read_text_safe(pkg_path) or "{}")
        except Exception:
            pkg_data = {}
        scripts = pkg_data.get("scripts") if isinstance(pkg_data, dict) else {}
        if isinstance(scripts, dict):
            script_key = next((k for k in ("dev", "serve", "start") if k in scripts), "")
            if script_key:
                script_cmd = str(scripts.get(script_key) or "")
                deps = {}
                if isinstance(pkg_data.get("dependencies"), dict):
                    deps.update(pkg_data["dependencies"])
                if isinstance(pkg_data.get("devDependencies"), dict):
                    deps.update(pkg_data["devDependencies"])

                if "vite" in deps or "vite" in script_cmd:
                    fw_name = "Vite"
                elif "next" in deps or "next" in script_cmd:
                    fw_name = "Next.js"
                elif "nuxt" in deps:
                    fw_name = "Nuxt"
                elif "vue" in deps:
                    fw_name = "Vue"
                elif "react" in deps:
                    fw_name = "React"
                else:
                    fw_name = "Web"

                fe_port: Optional[int] = None
                # 1) package.json script 里的 --port / -p
                m_script_port = re.search(r"(?:--port|-p|PORT=)\s*(\d{2,5})", script_cmd)
                if m_script_port:
                    fe_port = int(m_script_port.group(1))
                # 2) start.ps1 / README 里的 vite --port 或 Frontend : http://localhost:xxxx
                if not fe_port:
                    m_hint_port = (
                        re.search(r"vite[^\r\n]*?--port\s+(\d{2,5})", combined_hints, re.IGNORECASE)
                        or re.search(r"(?:前端|Frontend)[^\r\n]*?http://(?:localhost|127\.0\.0\.1):(\d{2,5})", combined_hints, re.IGNORECASE)
                    )
                    if m_hint_port:
                        fe_port = int(m_hint_port.group(1))
                # 3) vite.config.ts / vite.config.js
                if not fe_port:
                    for vcfg in ("vite.config.ts", "vite.config.js", "vite.config.mjs"):
                        vtxt = _read_text_safe(fe_dir / vcfg)
                        if vtxt:
                            mv = re.search(r"\bport\s*:\s*(\d{2,5})", vtxt)
                            if mv:
                                fe_port = int(mv.group(1))
                                break
                if not fe_port:
                    fe_port = 5173 if fw_name == "Vite" else 3000

                fe_entry_file = pkg_path.relative_to(root).as_posix()
                if (root / "start.ps1").is_file() and fe_dir != root:
                    fe_entry_file = f"start.ps1 · {fe_entry_file}"

                launch_entries.append({
                    "id": "frontend",
                    "kind": "frontend",
                    "label": f"前端服务 ({fw_name})",
                    "entry_file": fe_entry_file,
                    "command": f"npm run {script_key}",
                    "cwd": str(fe_dir),
                    "port": fe_port,
                    "url": f"http://localhost:{fe_port}",
                })

    return {
        "entry_files": entry_files[:8],
        "launch_entries": launch_entries,
    }


def _inspect_existing_repo(repo_path: Optional[str]) -> Dict[str, Any]:
    """检测 repo_path 是否为已有代码的存量工程，并提取代表性顶层目录/文件及环境启动入口。"""
    if not repo_path:
        return {"is_existing": False, "entries": [], "entry_files": [], "launch_entries": []}
    root = Path(repo_path)
    if not root.is_dir():
        return {"is_existing": False, "entries": [], "entry_files": [], "launch_entries": []}

    notable: List[str] = []
    substantive_count = 0
    try:
        items = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return {"is_existing": False, "entries": [], "entry_files": [], "launch_entries": []}

    for item in items:
        low = item.name.lower()
        if low in _IGNORE_NAMES or low.startswith(".git"):
            continue
        if item.is_dir():
            if low in _SCAFFOLD_EMPTY_DIRS:
                try:
                    has_child = any(True for _ in item.iterdir())
                except OSError:
                    has_child = False
                if not has_child:
                    continue
            if low == "plugins":
                # 仅含自动部署的 UnrealClientProtocol 不算存量业务代码
                try:
                    children = [c.name for c in item.iterdir()]
                except OSError:
                    children = []
                if children == ["UnrealClientProtocol"]:
                    continue
            substantive_count += 1
            notable.append(f"{item.name}/")
        elif item.is_file():
            if low == "readme.md":
                try:
                    txt = item.read_text(encoding="utf-8", errors="replace").strip()
                except OSError:
                    txt = ""
                if not txt or ("由 AI 自动开发系统创建的项目" in txt and len(txt) < 240):
                    continue
            substantive_count += 1
            notable.append(item.name)

    is_existing = substantive_count >= 2
    launch_info = _detect_launch_entries(root) if is_existing else {"entry_files": [], "launch_entries": []}
    return {
        "is_existing": is_existing,
        "entries": notable[:6],
        "entry_files": launch_info["entry_files"],
        "launch_entries": launch_info["launch_entries"],
    }


def _blob(*parts: str) -> str:
    return " ".join(p for p in parts if p).lower()


def _has_any(text: str, keys: List[str]) -> bool:
    return any(k in text for k in keys)


def _opt(oid: str, label: str, prompt: str, hint: str = "") -> Dict[str, str]:
    return {"id": oid, "label": label, "prompt": prompt, "hint": hint}


def build_icebreak_payload(
    name: str,
    description: str = "",
    traits: Optional[List[str]] = None,
    tech_stack: str = "",
    repo_path: Optional[str] = None,
) -> Dict[str, Any]:
    """根据项目背景生成破冰分析 + 可点选项。自动区分『存量工程接入』与『从零新建项目』。"""
    name = (name or "").strip() or "新项目"
    description = (description or "").strip()
    traits = [str(t) for t in (traits or []) if str(t).strip()]
    tech_stack = (tech_stack or "").strip()
    text = _blob(name, description, tech_stack, " ".join(traits))

    repo_info = _inspect_existing_repo(repo_path)
    if repo_info["is_existing"]:
        entries_str = "、".join(repo_info["entries"][:5])
        stack_str = f"，技术栈：{tech_stack}" if tech_stack else ""
        desc_str = f"（{description}）" if description else ""
        launch_entries = repo_info.get("launch_entries") or []
        entry_files = repo_info.get("entry_files") or []
        if launch_entries:
            svc_summary = "、".join(
                f"{e.get('label', '服务')} (:{e.get('port')})" if e.get("port") else str(e.get("label", "服务"))
                for e in launch_entries
            )
            launch_hint = f" 已识别到环境启动入口：{svc_summary}，可在下方直接检测/拉起后台服务并打开前台访问。"
        else:
            launch_hint = " 建议先对齐现有架构与实现进度，在此基础上增量迭代，而非从零重做原型。"
        analysis = (
            f"检测到「{name}」{desc_str}是已有代码的存量工程"
            f"（包含 {entries_str} 等）{stack_str}。{launch_hint}"
        )
        options = [
            _opt(
                "overview",
                "梳理现有架构与进展",
                f"请先读取「{name}」仓库的目录结构、README 和状态文档，帮我梳理当前已完成模块、技术架构与待办事项。",
                "推荐",
            ),
            _opt(
                "iterate",
                "基于现有代码新增/迭代功能",
                f"请结合「{name}」现有代码结构，帮我拆解下一条要推进的功能迭代需求并创建工单。",
                "走工单流",
            ),
            _opt(
                "audit",
                "排查未完项与代码体检",
                f"请检查「{name}」当前前后端实现的完整性、未打通环节或潜在问题，列出优先修复清单。",
                "查问题",
            ),
            _opt(
                "custom",
                "我有明确任务",
                f"项目「{name}」已有现成代码。先听我描述具体要改的模块或问题，再开始处理。",
                "自己描述",
            ),
        ]
        return {
            "type": "propose_icebreak",
            "title": "🧭 建议的切入方向（现有工程）",
            "project_name": name,
            "analysis": analysis,
            "options": options,
            "traits": traits,
            "is_existing": True,
            "entry_files": entry_files,
            "launch_entries": launch_entries,
            "source": "heuristic_existing",
        }

    engine = next((t.split(":", 1)[-1] for t in traits if t.startswith("engine:")), "")
    platform = next((t.split(":", 1)[-1] for t in traits if t.startswith("platform:")), "")
    category = next((t.split(":", 1)[-1] for t in traits if t.startswith("category:")), "")
    is_game = "category:game" in traits or _has_any(text, [
        "game", "游戏", "flappy", "snake", "tetris", "fps", "rpg", "塔防", "贪吃蛇",
    ])

    analysis, options = _analyze(name, description, text, traits, engine, platform, category, is_game)
    options.append(_opt(
        "custom",
        "我有别的想法",
        f"项目是「{name}」。先别按你猜的方向做，等我说明白再规划第一个需求。",
        "自己描述",
    ))

    return {
        "type": "propose_icebreak",
        "title": "🧭 建议的开发方向",
        "project_name": name,
        "analysis": analysis,
        "options": options,
        "traits": traits,
        "is_existing": False,
        "source": "heuristic",
    }


def _analyze(
    name: str,
    description: str,
    text: str,
    traits: List[str],
    engine: str,
    platform: str,
    category: str,
    is_game: bool,
) -> tuple[str, List[Dict[str, str]]]:
    desc_hint = f"：{description}" if description else ""

    if _has_any(text, ["flappy", "flap", "小鸟飞", "飞翔小鸟", "飞小鸟"]):
        return (
            f"从项目名「{name}」看，很像 Flappy Bird 类休闲跳跃。{description and '描述：' + description or '还没写玩法细节，先定载体再出可玩原型。'}",
            [
                _opt("h5", "网页版 Flappy Bird",
                     f"做「{name}」网页版 Flappy Bird：点击/空格上升、管道障碍、记分与重开。先出可玩原型，不要先做后台。",
                     "最快出可玩原型"),
                _opt("godot", "Godot 2D 客户端",
                     f"用 Godot 4 做「{name}」2D Flappy Bird：场景、物理、分数、重开。先出可玩关卡。",
                     "适合后续扩成完整游戏"),
                _opt("wechat", "微信小游戏",
                     f"把「{name}」做成微信小游戏版 Flappy Bird，先出可玩原型，再补分享和排行榜。",
                     "适合传播"),
            ],
        )

    if _has_any(text, ["snake", "贪吃蛇"]):
        return (
            f"「{name}」像贪吃蛇。先定平台，再做移动、吃食物、撞墙/撞自己。",
            [
                _opt("h5", "网页版贪吃蛇", f"做「{name}」网页贪吃蛇，键盘控制，先出可玩原型。", "最快"),
                _opt("godot", "Godot 2D", f"用 Godot 4 做「{name}」贪吃蛇，先出可玩关卡。", "客户端"),
                _opt("wechat", "微信小游戏", f"把「{name}」做成微信小游戏贪吃蛇。", "传播"),
            ],
        )

    if _has_any(text, ["tetris", "俄罗斯方块"]):
        return (
            f"「{name}」像俄罗斯方块。核心是方块生成、旋转、消行和计分。",
            [
                _opt("h5", "网页版俄罗斯方块", f"做「{name}」网页俄罗斯方块，先出可玩原型。", "最快"),
                _opt("godot", "Godot 2D", f"用 Godot 4 做「{name}」俄罗斯方块。", "客户端"),
            ],
        )

    if _has_any(text, ["fps", "射击", "first person", "第一人称"]):
        return (
            f"「{name}」偏射击/FPS{desc_hint}。先定引擎，再做移动和开火。",
            [
                _opt("ue", "UE5 第一人称", f"用 UE5 做「{name}」FPS，先出移动、开火、简单关卡。", "3D 品质"),
                _opt("godot", "Godot 3D 射击", f"用 Godot 4 做「{name}」射击原型。", "更轻"),
                _opt("design", "先写玩法策划", f"先给「{name}」写一页射击玩法策划（核心循环、武器、关卡），确认后再开工。", "先对齐"),
            ],
        )

    if _has_any(text, ["rpg", "角色扮演", "回合"]):
        return (
            f"「{name}」偏 RPG{desc_hint}。建议先定最小可玩循环，而不是一次性做完整世界观。",
            [
                _opt("combat", "先做战斗原型", f"「{name}」先做最小战斗循环（角色、敌人、胜负），不做大地图。", "验证手感"),
                _opt("design", "先写设定与需求", f"先整理「{name}」的世界观、职业和第一章需求列表，确认后再开发。", "先对齐"),
                _opt("web", "网页 Demo", f"用网页先做「{name}」的对话/战斗 Demo，验证循环。", "最快"),
            ],
        )

    if _has_any(text, ["shop", "商城", "电商", "购物"]):
        return (
            f"「{name}」偏电商/商城{desc_hint}。建议先做商品列表 + 下单闭环。",
            [
                _opt("web", "网页商城原型", f"做「{name}」网页商城：商品列表、详情、购物车、下单页。先出可点原型。", "最快"),
                _opt("wechat", "微信小程序商城", f"把「{name}」做成微信小程序商城，先出商品和下单。", "微信生态"),
                _opt("admin", "先做后台", f"「{name}」先做商品/订单管理后台，前台稍后。", "运营向"),
            ],
        )

    if _has_any(text, ["blog", "博客", "cms", "内容"]):
        return (
            f"「{name}」偏内容站/博客{desc_hint}。",
            [
                _opt("web", "博客站点", f"做「{name}」博客：文章列表、详情、发布。先出可浏览原型。", "最快"),
                _opt("admin", "先做编辑后台", f"「{name}」先做文章编辑和发布后台。", "内容运营"),
            ],
        )

    if is_game:
        if engine.startswith("godot"):
            return (
                f"「{name}」是游戏，已标 Godot{desc_hint}。建议先出最小可玩关卡。",
                [
                    _opt("playable", "先出可玩原型", f"用 Godot 做「{name}」最小可玩原型：一个场景、一套核心操作、胜负条件。", "推荐"),
                    _opt("design", "先写玩法策划", f"先给「{name}」写核心循环和关卡策划，确认后再进编辑器。", "先对齐"),
                ],
            )
        if engine in ("none", "") and (platform == "web" or _has_any(text, ["html", "h5", "网页"])):
            return (
                f"「{name}」像网页游戏{desc_hint}。建议 HTML5 先出可玩原型。",
                [
                    _opt("h5", "HTML5 可玩原型", f"用网页做「{name}」可玩原型，先验证核心玩法。", "最快"),
                    _opt("godot", "改用 Godot 2D", f"「{name}」改用 Godot 4 做 2D 客户端，先出可玩关卡。", "后续更好扩"),
                    _opt("design", "先写玩法策划", f"先给「{name}」写一页玩法策划，确认后再开发。", "先对齐"),
                ],
            )
        return (
            f"「{name}」是游戏项目{desc_hint}。还没完全定载体，先选一条路。",
            [
                _opt("h5", "网页可玩原型", f"用网页先做「{name}」核心玩法原型。", "最快验证"),
                _opt("godot", "Godot 2D/3D", f"用 Godot 4 做「{name}」，先出最小可玩关卡。", "独立游戏常用"),
                _opt("design", "先写策划再开工", f"先给「{name}」写核心循环、目标和第一关，确认后再开发。", "先对齐"),
            ],
        )

    if "platform:wechat" in traits or _has_any(text, ["小程序", "wechat", "微信"]):
        return (
            f"「{name}」偏微信小程序{desc_hint}。建议先做首页 + 一个核心流程。",
            [
                _opt("mvp", "小程序 MVP", f"做「{name}」微信小程序：首页和一个核心流程，先能点通。", "推荐"),
                _opt("design", "先列页面和需求", f"先列出「{name}」的页面结构和前 3 条需求，确认后再开发。", "先对齐"),
            ],
        )

    if "platform:web" in traits or category == "app" or _has_any(text, ["web", "网站", "网页", "系统", "平台"]):
        return (
            f"「{name}」偏网页应用{desc_hint}。建议先做主流程，而不是一次做完全部后台。",
            [
                _opt("mvp", "先做主流程原型", f"做「{name}」网页 MVP：核心页面和主流程先能走通。", "推荐"),
                _opt("req", "先拆第一条需求", f"根据「{name}」{desc_hint} 拆出第一条可开发需求，创建工单。", "走工单流"),
                _opt("design", "先写功能清单", f"先给「{name}」列功能清单和页面结构，确认后再开发。", "先对齐"),
            ],
        )

    trait_line = "、".join(traits) if traits else "尚未标注类型"
    return (
        f"项目「{name}」已创建（{trait_line}）{desc_hint}。我还不能 100% 锁定形态，请选一个起步方式。",
        [
            _opt("mvp", "先做最小可用原型", f"根据「{name}」{desc_hint} 先做最小可用原型，验证主流程。", "推荐"),
            _opt("req", "先创建第一条需求", f"帮「{name}」分析并创建第一条开发需求。", "走工单流"),
            _opt("design", "先讨论方向再开工", f"先根据「{name}」讨论 2-3 个可行方向和取舍，我选定后再开发。", "先对齐"),
        ],
    )


async def persist_project_icebreak(
    project_id: str,
    name: str,
    description: str = "",
    traits: Optional[List[str]] = None,
    tech_stack: str = "",
    repo_path: Optional[str] = None,
) -> Dict[str, Any]:
    """把破冰消息写入项目会话，刷新后能直接看到。"""
    from api.chat import _save_chat_message
    from database import db
    from utils import generate_id, now_iso

    if not repo_path and project_id:
        try:
            row = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id = ?", (project_id,))
            if row and row.get("git_repo_path"):
                repo_path = row["git_repo_path"]
        except Exception:
            pass

    payload = build_icebreak_payload(name, description, traits, tech_stack, repo_path=repo_path)
    session_id = generate_id("sess-")
    if payload.get("is_existing"):
        intro = (
            f"已接入现有项目「{payload['project_name']}」。"
            "请选择一个切入方式，或直接输入你要处理的模块与问题。"
        )
        sess_title = f"接入 · {payload['project_name']}"
    else:
        intro = (
            f"项目「{payload['project_name']}」已就绪。"
            "请选一个起步方向，我会据此创建第一个需求。"
        )
        sess_title = f"破冰 · {payload['project_name']}"
    await _save_chat_message(
        project_id=project_id,
        role="assistant",
        content=intro,
        action=payload,
        session_id=session_id,
    )
    try:
        await db.update(
            "chat_sessions",
            {"title": sess_title, "updated_at": now_iso()},
            "id = ?",
            (session_id,),
        )
    except Exception:
        pass
    return {
        "type": "propose_icebreak",
        "project_id": project_id,
        "session_id": session_id,
        "persisted": True,
        "reason": "项目破冰：方向卡片已写入项目聊天",
    }
