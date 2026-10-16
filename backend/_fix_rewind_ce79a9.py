"""一次性：把 TK-20260920-ce79a9 从假成功的 deployed 回退到 architecture_done 重跑。

    cd backend && python _fix_rewind_ce79a9.py          # 预演，只打印不写
    cd backend && python _fix_rewind_ce79a9.py --apply  # 真写

为什么要单独写个脚本，而不是走 reset_phases / PATCH status：
两条正规路径**都会正确地拒绝**，而它们拒绝得有道理，不该为一张工单去松：

  - `orchestrator._rewind_ticket_status` 查 `_HARD_TERMINAL`，`deployed` 在里面 ——
    这个守卫防的是「已交付的工单被后续流程悄悄改状态」。
  - `models.TICKET_TRANSITIONS[DEPLOYED] == [PENDING]`，所以
    `validate_ticket_transition('deployed', 'architecture_done')` 是 False ——
    状态机不允许从终态往回跳到中间态。

这是一次**人工数据订正**，不是一条该被产品化的流程：它之所以需要，
是因为六道闸门修好之前那张工单**本来就不该走到 deployed**。
闸门已经修了（见 dev-notes/2026-09-20_02），同样的假成功不会再发生，
所以没必要为它开一条通用后门。
"""
import sqlite3
import sys
from datetime import datetime

TICKET = "TK-20260920-ce79a9"
PROJECT = "PRJ-20260920-097430"
TARGET = "architecture_done"          # development 阶段的 trigger_on

# 假成功**之后**产生的产物才删。PRD（00:46）和架构（00:48）是开发阶段挂掉
# 之前正常产出的，删了等于让工单白跑两轮。
STALE_ARTIFACT_TYPES = ("code_review", "deploy_config")

APPLY = "--apply" in sys.argv
DB = r"F:\A_Works\ai-dev-system\backend\data\ai_dev_system_new.db"


def main():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    now = datetime.now().isoformat()

    t = c.execute("SELECT * FROM tickets WHERE id = ?", (TICKET,)).fetchone()
    if not t:
        print(f"找不到工单 {TICKET}")
        return 1
    t = dict(t)
    print(f"工单 {TICKET}")
    print(f"  标题     {t['title']}")
    print(f"  当前状态 {t['status']}  →  {TARGET}")
    print(f"  项目     {t['project_id']}  需求 {t['requirement_id']}")

    if t["status"] != "deployed":
        print(f"\n状态已不是 deployed（现为 {t['status']}），不重复回退。")
        return 0

    stale = c.execute(
        "SELECT id, type, name FROM artifacts WHERE ticket_id = ? AND type IN (%s)"
        % ",".join("?" * len(STALE_ARTIFACT_TYPES)),
        (TICKET, *STALE_ARTIFACT_TYPES),
    ).fetchall()
    keep = c.execute(
        "SELECT id, type FROM artifacts WHERE ticket_id = ? AND type NOT IN (%s)"
        % ",".join("?" * len(STALE_ARTIFACT_TYPES)),
        (TICKET, *STALE_ARTIFACT_TYPES),
    ).fetchall()

    print(f"\n将删除 {len(stale)} 个假成功之后的产物：")
    for a in stale:
        print(f"    - {a['type']:16} {a['id']}")
    print(f"  保留 {len(keep)} 个（开发挂掉之前正常产出的）：")
    for a in keep:
        print(f"    · {a['type']:16} {a['id']}")

    subs = c.execute(
        "SELECT status, COUNT(*) n FROM subtasks WHERE ticket_id = ? GROUP BY status",
        (TICKET,)).fetchall()
    print(f"  子任务状态：{{{', '.join(f'{s[0]}: {s[1]}' for s in subs)}}}（已是 pending，不动）")

    # 需求侧：`_check_requirement_completion` 只会往 completed **升**，从不往回降
    # （`all_done` 为假时它什么都不做）。所以工单退回去之后，需求会一直挂着
    # 「已完成」，而它下面有张工单正在重跑 —— 又是一个「状态说成了、其实没成」。
    req = c.execute("SELECT id, status FROM requirements WHERE id = ?",
                    (t["requirement_id"],)).fetchone()
    req_needs_reopen = req and req["status"] == "completed"
    if req_needs_reopen:
        siblings = c.execute(
            "SELECT id, status FROM tickets WHERE requirement_id = ? AND id != ? "
            "AND status != 'cancelled'", (t["requirement_id"], TICKET)).fetchall()
        print(f"\n  需求 {req['id']} 当前 completed → in_progress")
        print(f"    （同需求另外 {len(siblings)} 张工单仍是 "
              f"{{{', '.join(sorted({s['status'] for s in siblings}))}}}，不动）")

    if not APPLY:
        print("\n[预演] 未写库。确认无误后加 --apply 重跑。")
        return 0

    c.execute(
        "UPDATE tickets SET status = ?, completed_at = NULL, updated_at = ? WHERE id = ?",
        (TARGET, now, TICKET))
    for a in stale:
        c.execute("DELETE FROM artifacts WHERE id = ?", (a["id"],))
    if req_needs_reopen:
        c.execute(
            "UPDATE requirements SET status = 'in_progress', completed_at = NULL, "
            "updated_at = ? WHERE id = ?", (now, t["requirement_id"]))

    # 时间轴留痕：不是偷偷改库，用户在工单页要能看见这次订正。
    # 注意 ticket_logs **没有** message 列 —— 文案是放在 detail JSON 的 message 键里的。
    import uuid
    import json
    c.execute(
        "INSERT INTO ticket_logs (id, project_id, requirement_id, ticket_id, agent_type, "
        " action, from_status, to_status, detail, level, layer, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), t["project_id"], t["requirement_id"], TICKET, "Human",
         "phase_rewind", "deployed", TARGET,
         json.dumps({
             "message": (
                 f"人工回退：该工单是假成功（开发阶段 LLM 返回 tokens 0→0，"
                 f"规则兜底写了个 console.log 空壳就判成功），"
                 f"六道闸门修复后退回 {TARGET} 重跑"
             ),
             "reason": "false_success_remediation",
             "devnote": "dev-notes/2026-09-20_02_假成功链路六道闸门.md",
             "removed_artifacts": [a["id"] for a in stale],
             "requirement_reopened": bool(req_needs_reopen),
         }, ensure_ascii=False),
         "warning", "harness", now))
    c.commit()

    after = c.execute("SELECT status FROM tickets WHERE id = ?", (TICKET,)).fetchone()[0]
    print(f"\n✅ 已回退：status = {after}，删除 {len(stale)} 个产物，时间轴留痕一条。")
    if req_needs_reopen:
        rs = c.execute("SELECT status FROM requirements WHERE id = ?",
                       (t["requirement_id"],)).fetchone()[0]
        print(f"   需求 {t['requirement_id']} → {rs}")
    print("   后端下一轮 poll（30s）会重新派单给 DevAgent。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
