"""UETestGenAction —— 纯逻辑回归测试（不调 LLM、不跑 UBT）

    cd backend && python _test_ue_test_gen.py

只测确定性的部分，这也正是最容易出错的部分：
  1. include 路径推导 —— 硬约束 #5，SprintComponentTest.cpp 第一次编译
     C1083 就死在这。交给 LLM 猜等于白烧一轮编译，所以自己算，那就得测。
  2. 静态校验 —— 每一条都对应一个「不测就要编译一次才能发现」的错。
     正样本用真机实测通过的 SprintComponentTest.cpp，不用手编的假样本。
  3. 选目标 / 不覆盖既有测试 —— 人工写的测试比生成的值钱，覆盖了就是事故。
"""
import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

from actions.ue_test_gen import UETestGenAction  # noqa: E402

REPO = Path("F:/ADS_Projects/TestFPS")
MODULE = REPO / "Source" / "TestFPS"

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


GOOD = '''#include "Misc/AutomationTest.h"
#include "../SprintComponent.h"

#if WITH_DEV_AUTOMATION_TESTS

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
\tFSprintComponentDefaultsTest,
\t"Project.TestFPS.SprintComponent.Defaults",
\tEAutomationTestFlags::EditorContext | EAutomationTestFlags::CommandletContext
\t\t| EAutomationTestFlags::ProductFilter)

bool FSprintComponentDefaultsTest::RunTest(const FString& Parameters)
{
\tUSprintComponent* Sprint = NewObject<USprintComponent>();
\treturn TestNotNull(TEXT("可实例化"), Sprint);
}

#endif // WITH_DEV_AUTOMATION_TESTS
'''

INC = '#include "../SprintComponent.h"'


def test_include_path():
    a = UETestGenAction()
    hdr = MODULE / "SprintComponent.h"
    if not hdr.is_file():
        _lines.append("[SKIP] TestFPS 不存在，跳过 include 推导用例")
        return

    # flat layout + 子目录 → 必须是 ../ （真机 C1083 的那个坑）
    got = a._include_path_for(hdr, MODULE / "Tests", MODULE)
    check("flat layout 子目录 → ../Xxx.h", got == INC, got)

    # 同级 → 裸文件名
    got = a._include_path_for(hdr, MODULE, MODULE)
    check("同级 → 裸文件名", got == '#include "SprintComponent.h"', got)

    # Public/ 分层 → 相对 Public 锚点（用临时目录造布局）
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "Source" / "Foo"
        (m / "Public" / "Sub").mkdir(parents=True)
        (m / "Tests").mkdir()
        (m / "Foo.Build.cs").write_text("//", encoding="utf-8")
        h = m / "Public" / "Sub" / "Bar.h"
        h.write_text("#pragma once\n", encoding="utf-8")
        got = a._include_path_for(h, m / "Tests", m)
        check("Public/ 分层 → 相对 Public 锚点", got == '#include "Sub/Bar.h"', got)


def test_static_check():
    a = UETestGenAction()

    check("真机通过的样本无问题", a._static_check(GOOD, INC) == [],
          str(a._static_check(GOOD, INC)))

    # 最重要的正样本：**原封不动**读真机编译通过、playtest 跑绿的那个文件。
    # 上面的 GOOD 是我手工裁剪的，裁的时候顺手把注释去掉了，恰好避开了
    # 「注释里出现禁用词」这个坑 —— 于是单测全绿，真机连着三轮被自己的规则毙掉。
    # 自己编的样本会带着自己的盲区，正样本必须用真东西。
    real = MODULE / "Tests" / "SprintComponentTest.cpp"
    if real.is_file():
        src = real.read_text(encoding="utf-8", errors="replace")
        assert "SpawnActor" in src, "前提变了：真文件里已没有含禁用词的注释"
        probs = a._static_check(src, INC)
        check("真实手写测试（含 `// 不建 World / 不 SpawnActor` 注释）不被误判",
              probs == [], str(probs))

    # 注释里提到禁用词 = 合法；代码里用 = 违规
    check("注释里的 SpawnActor 不算违规",
          a._static_check(GOOD.replace("#if WITH_DEV",
                                       "// 不建 World / 不 SpawnActor\n#if WITH_DEV"),
                          INC) == [])
    check("块注释里的 UWorld 不算违规",
          a._static_check(GOOD.replace("#if WITH_DEV",
                                       "/* 不用 UWorld */\n#if WITH_DEV"), INC) == [])

    cases = [
        ("测试名缺 Project. 前缀",
         GOOD.replace('"Project.TestFPS', '"TestFPS'), "Project."),
        ("Filter 多于 1 个",
         GOOD.replace("| EAutomationTestFlags::ProductFilter",
                      "| EAutomationTestFlags::ProductFilter | EAutomationTestFlags::SmokeFilter"),
         "Filter"),
        ("缺 ApplicationContext",
         GOOD.replace("EAutomationTestFlags::EditorContext | "
                      "EAutomationTestFlags::CommandletContext\n\t\t| ", ""),
         "ApplicationContext"),
        ("用了 SpawnActor",
         GOOD.replace("NewObject<USprintComponent>()",
                      "GetWorld()->SpawnActor<AActor>()"), "nullrhi"),
        ("没包 WITH_DEV_AUTOMATION_TESTS",
         GOOD.replace("#if WITH_DEV_AUTOMATION_TESTS", "")
             .replace("#endif // WITH_DEV_AUTOMATION_TESTS", ""),
         "WITH_DEV_AUTOMATION_TESTS"),
        ("include 块被改动",
         GOOD.replace(INC, '#include "SprintComponent.h"'), "include"),
        ("没有任何测试宏",
         GOOD.replace("IMPLEMENT_SIMPLE_AUTOMATION_TEST", "SOME_OTHER_MACRO"), "宏"),
    ]
    for name, bad, keyword in cases:
        probs = a._static_check(bad, INC)
        check(f"抓到：{name}", any(keyword in p for p in probs),
              f"{len(probs)} problems: {probs[:1]}")


