"""隔离进程探针：运行生产 lifespan，只替换业务依赖；结果只含测试事件。"""
import asyncio
import json
import logging
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from unittest.mock import patch

import aiosqlite
import httpx
import uvicorn
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.disable(logging.CRITICAL)
with patch("dotenv.load_dotenv"), patch("dotenv.dotenv_values", return_value={}):
    import main
import config


async def probe(case, folder):
    events = []
    active = set()
    report = {}
    gc_tasks = []
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    class DB:
        conn = None

        async def connect(self):
            self.conn = await aiosqlite.connect(folder / "probe.sqlite")
            events.append("db.open")

        async def init_tables(self):
            if case == "schema-error":
                raise RuntimeError("synthetic schema failure")
            await self.conn.execute("CREATE TABLE sample(id INTEGER)")
            events.append("db.schema")

        async def fetch_all(self, query):
            if "git_repo_path" in query:
                events.append("projects.restore")
            return []

        async def execute(self, *args):
            pass

        async def disconnect(self):
            report["workers_at_db_close"] = sorted(active)
            report["gc_done_at_db_close"] = sum(t.done() for t in gc_tasks)
            if "http.200" in events:
                with socket.socket() as sock:
                    sock.settimeout(1)
                    report["port_closed_at_db_close"] = sock.connect_ex(("127.0.0.1", port)) != 0
            await self.conn.close()
            events.append("db.close")

    async def worker(name, **kwargs):
        active.add(name)
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)  # cancel() 本身不等于清理完成
            active.remove(name)
            events.append("stop." + name)

    def loop(name):
        return lambda **kwargs: worker(name, **kwargs)

    async def start_mcp():
        await asyncio.sleep(0)
        events.append("mcp.start")
        if case == "startup-cancel":
            raise asyncio.CancelledError()

    async def stop_mcp():
        report["workers_at_mcp_stop"] = sorted(active)
        events.append("mcp.stop")
        if case == "mcp-stop-error":
            raise RuntimeError("synthetic MCP failure")

    ns = SimpleNamespace
    modules = {
        "hooks.builtin": ns(register_builtin_hooks=lambda: events.append("hooks")),
        "permissions.gate": ns(permission_gate=object()),
        "llm_client": ns(llm_client=ns(is_configured=False)),
        "git_manager": ns(PROJECTS_DIR=folder, git_manager=object()),
        "api.knowledge": ns(GLOBAL_DOCS_DIR=folder, PROJECTS_DIR=folder,
                            _upsert_knowledge_index=None, _upsert_tickets_fts=None),
        "orchestrator": ns(orchestrator=ns(start_event_bus=loop("bus"), poll_loop=loop("poll"))),
        "ci_pipeline": ns(ci_pipeline=ns(start_scheduler=loop("ci"))),
        "image_processor": ns(image_processor_loop=loop("image")),
        "automation_scheduler": ns(automation_loop=loop("automation")),
        "mcp_client": ns(mcp_client=ns(start_enabled_servers=start_mcp, stop_all_servers=stop_mcp,
                                       get_status=lambda: {})),
    }
    db = DB()
    main.db = db  # 这是一次性子进程：与生产 db 单例寿命相同
    app = FastAPI(lifespan=main.lifespan)

    @app.get("/ready")
    async def ready():
        return {"ok": True}

    cfg = uvicorn.Config(app, log_config=None, lifespan="on", access_log=False)
    server = uvicorn.Server(cfg)
    # 不运行主应用的 API，不导入业务调度器，也不访问实际项目、素材库或 MCP 服务。
    with patch.dict(sys.modules, modules), \
            patch.object(config, "BASE_DIR", folder / "backend"), \
            patch.object(config.settings, "ART_ASSETS_LOCAL_PATH", ""), \
            patch.object(config.settings, "GLOBAL_KNOWLEDGE_LOCAL_PATH", ""):
        try:
            task = asyncio.create_task(server.serve(sockets=[listener]))
            while not server.started and not task.done():
                await asyncio.sleep(0.01)
            if server.started:
                async with httpx.AsyncClient(trust_env=False) as client:
                    r = await client.get(f"http://127.0.0.1:{port}/ready")
                    assert r.status_code == 200 and r.json() == {"ok": True}
                events.append("http.200")
                report["workers_at_ready"] = sorted(active)
                gc_tasks.extend(t for t in asyncio.all_tasks() if t.get_coro().__name__ in
                                {"_checkpoint_gc_loop", "_session_materials_gc_loop"})
                report["gc_at_ready"] = len(gc_tasks)
                server.should_exit = True
            await task
        finally:
            listener.close()
        report["workers_after_serve"] = sorted(active)
        with socket.socket() as sock:
            sock.settimeout(1)
            report["port_closed"] = sock.connect_ex(("127.0.0.1", port)) != 0
        report["events"] = list(events)
        (folder / "result.json").write_text(json.dumps(report), encoding="utf8")
        # 不手动收尾，让父进程区分 serve 返回与解释器实际退出。


if __name__ == "__main__":
    asyncio.run(probe(sys.argv[1], Path(sys.argv[2])))
