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
import subprocess
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


def _setup_desktop_file_log():
    """打包后无控制台时，把启动日志写到 exe 旁 desktop.log"""
    try:
        app_dir = os.path.dirname(os.path.abspath(
            sys.executable if getattr(sys, "frozen", False) else __file__
        ))
        fh = logging.FileHandler(os.path.join(app_dir, "desktop.log"),
                                 encoding="utf-8", mode="w")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s  %(message)s"))
        logging.getLogger().addHandler(fh)
        logging.getLogger("uvicorn.error").addHandler(fh)
        logging.getLogger("main").addHandler(fh)
    except Exception:
        pass


# ── 1. 后端启动 ───────────────────────────────────────────────────────────────

def _app_dir() -> str:
    """exe 所在目录（开发模式则为项目根）"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _log_backend_error(msg: str):
    """后端启动失败写入 exe 旁日志，便于无控制台时排查"""
    try:
        path = os.path.join(_app_dir(), "desktop-backend-error.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
        logger.error(msg)
    except Exception:
        pass


_backend_proc = None  # type: subprocess.Popen | None


def _prepare_backend_env_and_cwd():
    """切换 cwd / path，供后端进程使用"""
    if getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None):
        runtime = os.path.join(_app_dir(), "runtime")
        os.makedirs(runtime, exist_ok=True)
        os.chdir(runtime)
        if getattr(sys, "_MEIPASS", None):
            sys.path.insert(0, sys._MEIPASS)
    else:
        os.chdir(BACKEND_DIR)
        sys.path.insert(0, BACKEND_DIR)
    os.environ["PORT"] = str(APP_PORT)
    os.environ.setdefault("HOST", APP_HOST)


def _ensure_stdio():
    """windowed exe 下 sys.stdout/stderr 为 None，uvicorn 日志会崩；挂到文件。"""
    log_path = os.path.join(_app_dir(), "desktop-backend-stdout.log")
    if sys.stdout is None or sys.stderr is None:
        f = open(log_path, "a", encoding="utf-8", errors="replace")
        if sys.stdout is None:
            sys.stdout = f
        if sys.stderr is None:
            sys.stderr = f


def _run_backend_main():
    """后端入口（独立进程的主线程）。勿在 GUI 线程里直接调 uvicorn。"""
    _ensure_stdio()
    _setup_desktop_file_log()
    try:
        _prepare_backend_env_and_cwd()
        logger.info("[backend-process] import uvicorn / main …")
        import uvicorn
        from main import app
        logger.info("[backend-process] 绑定 %s:%s", APP_HOST, APP_PORT)
        uvicorn.run(app, host=APP_HOST, port=APP_PORT, log_level="info")
    except Exception:
        import traceback
        _log_backend_error("后端进程异常:\n" + traceback.format_exc())
        raise


def _spawn_backend_process() -> subprocess.Popen:
    """拉起独立后端进程（uvicorn 跑在该进程主线程，避免 Windows 线程卡死）"""
    global _backend_proc
    env = os.environ.copy()
    env["PORT"] = str(APP_PORT)
    env["HOST"] = APP_HOST

    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--backend"]
        cwd = _app_dir()
    else:
        # 开发模式：用当前解释器重新执行 desktop.py --backend
        cmd = [sys.executable, os.path.abspath(__file__), "--backend"]
        cwd = os.path.dirname(os.path.abspath(__file__))

    log_path = os.path.join(_app_dir(), "desktop-backend-stdout.log")
    log_f = open(log_path, "w", encoding="utf-8", errors="replace")
    creationflags = 0
    if sys.platform == "win32":
        # 不弹控制台窗口
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    logger.info("拉起后端进程: %s", cmd)
    _backend_proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=log_f,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    logger.info("后端进程 PID=%s", _backend_proc.pid)
    return _backend_proc


def _stop_backend_process():
    global _backend_proc
    if not _backend_proc:
        return
    try:
        if _backend_proc.poll() is None:
            logger.info("结束后端进程 PID=%s", _backend_proc.pid)
            _backend_proc.terminate()
            try:
                _backend_proc.wait(timeout=5)
            except Exception:
                _backend_proc.kill()
    except Exception as e:
        logger.warning("结束后端进程失败: %s", e)
    finally:
        _backend_proc = None


def _wait_for_server(timeout: int = 90) -> bool:
    """轮询直到服务就绪（打包首次 import/冷启动可能较慢）"""
    deadline = time.time() + timeout
    last_log = 0.0
    while time.time() < deadline:
        try:
            urllib.request.urlopen(HEALTH_URL, timeout=1)
            return True
        except Exception as e:
            now = time.time()
            if now - last_log > 5:
                logger.info("等待后端就绪… (%ds) %s", int(timeout - (deadline - now)), e)
                last_log = now
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
    _stop_backend_process()
    if _window:
        try:
            _window.destroy()
        except Exception:
            pass
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
    _setup_desktop_file_log()

    # 独立子进程启动后端（勿用线程：Windows 上 uvicorn 会卡死不监听）
    logger.info("正在启动后端服务 (port=%d)…", APP_PORT)
    try:
        _spawn_backend_process()
    except Exception:
        import traceback
        _log_backend_error("拉起后端进程失败:\n" + traceback.format_exc())

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
        ok = _wait_for_server(timeout=90)
        if ok:
            logger.info("后端就绪，加载 %s", APP_URL)
            _window.load_url(APP_URL)
        else:
            logger.error("后端启动超时")
            err_hint = ""
            for name in ("desktop-backend-error.log", "desktop-backend-stdout.log", "desktop.log"):
                path = os.path.join(_app_dir(), name)
                if os.path.isfile(path):
                    try:
                        with open(path, "r", encoding="utf-8", errors="replace") as f:
                            err_hint += f"\n----- {name} -----\n" + f.read()[-800:]
                    except Exception:
                        pass
            detail = (err_hint or "未写入错误日志，可能是端口被占用或依赖缺失").replace("<", "&lt;")
            _window.load_html(f"""
                <html><body style="background:#0f1117;color:#e5e7eb;
                    display:flex;flex-direction:column;align-items:center;justify-content:center;
                    height:100vh;font-family:sans-serif;padding:24px;box-sizing:border-box;">
                    <div style="color:#ef4444;font-size:18px;margin-bottom:16px;">❌ 后端服务启动超时</div>
                    <div style="color:#9ca3af;font-size:13px;margin-bottom:12px;">无需单独 startServer；内嵌后端未能就绪</div>
                    <pre style="max-width:900px;max-height:50vh;overflow:auto;background:#1f2937;
                        padding:12px;border-radius:8px;font-size:11px;white-space:pre-wrap;">{detail}</pre>
                    <div style="color:#6b7280;font-size:12px;margin-top:12px;">日志在 exe 同目录 desktop*.log</div>
                </body></html>
            """)

    # pywebview 主循环（阻塞直到窗口关闭）
    webview.start(_on_shown, debug=False)

    # 窗口关闭后清理
    _stop_backend_process()
    if _tray:
        try:
            _tray.stop()
        except Exception:
            pass


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--backend":
        _run_backend_main()
    else:
        main()
