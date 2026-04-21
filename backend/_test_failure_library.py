"""
FailureLibrary 单元测试

6 用例：
1. 关键词提取：去停用词 + 中英混合 + 去重
2. record 写入：失败案例落表，keywords 列非空
3. search 过滤：module + agent_type + failure_type 硬过滤，关键词软匹配
4. search 排序偏好：resolved=1 排在 resolved=0 前
5. search 排除自己：current_ticket_id 不在结果里
6. mark_resolved：把某 ticket 的所有案例 resolved 翻转为 1

运行：cd backend && PYTHONIOENCODING=utf-8 python _test_failure_library.py

使用临时 SQLite 文件，不污染主数据库。
"""
import asyncio
import os
import sys
import tempfile


async def _setup_temp_db():
    """初始化一个临时 DB + 建 failure_cases 表，返回临时文件路径供清理"""
    import database

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp_file.close()
    tmp_path = tmp_file.name

    # 替换全局 db 实例
    database.db = database.Database(db_path=tmp_path)
    await database.db.connect()

    # 只建 failure_cases 表（跳过其他表避免 foreign key 麻烦）
    await database.db._db.executescript("""
CREATE TABLE IF NOT EXISTS failure_cases (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    requirement_id TEXT,
    ticket_id TEXT,
    agent_type TEXT NOT NULL,
    module TEXT,
    failure_type TEXT NOT NULL,
    ticket_title TEXT,
    ticket_description TEXT,
    root_cause TEXT NOT NULL,
    missed_requirements TEXT,
    strategy_change TEXT,
    specific_changes TEXT,
    confidence REAL DEFAULT 0.5,
    keywords TEXT,
    resolved INTEGER DEFAULT 0,
    resolved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
""")
    await database.db._db.commit()
    return tmp_path


async def _teardown(tmp_path: str):
    import database
    try:
        await database.db.disconnect()
    except Exception:
        pass
    try:
        os.unlink(tmp_path)
        # WAL/SHM 文件
        for ext in ("-wal", "-shm"):
            p = tmp_path + ext
            if os.path.exists(p):
                os.unlink(p)
    except Exception:
        pass


def test_keyword_extraction():
    from failure_library import _extract_keywords

    text = "在 index.html 右下角加 visit counter 用 localStorage 持久化"
    kw = _extract_keywords(text)
    parts = kw.split()
    found = set(parts)
    # 英文 3+ 字
    assert "counter" in found, f"counter missing: {parts}"
    assert "localstorage" in found, f"localstorage missing: {parts}"
    assert "index" in found, f"index missing: {parts}"  # index.html 被正则切成 index + html
    assert "html" in found, f"html missing: {parts}"
    assert "visit" in found, f"visit missing: {parts}"
    # 中文 2+ 字片段
    assert any("右下" in t or "下角" in t or "持久" in t or "持久化" in t for t in found), \
        f"CN word missing: {parts}"
    # 去停用词
    assert "在" not in found
    assert "的" not in found
    # 空输入
    assert _extract_keywords("") == ""
    # 长度控制
    kw_long = _extract_keywords("功能 模块 " * 30)
    assert len(kw_long.split()) <= 30
    print("✅ Test 1 关键词提取通过")


async def test_record_inserts_row():
    from failure_library import failure_library
    from database import db

    reflection = {
        "root_cause": "没在 index.html 加计数器 DOM",
        "missed_requirements": ["DOM 元素", "localStorage 持久化"],
        "strategy_change": "直接改 index.html body",
        "specific_changes": ["加 <div id='counter'>", "加 script"],
        "confidence": 0.85,
    }
    case_id = await failure_library.record(
        agent_type="DevAgent",
        failure_type="acceptance_rejected",
        reflection=reflection,
        project_id="P-1",
        requirement_id="R-1",
        ticket_id="T-1",
        module="frontend",
        ticket_title="加访问计数",
        ticket_description="在右下角加访问计数器 localStorage 持久化",
    )
    assert case_id, "record 应返回 id"

    rows = await db.fetch_all("SELECT * FROM failure_cases WHERE id = ?", (case_id,))
    assert len(rows) == 1
    r = rows[0]
    assert r["agent_type"] == "DevAgent"
    assert r["module"] == "frontend"
    assert r["failure_type"] == "acceptance_rejected"
    assert r["root_cause"].startswith("没在")
    assert r["keywords"], "keywords 列不应为空"
    assert r["resolved"] == 0
    assert r["confidence"] == 0.85
    print("✅ Test 2 record 写入通过")


