"""
v0.18 UE 深耕 —— 端到端 smoke test

跑完整条链路：引擎检测 → 模板实例化 → 编译 → SOP 规则验证。
跑 TP_Blank（最小模板，编译最快），不动任何实际项目仓库（用临时目录）。

用法：
    cd backend && python _test_ue_e2e_smoke.py
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")


TMP_DIR = Path("D:/Projects/_v018_smoke_test")


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
        print(f"  [{marker}] {name}" + (f"  — {detail}" if detail else ""))
        if ok:
            passed += 1
        else:
            failed += 1

    # =========== 1. 引擎检测 ===========
    _banner("1. UEEngineResolver")
    from engines.ue_resolver import (
        detect_installed_engines,
        resolve_project_engine,
        verify_engine,
        get_ubt_path,
        get_templates_dir,
    )
    engines = detect_installed_engines()
    check("detect_installed_engines 返回非空", len(engines) > 0, f"{len(engines)} 个引擎")
    launcher_engines = [e for e in engines if e.type == "launcher" and e.version.startswith("5.")]
    check("至少 1 个 UE5 launcher 可用", len(launcher_engines) > 0)
    # 挑 5.3 做实际测试（TestFPS 关联版本）
    ue53 = next((e for e in launcher_engines if e.version.startswith("5.3")), None)
    if not ue53:
        ue53 = launcher_engines[0]
    check("UE5.3 has_ubt", ue53.has_ubt, f"path={ue53.path}")

    # =========== 2. TestFPS 的引擎关联 ===========
    _banner("2. resolve_project_engine(TestFPS)")
    testfps_uproject = Path("D:/Projects/TestFPS/TestFPS.uproject")
    if testfps_uproject.exists():
        resolved = resolve_project_engine(str(testfps_uproject))
        check("resolve TestFPS .uproject", resolved is not None)
        if resolved:
            check("resolved engine type=launcher", resolved.type == "launcher")
            check("resolved has_ubt", resolved.has_ubt)
    else:
        print(f"  [SKIP] {testfps_uproject} 不存在")

    # =========== 3. trait → template 映射 ===========
    _banner("3. pick_template_by_traits")
    from actions.instantiate_ue_template import pick_template_by_traits
    cases = [
        (["engine:ue5", "category:game", "genre:fps"], "TP_FirstPerson"),
        (["engine:ue5", "category:game", "genre:third_person"], "TP_ThirdPerson"),
        (["engine:ue5", "category:game", "genre:racing"], "TP_VehicleAdv"),
        (["engine:ue5"], "TP_Blank"),
    ]
    for traits, expect in cases:
        got = pick_template_by_traits(traits)
        check(f"traits={traits[-1]} → {expect}", got == expect, f"got={got}")

    # =========== 4. InstantiateUETemplateAction（TP_Blank 最小） ===========
    _banner("4. InstantiateUETemplateAction (TP_Blank → SmokeTest)")
    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR)
    TMP_DIR.mkdir(parents=True)

    from actions.instantiate_ue_template import InstantiateUETemplateAction
    action = InstantiateUETemplateAction()
    log_lines = []

    async def _log_cb(line: str):
        log_lines.append(line)

    ctx = {
        "engine_path": ue53.path,
        "template_name": "TP_Blank",
        "target_dir": str(TMP_DIR),
        "project_name": "SmokeTest",
        "copy_content_assets": False,
        "log_callback": _log_cb,
    }
    result = await action.run(ctx)
    d = result.to_dict()
    check("实例化 status=success", d.get("status") == "success", d.get("message", ""))
    check("生成 >= 5 文件", (d.get("files_created") or 0) >= 5, f"files={d.get('files_created')}")
    check("log_callback 被调", len(log_lines) >= 3, f"{len(log_lines)} 条 log")
    check(".uproject 生成", Path(d.get("uproject_path", "")).is_file())

    # =========== 5. UECompileCheckAction（不真跑，只验证早期错误能推 log） ===========
    _banner("5. UECompileCheckAction 早期错误路径")
    from actions.ue_compile_check import UECompileCheckAction
    action = UECompileCheckAction()
    log_lines.clear()
    # 故意不给 engine_path 也不给 uproject，应该早期失败 + 推 log
    ctx = {"log_callback": _log_cb}
    result = await action.run(ctx)
    d = result.to_dict()
    check("缺参数场景返回 status=error", d.get("status") == "error")
    check("log_callback 收到 [ubt] 入参 log", any("入参" in l for l in log_lines))
    check("log_callback 收到 [error] log", any(l.startswith("[error]") for l in log_lines))

    # =========== 6. SOP reject_goto 规则派生 ===========
    _banner("6. sop_to_transition_rules 派生 fix_issues 回跳")
    from sop.loader import compose_sop, sop_to_transition_rules
    cfg = compose_sop(
        traits=["engine:ue5", "category:game", "genre:fps", "multiplayer:true", "vcs:git"],
        ticket_type="feature",
    )
    rules = sop_to_transition_rules(cfg)
    check(
        "engine_compile_failed → DevAgent.fix_issues",
        rules.get("engine_compile_failed", {}).get("action") == "fix_issues",
    )
    check(
        "play_test_failed → DevAgent.fix_issues",
        rules.get("play_test_failed", {}).get("action") == "fix_issues",
    )
    check(
        "mp_stress_failed → DevAgent.fix_issues",
        rules.get("mp_stress_failed", {}).get("action") == "fix_issues",
    )
    check(
        "engine_compile_passed → TestAgent.run_playtest",
        rules.get("engine_compile_passed", {}).get("action") == "run_playtest",
    )

    # =========== 7. Skill Pack 注入（UE 项目 → DevAgent 吃到 UE skill） ===========
    _banner("7. Skills 注入（UE DevAgent）")
    from skills.loader import SkillLoader
    loader = SkillLoader()
    ue_prompt = loader.build_prompt_for_agent(
        "DevAgent",
        traits=["engine:ue5", "category:game", "genre:fps"],
        current_file="Source/SmokeTest/SmokeTestCharacter.cpp",
    )
    check("UE DevAgent prompt 含 UCLASS", "UCLASS" in (ue_prompt or ""))
    check("UE DevAgent prompt 含 Build.cs", "Build.cs" in (ue_prompt or ""))
    web_prompt = loader.build_prompt_for_agent("DevAgent", traits=["platform:web"], current_file=None)
    check("Web DevAgent prompt 不含 UCLASS", "UCLASS" not in (web_prompt or ""))

    # =========== 清理 ===========
    try:
        shutil.rmtree(TMP_DIR)
    except Exception:
        pass

    _banner("Summary")
    total = passed + failed
    print(f"  PASS {passed}/{total}  FAIL {failed}/{total}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
