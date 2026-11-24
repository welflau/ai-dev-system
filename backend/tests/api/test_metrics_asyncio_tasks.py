"""顶栏「异步任务」明细端点 GET /api/metrics/asyncio-tasks。

验证：字段完整、count == len(tasks)、summary 聚合正确、self 标记、
当前请求 task 不排除（保证与 /api/metrics 的 asyncio_tasks 口径一致）、
只取栈帧元信息不泄漏局部变量、done task 被过滤。
"""
import asyncio

import pytest

import main as main_mod


@pytest.mark.asyncio
async def test_detail_matches_all_tasks_口径():
    d = await main_mod.get_asyncio_tasks_detail()
    assert isinstance(d, dict)
    assert set(d) >= {"count", "tasks", "summary"}
    assert d["count"] == len(d["tasks"]), "列表条数必须与计数一致"
    # 同一时刻 all_tasks 的未完成数：明细端点自身也是一个未完成 task，
    # 因此 d['count'] 应当 >= 单独枚举值（差 0 或 1，取决于调用栈）
    n = sum(1 for t in asyncio.all_tasks() if not t.done())
    assert d["count"] in (n, n + 1), (d["count"], n)


@pytest.mark.asyncio
async def test_task_fields_complete():
    d = await main_mod.get_asyncio_tasks_detail()
    for t in d["tasks"]:
        assert set(t) == {"name", "coro", "done", "cancelling", "stack", "self"}
        assert t["done"] is False
        assert isinstance(t["self"], bool)
        assert isinstance(t["cancelling"], int)
        # 栈帧格式 file:func:line，不含局部变量值
        assert "secret" not in t["stack"]


@pytest.mark.asyncio
async def test_self_marks_current_task():
    d = await main_mod.get_asyncio_tasks_detail()
    selfs = [t for t in d["tasks"] if t["self"]]
    assert len(selfs) == 1, f"应恰好标记 1 个当前请求 task，实得 {len(selfs)}"
    assert "test_self_marks_current_task" in selfs[0]["coro"]


@pytest.mark.asyncio
async def test_summary_aggregates_by_coro():
    d = await main_mod.get_asyncio_tasks_detail()
    from collections import Counter
    expected = Counter(t["coro"] or "(unknown)" for t in d["tasks"])
    got = {g["coro"]: g["count"] for g in d["summary"]}
    assert got == dict(expected)
    assert sum(g["count"] for g in d["summary"]) == d["count"]


@pytest.mark.asyncio
async def test_done_task_excluded():
    async def _noop():
        return 1
    t = asyncio.create_task(_noop(), name="done-probe")
    await t
    assert t.done()
    d = await main_mod.get_asyncio_tasks_detail()
    assert "done-probe" not in [x["name"] for x in d["tasks"]]


@pytest.mark.asyncio
async def test_multiple_pending_tasks_are_listed():
    async def _wait(evt):
        await evt.wait()
    evt = asyncio.Event()
    created = [
        asyncio.create_task(_wait(evt), name=f"probe-{i}") for i in range(3)
    ]
    try:
        await asyncio.sleep(0)  # 让协程真正启动
        d = await main_mod.get_asyncio_tasks_detail()
        names = {x["name"] for x in d["tasks"]}
        assert {"probe-0", "probe-1", "probe-2"} <= names
        assert d["count"] >= 4
    finally:
        evt.set()
        await asyncio.gather(*created, return_exceptions=True)


def test_metrics_endpoint_uses_same_enumeration():
    """/api/metrics 与明细端点共用「未完成 all_tasks」口径（轻量计数分支）。"""
    src = open("main.py", encoding="utf-8").read()
    i = src.find("async def get_system_metrics")
    body = src[i:i + 900]
    assert "all_tasks(loop) if not t.done()" in body
    assert "_asyncio_task_details" not in body or "len(_asyncio_task_details" not in body
