"""
skill_audit.py — Skill 使用率审计

扫描 Skill 配置，结合数据库日志统计使用情况，生成 Markdown 审计报告。

用法：
  python scripts/skill_audit.py [--project <project_id>] [--days 7] [--output <path>]
  python scripts/skill_audit.py --scope <skill_id>   # 单个 skill 深度审计
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

_BACKEND = Path(__file__).parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


async def run_audit(
    project_id: str | None = None,
    days: int = 7,
    skill_scope: str | None = None,
) -> str:
    """执行审计，返回 Markdown 报告文本。"""
    from skills.loader import SkillLoader
    loader = SkillLoader()
    all_skills = loader.get_all_skills_status()
    all_rules = loader.rules

    cutoff = datetime.utcnow() - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    # 尝试从数据库获取使用统计
    skill_usage: dict[str, int] = {}
    rule_usage: dict[str, int] = {}
    aicr_stats = {"autoaicr_triggers": 0, "issues_found": 0}

    try:
        from database import db
        # skill 调用次数（通过 message_history 中的 skill_id 字段）
        rows = await db.fetch_all(
            """SELECT content FROM message_history
               WHERE created_at > ? AND content LIKE '%Skill:%'
               LIMIT 1000""",
            (cutoff_str,),
        )
        import re
        for row in rows:
            content = row.get("content", "")
            for m in re.finditer(r"Skill: (\S+)", content):
                sid = m.group(1).strip("()")
                skill_usage[sid] = skill_usage.get(sid, 0) + 1
            for m in re.finditer(r"Rule: (\S+)", content):
                rid = m.group(1).strip("()-->")
                rule_usage[rid] = rule_usage.get(rid, 0) + 1
    except Exception:
        pass  # DB 不可用时跳过使用统计

    # 生成报告
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Harness 审计报告 — {now_str}",
        f"\n统计周期：最近 {days} 天\n",
        "---\n",
    ]

    # ---- Rules 覆盖 ----
    lines.append("## Rules 覆盖\n")
    always_rules = [rid for rid, cfg in all_rules.items() if cfg.get("alwaysApply")]
    paths_rules  = [rid for rid, cfg in all_rules.items() if cfg.get("paths")]
    scene_rules  = [rid for rid, cfg in all_rules.items() if cfg.get("scene")]
    traits_rules = [rid for rid, cfg in all_rules.items() if cfg.get("traits_match")]

    lines.append(f"- 全局规则（alwaysApply）：{len(always_rules)} 条")
    lines.append(f"- 文件类型按需规则（paths）：{len(paths_rules)} 条")
    lines.append(f"- 场景规则（scene）：{len(scene_rules)} 条")
    lines.append(f"- 项目 traits 规则：{len(traits_rules)} 条")
    lines.append(f"- **合计：{len(all_rules)} 条**")

    if rule_usage:
        lines.append("\n近期规则命中（Top 5）：")
        for rid, cnt in sorted(rule_usage.items(), key=lambda x: -x[1])[:5]:
            lines.append(f"  - `{rid}`: {cnt} 次")
    lines.append("")

    # ---- Skills 状态 ----
    lines.append("## Skills 状态\n")
    enabled = {sid: s for sid, s in all_skills.items() if s.get("enabled")}
    used = {sid for sid in enabled if skill_usage.get(sid, 0) > 0}
    unused = {sid for sid in enabled if sid not in used}

    lines.append(f"- 启用 Skills：{len(enabled)} 个")
    lines.append(f"- 近 {days} 天被调用：{len(used)} 个 ({len(used)*100//max(len(enabled),1)}%)")
    lines.append(f"- 未被调用：{len(unused)} 个")

    if unused:
        lines.append(f"\n未被调用的 Skills（建议检查）：")
        for sid in sorted(unused)[:10]:
            desc = enabled[sid].get("description", "")[:60]
            lines.append(f"  - `{sid}` — {desc}")
        if len(unused) > 10:
            lines.append(f"  - （及另 {len(unused)-10} 个）")
    lines.append("")

    # ---- AICR 统计 ----
    lines.append("## AICR 统计\n")
    lines.append(f"- AutoAICR 触发：{aicr_stats['autoaicr_triggers']} 次（DB 日志暂不可用时为 0）")
    lines.append(f"- 发现问题：{aicr_stats['issues_found']} 条")
    lines.append("")

    # ---- 改进建议 ----
    lines.append("## 改进建议\n")
    suggestions = []
    if len(unused) > len(enabled) * 0.4:
        suggestions.append(f"- [ ] {len(unused)} 个 Skills 未被使用（超过 40%），建议检查是否需要删除或补充文档")
    if not paths_rules:
        suggestions.append("- [ ] 没有文件类型按需规则（paths: 规则），建议添加 cpp.md / ts.md 等提高注入精度")
    if not scene_rules:
        suggestions.append("- [ ] 没有场景规则（scene: 规则），建议添加 workflow/autoaicr.md 启用代码审查")

    if suggestions:
        lines.extend(suggestions)
    else:
        lines.append("- Harness 状态良好，无明显改进点。")
    lines.append("")

    # ---- 单 skill 深度审计 ----
    if skill_scope and skill_scope in all_skills:
        s = all_skills[skill_scope]
        lines.append(f"## Skill 深度审计：`{skill_scope}`\n")
        lines.append(f"- 名称：{s.get('name', skill_scope)}")
        lines.append(f"- 描述：{s.get('description', '(无)')}")
        lines.append(f"- 启用：{s.get('enabled')}")
        lines.append(f"- inject_to：{s.get('inject_to', [])}")
        lines.append(f"- prompt 文件存在：{s.get('prompt_exists')}")
        lines.append(f"- 近 {days} 天使用次数：{skill_usage.get(skill_scope, 0)}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Skill/Harness 审计工具")
    parser.add_argument("--project", default="", help="项目 ID")
    parser.add_argument("--days", type=int, default=7, help="统计天数")
    parser.add_argument("--output", "-o", default="", help="输出文件路径（默认输出到 stdout）")
    parser.add_argument("--scope", default="", help="单个 skill ID 深度审计")
    args = parser.parse_args()

    report = asyncio.run(run_audit(
        project_id=args.project or None,
        days=args.days,
        skill_scope=args.scope or None,
    ))

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"[INFO] 审计报告已写入: {args.output}", file=sys.stderr)
    else:
        print(report)


if __name__ == "__main__":
    main()
