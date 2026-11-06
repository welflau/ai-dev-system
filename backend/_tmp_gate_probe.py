import json
import sqlite3
import urllib.request
from pathlib import Path

pid = "PRJ-20261102-205a67"
tid = "TK-20261102-2560c5"
base = "http://127.0.0.1:8000"

def get(path):
    with urllib.request.urlopen(base + path, timeout=15) as r:
        return json.load(r)

d = get(f"/api/projects/{pid}/tickets/{tid}")
print("status", d.get("status"), "agent", d.get("assigned_agent"))
print("current_action", d.get("current_action"))
print("updated_at", d.get("updated_at"))
pg = d.get("pending_gate")
if pg is None:
    print("pending_gate None")
else:
    print("pending_gate", {
        k: pg.get(k)
        for k in ["title", "ticket_id", "session_id", "_message_id", "_state", "preview_paths", "summary"]
    })
print("output_files", d.get("output_files"))

try:
    ca = get(f"/api/projects/{pid}/tickets/{tid}/current-action")
    print("current-action", {k: ca.get(k) for k in [
        "current_action", "health", "elapsed_ms", "silence_ms", "latest_log", "started_at", "latest_log_at"
    ]})
except Exception as e:
    print("current-action fail", e)

try:
    logs = get(f"/api/tickets/{tid}/logs")
    items = logs.get("logs") or logs.get("items") or []
    print("logs", len(items))
    for row in items[-12:]:
        print(" ", row.get("created_at"), row.get("agent_type"), row.get("action"),
              str(row.get("message") or row.get("detail") or "")[:160])
except Exception as e:
    print("logs fail", e)

dbp = Path(r"F:\A_Works\ai-dev-system\backend\data\ai_dev_system.db")
con = sqlite3.connect(dbp)
con.row_factory = sqlite3.Row
row = con.execute(
    "SELECT status, assigned_agent, current_action, current_action_started_at, "
    "current_action_latest_log, current_action_updated_at, updated_at, "
    "substr(result,1,800) AS result FROM tickets WHERE id=?",
    (tid,),
).fetchone()
print("\n--- db ticket ---")
if row:
    print(dict(row))

print("\n--- waiting markers ---")
repo = con.execute("SELECT git_repo_path FROM projects WHERE id=?", (pid,)).fetchone()
print("repo", dict(repo) if repo else None)
if repo and repo["git_repo_path"]:
    works = Path(repo["git_repo_path"]) / "works"
    if works.is_dir():
        for p in sorted(works.glob("*/.ads-waiting-human.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                print(p, "read fail", e)
                continue
            print(str(p), {k: data.get(k) for k in [
                "waiting_human", "title", "ticket_id", "preview_paths", "message", "_state"
            ]})

print("\n--- confirm_video_gate ---")
for r in con.execute(
    """SELECT id, action_state, substr(action_data,1,300) AS ad, created_at
       FROM chat_messages
       WHERE project_id=? AND action_type='confirm_video_gate'
       ORDER BY created_at DESC LIMIT 8""",
    (pid,),
):
    print(dict(r))
