"""清掉 orchestrator 死循环产生的垃圾 code artifact，只保留 develop 阶段真正那条。

背景：generate_ue_tests 在 orchestrator 里缺结果分支，掉进 develop 的收尾，
每轮都往 artifacts 插一条 type='code'（内容是 ue_test_gen 的返回，没有 files）。
_build_context 取**最后一条** code artifact 当 dev_result，于是 dev_result 被污染。
修复已在 orchestrator.py 落地，这里只清历史脏数据。
"""
import json
import sqlite3
import sys

DB = "F:/A_Works/ai-dev-system/backend/data/ai_dev_system_new.db"
TICKET = sys.argv[1] if len(sys.argv) > 1 else "TK-20260918-23a48b"

conn = sqlite3.connect(DB)
rows = conn.execute(
    "SELECT id, content FROM artifacts WHERE ticket_id=? AND type='code' ORDER BY created_at",
    (TICKET,),
).fetchall()
if not rows:
    print("no code artifacts")
    sys.exit(0)

keep_id, keep_content = rows[0]
d = json.loads(keep_content)
files = list((d.get("files") or {}))
# 安全闸：保留的那条必须真是 develop 产出（带 files），否则不动任何东西
if not files:
    print(f"ABORT: 最早一条 code artifact 没有 files，不敢删。keys={list(d)[:10]}")
    sys.exit(1)

n = conn.execute(
    "DELETE FROM artifacts WHERE ticket_id=? AND type='code' AND id<>?",
    (TICKET, keep_id),
).rowcount
conn.commit()
print(f"deleted={n} kept={keep_id}")
print(f"kept files={files}")
conn.close()
