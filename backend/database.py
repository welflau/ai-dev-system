"""
AI 自动开发系统 - 数据库管理
SQLite + aiosqlite 异步数据库操作
"""
import aiosqlite
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from config import settings


class Database:
    """异步 SQLite 数据库管理器"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or settings.DB_PATH
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self):
        """连接数据库"""
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.commit()

    async def disconnect(self):
        """断开连接"""
        if self._db:
            await self._db.close()
            self._db = None

    async def init_tables(self):
        """初始化所有数据表"""
        await self._db.executescript(SCHEMA_SQL)
        await self._db.commit()

    # ==================== 通用 CRUD ====================

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        """执行 SQL"""
        cursor = await self._db.execute(sql, params)
        await self._db.commit()
        return cursor

    async def fetch_one(self, sql: str, params: tuple = ()) -> Optional[Dict]:
        """查询单条"""
        cursor = await self._db.execute(sql, params)
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None

    async def fetch_all(self, sql: str, params: tuple = ()) -> List[Dict]:
        """查询多条"""
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def insert(self, table: str, data: Dict[str, Any]) -> str:
        """插入数据"""
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        await self._db.execute(sql, tuple(data.values()))
        await self._db.commit()
        return data.get("id", "")

    async def update(self, table: str, data: Dict[str, Any], where: str, params: tuple = ()) -> int:
        """更新数据"""
        set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
        sql = f"UPDATE {table} SET {set_clause} WHERE {where}"
        cursor = await self._db.execute(sql, tuple(data.values()) + params)
        await self._db.commit()
        return cursor.rowcount

    async def delete(self, table: str, where: str, params: tuple = ()) -> int:
        """删除数据"""
        sql = f"DELETE FROM {table} WHERE {where}"
        cursor = await self._db.execute(sql, tuple(params))
        await self._db.commit()
        return cursor.rowcount


# ==================== 数据库 Schema ====================

SCHEMA_SQL = """
-- ============================================================
-- 项目表
-- ============================================================
CREATE TABLE IF NOT EXISTS projects (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
    tech_stack      TEXT,
    config          TEXT,
    git_repo_path   TEXT,
    git_remote_url  TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- ============================================================
-- 需求单表
-- ============================================================
CREATE TABLE IF NOT EXISTS requirements (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id),
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    priority        TEXT NOT NULL DEFAULT 'medium',
    status          TEXT NOT NULL DEFAULT 'submitted',
    submitter       TEXT DEFAULT 'user',
    prd_content     TEXT,
    module          TEXT,
    tags            TEXT,
    estimated_hours REAL,
    actual_hours    REAL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    completed_at    TEXT
);

-- ============================================================
-- 工单/任务单表（核心）
-- ============================================================
CREATE TABLE IF NOT EXISTS tickets (
    id              TEXT PRIMARY KEY,
    requirement_id  TEXT NOT NULL REFERENCES requirements(id),
    project_id      TEXT NOT NULL REFERENCES projects(id),
    parent_ticket_id TEXT REFERENCES tickets(id),
    title           TEXT NOT NULL,
    description     TEXT,
    type            TEXT NOT NULL DEFAULT 'feature',
    module          TEXT,
    priority        INTEGER NOT NULL DEFAULT 3,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending',
    assigned_agent  TEXT,
    current_owner   TEXT,
    estimated_hours REAL,
    actual_hours    REAL,
    estimated_completion TEXT,
    dependencies    TEXT,
    result          TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    started_at      TEXT,
    completed_at    TEXT
);

-- ============================================================
-- 子任务表
-- ============================================================
CREATE TABLE IF NOT EXISTS subtasks (
    id              TEXT PRIMARY KEY,
    ticket_id       TEXT NOT NULL REFERENCES tickets(id),
    title           TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    assigned_agent  TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    result          TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    completed_at    TEXT
);

-- ============================================================
-- 工单操作日志表（全流程可追溯）
-- ============================================================
CREATE TABLE IF NOT EXISTS ticket_logs (
    id              TEXT PRIMARY KEY,
    ticket_id       TEXT REFERENCES tickets(id),
    subtask_id      TEXT REFERENCES subtasks(id),
    requirement_id  TEXT REFERENCES requirements(id),
    project_id      TEXT NOT NULL REFERENCES projects(id),
    agent_type      TEXT,
    action          TEXT NOT NULL,
    from_status     TEXT,
    to_status       TEXT,
    detail          TEXT,
    level           TEXT NOT NULL DEFAULT 'info',
    created_at      TEXT NOT NULL
);

-- ============================================================
-- 产物表
-- ============================================================
CREATE TABLE IF NOT EXISTS artifacts (
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

-- ============================================================
-- LLM 会话记录表
-- ============================================================
CREATE TABLE IF NOT EXISTS llm_conversations (
    id              TEXT PRIMARY KEY,
    ticket_id       TEXT REFERENCES tickets(id),
    requirement_id  TEXT REFERENCES requirements(id),
    project_id      TEXT REFERENCES projects(id),
    agent_type      TEXT,
    action          TEXT,
    messages        TEXT NOT NULL,
    response        TEXT,
    model           TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    duration_ms     INTEGER,
    status          TEXT NOT NULL DEFAULT 'success',
    error           TEXT,
    created_at      TEXT NOT NULL
);

-- ============================================================
-- 工单执行命令表（Pipeline 配置 Tab）
-- ============================================================
CREATE TABLE IF NOT EXISTS ticket_commands (
    id              TEXT PRIMARY KEY,
    ticket_id       TEXT REFERENCES tickets(id),
    requirement_id  TEXT REFERENCES requirements(id),
    project_id      TEXT NOT NULL REFERENCES projects(id),
    agent_type      TEXT NOT NULL,
    action          TEXT NOT NULL,
    step_order      INTEGER NOT NULL DEFAULT 0,
    command_type    TEXT NOT NULL,
    command         TEXT NOT NULL,
    result          TEXT,
    status          TEXT NOT NULL DEFAULT 'success',
    duration_ms     INTEGER,
    created_at      TEXT NOT NULL
);

-- ============================================================
-- 索引
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_requirements_project ON requirements(project_id);
CREATE INDEX IF NOT EXISTS idx_requirements_status ON requirements(status);
CREATE INDEX IF NOT EXISTS idx_tickets_requirement ON tickets(requirement_id);
CREATE INDEX IF NOT EXISTS idx_tickets_project ON tickets(project_id);
CREATE INDEX IF NOT EXISTS idx_tickets_parent ON tickets(parent_ticket_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_module ON tickets(module);
CREATE INDEX IF NOT EXISTS idx_tickets_assigned ON tickets(assigned_agent);
CREATE INDEX IF NOT EXISTS idx_subtasks_ticket ON subtasks(ticket_id);
CREATE INDEX IF NOT EXISTS idx_ticket_logs_ticket ON ticket_logs(ticket_id);
CREATE INDEX IF NOT EXISTS idx_ticket_logs_requirement ON ticket_logs(requirement_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_ticket ON artifacts(ticket_id);
CREATE INDEX IF NOT EXISTS idx_llm_conversations_ticket ON llm_conversations(ticket_id);
CREATE INDEX IF NOT EXISTS idx_llm_conversations_requirement ON llm_conversations(requirement_id);
CREATE INDEX IF NOT EXISTS idx_llm_conversations_project ON llm_conversations(project_id);
CREATE INDEX IF NOT EXISTS idx_ticket_commands_ticket ON ticket_commands(ticket_id);
CREATE INDEX IF NOT EXISTS idx_ticket_commands_requirement ON ticket_commands(requirement_id);
"""


# 全局数据库实例
db = Database()