async def test_search_filters_module_and_keywords():
    from failure_library import failure_library
    from database import db

    # 清空（同一 DB 实例，连续测试间隔离）
    await db.execute("DELETE FROM failure_cases")

    # 插 2 条 frontend + 1 条 backend
    await failure_library.record(
        agent_type="DevAgent", failure_type="acceptance_rejected",
        reflection={"root_cause": "DOM 缺失", "strategy_change": "加 div"},
        project_id="P-1", ticket_id="T-a", module="frontend",
        ticket_title="加计数器", ticket_description="加 counter 到 index.html",
    )
    await failure_library.record(
        agent_type="DevAgent", failure_type="acceptance_rejected",
        reflection={"root_cause": "样式错", "strategy_change": "改 css"},
        project_id="P-1", ticket_id="T-b", module="frontend",
        ticket_title="按钮配色", ticket_description="按钮 颜色 调整",
    )
    await failure_library.record(
        agent_type="DevAgent", failure_type="acceptance_rejected",
        reflection={"root_cause": "SQL 错误", "strategy_change": "改 SQL"},
        project_id="P-1", ticket_id="T-c", module="backend",
        ticket_title="SQL 查询", ticket_description="修 SQL 查询",
    )

    # 搜索 frontend + counter 关键词：应命中 T-a（不含 T-b 因为关键词不搭、不含 T-c 因为 module 不对）
    hits = await failure_library.search_similar(
        agent_type="DevAgent",
        failure_type="acceptance_rejected",
        module="frontend",
        project_id="P-1",
        ticket_description="加 counter 到 index.html",
        current_ticket_id="T-new",
        limit=5,
    )
    titles = [h["ticket_title"] for h in hits]
    assert "加计数器" in titles, f"应包含 T-a，实际: {titles}"
    assert "SQL 查询" not in titles, "backend 条目应被 module 过滤掉"
    print("✅ Test 3 search 过滤通过")


async def test_search_prefers_resolved():
    from failure_library import failure_library
    from database import db

    await db.execute("DELETE FROM failure_cases")

    # 两条，都能命中，但 resolved 状态不同
    id1 = await failure_library.record(
        agent_type="DevAgent", failure_type="acceptance_rejected",
        reflection={"root_cause": "R1", "strategy_change": "S1", "confidence": 0.8},
        project_id="P-1", ticket_id="T-old1", module="frontend",
        ticket_title="旧案例 1", ticket_description="加 counter",
    )
    id2 = await failure_library.record(
        agent_type="DevAgent", failure_type="acceptance_rejected",
        reflection={"root_cause": "R2", "strategy_change": "S2", "confidence": 0.8},
        project_id="P-1", ticket_id="T-old2", module="frontend",
        ticket_title="旧案例 2", ticket_description="加 counter",
    )
    # 把 id2 标为已解决
    await failure_library.mark_resolved("T-old2")

    hits = await failure_library.search_similar(
        agent_type="DevAgent",
        failure_type="acceptance_rejected",
        module="frontend",
        project_id="P-1",
        ticket_description="加 counter 到 index.html",
        current_ticket_id="T-new",
        limit=5,
    )
    assert len(hits) == 2
    assert hits[0]["resolved"] is True, f"resolved=True 应排第一，实际 first={hits[0]}"
    assert hits[0]["ticket_title"] == "旧案例 2"
    print("✅ Test 4 resolved 优先排序通过")


async def test_search_excludes_current_ticket():
    from failure_library import failure_library
    from database import db

    await db.execute("DELETE FROM failure_cases")

    await failure_library.record(
        agent_type="DevAgent", failure_type="acceptance_rejected",
        reflection={"root_cause": "R", "strategy_change": "S"},
        project_id="P-1", ticket_id="T-self", module="frontend",
        ticket_title="正在重试的工单", ticket_description="加 counter",
    )

    hits = await failure_library.search_similar(
        agent_type="DevAgent",
        failure_type="acceptance_rejected",
        module="frontend",
        project_id="P-1",
        ticket_description="加 counter",
        current_ticket_id="T-self",  # 排除自己
        limit=5,
    )
    assert hits == [], f"应排除自己，实际: {hits}"
    print("✅ Test 5 排除当前 ticket 通过")


async def test_mark_resolved_flips_flag():
    from failure_library import failure_library
    from database import db

    await db.execute("DELETE FROM failure_cases")

    # 同一 ticket 两条（模拟多次反思）
    await failure_library.record(
        agent_type="DevAgent", failure_type="acceptance_rejected",
        reflection={"root_cause": "R1", "strategy_change": "S1"},
        ticket_id="T-multi", module="frontend",
        ticket_title="多轮工单", ticket_description="加 counter",
    )
    await failure_library.record(
        agent_type="DevAgent", failure_type="acceptance_rejected",
        reflection={"root_cause": "R2", "strategy_change": "S2"},
        ticket_id="T-multi", module="frontend",
        ticket_title="多轮工单", ticket_description="加 counter",
    )

    before = await db.fetch_all("SELECT resolved FROM failure_cases WHERE ticket_id = ?", ("T-multi",))
    assert all(r["resolved"] == 0 for r in before)

    rows = await failure_library.mark_resolved("T-multi")
    assert rows == 2

    after = await db.fetch_all("SELECT resolved, resolved_at FROM failure_cases WHERE ticket_id = ?", ("T-multi",))
    assert all(r["resolved"] == 1 for r in after)
    assert all(r["resolved_at"] for r in after), "resolved_at 应被填写"

    # 二次调用应幂等（没再翻转）
    rows_again = await failure_library.mark_resolved("T-multi")
    assert rows_again == 0, "已解决的不应再次被更新"
    print("✅ Test 6 mark_resolved 翻转通过")


async def main():
    # 先跑纯函数测试
    test_keyword_extraction()

    # DB 相关测试共享一个临时 DB
    tmp_path = await _setup_temp_db()
    try:
        await test_record_inserts_row()
        await test_search_filters_module_and_keywords()
        await test_search_prefers_resolved()
        await test_search_excludes_current_ticket()
        await test_mark_resolved_flips_flag()
    finally:
        await _teardown(tmp_path)

    print("\n🎉 FailureLibrary 单测全部通过（6/6）")


if __name__ == "__main__":
    asyncio.run(main())
