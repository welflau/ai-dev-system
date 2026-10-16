"""真机验证 demo-cover：gen_image 走真实 LightAI 出图，覆盖最后一个
还没在真实 CLI 验过的 MCP 工具 `mcp__skill_io__gen_image`。

链路：LLM 读内联 draft_article → 提炼封面要素 → 调 `mcp__skill_io__gen_image`
（委托 GenImageAction → LightAI create/poll/download）→ 保存到
images/cover.png → _collect_outputs 回收（二进制，is_binary=True）。

会真实生图、花钱、单次 30-300s。用法：cd backend && python _verify_cli_skill_cover.py
"""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

REQ_SHORT, TICKET_SHORT = "c0ffee", "beef01"


async def main():
    from skills.executable_loader import load_executable_skill
    from skills.runner import SkillRunner

    repo = Path(tempfile.mkdtemp(prefix="skillio_cover_"))
    print(f"仓库根: {repo}")

    skill = load_executable_skill("demo-cover")
    # 900s 已经给足；临时保留，但打印出来确认
    print(f"skill: {skill.name}  builtin_tools={skill.builtin_tools}")
    print(f"budget: max_seconds={skill.budget.get('max_seconds')}")

    draft = (
        "# 产物总线设计与实现：file 与 inline 两种存储形态的取舍\n\n"
        "本文讲清产物在流水线阶段间如何交接：file 形态落盘为文件、只登记元信息，"
        "inline 形态内容直传内存。通过体积阈值、消费次数、是否跨进程三个维度"
        "决定一条产物该走哪条路，并给出统一读写接口与生命周期管理。\n"
    )

    context = {
        "repo_path": str(repo),
        "req_short": REQ_SHORT,
        "ticket_short": TICKET_SHORT,
        "ticket_title": "产物总线设计与实现",
        "ticket_description": "讲清 file 与 inline 两种存储形态的取舍",
        "_artifacts": {
            "draft_article": {
                "artifact_id": "art-draft",
                "path": f"artifacts/{REQ_SHORT}/{TICKET_SHORT}/draft_article/draft.md",
                "abs_path": str(repo / "artifacts" / REQ_SHORT / TICKET_SHORT
                                / "draft_article" / "draft.md"),
                "mime": "text/markdown",
                "size": len(draft),
                "produced_by": "demo-draft",
                "text": draft,
            },
        },
        "sop_config": {
            "_produces": [{"kind": "cover_image", "glob": "images/*.png"}],
        },
    }

    t0 = time.time()
    result = await SkillRunner(skill).execute(context)
    dt = time.time() - t0

    print(f"\n=== 结果（耗时 {dt:.0f}s）===")
    print(f"status : {result.status}")
    print(f"rounds : {result.rounds}")
    print(f"message: {(result.message or '')[:500]}")
    print(f"outputs: {len(result.outputs)} 个")
    for o in result.outputs:
        print(f"  - {o.rel_path}  ({o.mime}, {o.size} bytes, kind={o.kind}, "
              f"binary={o.is_binary})")

    out_root = repo / "artifacts" / REQ_SHORT / TICKET_SHORT / "cover_image"
    cover = out_root / "images" / "cover.png"
    ok = result.status == "success" and cover.is_file() and cover.stat().st_size > 0
    if cover.is_file():
        raw = cover.read_bytes()
        is_png = raw[:8] == b"\x89PNG\r\n\x1a\n"
        print(f"\n=== cover.png ===")
        print(f"大小: {cover.stat().st_size} bytes, PNG 头: {'正确' if is_png else '异常'}")

    print(f"\n{'✅ 成功' if ok else '❌ 失败'}: "
          f"status={result.status}, cover.png {'落盘' if cover.is_file() else '缺失'}")
    print(f"(仓库保留在 {repo})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
