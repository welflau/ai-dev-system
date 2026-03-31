#!/usr/bin/env python3
"""
AI Dev System - 每日开发日报自动生成
用法: python scripts/daily-summary.py [日期 YYYY-MM-DD]
不传日期默认生成今天的日报
"""
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
NOTES_DIR = BASE_DIR / "dev-notes"
NOTES_DIR.mkdir(exist_ok=True)


def run_git(*args):
    result = subprocess.run(
        ["git"] + list(args),
        cwd=str(BASE_DIR), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return result.stdout.strip()


def generate_daily_summary(date_str: str):
    """生成指定日期的开发日报"""
    date = datetime.strptime(date_str, "%Y-%m-%d")
    next_day = (date + timedelta(days=1)).strftime("%Y-%m-%d")

    # 获取当日 commits
    log = run_git("log", "--oneline", f"--since={date_str}", f"--until={next_day}")
    commits = log.strip().split("\n") if log.strip() else []

    # 获取当日变更文件
    diff_stat = run_git("log", "--stat", "--format=", f"--since={date_str}", f"--until={next_day}")

    # 获取变更文件列表（去重）
    changed_files = set()
    for line in diff_stat.split("\n"):
        line = line.strip()
        if "|" in line:
            fname = line.split("|")[0].strip()
            if fname:
                changed_files.add(fname)

    # 统计插入/删除行数
    shortstat = run_git("log", "--shortstat", "--format=", f"--since={date_str}", f"--until={next_day}")
    insertions = 0
    deletions = 0
    for line in shortstat.split("\n"):
        if "insertion" in line or "deletion" in line:
            parts = line.strip().split(",")
            for p in parts:
                p = p.strip()
                if "insertion" in p:
                    insertions += int(p.split()[0])
                elif "deletion" in p:
                    deletions += int(p.split()[0])

    # 按目录分组文件
    by_dir = {}
    for f in sorted(changed_files):
        d = f.split("/")[0] if "/" in f else "."
        by_dir.setdefault(d, []).append(f)

    # 如果没有 commits，生成空报告
    if not commits:
        md = f"# 开发日报 — {date_str}\n\n> 当日无提交\n"
    else:
        md = f"""# 开发日报 — {date_str}

> 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}

## 概要

| 指标 | 值 |
|------|------|
| 提交数 | {len(commits)} |
| 变更文件 | {len(changed_files)} |
| 新增行数 | +{insertions} |
| 删除行数 | -{deletions} |

## 提交记录

"""
        for c in commits:
            hash_short = c[:7]
            msg = c[8:] if len(c) > 8 else c
            md += f"- `{hash_short}` {msg}\n"

        md += "\n## 变更文件\n\n"
        for d, files in by_dir.items():
            md += f"### {d}/\n"
            for f in files:
                md += f"- {f}\n"
            md += "\n"

    # 写入文件
    note_file = NOTES_DIR / f"{date_str}.md"
    # 如果已有手写笔记，追加而非覆盖
    if note_file.exists():
        existing = note_file.read_text(encoding="utf-8")
        if "## 概要" not in existing:
            # 手写笔记存在但没有自动生成部分，追加
            md = existing + "\n\n---\n\n" + md.replace(f"# 开发日报 — {date_str}", "## 自动统计")
        else:
            # 已有自动生成内容，不覆盖
            print(f"[skip] {note_file} 已存在自动统计")
            return str(note_file)

    note_file.write_text(md, encoding="utf-8")
    print(f"[ok] 日报已生成: {note_file}")
    return str(note_file)


def commit_and_push():
    """提交并推送日报"""
    # Stage dev-notes
    run_git("add", "dev-notes/")

    # Check if there are changes
    status = run_git("status", "--porcelain", "dev-notes/")
    if not status.strip():
        print("[skip] 无新日报需提交")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    run_git("commit", "-m", f"docs: 开发日报 {today}")

    result = subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=str(BASE_DIR), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if result.returncode == 0:
        print("[ok] 已推送到远程仓库")
    else:
        print(f"[warn] 推送失败: {result.stderr[:200]}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    else:
        target_date = datetime.now().strftime("%Y-%m-%d")

    generate_daily_summary(target_date)
    commit_and_push()
