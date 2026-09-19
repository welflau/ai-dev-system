"""ue_test_gen 真机验证 —— 真调 LLM + 真跑 UBT -SingleFile

    cd backend && python _probe_ue_test_gen_live.py

这是 _test_ue_test_gen.py 覆盖不到的那一半：生成内容好不好、编不编得过。

做法：把手写的 SprintComponentTest.cpp 临时挪到仓库**外面**，让生成器以为
这个类还没有测试，跑完整流程，然后无论成败都恢复原文件。
备份放 repo 外是刻意的 —— 放 Tests/ 下面会被 UBT 一起编译。
"""
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

PROJECT_ID = "PRJ-20260624-28f539"
REPO = Path("F:/ADS_Projects/TestFPS")
MODULE = REPO / "Source" / "TestFPS"
EXISTING = MODULE / "Tests" / "SprintComponentTest.cpp"

OUT = BACKEND / "_uetg_live.txt"
lines = []


def say(s):
    lines.append(s)
    OUT.write_text("\n".join(lines), encoding="utf-8")


async def main():
    from actions.ue_test_gen import UETestGenAction
    from database import db
    await db.connect()   # _resolve_repo 要查 projects.git_repo_path

    backup_dir = Path(tempfile.mkdtemp(prefix="uetg_backup_"))
    backup = backup_dir / EXISTING.name
    had_existing = EXISTING.is_file()
    if had_existing:
        shutil.copy2(EXISTING, backup)
        EXISTING.unlink()
        say(f"[setup] 已把 {EXISTING.name} 临时移出仓库 -> {backup}")

    try:
        ctx = {
            "project_id": PROJECT_ID,
            "ticket_title": "冲刺组件回归测试",
            "ue_engine_version": "5.7",
            "dev_result": {"files": {"Source/TestFPS/SprintComponent.h": ""}},
            "sop_config": {
                "ue_test_gen_enabled": True,
                "ue_test_gen_compile": True,
                "ue_test_gen_timeout": 300,
                "ue_test_gen_max_targets": 1,
            },
        }
        say("[run] 开始生成（真 LLM + 真 UBT，预计 2~3 分钟）...")
        result = await UETestGenAction().run(ctx)
        d = (result.data or {}).get("ue_test_gen", {})

        say(f"[result] success={result.success} status={(result.data or {}).get('status')}")
        say(f"[result] summary  = {d.get('summary')}")
        say(f"[result] generated= {d.get('generated')}")
        say(f"[result] warnings = {d.get('warnings')}")
        for det in d.get("details") or []:
            say(f"[detail] {det}")

        produced = MODULE / "Tests" / "SprintComponentTest.cpp"
        if produced.is_file():
            body = produced.read_text(encoding="utf-8", errors="replace")
            # 先存一份再说 —— finally 里会用手写版覆盖回去，不存就永远看不到了
            (BACKEND / "_uetg_generated.cpp").write_text(body, encoding="utf-8")
            say("\n========== 生成出来的文件内容 ==========")
            say(body)
            say("========== end ==========")
            say("[teardown] 生成内容已存到 backend/_uetg_generated.cpp")
            if not had_existing:
                produced.unlink()
        else:
            say("\n[result] 仓库里没有留下文件 —— 说明走了回滚路径（预期行为之一）")
    finally:
        if had_existing:
            EXISTING.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, EXISTING)
            same = EXISTING.read_bytes() == backup.read_bytes()
            say(f"[teardown] 手写测试已恢复，字节一致={same}")
        shutil.rmtree(backup_dir, ignore_errors=True)
        try:
            from database import db as _db
            await _db.disconnect()   # 否则 aiosqlite 后台线程吊住进程不退出
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
    print(f"done -> {OUT}")
