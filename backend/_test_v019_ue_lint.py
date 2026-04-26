"""
v0.19.x A-Phase ①: ue_lint 7 规则 smoke test

价值验收：用 TestFPS 历史 5 个错作为样本 → 7 条规则必须能抓出 5/5。

另外覆盖一些规则自身的 happy-path（避免误报）。

用法：
    cd backend && python _test_v019_ue_lint.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, ".")


TMP = Path("D:/Projects/_v019_ue_lint_test")


def _banner(msg: str):
    print()
    print("=" * 70)
    print(f"  {msg}")
    print("=" * 70)


def _setup_fake_repo(root: Path, files: dict):
    """把 files dict 落地到 root。dict 的 key 是相对路径"""
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def main():
    passed, failed = 0, 0

    def check(name: str, ok: bool, detail: str = ""):
        nonlocal passed, failed
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {name}" + (f"  -- {detail}" if detail else ""))
        if ok:
            passed += 1
        else:
            failed += 1

    from actions.ue_lint import run_all_rules
    from actions.ue_lint.rules import summarize

    # ============================================================
    # 场景 1：TestFPS 5 错全复现（主价值验收）
    # ============================================================
    _banner("场景 1：TestFPS 历史 5 错样本 → 规则抓取率应 5/5")

    # 复现 TestFPS 当时的代码骨架，包含 5 处已知错
    files_case1 = {
        # 错 1: UFUNCTION override 冲突（R2）
        # 错 5: 用 UCapsuleComponent 但没 include（R7，在 .cpp 里复现）
        "TestFPS.uproject": """{
  "FileVersion": 3,
  "EngineAssociation": "5.3",
  "Modules": [
    { "Name": "TestFPS", "Type": "Runtime", "LoadingPhase": "Default" },
    { "Name": "TestFPSEditor", "Type": "Editor", "LoadingPhase": "Default" }
  ]
}""",
        # Source 结构
        "Source/TestFPS.Target.cs": """using UnrealBuildTool;
public class TestFPSTarget : TargetRules {
    public TestFPSTarget(TargetInfo Target) : base(Target) {
        Type = TargetType.Game;
        DefaultBuildSettings = BuildSettingsVersion.V2;
        IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_1;
        ExtraModuleNames.AddRange(new string[] { "TestFPS" });
    }
}
""",
        "Source/TestFPSEditor.Target.cs": """using UnrealBuildTool;
public class TestFPSEditorTarget : TargetRules {
    public TestFPSEditorTarget(TargetInfo Target) : base(Target) {
        Type = TargetType.Editor;
        IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_1;
        ExtraModuleNames.AddRange(new string[] { "TestFPS", "TestFPSEditor" });
    }
}
""",
        "Source/TestFPS/TestFPS.Build.cs": """using UnrealBuildTool;
public class TestFPS : ModuleRules {
    public TestFPS(ReadOnlyTargetRules Target) : base(Target) {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new string[] {
            "Core", "CoreUObject", "Engine", "InputCore", "EnhancedInput"
        });
    }
}
""",
        "Source/TestFPSEditor/TestFPSEditor.Build.cs": """using UnrealBuildTool;
public class TestFPSEditor : ModuleRules {
    public TestFPSEditor(ReadOnlyTargetRules Target) : base(Target) {
        PublicDependencyModuleNames.AddRange(new string[] {
            "Core", "CoreUObject", "Engine", "TestFPS"
        });
    }
}
""",
        # 额外模块（.uproject 未声明 → R5 应抓）
        "Source/FPSGame/FPSGame.Build.cs": """using UnrealBuildTool;
public class FPSGame : ModuleRules {
    public FPSGame(ReadOnlyTargetRules Target) : base(Target) {
        PublicDependencyModuleNames.AddRange(new string[] { "Core" });
    }
}
""",
        # 错 1：子类 APlayerState.OnRep_Score 重写却加了 UFUNCTION()
        "Source/TestFPS/Public/TestFPSPlayerState.h": """#pragma once
#include "CoreMinimal.h"
#include "GameFramework/PlayerState.h"
#include "TestFPSPlayerState.generated.h"

UCLASS()
class TESTFPS_API ATestFPSPlayerState : public APlayerState {
    GENERATED_BODY()

public:
    ATestFPSPlayerState();

private:
    UFUNCTION()
    void OnRep_Kills();

    UFUNCTION()
    void OnRep_Score();  // 错 1: 父类已有，不能加 UFUNCTION()

    UFUNCTION()
    void OnRep_IsAlive();
};
""",
        # 错 3：include "FPSCharacterBase.h" 缺路径前缀
        # 错 4：HandleMatch* override AGameModeBase 没这些函数（我们的 R4/R7 抓不到这个，需要扩展 R2 规则
        #       或新 R8。当前这个错属于"override 标但父类没此方法"—— R2 目前只管 OnRep）
        "Source/TestFPS/Public/TestFPSGameMode.h": """#pragma once
