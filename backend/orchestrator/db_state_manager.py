"""
SQLite 持久化状态管理器
替代内存版 StateManager，数据持久化到 SQLite，重启不丢失
"""
import os
import json
import sqlite3
from typing import Dict, Any, List, Optional
from datetime import datetime
from contextlib import contextmanager

from models.schemas import (
    Task, Requirement, ProjectState, Artifact, ProjectPlan,
    AgentContext, ExecutionResult
)
from models.enums import TaskStatus, ProjectPhase, TaskType, AgentType, Priority


class DbStateManager:
    """SQLite 持久化状态管理器"""

    def __init__(self, db_path: str = "ai_dev_system.db"):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_conn(self):
        """获取数据库连接（上下文管理器）"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        """初始化数据库表"""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '未命名',
                    description TEXT DEFAULT '',
                    requirement_id TEXT,
                    requirement_json TEXT,
                    current_phase TEXT NOT NULL DEFAULT 'requirement_analysis',
                    global_context TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    assigned_agent TEXT,
                    priority TEXT DEFAULT 'medium',
                    estimated_hours REAL,
                    actual_hours REAL,
                    dependencies TEXT DEFAULT '[]',
                    result TEXT,
                    error_message TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    duration_seconds REAL,
                    FOREIGN KEY (project_id) REFERENCES projects(project_id)
                );

                CREATE TABLE IF NOT EXISTS task_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    level TEXT NOT NULL DEFAULT 'info',
                    message TEXT NOT NULL,
                    detail TEXT DEFAULT '',
                    FOREIGN KEY (project_id) REFERENCES projects(project_id),
                    FOREIGN KEY (task_id) REFERENCES tasks(id)
                );

                CREATE TABLE IF NOT EXISTS project_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    event TEXT NOT NULL,
                    data TEXT DEFAULT '{}',
                    FOREIGN KEY (project_id) REFERENCES projects(project_id)
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_project
                    ON tasks(project_id);
                CREATE INDEX IF NOT EXISTS idx_tasks_status
                    ON tasks(project_id, status);
                CREATE INDEX IF NOT EXISTS idx_logs_project
                    ON project_logs(project_id);
                CREATE INDEX IF NOT EXISTS idx_task_logs_task
                    ON task_logs(task_id);
                CREATE INDEX IF NOT EXISTS idx_task_logs_project
                    ON task_logs(project_id);
            """)

    # ============ 项目操作 ============

    def create_project(
        self,
        project_id: str,
        requirement: Requirement,
        tasks: List[Task],
    ) -> ProjectState:
        """创建项目"""
        now = datetime.now()
        now_iso = now.isoformat()

        req_json = requirement.model_dump_json() if hasattr(requirement, 'model_dump_json') else requirement.json()

        with self._get_conn() as conn:
            # 插入项目
            conn.execute(
                """INSERT INTO projects
                   (project_id, name, description, requirement_id, requirement_json,
                    current_phase, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    requirement.project_name or "未命名",
                    requirement.description[:500],
                    requirement.id,
                    req_json,
                    ProjectPhase.REQUIREMENT_ANALYSIS.value,
                    now_iso,
                    now_iso,
                )
            )

            # 批量插入任务
            for task in tasks:
                deps_json = json.dumps(task.dependencies if isinstance(task.dependencies, list) else [])
                conn.execute(
                    """INSERT INTO tasks
                       (id, project_id, name, description, type, status,
                        assigned_agent, priority, estimated_hours, dependencies)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        task.id,
                        project_id,
                        task.name,
                        task.description or "",
                        task.type if isinstance(task.type, str) else task.type.value,
                        task.status if isinstance(task.status, str) else task.status.value,
                        task.assigned_agent if isinstance(task.assigned_agent, str) else (task.assigned_agent.value if task.assigned_agent else None),
                        task.priority if isinstance(task.priority, str) else task.priority.value,
                        task.estimated_hours,
                        deps_json,
                    )
                )

            # 记录日志
            conn.execute(
                """INSERT INTO project_logs (project_id, timestamp, event, data)
                   VALUES (?, ?, ?, ?)""",
                (
                    project_id,
                    now_iso,
                    "project_created",
                    json.dumps({
                        "task_count": len(tasks),
                        "requirement": requirement.description[:200],
                    }, ensure_ascii=False),
                )
            )

        return self._build_project_state(project_id)

    def get_project(self, project_id: str) -> Optional[ProjectState]:
        """获取项目状态"""
        return self._build_project_state(project_id)

    def get_all_projects(self) -> List[Dict[str, Any]]:
        """获取所有项目摘要"""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT
                     p.project_id, p.name, p.description, p.current_phase,
                     p.created_at, p.updated_at,
                     COUNT(t.id) as task_count,
                     SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END) as completed_count,
                     SUM(CASE WHEN t.status = 'in_progress' THEN 1 ELSE 0 END) as in_progress_count,
                     SUM(CASE WHEN t.status = 'failed' THEN 1 ELSE 0 END) as failed_count
                   FROM projects p
                   LEFT JOIN tasks t ON p.project_id = t.project_id
                   GROUP BY p.project_id
                   ORDER BY p.created_at DESC"""
            ).fetchall()

        return [
            {
                "project_id": r["project_id"],
                "name": r["name"],
                "description": (r["description"] or "")[:100],
                "phase": r["current_phase"],
                "task_count": r["task_count"] or 0,
                "completed_count": r["completed_count"] or 0,
                "in_progress_count": r["in_progress_count"] or 0,
                "failed_count": r["failed_count"] or 0,
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    # ============ 任务操作 ============

    def update_task_status(
        self,
        project_id: str,
        task_id: str,
        status: TaskStatus,
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> Optional[Task]:
        """更新任务状态"""
        now_iso = datetime.now().isoformat()

        with self._get_conn() as conn:
            # 查当前任务
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ? AND project_id = ?",
                (task_id, project_id)
            ).fetchone()
            if not row:
                return None

            old_status = row["status"]
            status_val = status if isinstance(status, str) else status.value

            # 更新字段
            updates = {"status": status_val}
            if result is not None:
                updates["result"] = json.dumps(result, ensure_ascii=False)
            if error_message is not None:
                updates["error_message"] = error_message

            # 记录时间戳
            if status_val == "in_progress" and old_status != "in_progress":
                updates["started_at"] = now_iso
            elif status_val in ("completed", "failed"):
                updates["completed_at"] = now_iso
                # 计算耗时
                started = row["started_at"]
                if started:
                    try:
                        start_dt = datetime.fromisoformat(started)
                        end_dt = datetime.fromisoformat(now_iso)
                        duration = (end_dt - start_dt).total_seconds()
                        updates["duration_seconds"] = round(duration, 2)
                    except Exception:
                        pass

            set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
            values = list(updates.values()) + [task_id, project_id]
            conn.execute(
                f"UPDATE tasks SET {set_clause} WHERE id = ? AND project_id = ?",
                values
            )

            # 更新项目时间
            conn.execute(
                "UPDATE projects SET updated_at = ? WHERE project_id = ?",
                (now_iso, project_id)
            )

            # 日志
            conn.execute(
                """INSERT INTO project_logs (project_id, timestamp, event, data)
                   VALUES (?, ?, ?, ?)""",
                (
                    project_id,
                    now_iso,
                    "task_status_changed",
                    json.dumps({
                        "task_id": task_id,
                        "task_name": row["name"],
                        "old_status": old_status,
                        "new_status": status_val,
                    }, ensure_ascii=False),
                )
            )

        # 自动推进阶段
        self._advance_phase(project_id)

        # 返回更新后的 Task
        return self._build_task(task_id, project_id)

    def get_task_summary(self, project_id: str) -> Dict[str, Any]:
        """获取任务统计摘要"""
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT
                     COUNT(*) as total,
                     SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                     SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
                     SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                     SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
                   FROM tasks WHERE project_id = ?""",
                (project_id,)
            ).fetchone()

        if not row:
            return {"total": 0, "completed": 0, "in_progress": 0, "pending": 0, "failed": 0}

        return {
            "total": row["total"] or 0,
            "completed": row["completed"] or 0,
            "in_progress": row["in_progress"] or 0,
            "pending": row["pending"] or 0,
            "failed": row["failed"] or 0,
        }

    def get_tasks_by_phase(self, project_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """按阶段分组获取任务"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE project_id = ? ORDER BY id",
                (project_id,)
            ).fetchall()

        phases: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            phase = r["type"]
            if phase not in phases:
                phases[phase] = []
            phases[phase].append({
                "id": r["id"],
                "name": r["name"],
                "description": r["description"],
                "status": r["status"],
                "assigned_agent": r["assigned_agent"],
                "priority": r["priority"],
                "estimated_hours": r["estimated_hours"],
                "dependencies": json.loads(r["dependencies"] or "[]"),
                "started_at": r["started_at"],
                "completed_at": r["completed_at"],
                "duration_seconds": r["duration_seconds"],
            })

        return phases

    def get_project_logs(self, project_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """获取项目日志"""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT timestamp, event, data
                   FROM project_logs
                   WHERE project_id = ?
                   ORDER BY id DESC LIMIT ?""",
                (project_id, limit)
            ).fetchall()

        return [
            {
                "timestamp": r["timestamp"],
                "event": r["event"],
                "data": json.loads(r["data"] or "{}"),
            }
            for r in reversed(rows)  # 返回正序（最早到最晚）
        ]

    # ============ 内部方法 ============

    def add_task_log(
        self,
        project_id: str,
        task_id: str,
        level: str,
        message: str,
        detail: str = "",
    ):
        """添加任务级别的日志"""
        now_iso = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO task_logs (project_id, task_id, timestamp, level, message, detail)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (project_id, task_id, now_iso, level, message, detail)
            )

    def get_task_logs(
        self, project_id: str, task_id: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """获取某个任务的日志"""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT timestamp, level, message, detail
                   FROM task_logs
                   WHERE project_id = ? AND task_id = ?
                   ORDER BY id ASC LIMIT ?""",
                (project_id, task_id, limit)
            ).fetchall()

        return [
            {
                "timestamp": r["timestamp"],
                "level": r["level"],
                "message": r["message"],
                "detail": r["detail"],
            }
            for r in rows
        ]

    def _advance_phase(self, project_id: str) -> None:
        """根据任务完成情况自动推进项目阶段"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT type, status FROM tasks WHERE project_id = ?",
                (project_id,)
            ).fetchall()

        if not rows:
            return

        phase_order = [
            ("requirement", "requirement_analysis"),
            ("design", "design"),
            ("development", "development"),
            ("testing", "testing"),
            ("deployment", "deployment"),
        ]

        new_phase = "requirement_analysis"
        for task_type, phase_val in phase_order:
            phase_tasks = [r for r in rows if r["type"] == task_type]
            if phase_tasks and all(r["status"] == "completed" for r in phase_tasks):
                new_phase = phase_val
            elif phase_tasks:
                break

        # 全部完成
        all_done = all(r["status"] == "completed" for r in rows)
        if all_done:
            new_phase = "completed"

        with self._get_conn() as conn:
            conn.execute(
                "UPDATE projects SET current_phase = ? WHERE project_id = ?",
                (new_phase, project_id)
            )

    def _build_project_state(self, project_id: str) -> Optional[ProjectState]:
        """从数据库构建 ProjectState 对象"""
        with self._get_conn() as conn:
            proj = conn.execute(
                "SELECT * FROM projects WHERE project_id = ?",
                (project_id,)
            ).fetchone()
            if not proj:
                return None

            task_rows = conn.execute(
                "SELECT * FROM tasks WHERE project_id = ?",
                (project_id,)
            ).fetchall()

        # 重建 Requirement
        req = None
        if proj["requirement_json"]:
            try:
                req = Requirement.model_validate_json(proj["requirement_json"])
            except Exception:
                try:
                    req = Requirement.parse_raw(proj["requirement_json"])
                except Exception:
                    req = Requirement(
                        id=proj["requirement_id"] or "unknown",
                        description=proj["description"] or "",
                        project_name=proj["name"],
                    )

        # 重建 Tasks
        task_dict = {}
        for r in task_rows:
            deps = json.loads(r["dependencies"] or "[]")
            result_data = json.loads(r["result"]) if r["result"] else None
            task = Task(
                id=r["id"],
                name=r["name"],
                description=r["description"] or "",
                type=r["type"],
                status=r["status"],
                assigned_agent=r["assigned_agent"],
                priority=r["priority"] or "medium",
                estimated_hours=r["estimated_hours"],
                dependencies=deps,
                result=result_data,
                error_message=r["error_message"],
            )
            task_dict[r["id"]] = task

        return ProjectState(
            project_id=project_id,
            requirements=req,
            tasks=task_dict,
            current_phase=proj["current_phase"],
            global_context=json.loads(proj["global_context"] or "{}"),
            created_at=datetime.fromisoformat(proj["created_at"]),
            updated_at=datetime.fromisoformat(proj["updated_at"]),
        )

    def _build_task(self, task_id: str, project_id: str) -> Optional[Task]:
        """从数据库构建单个 Task"""
        with self._get_conn() as conn:
            r = conn.execute(
                "SELECT * FROM tasks WHERE id = ? AND project_id = ?",
                (task_id, project_id)
            ).fetchone()
        if not r:
            return None

        return Task(
            id=r["id"],
            name=r["name"],
            description=r["description"] or "",
            type=r["type"],
            status=r["status"],
            assigned_agent=r["assigned_agent"],
            priority=r["priority"] or "medium",
            estimated_hours=r["estimated_hours"],
            dependencies=json.loads(r["dependencies"] or "[]"),
            result=json.loads(r["result"]) if r["result"] else None,
            error_message=r["error_message"],
        )
