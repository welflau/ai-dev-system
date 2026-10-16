"""artifacts 表 schema 与迁移路径的单测。

两条路径都必须覆盖 —— 这是 `_auto_migrate` 机制的本质：
  新库：executescript(SCHEMA_SQL) 一次建全
  老库：表已存在 → `CREATE TABLE IF NOT EXISTS` 是 no-op → 靠 ALTER TABLE 补列

只写 SCHEMA_SQL 会让老库永远缺列；只写 migrations 会让新库的建表注释与实际脱节。
漏任何一边都要在真实部署时才暴露。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.6
"""
import asyncio
import re
import sqlite3
from contextlib import asynccontextmanager

import pytest

from database import SCHEMA_SQL, Database

# v0.20 产物总线新增列
NEW_COLUMNS = ("kind", "mime", "size_bytes", "produced_by")

# 老列：一个都不能少（否则 13 处 db.insert 和 4 处 SELECT * 全炸）
LEGACY_COLUMNS = (
    "id", "project_id", "requirement_id", "ticket_id",
    "type", "name", "path", "content", "metadata", "created_at",
)


def _artifacts_columns(db_path) -> list:
    conn = sqlite3.connect(db_path)
    try:
        return [r[1] for r in conn.execute("PRAGMA table_info(artifacts)")]
    finally:
        conn.close()


@asynccontextmanager
async def _migrated_db(db_file):
    """连接 + init_tables，**保证 disconnect 一定执行**。

    ⚠️ 不要在测试里裸写 `connect(); init_tables(); ...; disconnect()`。
    aiosqlite 用一个**非守护**的 worker 线程跑所有 SQL；漏掉 disconnect
    会让该线程不退出，于是 Python 卡在解释器退出阶段 —— 表现为
    **pytest 完全无输出地挂死**（实测 2 分钟无 traceback、无红色断言）。

    这正是「测试本该变红却变成挂起」的机制：异常从 await 抛出 →
    跳过了 disconnect → 线程泄漏 → 进程不退出。断言信息根本来不及打印。
    用 try/finally 包住后，失败就只是普通的 FAILED。
    """
    db = Database(db_path=str(db_file))
    await db.connect()
    try:
        await db.init_tables()
        yield db
    finally:
        await db.disconnect()


# ───────────────────── 路径 1：新库（SCHEMA_SQL） ─────────────────────

def test_fresh_db_has_all_columns(tmp_path):
    """新库由 executescript(SCHEMA_SQL) 一次建全，不依赖迁移。"""
    db_file = tmp_path / "fresh.db"
    conn = sqlite3.connect(db_file)
    conn.executescript(SCHEMA_SQL)
    conn.close()

    cols = _artifacts_columns(db_file)
    for c in LEGACY_COLUMNS + NEW_COLUMNS:
        assert c in cols, f"新库缺列 {c}"


def test_schema_sql_executes_without_error(tmp_path):
    """整段 SCHEMA_SQL 必须一次跑通。

    executescript **一条语句失败会整段中止**，其后所有建表全废。
    所以「给新列建索引」这种看似无害的改动会炸老库 —— 老库跑到
    `CREATE INDEX ... (kind)` 时该列尚不存在（迁移在 executescript 之后）。
    这条测试只能守住新库；老库那条由 test_migration_on_legacy_db 守。
    """
    db_file = tmp_path / "exec.db"
    conn = sqlite3.connect(db_file)
    try:
        conn.executescript(SCHEMA_SQL)      # 不抛异常即通过
    finally:
        conn.close()


def test_no_index_references_new_columns():
    """SCHEMA_SQL 里不得有索引引用这 4 个新列。

    原因见 database.py 中 ticket_command_log 上方的警告：老库升级时
    executescript 先于 ALTER TABLE 执行，索引引用不存在的列会中止整段。

    把它做成测试而不只是注释 —— 注释拦不住「顺手给 kind 加个索引」。
    """
    index_stmts = re.findall(
        r"CREATE INDEX[^;]*artifacts[^;]*;", SCHEMA_SQL, re.IGNORECASE
    )
    for stmt in index_stmts:
        for col in NEW_COLUMNS:
            assert col not in stmt, (
                f"索引 {stmt.strip()[:80]} 引用了迁移列 {col} —— "
                f"老库升级时会让 executescript 整段中止"
            )


# ───────────────────── 路径 2：老库（_auto_migrate） ─────────────────────

def _make_legacy_db(db_file) -> None:
    """造一个「v0.20 之前」的库：完整 schema，但 artifacts 退回 10 个老列。

    做法是先 executescript(SCHEMA_SQL) 建全，再把 artifacts 换成旧定义。
    看起来绕，但**必须这样**：

    init_tables 的末尾会调 `_ensure_default_sessions` / `_ensure_global_project`，
    它们要写 chat_sessions 和 projects（带 description 等列）。如果只手搓
    artifacts + 几张 FK 目标表，迁移会在那两步抛
    `table projects has no column named description`，而 aiosqlite 的
    worker thread 让异常表现为**整个 pytest 进程挂起**（实测 2 分钟无输出、
    无 traceback）。这个坑比缺列本身难排查得多。

    附带好处：这更贴近真实升级场景 —— 真实老库的其它表本来就是全的。
    """
    conn = sqlite3.connect(db_file)
    conn.executescript(SCHEMA_SQL)
    conn.executescript("""
        ALTER TABLE artifacts RENAME TO _artifacts_v20;
        CREATE TABLE artifacts (
            id              TEXT PRIMARY KEY,
            project_id      TEXT NOT NULL REFERENCES projects(id),
            requirement_id  TEXT REFERENCES requirements(id),
            ticket_id       TEXT REFERENCES tickets(id),
            type            TEXT NOT NULL,
            name            TEXT,
            path            TEXT,
            content         TEXT,
            metadata        TEXT,
            created_at      TEXT NOT NULL
        );
        DROP TABLE _artifacts_v20;

        INSERT INTO projects (id, name, created_at, updated_at)
        VALUES ('P1', 'demo', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');

        INSERT INTO artifacts
            (id, project_id, type, name, content, created_at)
        VALUES
            ('A1', 'P1', 'prd',       'PRD - x',  '{"a":1}', '2026-01-01T00:00:00Z'),
            ('A2', 'P1', 'ux_design', 'UX - y',   '{"b":2}', '2026-01-02T00:00:00Z');
    """)
    conn.commit()
    conn.close()


