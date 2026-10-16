"""真机确认超时修复：给 demo-outline 一个必然超时的预算（3s），
验证 status 落到 budget_exceeded 而不是 success（旧假成功）。

用法：cd backend && python _verify_cli_timeout_fix.py
"""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def main():
    from skills.executable_loader import load_executable_skill
    from skills.runner import SkillRunner

    repo = Path(tempfile.mkdtemp(prefix="skillio_tmo_"))
    skill = load_executable_skill("demo-outline")
    # 3s 必然不够真实模型跑完 → 应该触发超时路径
    skill.budget["max_seconds"] = 3

    context = {
        "repo_path": str(repo),
        "req_short": "c0ffee", "ticket_short": "beef01",
        "ticket_title": "产物总线", "ticket_description": "file 与 inline 取舍",
        "_artifacts": {
            "ticket_brief": {
                "artifact_id": "art-fake", "path": "x/brief.json",
                "abs_path": str(repo / "brief.json"),
                "mime": "application/json", "size": 40,
                "produced_by": "t", "text": json.dumps({"title": "产物总线",
                                                          "description": "取舍"},
                                                         ensure_ascii=False),
            }
        },
        "sop_config": {},
    }

    t0 = time.time()
    result = await SkillRunner(skill).execute(context)
    dt = time.time() - t0

    print(f"status : {result.status}")
    print(f"message: {(result.message or '')[:200]}")
    print(f"outputs: {len(result.outputs)} 个")
    for o in result.outputs:
        print(f"  - {o.rel_path}")
    print(f"耗时 {dt:.0f}s")

    ok = result.status == "budget_exceeded"
    print(f"\n{'✅ 修复生效' if ok else '❌ 未生效'}: "
          f"status={result.status}（期望 budget_exceeded）")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
