"""
v0.19.x A 方案端到端 smoke：SelfTestAction UE 分支 + SOP + Reflexion 贯通

不真跑 UBT，只验证：
  1. traits 含 engine:ue5 的工单，SelfTestAction 走 UE 分支
  2. 含 blocking issues 时返回 status=fail，data 带 ue_blocking_issues 结构化
  3. SOP `self_test_failed → DevAgent.fix_issues` 派生规则存在
  4. Reflexion 的 `self_test_failed` 分支 prompt 含 UE issues 正确格式

用法：
    cd backend && python _test_v019_ue_selftest_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, ".")


TMP = Path("D:/Projects/_v019_ue_selftest_e2e")


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
    from actions.self_test import SelfTestAction
    from utils import generate_id, now_iso

    await db.connect()
    await db.init_tables()

    # =========== 1. 准备 UE 项目 + 错误代码 ===========
    _banner("1. 准备 UE 项目 + 含 R2/R7 错的代码")
    if TMP.exists():
        shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True, exist_ok=True)

    pid = generate_id("PRJ")
    await db.insert("projects", {
        "id": pid, "name": "UESelfTestE2E", "description": "",
        "status": "active", "tech_stack": "UE5 C++", "config": "{}",
        "git_repo_path": str(TMP),
        "git_remote_url": "",
        "traits": json.dumps(["platform:desktop", "category:game", "engine:ue5"]),
        "traits_confidence": "{}", "preset_id": None,
        "ue_engine_version": "5.3.2",
        "created_at": now_iso(), "updated_at": now_iso(),
    })

    # 准备 Source 结构 + 一些正确文件让 R3/R4/R5 不误报
    files_to_disk = {
        "Bad.uproject": """{"FileVersion":3,"EngineAssociation":"5.3","Modules":[{"Name":"Bad","Type":"Runtime"}]}""",
        "Source/Bad/Bad.Build.cs": """public class Bad : ModuleRules { public Bad(ReadOnlyTargetRules T) : base(T) { PublicDependencyModuleNames.AddRange(new string[]{"Core","Engine"}); } }""",
        "Source/Bad/Public/MyState.h": """#pragma once
#include "CoreMinimal.h"
#include "GameFramework/PlayerState.h"
#include "MyState.generated.h"

UCLASS()
class BAD_API AMyState : public APlayerState {
    GENERATED_BODY()
private:
    // R2 错：OnRep_Score 不能加 UFUNCTION()
    UFUNCTION()
    void OnRep_Score();
};
""",
        "Source/Bad/Private/MyActor.cpp": """#include "MyActor.h"
// R7 错：用 UCapsuleComponent 没 include
void F() {
    UCapsuleComponent* Caps = CreateDefaultSubobject<UCapsuleComponent>(TEXT("C"));
}
""",
        "Source/Bad/Public/MyActor.h": """#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "MyActor.generated.h"
