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
    # 后端数据目录
    (str(BACKEND / "skills"),                "backend/skills"),
    (str(BACKEND / "sop"),                   "backend/sop"),
    (str(BACKEND / "templates"),             "backend/templates"),
    (str(BACKEND / "knowledge_config.yaml"), "backend"),
    (str(BACKEND / "mcp_servers.json"),      "backend"),
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
    "agents",
    "agents.chat_assistant",
    "agents.base",
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
    optimize=1,
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
    console=False,          # 无控制台窗口
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