def test_migration_on_legacy_db(tmp_path):
    """老库升级：补齐 4 列、不丢数据、老查询照常。"""
    db_file = tmp_path / "legacy.db"
    _make_legacy_db(db_file)

    before = _artifacts_columns(db_file)
    for c in NEW_COLUMNS:
        assert c not in before, "前置条件错误：老库不该已有新列"

    async def migrate():
        async with _migrated_db(db_file):
            pass

    asyncio.run(migrate())

    after = _artifacts_columns(db_file)
    for c in NEW_COLUMNS:
        assert c in after, f"迁移后仍缺列 {c}"
    for c in LEGACY_COLUMNS:
        assert c in after, f"迁移丢失老列 {c}"

    conn = sqlite3.connect(db_file)
    try:
        assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 2
        # 老查询路径（actions/write_ux_design.py:58 那类）必须照常工作
        assert conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE type IN ('prd','ux_design')"
        ).fetchone()[0] == 2
    finally:
        conn.close()


def test_migration_leaves_existing_rows_unfilled(tmp_path):
    """存量行的 kind 保持 NULL —— **刻意不回填 kind = type**。

    回填看起来很顺手，但那等于声称老产物符合 kinds.yaml 的 file 存储契约
    （内容在磁盘、path 有效），而它们的内容其实在 content 列里。
    一旦 ArtifactStore / injector 按 kind 非空就当作文件去读，会全线落空。

    正确做法是读取侧用 COALESCE(kind, type) 区分两套语义。
    """
    db_file = tmp_path / "nofill.db"
    _make_legacy_db(db_file)

    async def migrate():
        async with _migrated_db(db_file):
            pass

    asyncio.run(migrate())

    conn = sqlite3.connect(db_file)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE kind IS NULL"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE size_bytes = 0"
        ).fetchone()[0] == 2
        # COALESCE 回退能正确取到语义
        rows = conn.execute(
            "SELECT COALESCE(kind, type) FROM artifacts ORDER BY id"
        ).fetchall()
        assert [r[0] for r in rows] == ["prd", "ux_design"]
    finally:
        conn.close()


def test_migration_is_idempotent(tmp_path):
    """重复 init_tables 不报错、不重复加列。

    真实场景：每次进程启动都会跑 init_tables。
    """
    db_file = tmp_path / "idem.db"
    _make_legacy_db(db_file)

    async def migrate_twice():
        for _ in range(2):
            async with _migrated_db(db_file):
                pass

    asyncio.run(migrate_twice())

    cols = _artifacts_columns(db_file)
    assert len(cols) == len(set(cols)), f"列重复: {cols}"
    for c in NEW_COLUMNS:
        assert cols.count(c) == 1


def test_new_columns_are_writable_after_migration(tmp_path):
    """迁移后能真正写入新列（光有列名不够，DEFAULT / 类型也要对）。"""
    db_file = tmp_path / "write.db"
    _make_legacy_db(db_file)

    async def migrate_and_write():
        async with _migrated_db(db_file) as db:
            # 模拟 ArtifactStore.put 的双写：type 与 kind 同值
            await db.insert("artifacts", {
                "id": "A3", "project_id": "P1",
                "type": "content_outline", "kind": "content_outline",
                "name": "outline.md",
                "path": "artifacts/abc123/def456/content_outline/outline.md",
                "content": None,
                "mime": "text/markdown", "size_bytes": 2048,
                "produced_by": "demo-outline",
                "created_at": "2026-10-15T00:00:00Z",
            })
            return await db.fetch_all(
                "SELECT * FROM artifacts WHERE id = ?", ("A3",)
            )

    rows = asyncio.run(migrate_and_write())
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "content_outline"
    assert row["type"] == "content_outline"       # 双写，老查询可命中
    assert row["content"] is None                 # file 存储：内容不入库
    assert row["size_bytes"] == 2048
    assert row["mime"] == "text/markdown"
    assert row["produced_by"] == "demo-outline"


def test_select_star_still_works_for_legacy_consumers(tmp_path):
    """4 处 `SELECT * FROM artifacts` 的消费方不能被新列打坏。

    api/tickets.py:124 / :1844、orchestrator.py:3501 / :3741 都是
    `SELECT *` 后 `dict(row)` 直接回传。新列只会多出几个 key，
    但要确认它们是 JSON 可序列化的（NULL / int / str，无 bytes）。
    """
    db_file = tmp_path / "star.db"
    _make_legacy_db(db_file)

    async def run():
        async with _migrated_db(db_file) as db:
            return await db.fetch_all("SELECT * FROM artifacts ORDER BY id")

    rows = asyncio.run(run())
    assert len(rows) == 2
    for row in rows:
        for c in NEW_COLUMNS:
            assert c in row
        import json
        json.dumps(row)      # 不抛异常即通过