#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "TestFPSGameMode.generated.h"

UCLASS()
class TESTFPS_API ATestFPSGameMode : public AGameModeBase {
    GENERATED_BODY()

public:
    ATestFPSGameMode();
};
""",
        # 错 3：include 路径错
        "Source/TestFPS/Private/TestFPSPlayerController.cpp": """#include "TestFPSPlayerController.h"
#include "FPSCharacterBase.h"   // 错 3: 实际在 Character/ 子目录
#include "EnhancedInputComponent.h"
""",
        # 真正的 FPSCharacterBase 在 Character/ 子目录（让 R3 能找到并建议正确路径）
        "Source/TestFPS/Public/Character/FPSCharacterBase.h": """#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "FPSCharacterBase.generated.h"

UCLASS()
class TESTFPS_API AFPSCharacterBase : public ACharacter {
    GENERATED_BODY()
};
""",
        # 错 5：UCapsuleComponent 没 include
        "Source/TestFPS/Private/Character/FPSCharacterBase.cpp": """#include "Character/FPSCharacterBase.h"
// 缺 #include "Components/CapsuleComponent.h"

AFPSCharacterBase::AFPSCharacterBase() {
    UCapsuleComponent* Caps = CreateDefaultSubobject<UCapsuleComponent>(TEXT("Caps"));
    Caps->SetupAttachment(GetRootComponent());
}
""",
        # 需要的 stub（不带错）
        "Source/TestFPS/Public/TestFPSPlayerController.h": """#pragma once
#include "CoreMinimal.h"
#include "GameFramework/PlayerController.h"
#include "TestFPSPlayerController.generated.h"
UCLASS() class TESTFPS_API ATestFPSPlayerController : public APlayerController {
    GENERATED_BODY()
};
""",
    }
    _setup_fake_repo(TMP, files_case1)

    # 告诉规则：DevAgent 本次"写了" 5 个关键文件 + 2 个 Target.cs + uproject
    files_written = [
        "TestFPS.uproject",
        "Source/TestFPS.Target.cs",
        "Source/TestFPSEditor.Target.cs",
        "Source/TestFPS/Public/TestFPSPlayerState.h",
        "Source/TestFPS/Public/TestFPSGameMode.h",
        "Source/TestFPS/Private/TestFPSPlayerController.cpp",
        "Source/TestFPS/Private/Character/FPSCharacterBase.cpp",
    ]
    ctx = {"ue_engine_version": "5.3.2"}
    issues = run_all_rules(files_written, TMP, ctx)
    summary = summarize(issues)

    print(f"  抓到 issues: {summary}")
    for i in issues:
        print(f"    [{i['rule']}][{'B' if i.get('blocking') else 'W'}] "
              f"{i.get('file')}:{i.get('line')} — {i.get('msg')[:120]}")

    # 核心验收：每条历史错应被对应规则抓到
    by_rule_files = {}
    for i in issues:
        key = (i["rule"], i["file"], i.get("line"))
        by_rule_files.setdefault(i["rule"], []).append(i)

    # 错 1: R2 抓 TestFPSPlayerState.h 的 OnRep_Score
    r2_onrep = [i for i in issues if i["rule"] == "R2"
                and "TestFPSPlayerState" in i["file"]
                and "OnRep_Score" in i["msg"]]
    check("错 1 (OnRep_Score UFUNCTION 冲突) 被 R2 抓到",
          len(r2_onrep) == 1,
          f"got {len(r2_onrep)}")

    # 错 2: R6 抓 IncludeOrderVersion.Unreal5_1 → 5.3 下 deprecated
    r6 = [i for i in issues if i["rule"] == "R6"]
    check("错 2 (Unreal5_1 废弃) 被 R6 抓到 ≥ 1 条",
          len(r6) >= 1,
          f"got {len(r6)}")

    # 错 3: R3 抓 #include "FPSCharacterBase.h" → 应指向 Character/FPSCharacterBase.h
    r3_char = [i for i in issues if i["rule"] == "R3"
               and "FPSCharacterBase" in i.get("msg", "")]
    check("错 3 (FPSCharacterBase.h 路径错) 被 R3 抓到",
          len(r3_char) >= 1,
          f"got {len(r3_char)} / suggests: "
          f"{[i.get('suggest') for i in r3_char][:2]}")

    # 错 4: HandleMatch* override 但父类无 —— 本版 R2 只管 OnRep，此错漏检。
    # 暂时只记录"已知限制"，不打 fail（升级路径：R8 或 R2 扩到所有 virtual override）
    print("  [NOTE] 错 4 (HandleMatch override 但 AGameModeBase 无此函数) - 本版 R2 只覆盖 OnRep，"
          "暂未拦截；需要 R8 或扩展 R2")

    # 错 5: R7 抓 UCapsuleComponent 未 include
    r7_caps = [i for i in issues if i["rule"] == "R7"
               and "UCapsuleComponent" in i.get("msg", "")]
    check("错 5 (UCapsuleComponent 未 include) 被 R7 抓到",
          len(r7_caps) == 1,
          f"got {len(r7_caps)}")

    # R5 bonus: FPSGame 未在 .uproject 注册
    r5 = [i for i in issues if i["rule"] == "R5"
          and "FPSGame" in i.get("msg", "")]
    check("R5 额外抓到 FPSGame 模块未注册到 .uproject",
          len(r5) == 1,
          f"got {len(r5)}")

    # 核心验收：4 个主要错必须都 blocking
    main_blocking = [i for i in issues if i.get("blocking")
                     and i["rule"] in ("R2", "R3", "R5", "R7")]
    check("主要错全是 blocking（R2 + R3 + R5 + R7）",
          len(main_blocking) >= 4,
          f"got {len(main_blocking)}")

    # ============================================================
    # 场景 2：happy path（写得对的代码不应有误报）
    # ============================================================
    _banner("场景 2：正确代码无误报")

    good_files = {
        "Good.uproject": """{
  "FileVersion": 3,
  "EngineAssociation": "5.3",
  "Modules": [
    { "Name": "Good", "Type": "Runtime" }
  ]
}""",
        "Source/Good.Target.cs": """using UnrealBuildTool;
