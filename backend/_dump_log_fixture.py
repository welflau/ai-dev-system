"""从真实 DB 导出几个代表性工单的日志，给 _test_log_task_link.js 当样本。

为什么要真实数据：上一版链接功能的测试全用构造日志，测的是"我以为日志长什么样"，
结果真实的 UE 工单里 UBT 编译是 action=complete 带 command 无文件，一条都没覆盖到。
固化成 fixture 后，以后改建表规则会立刻发现哪类真实日志掉链子。

    cd backend && python _dump_log_fixture.py
"""
import asyncio, json, sys
sys.path.insert(0, '.')

# 挑选依据：覆盖不同形态，不是挑"日志最多的"
TARGETS = {
    # UE 工单：UBT 编译 + Playtest（complete 带 command 无文件）+ ToolError
    'TK-20260722-8d570f': {'expect_min': 4, 'expect_actions': ['complete', 'ToolError']},
    # UE 工单：ToolError 为主
    'TK-20260722-0188c8': {'expect_min': 3, 'expect_actions': ['ToolError']},
    # 完整跑通的 UE 工单：tool_done + 编译 complete + thought_done 带产出
    'TK-20260918-23a48b': {'expect_min': 6, 'expect_actions': ['tool_done', 'complete']},
    # 早期 web 工单：tool_done 连发 + reject 补编译详情
    'TK-20260731-9df2b4': {'expect_min': 5, 'expect_actions': ['tool_done']},
}

KEEP = ('id', 'ticket_id', 'action', 'agent_type', 'level', 'detail', 'created_at')


async def main():
    from database import db
    await db.connect()
    try:
        out = {}
        for tid, meta in TARGETS.items():
            rows = await db.fetch_all(
                "SELECT * FROM ticket_logs WHERE ticket_id = ? ORDER BY created_at ASC", (tid,))
            if not rows:
                print(f"跳过 {tid}（库里没有）")
                continue
            logs = []
            for r in rows:
                d = dict(r)
                logs.append({k: d.get(k) for k in KEEP})
            out[tid] = {**meta, 'logs': logs}
            print(f"{tid}: {len(logs)} 条")
        with open('_fixture_ticket_logs.json', 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"已写入 _fixture_ticket_logs.json（{len(out)} 个工单）")
    finally:
        await db.disconnect()


asyncio.run(main())
