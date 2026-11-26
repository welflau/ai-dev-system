"""重跑四个隔离子进程，将观测结果绘成报告；不连接开发服务。"""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "tests"))
from test_app_lifespan import run_probe


def capture():
    cases = [("正常停机", "normal"), ("MCP 停止报错", "mcp-stop-error"),
             ("建表失败", "schema-error"), ("启动中取消", "startup-cancel")]
    rows = []
    for label, case in cases:
        with TemporaryDirectory() as folder:
            d = run_probe(case, Path(folder))
        events = d["events"]
        assert d["exit"] == 0 and d["port_closed"] and events[-1] == "db.close"
        assert not d["workers_at_db_close"] and not d["workers_after_serve"]
        served = "http.200" in events
        assert served == (case in {"normal", "mcp-stop-error"})
        if served:
            assert d["gc_at_ready"] == d["gc_done_at_db_close"] == 2 and d["port_closed_at_db_close"]
        workers = len(d["workers_at_db_close"]) + d.get("gc_at_ready", 0) - d["gc_done_at_db_close"]
        rows.append([label, "200" if served else "未就绪", workers,
                     "已调用" if "mcp.stop" in events else "未启动", "已关闭", str(d["exit"])])

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 900, "height": 540})
        page.set_content("""<!doctype html><meta charset=utf-8><style>
        *{box-sizing:border-box}body{margin:0;background:#fafcfb;color:#19372f;
        font:16px/1.6 'Microsoft YaHei',sans-serif}main{border-top:6px solid #26735b;padding:24px 30px}
        small,footer{color:#48675e}h1{font-size:27px;margin:6px 0}p{margin:4px 0 20px}
        table{border-collapse:collapse;width:100%;background:white}
        th,td{padding:10px;border-bottom:1px solid #d5e3dc;text-align:left}th{background:#e0eee6}
        footer{margin-top:15px;font-size:14px}</style><main><small>代码重构　 /　 DEVNOTE 21　 /　 子进程实测</small>
        <h1>端口关闭后，进程是否也退出？</h1><p>每行启动一个 Uvicorn 子进程，使用临时 SQLite 和替身调度器。</p>
        <table><thead><tr><th>条件</th><th>就绪请求</th><th>关库时存活任务</th><th>MCP 清理</th>
        <th>数据库</th><th>进程退出码</th></tr></thead><tbody></tbody></table>
        <footer>就绪请求返回 200 的两组，均在关库时确认端口已停止监听。退出码由父进程读取。</footer></main>""")
        page.evaluate("""rows=>{for(const row of rows){const tr=document.querySelector('tbody').insertRow();
            for(const value of row) tr.insertCell().textContent=value;}}""", rows)
        page.locator("main").screenshot(path=str(Path(__file__).with_suffix(".png")))
        browser.close()
    print("4 isolated process exits verified")


if __name__ == "__main__":
    capture()
