"""真实 ASGI 路由和 SSE 帧；不启动 lifespan，消息只进本次测试的管理器。"""
import asyncio
import json
from contextlib import asynccontextmanager

import pytest

import events
import main
from api import tickets


class ObservedManager(events.EventManager):
    def __init__(self):
        super().__init__()
        self.joined = asyncio.Queue()

    def subscribe(self, channel):
        queue = super().subscribe(channel)
        self.joined.put_nowait(channel)
        return queue


@asynccontextmanager
async def stream(path, channel, manager):
    # 模拟 ASGI 服务器：响应头与消息分开读取，退出时发送真正的 disconnect。
    incoming = asyncio.Queue()
    outgoing = asyncio.Queue()
    incoming.put_nowait({"type": "http.request", "body": b""})
    task = asyncio.create_task(main.app(
        {"type": "http", "method": "GET", "scheme": "http", "path": path,
         "http_version": "1.1", "query_string": b"", "headers": []},
        incoming.get, outgoing.put,
    ))
    try:
        start = await asyncio.wait_for(outgoing.get(), 5)
        assert start["type"] == "http.response.start" and start["status"] == 200
        headers = dict(start["headers"])
        assert headers[b"content-type"].split(b";")[0] == b"text/event-stream"
        assert headers[b"x-accel-buffering"] == b"no"
        assert await asyncio.wait_for(manager.joined.get(), 5) == channel
        yield outgoing
    finally:
        incoming.put_nowait({"type": "http.disconnect"})
        await asyncio.wait_for(task, 5)


async def next_log(outgoing):
    message = await asyncio.wait_for(outgoing.get(), 5)
    assert message["type"] == "http.response.body" and message["more_body"]
    event, data, blank, end = message["body"].decode("utf-8").split("\r\n")
    assert event == "event: log_added" and data.startswith("data: ")
    assert blank == end == ""
    return json.loads(data[len("data: "):])


@pytest.mark.asyncio
async def test_same_named_events_stay_in_their_channels(monkeypatch):
    manager = ObservedManager()
    monkeypatch.setattr(events, "event_manager", manager)
    monkeypatch.setattr(tickets, "event_manager", manager)
    async with (stream("/api/events/global", "global", manager) as g,
                stream("/api/projects/demo/events", "project:demo", manager) as p,
                stream("/api/tickets/demo/events", "ticket:demo", manager) as t):
        for seq in (1, 2):
            project = {"message": "测试项目", "seq": seq}
            ticket = {"message": "测试工单", "seq": seq}
            global_log = {"message": "全局\n第二行", "seq": seq}
            await tickets.event_manager.publish_to_project("demo", "log_added", project)
            await tickets.event_manager.publish_to_ticket("demo", "log_added", ticket)
            await events.event_manager.publish("global", "log_added", global_log)
            assert await next_log(g) == global_log
            assert await next_log(p) == project
            assert await next_log(t) == ticket
    assert manager._subscribers == {}


@pytest.mark.asyncio
async def test_disconnecting_one_global_listener_keeps_the_other(monkeypatch):
    manager = ObservedManager()
    monkeypatch.setattr(events, "event_manager", manager)
    async with stream("/api/events/global", "global", manager) as first:
        async with stream("/api/events/global", "global", manager) as second:
            await manager.publish("global", "log_added", {"seq": 1})
            assert await next_log(first) == await next_log(second) == {"seq": 1}
        assert len(manager._subscribers["global"]) == 1
        await manager.publish("global", "log_added", {"seq": 2})
        assert await next_log(first) == {"seq": 2}
    assert manager._subscribers == {}


@pytest.mark.parametrize("path", [
    "/api/events/global", "/api/projects/{project_id}/events", "/api/tickets/{ticket_id}/events",
])
def test_openapi_declares_sse_response(path):
    response = main.app.openapi()["paths"][path]["get"]["responses"]["200"]
    assert set(response["content"]) == {"text/event-stream"}
