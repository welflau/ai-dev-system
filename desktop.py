"""
AI Dev System — 桌面版入口
使用 pywebview 将 Web 界面包装为原生桌面窗口，
pystray 提供系统托盘支持。

启动流程：
  1. 后台线程启动 FastAPI（uvicorn）
  2. 等待服务就绪（最多 30 秒）
  3. pywebview 创建窗口加载 http://127.0.0.1:PORT
  4. 系统托盘图标（最小化/恢复/退出）
"""

import os
import sys
import threading
import time
import urllib.request
import logging

# ── 路径修正：打包后资源路径 ──────────────────────────────────────────────────
def _resource(rel: str) -> str:
    """PyInstaller 打包后 sys._MEIPASS 指向临时解压目录"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

# ── 配置 ──────────────────────────────────────────────────────────────────────
APP_TITLE    = "AI Dev System"
APP_HOST     = "127.0.0.1"
APP_PORT     = 18000          # 桌面版用独立端口，避免与开发服务冲突
APP_URL      = f"http://{APP_HOST}:{APP_PORT}/app"        # 前端挂载在 /app
HEALTH_URL   = f"http://{APP_HOST}:{APP_PORT}/api/health" # 健康检查独立路径
BACKEND_DIR = _resource("backend")
ICON_PATH   = _resource("assets/icon.ico")
ICON_PNG    = _resource("assets/icon.png")
WIN_W, WIN_H = 1440, 900

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s")
logger = logging.getLogger("desktop")


# ── 1. 后端启动 ───────────────────────────────────────────────────────────────

def _start_backend():
    """在子线程里启动 FastAPI；切换工作目录到 backend/"""
    os.chdir(BACKEND_DIR)
    sys.path.insert(0, BACKEND_DIR)

    # 覆盖端口（不改 .env）
    os.environ.setdefault("PORT", str(APP_PORT))
    os.environ["PORT"] = str(APP_PORT)

    import uvicorn
    from main import app
    uvicorn.run(app, host=APP_HOST, port=APP_PORT, log_level="warning")


def _wait_for_server(timeout: int = 30) -> bool:
    """轮询直到服务就绪"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(HEALTH_URL, timeout=1)
            return True
        except Exception:
            time.sleep(0.4)
    return False


# ── 2. 系统托盘 ───────────────────────────────────────────────────────────────

_window = None          # pywebview 窗口引用（主线程设置）
_tray   = None          # pystray 托盘引用

def _tray_show(icon, item):
    """托盘菜单：显示/恢复窗口"""
    if _window:
        try:
            _window.show()
            _window.restore()
        except Exception:
            pass

def _tray_hide(icon, item):
    """托盘菜单：隐藏到后台"""
    if _window:
        try:
            _window.hide()
        except Exception:
            pass

def _tray_quit(icon, item):
    """托盘菜单：退出程序"""
    icon.stop()
    if _window:
        try:
            _window.destroy()
        except Exception:
            pass
    # 强制退出（uvicorn 子线程为 daemon，随主线程退出）
    os._exit(0)

def _build_tray_icon() -> "pystray.Icon":
    import pystray
    from PIL import Image

    try:
        img = Image.open(ICON_PNG).resize((64, 64))
    except Exception:
        # 若图标不存在，生成一个简单蓝色方块
        img = Image.new("RGBA", (64, 64), (99, 102, 241, 255))

    menu = pystray.Menu(
        pystray.MenuItem("显示窗口",  _tray_show, default=True),
        pystray.MenuItem("隐藏到后台", _tray_hide),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出",      _tray_quit),
    )
    return pystray.Icon(APP_TITLE, img, APP_TITLE, menu)


def _start_tray():
    """在独立线程里运行托盘（pystray 需要自己的消息循环）"""
    global _tray
    _tray = _build_tray_icon()
    _tray.run_detached()   # 非阻塞，托盘在后台线程自己循环


# ── 3. 加载画面 ───────────────────────────────────────────────────────────────

_LOADING_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    background: #0f1117;
    color: #e5e7eb;
    font-family: -apple-system, 'Segoe UI', sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100vh;
    gap: 24px;
  }
  .logo {
    width: 80px; height: 80px;
    background: #6366f1;
    border-radius: 20px;
    display: flex; align-items: center; justify-content: center;
    font-size: 40px;
  }
  h1 { font-size: 24px; font-weight: 600; }
  .sub { color: #9ca3af; font-size: 14px; }
  .spinner {
    width: 40px; height: 40px;
    border: 3px solid #374151;
    border-top-color: #6366f1;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
  <div class="logo">🤖</div>
  <h1>AI Dev System</h1>
  <p class="sub">正在启动服务…</p>
  <div class="spinner"></div>
</body>
</html>
"""


# ── 4. 主入口 ─────────────────────────────────────────────────────────────────

def main():
    global _window

    # 启动后端（daemon 线程，主线程退出时自动结束）
    logger.info("正在启动后端服务 (port=%d)…", APP_PORT)
    backend_thread = threading.Thread(target=_start_backend, daemon=True, name="backend")
    backend_thread.start()

    # 启动系统托盘
    try:
        _start_tray()
        logger.info("系统托盘已启动")
    except Exception as e:
        logger.warning("系统托盘启动失败（非致命）: %s", e)

    # 创建 pywebview 窗口（先显示加载画面）
    import webview

    _window = webview.create_window(
        APP_TITLE,
        html=_LOADING_HTML,
        width=WIN_W,
        height=WIN_H,
        resizable=True,
        min_size=(800, 600),
    )

    def _on_shown():
        """窗口显示后，等服务就绪再跳转"""
        logger.info("等待后端服务就绪…")
        ok = _wait_for_server(timeout=30)
        if ok:
            logger.info("后端就绪，加载 %s", APP_URL)
            _window.load_url(APP_URL)
        else:
            logger.error("后端启动超时")
            _window.load_html("""
                <html><body style="background:#0f1117;color:#ef4444;
                    display:flex;align-items:center;justify-content:center;
                    height:100vh;font-family:sans-serif;font-size:18px;">
                    ❌ 后端服务启动超时，请重试
                </body></html>
            """)

    # pywebview 主循环（阻塞直到窗口关闭）
    webview.start(_on_shown, debug=False)

    # 窗口关闭后清理托盘
    if _tray:
        try:
            _tray.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
