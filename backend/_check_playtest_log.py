import sqlite3, sys, os
sys.stdout.reconfigure(encoding='utf-8')

db_path = os.path.join(os.path.dirname(__file__), 'data', 'ai_dev_system.db')
conn = sqlite3.connect(db_path)

# 取最新 playtest build id
row = conn.execute("SELECT id FROM ci_builds WHERE build_type='playtest' ORDER BY created_at DESC LIMIT 1").fetchone()
build_id = row[0]
print("build_id:", build_id)

# 强制更新 error_message
test_msg = "TEST_游戏模块未编译_TEST"
conn.execute("UPDATE ci_builds SET error_message=? WHERE id=?", (test_msg, build_id))
conn.commit()

# 读回
row2 = conn.execute("SELECT error_message FROM ci_builds WHERE id=?", (build_id,)).fetchone()
print("after update:", repr(row2[0]))
conn.close()
