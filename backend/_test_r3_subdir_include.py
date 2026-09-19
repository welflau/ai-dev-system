"""R3（include 路径）子目录漏报 / 同级误报 —— 回归测试

    cd backend && python _test_r3_subdir_include.py

背景：`#include "Xxx.h"` 的合法性取决于**引用方所在目录**，不是头文件是否
位于模块根。旧实现按后者判，于是：
  - 漏报：Tests/ 子目录里 include 模块根的头 → lint 0 issue，真编译 C1083
    （实测 SprintComponentTest.cpp 第一次编译就死在这，见
     docs/20260918_01_OpenSpec四阶段闭环修复方案.md §3.2）
  - 误报：Tests/ 里 include 同目录的头 → 报 blocking，且 suggest 与原文逐字
    相同，DevAgent 无从修改

用真实项目 TestFPS（flat layout，无 Public/Private 分层）跑，不用 mock ——
这条规则的判定全靠磁盘布局，mock 出来的目录树证明不了什么。
"""
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

from actions.ue_lint.rules import run_all_rules  # noqa: E402

REPO = Path("F:/ADS_Projects/TestFPS")
MODULE = REPO / "Source" / "TestFPS"
TESTS = MODULE / "Tests"

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


def lint(rel: str):
    issues = run_all_rules([rel], REPO, {"ue_engine_version": "5.7"})
    return [i for i in issues if i["rule"] == "R3"]


def main():
    if not MODULE.is_dir():
        _lines.append(f"[SKIP] 项目不存在: {MODULE}")
        return 0

    created = []
    TESTS.mkdir(exist_ok=True)
    try:
        # ---- ① 漏报用例：子目录引用模块根的头，无路径前缀 → 必须 blocking ----
        bad = TESTS / "_probe_bad.cpp"
        bad.write_text(
            '#include "Misc/AutomationTest.h"\n'
            '#include "SprintComponent.h"\n',
            encoding="utf-8",
        )
        created.append(bad)
        got = lint("Source/TestFPS/Tests/_probe_bad.cpp")
        check(
            "子目录 include 模块根头（无前缀）被抓到",
            len(got) == 1 and got[0]["blocking"],
            f"issues={len(got)}",
        )
        if got:
            sug = got[0].get("suggest") or ""
            # 建议必须真的能用：指向上一级
            check(
                "suggest 给出可照抄的相对路径（../）",
                "../SprintComponent.h" in sug,
                sug,
            )
            check(
                "suggest 不等于原文（否则 DevAgent 无从修改）",
                '"SprintComponent.h"' not in sug.replace("../SprintComponent.h", ""),
                sug,
            )

        # ---- ② 真实修复后的写法 → 不应报 ----
        real = "Source/TestFPS/Tests/SprintComponentTest.cpp"
        if (REPO / real).is_file():
            got = lint(real)
            check(
                "已修复的 SprintComponentTest.cpp（用 ../）无 R3",
                len(got) == 0,
                f"issues={len(got)}",
            )

        # ---- ③ 同级误报用例：Tests/ 内部互相引用 → 不应报 ----
        hdr = TESTS / "_probe_helper.h"
        hdr.write_text("#pragma once\n", encoding="utf-8")
        created.append(hdr)
        same = TESTS / "_probe_same.cpp"
        same.write_text('#include "_probe_helper.h"\n', encoding="utf-8")
        created.append(same)
        got = lint("Source/TestFPS/Tests/_probe_same.cpp")
        check(
            "子目录内同级 include 不误报",
            len(got) == 0,
            f"issues={len(got)}",
        )

        # ---- ④ flat layout 同级（模块根）→ 不应报（旧行为不能回退）----
        flat = MODULE / "_probe_flat.cpp"
        flat.write_text('#include "SprintComponent.h"\n', encoding="utf-8")
        created.append(flat)
        got = lint("Source/TestFPS/_probe_flat.cpp")
        check(
            "flat layout 模块根同级 include 不误报",
            len(got) == 0,
            f"issues={len(got)}",
        )
    finally:
        for p in created:
            try:
                p.unlink()
            except Exception:
                pass
        try:
            if TESTS.is_dir() and not any(TESTS.iterdir()):
                shutil.rmtree(TESTS)
        except Exception:
            pass

    return 1 if _fail else 0


if __name__ == "__main__":
    rc = main()
    _lines.append(f"\n=== {_pass} passed / {_fail} failed ===")
    out = BACKEND / "_r3_out.txt"
    out.write_text("\n".join(_lines), encoding="utf-8")
    print(f"wrote {out}  pass={_pass} fail={_fail}")
    sys.exit(rc)
