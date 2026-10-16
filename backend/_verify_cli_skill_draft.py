"""真机验证 demo-draft：消费上游 + 写 draft.md，覆盖两个 MCP 工具。

- `content_outline`（mode: text）内联进 prompt —— 验框架的 consumes 注入
- `style_guide`（mode: path，可选）只给路径 —— 逼 LLM 调
  `mcp__skill_io__read_repo_file` 读盘
- 写 `draft.md` 走 `mcp__skill_io__write_output`

一次跑覆盖 read_repo_file + write_output 两个还没在真实 CLI 验过的工具。

用法：cd backend && python _verify_cli_skill_draft.py
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

    repo = Path(tempfile.mkdtemp(prefix="skillio_draft_"))
    print(f"仓库根: {repo}")

    skill = load_executable_skill("demo-draft")
    # 真实模型写一篇成稿，300s 偏紧，临时放宽到 600s
    skill.budget["max_seconds"] = 600
    print(f"skill: {skill.name}  builtin_tools={skill.builtin_tools}")

    # 上游 1：content_outline（mode: text，内联）
    outline = (
        "# 产物总线设计与实现：file 与 inline 两种存储形态的取舍\n\n"
        "## 读者与目标\n- 读者：后端工程师\n- 读完能做什么：能判断该走 file 还是 inline\n\n"
        "## 章节\n"
        "1. 问题背景 — 阶段间如何交接产出 / 为什么要统一抽象\n"
        "2. file 形态 — 落盘 + 只登记元信息 / 适用大产物、跨进程\n"
        "3. inline 形态 — 内容直传内存 / 适用小产物、同进程\n"
        "4. 取舍判据 — 体积阈值 / 消费次数 / 是否跨进程\n"
        "5. 总线接口与实现要点 — 统一读写接口 / 生命周期管理\n\n"
        "## 关键术语\n- 产物总线：阶段间传递产物的机制\n"
    )
    outline_path = f"artifacts/{REQ_SHORT}/{TICKET_SHORT}/content_outline/outline.md"

    # 上游 2：style_guide（mode: path，逼 LLM 用 read_repo_file 读盘）
    style_guide_rel = f"artifacts/{REQ_SHORT}/{TICKET_SHORT}/style_guide/guide.md"
    style_guide_file = repo / style_guide_rel
    style_guide_file.parent.mkdir(parents=True, exist_ok=True)
    style_guide_file.write_text(
        "# 风格指南\n\n- 技术博客，克制、面向工程师\n- 章节标题用陈述句，不用问句\n"
        "- 代码示例用 Python，带注释\n- 不用 emoji\n",
        encoding="utf-8",
    )
    print(f"style_guide 落盘: {style_guide_file}")

    context = {
        "repo_path": str(repo),
        "req_short": REQ_SHORT,
        "ticket_short": TICKET_SHORT,
        "ticket_title": "产物总线设计与实现",
        "ticket_description": "讲清 file 与 inline 两种存储形态的取舍",
        "_artifacts": {
            "content_outline": {
                "artifact_id": "art-outline",
                "path": outline_path,
                "abs_path": str(repo / outline_path),
                "mime": "text/markdown",
                "size": len(outline),
                "produced_by": "demo-outline",
                "text": outline,
            },
            "style_guide": {
                "artifact_id": "art-style",
                "path": style_guide_rel,
                "abs_path": str(style_guide_file),
                "mime": "text/markdown",
                "size": style_guide_file.stat().st_size,
                "produced_by": "test-driver",
                # mode: path —— 不给 text，逼 LLM 自己读
            },
        },
        "sop_config": {
            "_produces": [{"kind": "draft_article", "glob": "draft.md"}],
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
        print(f"  - {o.rel_path}  ({o.mime}, {o.size} bytes, kind={o.kind})")

    out_root = repo / "artifacts" / REQ_SHORT / TICKET_SHORT / "draft_article"
    draft = out_root / "draft.md"
    ok = result.status == "success" and draft.is_file() and draft.stat().st_size > 0
    if draft.is_file():
        print(f"\n=== draft.md 前 600 字 ===")
        print(draft.read_text(encoding="utf-8")[:600])

    # 关键验证点：draft 里有没有消化掉 outline 的章节结构
    if draft.is_file():
        body = draft.read_text(encoding="utf-8")
        has_outline_structure = "产物总线" in body or "file" in body.lower()
        print(f"\n消费了上游大纲: {'是' if has_outline_structure else '否'}")

    print(f"\n{'✅ 成功' if ok else '❌ 失败'}: "
          f"status={result.status}, draft.md {'落盘' if draft.is_file() else '缺失'}")
    print(f"(仓库保留在 {repo})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
