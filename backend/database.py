"""
AI 自动开发系统 - 数据库管理
SQLite + aiosqlite 异步数据库操作
"""
import aiosqlite
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from config import settings

logger = logging.getLogger("database")


class Database:
    """异步 SQLite 数据库管理器"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or settings.DB_PATH
        self._db: Optional[aiosqlite.Connection] = None
        self._write_lock = asyncio.Lock()  # 防止并发写冲突

    async def connect(self):
        """连接数据库"""
        # timeout=30 让 sqlite3 在锁冲突时最多等待 30 秒，彻底解决 database is locked
        self._db = await aiosqlite.connect(self.db_path, timeout=30)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.execute("PRAGMA busy_timeout=30000")  # 30s 等待
        await self._db.execute("PRAGMA synchronous=NORMAL")  # WAL 模式下安全且更快
        await self._db.commit()

    async def disconnect(self):
        """断开连接"""
        if self._db:
            await self._db.close()
            self._db = None

    async def init_tables(self):
        """初始化所有数据表"""
        async with self._write_lock:
            await self._db.executescript(SCHEMA_SQL)
            await self._db.commit()
        # 自动迁移：检测并添加缺失的列
        await self._auto_migrate()

    async def _auto_migrate(self):
        """自动检测并添加缺失的列（兼容旧数据库）"""
        migrations = [
            # (表名, 列名, 列定义)
            ("projects", "git_repo_path", "TEXT"),
            ("projects", "git_remote_url", "TEXT"),
            ("requirements", "milestone_id", "TEXT"),
            ("requirements", "estimated_days", "REAL"),
            ("requirements", "branch_name", "TEXT"),
            ("tickets", "verification_status", "TEXT DEFAULT 'pending'"),
            ("tickets", "verified_by", "TEXT"),
            ("tickets", "verification_date", "TEXT"),
            ("tickets", "verification_notes", "TEXT"),
            ("chat_messages", "images_json", "TEXT"),  # 聊天图片文件路径列表 JSON
            ("bugs", "fix_notes", "TEXT"),
            ("bugs", "version_id", "TEXT"),
            ("bugs", "ticket_id", "TEXT"),
            # v0.17 Trait-First 多项目类型支持
            ("projects", "traits", "TEXT DEFAULT '[]'"),          # JSON array: ["platform:web", ...]
            ("projects", "traits_confidence", "TEXT DEFAULT '{}'"),  # JSON: {trait: {score, source, evidence}}
            ("projects", "preset_id", "TEXT"),                     # 可选，建项目时选的 preset 名字
            # v0.17 卡壳诊断（BLOCKED 工单的 LLM 诊断结果）
            ("tickets", "diagnosis", "TEXT"),                      # JSON: {symptom, root_cause, severity, suggested_actions, ...}
            # v0.18 UE 项目配置（持久化到项目级别，避免每次卡片里重选）
            ("projects", "ue_engine_path", "TEXT"),                # 引擎根目录，如 "G:/EpicGames/UE_5.3"
            ("projects", "ue_engine_version", "TEXT"),             # 版本号冗余，如 "5.3.2"
            ("projects", "ue_engine_type", "TEXT"),                # "launcher" / "source_build"
            ("projects", "uproject_path", "TEXT"),                 # .uproject 相对仓库根路径
            ("projects", "ue_target_name", "TEXT"),                # 编译 target 名，如 "TestFPSEditor"
            ("projects", "ue_target_platform", "TEXT DEFAULT 'Win64'"),
            ("projects", "ue_target_config", "TEXT DEFAULT 'Development'"),
            # v0.19.1 action state 持久化：防止卡片刷新后被重复点击
            ("chat_messages", "action_state", "TEXT"),   # NULL / pending / executed / cancelled
            ("chat_messages", "action_result", "TEXT"),  # JSON：{executed_at, commit, template, ...}
            # v0.19.x 构建详情：存最后 8KB stdout，供"详情"弹窗显示
            ("ci_builds", "raw_output_tail", "TEXT"),
            # v0.19.x 工单面板"当前进度"区：让 UBT / Package 的 3-5 分钟等待有活性反馈
            ("tickets", "current_action", "TEXT"),              # "DevAgent.run_engine_compile"
            ("tickets", "current_action_started_at", "TEXT"),   # ISO 时间戳
            ("tickets", "current_action_latest_log", "TEXT"),   # 最近一行关键 log（<=200 字符）
            ("tickets", "current_action_updated_at", "TEXT"),   # 最近一次心跳时间
        ]
        async with self._write_lock:
            for table, column, col_def in migrations:
                cursor = await self._db.execute(f"PRAGMA table_info({table})")
                columns = [row[1] for row in await cursor.fetchall()]
                if column not in columns:
                    await self._db.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"
                    )
                    logger.info("数据库迁移: 已添加列 %s.%s (%s)", table, column, col_def)
            await self._db.commit()

    # ==================== 通用 CRUD ====================

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        """执行 SQL（写操作加锁）"""
        async with self._write_lock:
            cursor = await self._db.execute(sql, params)
            await self._db.commit()
            return cursor

    async def fetch_one(self, sql: str, params: tuple = ()) -> Optional[Dict]:
        """查询单条（读操作不加锁）"""
        cursor = await self._db.execute(sql, params)
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None

    async def fetch_all(self, sql: str, params: tuple = ()) -> List[Dict]:
        """查询多条（读操作不加锁）"""
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def insert(self, table: str, data: Dict[str, Any]) -> str:
        """插入数据"""
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        async with self._write_lock:
            await self._db.execute(sql, tuple(data.values()))
            await self._db.commit()
        return data.get("id", "")

    async def update(self, table: str, data: Dict[str, Any], where: str, params: tuple = ()) -> int:
        """更新数据"""
        set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
        sql = f"UPDATE {table} SET {set_clause} WHERE {where}"
        async with self._write_lock:
            cursor = await self._db.execute(sql, tuple(data.values()) + params)
            await self._db.commit()
        return cursor.rowcount

    async def delete(self, table: str, where: str, params: tuple = ()) -> int:
        """删除数据"""
        sql = f"DELETE FROM {table} WHERE {where}"
        async with self._write_lock:
            cursor = await self._db.execute(sql, tuple(params))
            await self._db.commit()
        return cursor.rowcount


# ==================== 数据库 Schema ====================

SCHEMA_SQL = """
-- ============================================================
-- 项目表
-- ============================================================
CREATE TABLE IF NOT EXISTS projects (
    id                 TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    description        TEXT,
    status             TEXT NOT NULL DEFAULT 'active',
    tech_stack         TEXT,
    config             TEXT,
    git_repo_path      TEXT,
    git_remote_url     TEXT,
    traits             TEXT DEFAULT '[]',   -- v0.17: JSON array of trait strings
    traits_confidence  TEXT DEFAULT '{}',   -- v0.17: JSON {trait: {score, source, evidence}}
    preset_id          TEXT,                -- v0.17: 可选，建项目时的 preset 引用
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
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
    milestone_id    TEXT REFERENCES milestones(id),
    estimated_days  REAL,
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
-- 里程碑表（Roadmap Milestones）
-- ============================================================
CREATE TABLE IF NOT EXISTS milestones (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id),
    title           TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'planned',
    planned_start   TEXT,
    planned_end     TEXT,
    actual_start    TEXT,
    actual_end      TEXT,
    source          TEXT NOT NULL DEFAULT 'ai_generated',
    progress        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- ============================================================
-- 聊天消息表（全局聊天历史）
-- ============================================================
CREATE TABLE IF NOT EXISTS chat_messages (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id),
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    action_type     TEXT,
    action_data     TEXT,
    created_at      TEXT NOT NULL
);

