"""时间轴阶段标注（树形分组的数据源）回归

    cd backend && python _test_timeline_stage.py

测的是 build_stage_index + _annotate_timeline_stages，重点在两个易错点：

  ① 不能用 build_pipeline_stages 的 in_statuses 做映射源 —— 那份数据被
     「返工阶段启发式」筛过，UE SOP 的 testing 组里只剩 play_test_*，
     ue_test_gen_passed / engine_compile_passed 全不在。拿它映射，一张 UE 工单
     最忙那段会集体掉进「未归类」。这里直接断言这些状态能查到。
  ② 覆盖率。thought_start / llm_call / checkpoint 这类日志既没 action 映射也没
     status（实测占全库九成），必须靠「继承前一条」兜住，否则树建了也没用。
"""
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

UE_TRAITS = ["platform:desktop", "category:game", "engine:ue5", "lang:cpp", "vcs:git"]
WEB_TRAITS = ["platform:web", "category:service", "lang:python", "vcs:git"]
TICKET_ID = "TK-20260918-23a48b"   # 真跑过的 UE 工单（含 114 轮死循环日志）

_pass, _fail = 0, 0
_lines = []


def check(name, cond, detail=""):
    global _pass, _fail
    if cond:
        _pass += 1
        _lines.append(f"[OK] {name}" + (f" -- {detail}" if detail else ""))
    else:
        _fail += 1
        _lines.append(f"[FAIL] {name}" + (f" -- {detail}" if detail else ""))


def test_index():
    from sop.loader import build_pipeline_stages, build_stage_index, compose_sop

    cfg = compose_sop(traits=UE_TRAITS)
    idx = build_stage_index(cfg)

    check("groups 非空且带 key/name", bool(idx["groups"])
          and all(g.get("key") and g.get("name") for g in idx["groups"]),
          f"{len(idx['groups'])} 组")

    # groups 顺序 = pipeline_view 声明序（树干顺序靠它）
    declared = [u["key"] for u in (cfg.get("pipeline_view") or {}).get("stages", [])]
    check("groups 保持 pipeline_view 声明序",
          [g["key"] for g in idx["groups"]] == declared)

    # 每个 SOP stage 的 action 和 trigger_on 都要能查到
    for s in cfg["stages"]:
        act, trg = s.get("action"), s.get("trigger_on")
        if act:
            check(f"action 可查: {act}", act in idx["by_action"])
        if trg:
            check(f"trigger_on 可查: {trg}", trg in idx["by_from_status"])

    # ① 关键：这些状态在 in_statuses 里查不到，在这里必须查得到
    pv = build_pipeline_stages(cfg)
    in_all = set()
    for d in pv["defs"]:
        in_all |= set(d.get("in_statuses") or [])
    for st in ("ue_test_gen_passed", "engine_compile_passed"):
        check(f"{st} 能映射到 SOP 阶段", st in idx["by_from_status"], st)
        # 顺带把「为什么不能用 in_statuses」钉住：真哪天 in_statuses 覆盖全了，
        # 这条会红，提醒人回来重新评估，而不是让注释里的理由悄悄过期。
        check(f"{st} 确实不在 in_statuses 里（用它做映射会漏）",
              st not in in_all)

    # ue_test_gen / engine_compile / play_test 应归到同一个 UI 组
    gs = {sid: idx["by_action"][a]["group"]
          for sid, a in (("ue_test_gen", "generate_ue_tests"),
                         ("engine_compile", "run_engine_compile"),
                         ("play_test", "run_playtest"))}
    check("UE 三个测试阶段同属一个 UI 组", len(set(gs.values())) == 1, str(gs))

    # pipeline_view 没覆盖的 stage → group 为 None，不许乱塞
    check("planning 未被硬塞进某个组",
          idx["by_action"].get("write_prd", {}).get("group") is None,
          str(idx["by_action"].get("write_prd", {}).get("group")))
    check("deploy 未被硬塞进某个组",
          idx["by_action"].get("deploy", {}).get("group") is None,
          str(idx["by_action"].get("deploy", {}).get("group")))

    # web SOP 也得能建（不是只对 UE 生效）
    widx = build_stage_index(compose_sop(traits=WEB_TRAITS))
    check("web SOP 也能建索引", bool(widx["by_action"]) and bool(widx["groups"]),
          f"{len(widx['by_action'])} action / {len(widx['groups'])} 组")

    # 空配置不许炸
    empty = build_stage_index({})
    check("空配置返回空索引不报错",
          empty["groups"] == [] and empty["by_action"] == {})
    # 没有 pipeline_view 时仍要能按 stage 映射（group 全 None）
    nopv = build_stage_index({"stages": cfg["stages"]})
    check("无 pipeline_view 时仍能映射 stage（group 为 None）",
          bool(nopv["by_action"])
          and all(v["group"] is None for v in nopv["by_action"].values()))


