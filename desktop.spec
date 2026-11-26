# -*- mode: python ; coding: utf-8 -*-
"""
AI Dev System — PyInstaller 打包配置
用法：
  cd F:\A_Works\ai-dev-system
  pyinstaller desktop.spec
输出：dist/AI-Dev-System/AI-Dev-System.exe（目录模式，启动更快）
"""

import os
import sys
from pathlib import Path

ROOT    = Path(SPECPATH)           # F:\A_Works\ai-dev-system
BACKEND = ROOT / "backend"

# ── 数据文件（目标路径相对于打包根目录）────────────────────────────────────────
datas = [
    # 前端
    (str(ROOT / "frontend"),                 "frontend"),
    # 与 Python 包同级（skills.loader / sop / pack_installer 用 Path(__file__).parent）
    (str(BACKEND / "skills"),                "skills"),
    (str(BACKEND / "sop"),                   "sop"),
    (str(BACKEND / "templates"),             "templates"),
    (str(BACKEND / "config_packs"),          "config_packs"),
    (str(BACKEND / "knowledge_config.yaml"), "."),
    (str(BACKEND / "mcp_servers.json"),      "."),
    # 图标
    (str(ROOT / "assets"),                   "assets"),
]

# 仅打包已存在的路径
datas = [(src, dst) for src, dst in datas if Path(src).exists()]

# ── 隐式导入（FastAPI/Uvicorn 动态加载的模块）────────────────────────────────
hiddenimports = [
    # FastAPI / Starlette
    "uvicorn.lifespan.on",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "starlette.routing",
    "starlette.middleware.cors",
    "sse_starlette.sse",
    # 数据库
    "aiosqlite",
    # HTTP
    "httpx",
    "anyio",
    "anyio.abc",
    "anyio._backends._asyncio",
    # 序列化
    "yaml",
    "dotenv",
    # 后端模块（相对导入）
    "main",
    "app_runtime.lifecycle",
    "app_runtime.startup_data",
    "config",
    "database",
    "orchestrator",
    "orchestration",
    "orchestration.result_flow",
    "orchestration.result_handlers",
    "orchestration.result_handlers.context",
    "orchestration.result_handlers.architect",
    "orchestration.result_handlers.art",
    "orchestration.result_handlers.artist",
    "orchestration.result_handlers.deploy",
    "orchestration.result_handlers.dev",
    "orchestration.result_handlers.planner",
    "orchestration.result_handlers.product",
    "orchestration.result_handlers.review",
    "orchestration.result_handlers.skill",
    "orchestration.result_handlers.tester",
    "orchestration.result_handlers.ue_editor",
    "orchestration.result_handlers.ux",
    "orchestration.requirement_pipeline",
    "orchestration.rewind",
    "orchestration.sop_rules",
    "orchestration.change_flows",
    "orchestration.reporting",
    "orchestration.polling",
    "orchestration.bug_flow",
    "orchestration.agent_state",
    "orchestration.failure_counters",
    "orchestration.ticket_log",
    "orchestration.context_builder",
    "orchestration.openspec_closeout",
    "orchestration.git_persist",
    "orchestration.blocked_diagnosis",
    "orchestration.poll_cycle",
    "orchestration.context_assembly",
    "orchestration.ticket_pipeline",
    "llm_client",
    "agent_registry",
    "agents",
    "agents.chat_assistant",
    "agents.base",
    # orchestrator 经 runtime_facade 按名字取这些模块，没有静态导入，要手动列出
    "agents.test",
    "agents.deploy",
    "actions.diagnose_ticket",
    "actions.knowledge_distill",
    "actions.ue_editor_control",
    "query_engine",
    "query_engine.engine",
    "query_engine.events",
    "skills",
    "skills.loader",
    "hooks",
    "hooks.registry",
    "hooks.builtin",
    "mcp_client",
    "event_bus",
    "session_logger",
    "api",
    "api.tickets",
    "api.event_streams",
    "api.frontend_pages",
    "api.local_images",
    "api.system",
    "services.agent_tools_settings",
    "services.file_manager",
    "api.llm_config",
    "services.llm_config",
    "services.global_llm_config",
    "api.metrics",
    "services.metrics",
    "api.sop_config",
    "services.sop_config",
    "api.chat",
    "api.chat.session_lists",
    "services.chat.session_lists",
    "api.projects",
    "api.project_preview",
    # pywebview 后端
    "webview",
    "webview.guilib",
    "pythonnet",
    "clr",
    # pystray
    "pystray",
    "PIL",
    "PIL.Image",
]

# ── 分析 ──────────────────────────────────────────────────────────────────────
a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT), str(BACKEND)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的大型包
        "tkinter", "matplotlib", "numpy", "pandas",
        "scipy", "IPython", "jupyter",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AI-Dev-System",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # 无控制台窗口；排查启动问题时可临时改 True
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AI-Dev-System",
)
