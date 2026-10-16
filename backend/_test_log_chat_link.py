"""时间轴日志 →「↗ 对话」定位：后端锚点标注回归（跑真实 DB）
    cd backend && python _test_log_chat_link.py

链接的全部价值在于**点下去一定能落到某条条目上**。所以这里不测"标了多少"，
测的是"标出来的每一个锚点，在对话接口返回的消息里都真实存在"—— 零死链。

为什么必须用真实 DB：「📟 后台记录」那版链接的测试全用构造日志，测的是
"我以为日志长什么样"，真实 UE 工单的形态一条都没覆盖到，全绿但功能是坏的。
"""
import asyncio
import sys
from collections import Counter

sys.path.insert(0, '.')

PASS = FAIL = 0


def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[OK] {name}" + (f" -- {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name}" + (f" -- {detail}" if detail else ""))


# 挑选依据：覆盖不同形态，不是挑日志最多的
# dd055e = OpenSpec 全流程；23a48b = 124 条 checkpoint（Feed 不收）；
# 8d570f = UE 工单无 llm_call；9df2b4 = 早期 web，18 条 skill_step_start + 6 条 llm_call
TICKETS = ('TK-20260810-dd055e', 'TK-20260918-23a48b',
           'TK-20260722-8d570f', 'TK-20260731-9df2b4')


async def main():
    from database import db
    await db.connect()
    try:
        from api.tickets import get_ticket_timeline, _annotate_chat_anchors
        from api.chat import get_ticket_conversations, FEED_LOG_ACTIONS

        # ── 1. 单一来源 ────────────────────────────────────────────
        check('FEED_LOG_ACTIONS 是可用集合', isinstance(FEED_LOG_ACTIONS, (set, frozenset))
              and len(FEED_LOG_ACTIONS) > 10, f"{len(FEED_LOG_ACTIONS)} 类 action")
        # Feed 端点和标注函数必须看同一份清单 —— 用 chat.py 的源码反查，
        # 端点里若又出现内联字面量，说明有人把清单复制回去了
        import inspect
        feed_src = inspect.getsource(get_ticket_conversations)
        check('Feed 端点只引用常量，没有内联的 action 字面量',
              'LOG_ACTIONS_SHOW = FEED_LOG_ACTIONS' in feed_src
              and '"thought_done"' not in feed_src)

        total_logs = total_anchored = total_dead = 0
        llm_total = llm_paired = 0

        for tid in TICKETS:
            row = await db.fetch_one("SELECT project_id FROM tickets WHERE id=?", (tid,))
            if not row:
                check(f'{tid} 存在于库中', False, '样本工单不见了，测试失去意义')
                continue

            tl = await get_ticket_timeline(tid)
            logs = [i for i in tl['timeline'] if i.get('_type') == 'log']
            anchored = [i for i in logs if i.get('_chat_anchor')]

            # 对话接口真实返回的可定位 id：事件条目 + LLM 气泡
            conv = await get_ticket_conversations(row['project_id'], tid)
            dom_ids = {m.get('id') for m in conv['messages']
                       if m.get('is_event') or m.get('is_agent')}

            dead = [i for i in anchored if i['_chat_anchor'] not in dom_ids]
            check(f'{tid} 零死链', not dead,
                  f"{len(anchored)}/{len(logs)} 条有锚点"
                  + (f"，死链 {len(dead)}: {[d['action'] for d in dead[:3]]}" if dead else ""))

            # Feed 白名单里的 action 一条都不能漏标 —— 漏了就是"明明能跳却没链接"
            missed = [i for i in logs
                      if i.get('action') in FEED_LOG_ACTIONS and not i.get('_chat_anchor')]
            check(f'{tid} 白名单内的 action 全部标了锚点', not missed,
                  f"漏标 {dict(Counter(i['action'] for i in missed))}" if missed else '')

            # 白名单内的锚点必须就是 ticket_logs.id（chat.py 里 `"id": lr["id"]`）
            wrong = [i for i in anchored
                     if i.get('action') in FEED_LOG_ACTIONS and i['_chat_anchor'] != i['id']]
            check(f'{tid} 事件锚点 == ticket_logs.id', not wrong)

            llm = [i for i in logs if i.get('action') == 'llm_call']
            lok = [i for i in llm if i.get('_chat_anchor')]
            if llm:
                check(f'{tid} llm_call 配到了 LLM 回复', len(lok) == len(llm),
                      f"{len(lok)}/{len(llm)}")
                check(f'{tid} llm_call 锚点指向回复气泡（_resp 后缀）',
                      all(i['_chat_anchor'].endswith('_resp') for i in lok))
            llm_total += len(llm)
            llm_paired += len(lok)

            total_logs += len(logs)
            total_anchored += len(anchored)
            total_dead += len(dead)

        check('全样本零死链', total_dead == 0,
              f"{total_anchored}/{total_logs} 条日志可定位")
        check('llm_call 全部配上', llm_total and llm_paired == llm_total,
              f"{llm_paired}/{llm_total}")

        # ── 2. 配不上就不标（宁缺毋滥）────────────────────────────
        # 造一条时间上离所有 conversation 都很远的 llm_call，必须不标锚点
        tid = TICKETS[0]
        fake = [{'_type': 'log', 'id': 'LOG-fake', 'action': 'llm_call',
                 'created_at': '1999-01-01T00:00:00'}]
        out = await _annotate_chat_anchors(tid, fake)
        check('时间配不上的 llm_call 不标锚点（宁缺毋滥）',
              not out[0].get('_chat_anchor'))

        # 白名单外的 action 不标
        fake2 = [{'_type': 'log', 'id': 'LOG-x', 'action': 'checkpoint',
                  'created_at': '2026-08-10T00:00:00'}]
        out2 = await _annotate_chat_anchors(tid, fake2)
        check('白名单外的 action 不标锚点（checkpoint 等）',
              not out2[0].get('_chat_anchor'))

        # 评论条目不该被标（它们走 locateInTicketFeed 那条老路）
        fake3 = [{'_type': 'comment', 'id': 'CMT-x', 'created_at': '2026-08-10T00:00:00'}]
        out3 = await _annotate_chat_anchors(tid, fake3)
        check('评论条目不标锚点（评论有自己的定位入口）',
              not out3[0].get('_chat_anchor'))

        # 没有 llm_call 时不该白查一次 llm_conversations（省一次全表扫）
        # 用不存在的工单 id 调：能正常返回说明没依赖查询结果
        out4 = await _annotate_chat_anchors('TK-NOT-EXIST', [
            {'_type': 'log', 'id': 'L1', 'action': 'complete', 'created_at': '2026-01-01T00:00:00'}])
        check('工单查不到时也能标（不依赖 llm_conversations 有行）',
              out4[0].get('_chat_anchor') == 'L1')

    finally:
        await db.disconnect()   # 不 disconnect，aiosqlite 的后台线程会挂住进程

    print(f"\n=== {PASS} 通过 / {FAIL} 失败 ===")
    return 1 if FAIL else 0


sys.exit(asyncio.run(main()))
