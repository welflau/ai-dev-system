"""
gen_wiki_index.py — 扫描 wiki 目录生成两级树状索引

用法：
  python scripts/gen_wiki_index.py <wiki_dir> [--output <index_file>]

扫描 wiki_dir/**/*.md，读取 frontmatter，生成：
  - wiki_index.md：LLM 友好的两级导航（按 feature 分组）
  - 标准输出：简洁摘要（供 get_memory_prompt 注入）

Frontmatter 规范（wiki 条目必填）：
  ---
  title:   "文档标题"
  feature: mass-npc        # 功能域
  role:    [programmer]    # 目标职能
  type:    technical-design
  status:  active
  tags:    [network-sync, LOD]
  ---
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional


_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    try:
        import yaml
        fm = yaml.safe_load(m.group(1)) or {}
    except Exception:
        fm = {}
    return fm, m.group(2)


def scan_wiki(wiki_dir: Path) -> list[dict]:
    """扫描目录，返回所有有效 wiki 条目的 metadata 列表。"""
    entries = []
    for md_file in sorted(wiki_dir.rglob("*.md")):
        if md_file.name.startswith("_"):
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, body = _parse_frontmatter(text)
        if not fm.get("title"):
            continue
        status = fm.get("status", "active")
        if status in ("deprecated", "deleted"):
            continue
        summary = ""
        for line in body.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("---"):
                summary = line[:100]
                break
        entries.append({
            "title":   fm.get("title", md_file.stem),
            "feature": fm.get("feature", "misc"),
            "role":    fm.get("role") or [],
            "type":    fm.get("type", ""),
            "status":  status,
            "tags":    fm.get("tags") or [],
            "summary": fm.get("summary") or summary,
            "file":    str(md_file),
        })
    return entries


def build_index(entries: list[dict], token_budget: int = 800) -> str:
    """生成两级树状 LLM 索引文本（token 预算控制）。"""
    by_feature: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_feature[e["feature"]].append(e)

    lines = ["## Wiki 知识索引", ""]
    total_chars = 0
    for feature in sorted(by_feature):
        feature_lines = [f"### {feature}"]
        for e in by_feature[feature]:
            type_tag = f" [{e['type']}]" if e["type"] else ""
            summary = f" — {e['summary']}" if e["summary"] else ""
            feature_lines.append(f"- **{e['title']}**{type_tag}{summary}")
        feature_lines.append("")
        block = "\n".join(feature_lines)
        if total_chars + len(block) > token_budget * 4:  # 粗略 4 char/token
            lines.append(f"### {feature}")
            lines.append(f"（{len(by_feature[feature])} 篇文档，已省略）")
            lines.append("")
        else:
            lines.extend(feature_lines)
            total_chars += len(block)

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 wiki_index.md")
    parser.add_argument("wiki_dir", help="wiki 目录路径")
    parser.add_argument("--output", "-o", default="", help="输出文件路径（默认 <wiki_dir>/_wiki_index.md）")
    parser.add_argument("--budget", type=int, default=800, help="token 预算（默认 800）")
    args = parser.parse_args()

    wiki_dir = Path(args.wiki_dir)
    if not wiki_dir.exists():
        print(f"[ERROR] 目录不存在: {wiki_dir}", file=sys.stderr)
        sys.exit(1)

    entries = scan_wiki(wiki_dir)
    print(f"[INFO] 扫描到 {len(entries)} 篇 wiki 文档", file=sys.stderr)

    index_text = build_index(entries, token_budget=args.budget)

    out_path = Path(args.output) if args.output else wiki_dir / "_wiki_index.md"
    out_path.write_text(index_text, encoding="utf-8")
    print(f"[INFO] wiki_index 已写入: {out_path}", file=sys.stderr)
    print(index_text)


if __name__ == "__main__":
    main()