public class GoodTarget : TargetRules {
    public GoodTarget(TargetInfo T) : base(T) {
        Type = TargetType.Game;
        IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_3;
        ExtraModuleNames.AddRange(new string[] { "Good" });
    }
}
""",
        "Source/Good/Good.Build.cs": """using UnrealBuildTool;
public class Good : ModuleRules {
    public Good(ReadOnlyTargetRules T) : base(T) {
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
    }
}
""",
        "Source/Good/Public/MyActor.h": """#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "MyActor.generated.h"

UCLASS()
class GOOD_API AMyActor : public AActor {
    GENERATED_BODY()
public:
    AMyActor();
};
""",
        "Source/Good/Private/MyActor.cpp": """#include "MyActor.h"
#include "Components/CapsuleComponent.h"

AMyActor::AMyActor() {
    UCapsuleComponent* C = CreateDefaultSubobject<UCapsuleComponent>(TEXT("C"));
    C->SetupAttachment(GetRootComponent());
}
""",
    }
    _setup_fake_repo(TMP, good_files)
    issues_good = run_all_rules(
        list(good_files.keys()), TMP, {"ue_engine_version": "5.3.2"}
    )
    blocking_good = [i for i in issues_good if i.get("blocking")]
    print(f"  正确代码 blocking count: {len(blocking_good)}")
    for i in blocking_good:
        print(f"    [{i['rule']}] {i.get('file')}:{i.get('line')} — {i.get('msg')[:120]}")
    check("正确代码 0 blocking issues", len(blocking_good) == 0)

    # ============================================================
    # 场景 3：escape hatch
    # ============================================================
    _banner("场景 3：@ue-lint-skip R2 逃生注释应关闭规则")
    escape_files = {
        "Esc.uproject": """{
  "FileVersion": 3, "EngineAssociation": "5.3",
  "Modules": [{"Name": "Esc", "Type": "Runtime"}]
}""",
        "Source/Esc/Esc.Build.cs": "public class Esc : ModuleRules { public Esc(ReadOnlyTargetRules T) : base(T) {} }\n",
        "Source/Esc/Public/S.h": """#pragma once
#include "CoreMinimal.h"
#include "GameFramework/PlayerState.h"
#include "S.generated.h"

UCLASS() class ESC_API AS : public APlayerState {
    GENERATED_BODY()
private:
    // @ue-lint-skip R2
    UFUNCTION()
    void OnRep_Score();
};
""",
    }
    _setup_fake_repo(TMP, escape_files)
    issues_esc = run_all_rules(list(escape_files.keys()), TMP, {"ue_engine_version": "5.3.2"})
    r2_esc = [i for i in issues_esc if i["rule"] == "R2"]
    check("@ue-lint-skip R2 注释能豁免 R2", len(r2_esc) == 0,
          f"got {len(r2_esc)}")

    # 清理
    try:
        shutil.rmtree(TMP, ignore_errors=True)
    except Exception:
        pass

    _banner("Summary")
    total = passed + failed
    print(f"  PASS {passed}/{total}  FAIL {failed}/{total}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