UCLASS() class BAD_API AMyActor : public AActor { GENERATED_BODY() };
""",
    }
    for rel, content in files_to_disk.items():
        p = TMP / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    # 让 git_manager 知道这个项目的路径
    from git_manager import git_manager
    git_manager.set_project_path(pid, str(TMP))

    # =========== 2. SelfTestAction UE 分支触发 ===========
    _banner("2. SelfTestAction 检测 engine:ue5 → 走 UE 分支")
    action = SelfTestAction()
    context = {
        "project_id": pid,
        "_files": {
            "Source/Bad/Public/MyState.h": files_to_disk["Source/Bad/Public/MyState.h"],
            "Source/Bad/Private/MyActor.cpp": files_to_disk["Source/Bad/Private/MyActor.cpp"],
        },
        "traits": ["platform:desktop", "category:game", "engine:ue5"],
        "ue_engine_version": "5.3.2",
        "sop_config": {"ue_precompile": False},   # 不跑 Layer 2
    }
    result = await action.run(context)
    d = result.data or {}
    st = d.get("self_test") or {}

    check("ActionResult.success=False（因 blocking）", result.success is False)
    check("phase=layer1_static", st.get("phase") == "layer1_static",
          f"got={st.get('phase')}")
    check("passed=False", st.get("passed") is False)
    check("ue_blocking_issues 非空",
          len(st.get("ue_blocking_issues") or []) > 0,
          f"count={len(st.get('ue_blocking_issues') or [])}")
    issues = st.get("ue_blocking_issues") or []
    rules = {i.get("rule") for i in issues}
    check("含 R2 OnRep 规则", "R2" in rules, f"rules={rules}")
    check("含 R7 类型 header 规则", "R7" in rules)

    # =========== 3. SOP 派生 self_test_failed → DevAgent.fix_issues ===========
    _banner("3. SOP 派生 transition rule: self_test_failed → DevAgent.fix_issues")
    from sop.loader import compose_sop, sop_to_transition_rules
    cfg = compose_sop(
        traits=["platform:desktop", "category:game", "engine:ue5"],
        ticket_type="feature",
    )
    rules_dict = sop_to_transition_rules(cfg)
    r = rules_dict.get("self_test_failed")
    check("存在 self_test_failed 规则", r is not None,
          f"keys sample={sorted(list(rules_dict))[:8]}")
    if r:
        check("规则指向 DevAgent", r.get("agent") == "DevAgent")
        check("规则 action=fix_issues", r.get("action") == "fix_issues")

    # =========== 4. Reflexion 的 self_test_failed 分支 ===========
    _banner("4. ReflectionAction 能消费 ue_blocking_issues")
    # 不真调 LLM，只验证 prompt 构造器能吃这个分支
    refl_src = Path("actions/reflection.py").read_text(encoding="utf-8")
    check("reflection.py 含 self_test_failed 分支",
          '"self_test_failed"' in refl_src)
    check("prompt 含静态预检提示",
          "Layer 1 静态预检" in refl_src or "静态预检" in refl_src)

    # =========== 5. 正确 UE 代码应 pass ===========
    _banner("5. 正确 UE 代码 → self_test passed")
    good_files = {
        "Good/Source/Good.Build.cs": """public class Good : ModuleRules { public Good(ReadOnlyTargetRules T) : base(T){} }""",
        "Good.uproject": """{"FileVersion":3,"EngineAssociation":"5.3","Modules":[{"Name":"Good","Type":"Runtime"}]}""",
    }
    # 换个项目路径
    good_tmp = Path("D:/Projects/_v019_ue_selftest_good")
    if good_tmp.exists(): shutil.rmtree(good_tmp, ignore_errors=True)
    good_tmp.mkdir(parents=True)
    (good_tmp / "Good.uproject").write_text(good_files["Good.uproject"], encoding="utf-8")
    (good_tmp / "Source" / "Good").mkdir(parents=True)
    (good_tmp / "Source" / "Good" / "Good.Build.cs").write_text(good_files["Good/Source/Good.Build.cs"], encoding="utf-8")

    pid_good = generate_id("PRJ")
    await db.insert("projects", {
        "id": pid_good, "name": "GoodUE", "description": "",
        "status": "active", "tech_stack": "", "config": "{}",
        "git_repo_path": str(good_tmp), "git_remote_url": "",
        "traits": json.dumps(["engine:ue5", "category:game"]),
        "traits_confidence": "{}", "preset_id": None,
        "ue_engine_version": "5.3",
        "created_at": now_iso(), "updated_at": now_iso(),
    })
    git_manager.set_project_path(pid_good, str(good_tmp))

    ctx_good = {
        "project_id": pid_good,
        "_files": {},    # 没改动文件
        "traits": ["engine:ue5", "category:game"],
        "ue_engine_version": "5.3",
        "sop_config": {"ue_precompile": False},
    }
    result2 = await action.run(ctx_good)
    d2 = result2.data or {}
    st2 = d2.get("self_test") or {}
    check("无改动 UE 项目 → passed",
          result2.success is True and st2.get("passed") is True,
          f"phase={st2.get('phase')} issues={len(st2.get('issues') or [])}")

    # =========== 清理 ===========
    _banner("清理")
    for p in (pid, pid_good):
        try: await db.execute("DELETE FROM projects WHERE id = ?", (p,))
        except Exception: pass
    try:
        shutil.rmtree(TMP, ignore_errors=True)
        shutil.rmtree(good_tmp, ignore_errors=True)
    except Exception: pass

    _banner("Summary")
    total = passed + failed
    print(f"  PASS {passed}/{total}  FAIL {failed}/{total}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
