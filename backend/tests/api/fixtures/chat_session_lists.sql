-- 合成会话；只需要列表使用的列。脚本结束后启用只读模式。
CREATE TABLE chat_sessions (
    id TEXT PRIMARY KEY, project_id TEXT, title TEXT, source TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE chat_messages (id TEXT PRIMARY KEY, project_id TEXT, session_id TEXT);
INSERT INTO chat_sessions VALUES
    ('a-new', 'alpha', '分镜讨论', 'chat', '2026-01-01', '2026-01-04'),
    ('a-empty', 'alpha', '空白草案', 'group', '2026-01-01', '2026-01-02'),
    ('b-one', 'beta', '音效记录', 'chat', '2026-01-01', '2026-01-03'),
    ('g-one', NULL, '全局备忘', 'chat', '2026-01-01', '2026-01-05');
INSERT INTO chat_messages VALUES
    ('m1', 'alpha', 'a-new'), ('m2', 'alpha', 'a-new'), ('m3', '__global__', 'g-one'),
    ('m4', 'beta', 'b-one'),
    -- 两条历史归属不一致的数据，以及一条没有会话的旧消息；均不应增加列表计数。
    ('m5', 'beta', 'a-new'), ('m6', 'beta', 'g-one'), ('m7', 'alpha', NULL);
WITH RECURSIVE seq(i) AS (VALUES(1) UNION ALL SELECT i+1 FROM seq WHERE i<51)
INSERT INTO chat_sessions
SELECT printf('bulk-%02d',i), 'bulk', '批次样本', 'chat', '2026-01-01', '2026-01-01' FROM seq;
PRAGMA query_only=ON;