-- ============================================================
-- BUG 表
-- ============================================================
CREATE TABLE IF NOT EXISTS bugs (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id),
    requirement_id  TEXT REFERENCES requirements(id),
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    priority        TEXT NOT NULL DEFAULT 'medium',
    status          TEXT NOT NULL DEFAULT 'open',
    version_id      TEXT,
    fix_notes       TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    fixed_at        TEXT
);

-- ============================================================
-- CI/CD 构建记录表
-- ============================================================
CREATE TABLE IF NOT EXISTS ci_builds (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id),
    build_type      TEXT NOT NULL,
    branch          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    trigger         TEXT NOT NULL DEFAULT 'auto',
    commit_hash     TEXT,
    merge_commit    TEXT,
    build_log       TEXT,
    error_message   TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    created_at      TEXT NOT NULL
);

-- ============================================================
-- 项目环境表（dev / test / prod）
-- ============================================================
CREATE TABLE IF NOT EXISTS project_environments (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id),
    env_type        TEXT NOT NULL,
    branch          TEXT,
    deploy_path     TEXT,
    port            INTEGER,
    status          TEXT NOT NULL DEFAULT 'inactive',
    url             TEXT,
    last_commit     TEXT,
    last_deployed_at TEXT,
    created_at      TEXT NOT NULL
);

-- ============================================================
-- 失败案例库（Failure Library）
-- 跨工单反思学习：捕获 Reflexion 产出的失败反思，供未来相似场景检索
-- 详见 docs/20260420_02_失败案例库实现方案.md
-- ============================================================
CREATE TABLE IF NOT EXISTS failure_cases (
    id                   TEXT PRIMARY KEY,
    project_id           TEXT,
    requirement_id       TEXT,
    ticket_id            TEXT,
    agent_type           TEXT NOT NULL,
    module               TEXT,
    failure_type         TEXT NOT NULL,
    ticket_title         TEXT,
    ticket_description   TEXT,
    root_cause           TEXT NOT NULL,
    missed_requirements  TEXT,
    strategy_change      TEXT,
    specific_changes     TEXT,
    confidence           REAL DEFAULT 0.5,
    keywords             TEXT,
    resolved             INTEGER DEFAULT 0,
    resolved_at          TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
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
CREATE INDEX IF NOT EXISTS idx_chat_messages_project ON chat_messages(project_id);
CREATE INDEX IF NOT EXISTS idx_milestones_project ON milestones(project_id);
CREATE INDEX IF NOT EXISTS idx_milestones_status ON milestones(status);
CREATE INDEX IF NOT EXISTS idx_failure_cases_lookup
    ON failure_cases(agent_type, module, failure_type, resolved);
CREATE INDEX IF NOT EXISTS idx_failure_cases_ticket ON failure_cases(ticket_id);
CREATE INDEX IF NOT EXISTS idx_failure_cases_project ON failure_cases(project_id);
CREATE INDEX IF NOT EXISTS idx_requirements_milestone ON requirements(milestone_id);
CREATE INDEX IF NOT EXISTS idx_ci_builds_project ON ci_builds(project_id);
CREATE INDEX IF NOT EXISTS idx_ci_builds_status ON ci_builds(status);
CREATE INDEX IF NOT EXISTS idx_ci_builds_type ON ci_builds(build_type);
CREATE INDEX IF NOT EXISTS idx_project_environments_project ON project_environments(project_id);
CREATE INDEX IF NOT EXISTS idx_bugs_project ON bugs(project_id);
CREATE INDEX IF NOT EXISTS idx_bugs_status ON bugs(status);
CREATE INDEX IF NOT EXISTS idx_bugs_requirement ON bugs(requirement_id);
"""


# 全局数据库实例
db = Database()