def test_pick_targets():
    a = UETestGenAction()
    ctx = {"dev_result": {"files": {
        "Source/TestFPS/SprintComponent.h": "",
        "Source/TestFPS/SprintComponent.cpp": "",      # .cpp 不选
        "Source/TestFPS/Tests/SprintComponentTest.cpp": "",  # 测试目录不选
        "Source/TestFPS/TestFPS.h": "",
    }}}
    if not MODULE.is_dir():
        _lines.append("[SKIP] TestFPS 不存在，跳过选目标用例")
        return
    got = a._pick_targets(ctx, REPO, 5)
    names = [p.name for p in got]
    check("只挑 .h", all(n.endswith(".h") for n in names), str(names))
    check("不给测试再生成测试", "SprintComponentTest.cpp" not in str(names), str(names))
    check("limit 生效", len(a._pick_targets(ctx, REPO, 1)) == 1)


async def test_no_overwrite():
    """既有测试文件必须跳过 —— 这一步在调 LLM 之前，所以无需 LLM 也能测"""
    a = UETestGenAction()
    hdr = MODULE / "SprintComponent.h"
    existing = MODULE / "Tests" / "SprintComponentTest.cpp"
    if not (hdr.is_file() and existing.is_file()):
        _lines.append("[SKIP] 缺少 SprintComponentTest.cpp，跳过不覆盖用例")
        return
    before = existing.read_bytes()
    d = await a._gen_one({"project_id": ""}, REPO, hdr, {})
    check("既有测试不被覆盖（跳过生成）",
          d.get("written") is False and "已存在" in (d.get("reason") or ""),
          str(d.get("reason")))
    check("文件内容原样未动", existing.read_bytes() == before)


def test_extract_class_names():
    """UCLASS 宏参数是嵌套括号 —— 真机漏报过，必须有回归

    `UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))`
    用 `\\([^)]*\\)` 匹配会停在 `(Custom)` 上整条失配，于是对绝大多数组件类
    都报「没有 UCLASS/USTRUCT」。正样本直接用真实的 SprintComponent.h。
    """
    from actions.ue_test_gen import _extract_class_names

    hdr = MODULE / "SprintComponent.h"
    if hdr.is_file():
        got = _extract_class_names(hdr.read_text(encoding="utf-8", errors="replace"))
        check("真实 SprintComponent.h 抓到 USprintComponent",
              "USprintComponent" in got, str(got))

    cases = [
        ("嵌套括号的 UCLASS",
         "UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))\n"
         "class TESTFPS_API USprintComponent : public UActorComponent\n{",
         "USprintComponent"),
        ("裸 UCLASS()",
         "UCLASS()\nclass AFoo : public AActor\n{", "AFoo"),
        ("宏参数跨行",
         "UCLASS(Blueprintable,\n\tmeta = (A = (B)))\n"
         "class TESTFPS_API UBar : public UObject\n{", "UBar"),
        ("USTRUCT",
         "USTRUCT(BlueprintType)\nstruct FBaz\n{", "FBaz"),
    ]
    for name, src, expect in cases:
        got = _extract_class_names(src)
        check(f"解析：{name}", expect in got, str(got))

    check("没有 UCLASS 时返回空",
          _extract_class_names("class FPlain {};") == [], "")


async def test_resolve_repo():
    """自定义仓库路径必须能从 DB 补注册。

    git_manager._repo_path() 只认进程内注册过的 _custom_paths，没注册就退回
    PROJECTS_DIR/<id> —— 对 TestFPS（仓库在 F:/ADS_Projects/）会静默指到不存在的
    目录，Action 于是报「没有可测的头文件」，错得很难查。真机上就是这么中的。
    """
    a = UETestGenAction()

    # context 里直接给 repo_path 时优先用
    got = await a._resolve_repo({"repo_path": str(REPO)}, "")
    check("context.repo_path 优先", got is not None and got.resolve() == REPO.resolve(),
          str(got))

    # 从 DB 补注册
    try:
        from database import db
        await db.connect()
    except Exception as e:
        _lines.append(f"[SKIP] DB 不可用，跳过补注册用例: {e}")
        return
    from git_manager import git_manager
    pid = "PRJ-20260624-28f539"
    git_manager._custom_paths.pop(pid, None)   # 模拟全新进程
    got = await a._resolve_repo({}, pid)
    check("未注册时能从 projects.git_repo_path 补出真实路径",
          got is not None and got.resolve() == REPO.resolve(), str(got))
    check("补注册后 (Source/TestFPS) 确实存在",
          got is not None and (got / "Source" / "TestFPS").is_dir())


async def main():
    test_include_path()
    test_static_check()
    test_extract_class_names()
    test_pick_targets()
    await test_resolve_repo()
    await test_no_overwrite()
    # 不断开的话 aiosqlite 的后台线程会吊住进程，脚本跑完不退出
    try:
        from database import db
        await db.disconnect()
    except Exception:
        pass
    return 1 if _fail else 0


if __name__ == "__main__":
    rc = asyncio.run(main())
    _lines.append(f"\n=== {_pass} passed / {_fail} failed ===")
    (BACKEND / "_uetg_out.txt").write_text("\n".join(_lines), encoding="utf-8")
    print(f"pass={_pass} fail={_fail}")
    sys.exit(rc)