async def test_annotate():
    from database import db
    from api.tickets import _annotate_timeline_stages, get_ticket_timeline
    await db.connect()
    try:
        t = await db.fetch_one("SELECT id FROM tickets WHERE id = ?", (TICKET_ID,))
        if not t:
            _lines.append(f"[SKIP] 工单 {TICKET_ID} 不在库里，跳过真实数据用例")
            return

        data = await get_ticket_timeline(TICKET_ID)
        items = data["timeline"]
        check("接口返回 stage_groups", bool(data.get("stage_groups")),
              f"{len(data.get('stage_groups') or [])} 组")

        tagged = [i for i in items if i.get("_stage")]
        exact = [i for i in tagged if i.get("_stage_exact")]
        cov = len(tagged) * 100 / max(1, len(items))
        _lines.append(f"     真实数据: {len(items)} 条, 已标注 {len(tagged)} "
                      f"({cov:.1f}%), 其中精确命中 {len(exact)}")
        # ② 覆盖率：靠继承兜住无 action / 无 status 的大多数
        check("标注覆盖率 > 95%", cov > 95, f"{cov:.1f}%")
        check("存在精确命中的锚点", len(exact) >= 5, f"{len(exact)} 条")
        check("精确命中只是少数（其余靠继承）", len(exact) < len(tagged))

        # 首条日志之前没有锚点 → 允许未标注；但不能整体没标
        check("每个标注条目都带 group 或明确为 None",
              all("_stage_group" in i for i in tagged))

        # 阶段序列应当单调推进（同一阶段的日志连续成段，不来回跳）
        seq = [i["_stage"] for i in items if i.get("_stage")]
        segs = [s for k, s in enumerate(seq) if k == 0 or s != seq[k - 1]]
        check("同阶段日志连续成段（段数远小于条目数）",
              len(segs) < len(seq) / 10, f"{len(segs)} 段 / {len(seq)} 条")
        _lines.append("     阶段推进: " + " → ".join(segs[:12])
                      + (" …" if len(segs) > 12 else ""))

        # 排序后标注：时间必须仍是升序（防止有人把标注挪到 sort 之前）
        ts = [i.get("created_at") or "" for i in items]
        check("标注后仍按时间升序", ts == sorted(ts))

        # 无 traits 的项目 → 原样返回，不报错（老 web 项目走这条）
        empty_items = [{"_type": "log", "action": "complete", "from_status": "x"}]
        out, groups = await _annotate_timeline_stages("TK-NOT-EXIST", empty_items)
        check("未知工单不报错且不标注",
              out is empty_items and groups == [] and "_stage" not in out[0])
    finally:
        await db.disconnect()   # aiosqlite 后台线程不断开会吊住进程


def main():
    test_index()
    asyncio.run(test_annotate())
    _lines.append(f"\n=== {_pass} passed / {_fail} failed ===")
    (BACKEND / "_tl_stage_out.txt").write_text("\n".join(_lines), encoding="utf-8")
    print(f"pass={_pass} fail={_fail}")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
