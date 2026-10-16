"""完整链路：真 SkillRunner → 真 QueryEngine → 真 codebuddy CLI → skill_io MCP。

外科测试（_verify_cli_skill_surgical.py）已证明嵌套 CLI 会真调
mcp__skill_io__write_output。这里走完整生产路径，验的是：
  SkillRunner.execute 组装 actions + 进 skill_io 上下文 → QueryEngine CLI 分支
  → codebuddy 子进程 → mcp__skill_io__write_output 写到 outputs.root
  → _collect_outputs 扫到 → status=success

不打桩、不 mock LLM。demo-outline 消费 ticket_brief（mode=text），
这里把简报直接塞进 context["_artifacts"]，模拟上游已产出。
"""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

REQ_SHORT, TICKET_SHORT = "c0ffee", "beef01"


def _brief() -> dict:
    return {
        "title": "产物总线设计与实现",
        "description": "讲清 file 与 inline 两种存储形态的取舍",
        "type": "feature",
        "project_traits": ["pipeline:content"],
    }


async def main():
    from skills.executable_loader import load_executable_skill
    from skills.runner import SkillRunner

    repo = Path(tempfile.mkdtemp(prefix="skillio_full_"))
    print(f"仓库根: {repo}")

    skill = load_executable_skill("demo-outline")
    # 上一轮实测 240s 不够（模型写完 outline 但没来得及回调 done 就被掐断）。
    # 这里临时放宽预算，验「预算充足时能优雅走完 done」的干净路径。
    skill.budget["max_seconds"] = 600
    print(f"skill: {skill.name}  builtin_tools={skill.builtin_tools}")
    print(f"outputs.root: {skill.output_root_template}")
    print(f"budget: max_seconds={skill.budget.get('max_seconds')}")

    brief = _brief()
    context = {
        "repo_path": str(repo),
        "req_short": REQ_SHORT,
        "ticket_short": TICKET_SHORT,
        "ticket_title": brief["title"],
        "ticket_description": brief["description"],
        # ticket_brief 上游产物（demo-outline 的 consumes，mode=text 内联）
        "_artifacts": {
            "ticket_brief": {
                "artifact_id": "art-fake-brief",
                "path": f"artifacts/{REQ_SHORT}/{TICKET_SHORT}/ticket_brief/brief.json",
                "abs_path": str(repo / "artifacts" / REQ_SHORT / TICKET_SHORT
                                / "ticket_brief" / "brief.json"),
                "mime": "application/json",
                "size": len(json.dumps(brief)),
                "produced_by": "test-driver",
                "text": json.dumps(brief, ensure_ascii=False),
            }
        },
        "sop_config": {},
    }

    runner = SkillRunner(skill)
    t0 = time.time()
    result = await runner.execute(context)
    dt = time.time() - t0

    print(f"\n=== 结果（耗时 {dt:.0f}s）===")
    print(f"status : {result.status}")
    print(f"rounds : {result.rounds}")
    print(f"message: {(result.message or '')[:600]}")
    print(f"outputs: {len(result.outputs)} 个")
    for o in result.outputs:
        print(f"  - {o.rel_path}  ({o.mime}, {o.size} bytes, kind={o.kind})")

    out_root = repo / "artifacts" / REQ_SHORT / TICKET_SHORT / "content_outline"
    outline = out_root / "outline.md"
    ok = result.status == "success" and outline.is_file() and outline.stat().st_size > 0
    if outline.is_file():
        print(f"\n=== outline.md 内容 ===")
        print(outline.read_text(encoding="utf-8")[:800])

    print(f"\n{'✅ 成功' if ok else '❌ 失败'}: "
          f"status={result.status}, outline.md {'落盘' if outline.is_file() else '缺失'}")
    print(f"(仓库保留在 {repo})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
