"""
v0.19.x CI/CD 合并改造 —— Phase A+B+C+D 完整 smoke test

验证：
  Phase A: CIStrategy loader 注册 web / ue / default；按 traits 分派
  Phase C: UECIStrategy 元数据正确（stages / envs / build_types 差异化）
  Phase D: SOP deploy_web / deploy_ue fragment 能被 compose 进 UE / Web 项目的 SOP
           DeployAgent.run_ci_deploy dispatch 存在

用法：
    cd backend && python _test_v019_ci_phase_abcd.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")


def _banner(msg: str):
    print()
    print("=" * 70)
    print(f"  {msg}")
    print("=" * 70)


async def main():
    passed, failed = 0, 0

    def check(name: str, ok: bool, detail: str = ""):
        nonlocal passed, failed
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {name}" + (f"  -- {detail}" if detail else ""))
        if ok:
            passed += 1
        else:
            failed += 1

    from database import db
    from ci.loader import ci_loader
    from ci.strategies.ue import UECIStrategy
    from ci.strategies.web import WebCIStrategy
    from utils import generate_id, now_iso

    await db.connect()

    # =========== A1. 策略注册 ===========
    _banner("A1. Loader 注册 web / ue / default")
    ci_loader.load_all()
    names = [s.name for s in ci_loader.all_strategies()]
    check("含 web", "web" in names)
    check("含 ue", "ue" in names, f"names={names}")
    check("含 default", "default" in names)
    # UE priority 应 > Web
    web_inst = next(s for s in ci_loader.all_strategies() if s.name == "web")
    ue_inst = next(s for s in ci_loader.all_strategies() if s.name == "ue")
    check("UE priority > Web priority",
          ue_inst.priority > web_inst.priority,
          f"ue={ue_inst.priority} web={web_inst.priority}")

    # =========== A2. trait 分派 ===========
    _banner("A2. trait 分派正确")
    pid_web = generate_id("PRJ")
    await db.insert("projects", {
        "id": pid_web, "name": "PhaseABCDWeb", "description": "",
        "status": "active", "tech_stack": "", "config": "{}",
        "git_repo_path": "D:/Projects/_web", "git_remote_url": "",
        "traits": json.dumps(["platform:web", "category:app"]),
        "traits_confidence": "{}", "preset_id": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    })
    pid_ue = generate_id("PRJ")
    await db.insert("projects", {
        "id": pid_ue, "name": "PhaseABCDUE", "description": "",
        "status": "active", "tech_stack": "", "config": "{}",
        "git_repo_path": "D:/Projects/_ue", "git_remote_url": "",
        "traits": json.dumps(["platform:desktop", "category:game", "engine:ue5"]),
        "traits_confidence": "{}", "preset_id": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    })
    pid_empty = generate_id("PRJ")
    await db.insert("projects", {
        "id": pid_empty, "name": "PhaseABCDEmpty", "description": "",
        "status": "active", "tech_stack": "", "config": "{}",
        "git_repo_path": "D:/Projects/_empty", "git_remote_url": "",
        "traits": "[]", "traits_confidence": "{}", "preset_id": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    })

    s_web = await ci_loader.pick_for_project(pid_web)
    s_ue = await ci_loader.pick_for_project(pid_ue)
    s_def = await ci_loader.pick_for_project(pid_empty)
    check("Web 项目 → web 策略", s_web.name == "web", f"got={s_web.name}")
    check("UE 项目 → ue 策略", s_ue.name == "ue", f"got={s_ue.name}")
    check("空 traits → default", s_def.name == "default")

    # =========== C1. UE 策略元数据差异化 ===========
    _banner("C1. UE 策略 stages / envs / build_types 跟 Web 完全不同")
    ue_stages = {s.id for s in s_ue.pipeline_stages()}
    web_stages = {s.id for s in s_web.pipeline_stages()}
    check("UE 含 ubt_compile stage", "ubt_compile" in ue_stages)
    check("UE 含 playtest stage", "playtest" in ue_stages)
    check("UE 含 package_client stage", "package_client" in ue_stages)
    check("Web 不含 UE 专属 stage",
          not (web_stages & {"ubt_compile", "playtest", "package_client"}),
          f"web_stages={web_stages}")

    ue_envs = {e.name for e in s_ue.environment_specs()}
    web_envs = {e.name for e in s_web.environment_specs()}
    check("UE envs 含 packaged_win64", "packaged_win64" in ue_envs)
    check("UE envs 含 editor_live", "editor_live" in ue_envs)
    check("Web envs 仍是 dev/test/prod",
          web_envs == {"dev", "test", "prod"},
          f"web_envs={web_envs}")

    ue_bts = {b.id for b in s_ue.build_types()}
    check("UE build_types 含 ubt_compile / playtest / package_client",
          ue_bts == {"ubt_compile", "playtest", "package_client"},
          f"ue_bts={ue_bts}")

    # =========== C2. to_definition 结构可被前端消费 ===========
    _banner("C2. to_definition() 结构")
    ue_def = s_ue.to_definition()
    check("UE def.strategy=ue", ue_def.get("strategy") == "ue")
    check("UE def.stages 有 4 条", len(ue_def.get("stages") or []) == 4)
    check("UE def.environments 有 3 条", len(ue_def.get("environments") or []) == 3)
    check("UE def.build_types 有 3 条", len(ue_def.get("build_types") or []) == 3)
    check("UE def.required_traits 含 engine:ue5",
          "engine:ue5" in (ue_def.get("required_traits") or {}).get("any_of", []))

    # =========== D1. SOP fragment deploy_web/deploy_ue 被装配 ===========
    _banner("D1. SOP compose 对 Web / UE 项目装配出对应 deploy fragment")
    from sop.loader import compose_sop

    web_cfg = compose_sop(traits=["platform:web", "category:app"], ticket_type="feature")
    web_frag_ids = {f.get("id") for f in (web_cfg.get("_applied_fragments") or [])} \
                   if "_applied_fragments" in web_cfg else set()
    web_stage_ids = {s.get("id") for s in (web_cfg.get("stages") or [])}
    check("Web SOP 含 deploy_web 阶段",
          "deploy_web" in web_stage_ids,
          f"stages={sorted(web_stage_ids)}")

    ue_cfg = compose_sop(
        traits=["platform:desktop", "category:game", "engine:ue5", "lang:cpp"],
        ticket_type="feature",
    )
    ue_stage_ids = {s.get("id") for s in (ue_cfg.get("stages") or [])}
    check("UE SOP 含 deploy_ue 阶段",
          "deploy_ue" in ue_stage_ids,
          f"ue_stages={sorted(ue_stage_ids)}")
    check("UE SOP 同时有 engine_compile + play_test + deploy_ue",
          {"engine_compile", "play_test", "deploy_ue"}.issubset(ue_stage_ids))

    # =========== D2. DeployAgent.run_ci_deploy dispatch 存在 ===========
    _banner("D2. DeployAgent.run_ci_deploy dispatch")
    from agents.deploy import DeployAgent
    agent = DeployAgent()
    check("DeployAgent 有 run_ci_deploy 方法",
          hasattr(agent, "run_ci_deploy") and callable(agent.run_ci_deploy))
    bad = await agent.execute("nonexistent", {})
    check("未知 task 返回 error", bad.get("status") == "error")

    # =========== D3. SOP 派生规则（Phase D 跟 v0.18 reject_goto 体系协同）===========
    _banner("D3. SOP 派生 transition rules 含 deploy 相关")
    from sop.loader import sop_to_transition_rules
    ue_rules = sop_to_transition_rules(ue_cfg)
    check("UE SOP 规则含 packaging_failed（由 reject_status/reject_goto 派生）",
          "packaging_failed" in ue_rules)
    if "packaging_failed" in ue_rules:
        r = ue_rules["packaging_failed"]
        check("packaging_failed → DevAgent", r.get("agent") == "DevAgent")
        check("packaging_failed → fix_issues", r.get("action") == "fix_issues")

    web_rules = sop_to_transition_rules(web_cfg)
    # 规则 key 是前一 stage 的 success_status（不是本 stage 的 trigger_on），
    # 检查某条规则 dispatch 到 DeployAgent.run_ci_deploy 即可
    web_has_ci_deploy = any(
        r.get("agent") == "DeployAgent" and r.get("action") == "run_ci_deploy"
        for r in web_rules.values()
    )
    check("Web SOP 有规则 dispatch 到 DeployAgent.run_ci_deploy",
          web_has_ci_deploy,
          f"rules keys sample={sorted(list(web_rules))[:10]}")
    ue_has_ci_deploy = any(
        r.get("agent") == "DeployAgent" and r.get("action") == "run_ci_deploy"
        for r in ue_rules.values()
    )
    check("UE SOP 有规则 dispatch 到 DeployAgent.run_ci_deploy", ue_has_ci_deploy)

    # =========== 清理 ===========
    _banner("清理")
    for p in (pid_web, pid_ue, pid_empty):
        try:
            await db.execute("DELETE FROM projects WHERE id = ?", (p,))
        except Exception:
            pass

    _banner("Summary")
    total = passed + failed
    print(f"  PASS {passed}/{total}  FAIL {failed}/{total}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
