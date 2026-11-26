"""读取会话摘要；全局会话与全局消息在旧表中使用不同的项目标记。"""
from database import db


async def fetch_session_summaries(project_id: str | None, limit: int):
    message_project = "__global__" if project_id is None else project_id
    return await db.fetch_all(
        """SELECT s.id, s.title, s.source, s.created_at, s.updated_at,
                  COALESCE(c.message_count, 0) AS message_count
           FROM chat_sessions AS s
           LEFT JOIN (
               SELECT session_id, COUNT(id) AS message_count FROM chat_messages
               WHERE project_id = ? GROUP BY session_id
           ) AS c ON c.session_id = s.id
           WHERE s.project_id IS ?
           ORDER BY s.updated_at DESC, s.id ASC LIMIT ?""",
        (message_project, project_id, limit),
    )
