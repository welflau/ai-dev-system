#!/usr/bin/env python3
"""
ue_antipattern_extract.py — 从 incidents/ 自动提炼反模式草案到 AntiPatterns.md

用法：
    python scripts/ue_antipattern_extract.py --project F:/UEProjects/MyGame
    python scripts/ue_antipattern_extract.py --project . --list
    python scripts/ue_antipattern_extract.py --project . --confirm BP-003

退出码：
    0 = 成功
    1 = 无新事故文件
    2 = 配置错误
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

INCIDENTS_DIR    = '.claude/ue-runtime/incidents'
ANTIPATTERNS_FILE = '.claude/ue-runtime/AntiPatterns.md'

# 模块 → ID 前缀映射
MODULE_PREFIX = {
    'Blueprint': 'BP',
    'UEPython':  'PY',
    'CI':        'CI',
    'GAS':       'GAS',
    'DataTable': 'DT',
    'Editor':    'UE',
    'Other':     'UE',
}


# ── 解析事故文件 ──────────────────────────────────────────────────────────────

def parse_incident(filepath: Path) -> dict | None:
    """解析单个事故文件，提取关键字段。"""
    try:
        content = filepath.read_text(encoding='utf-8')
    except Exception:
        return None

    # 解析 YAML frontmatter
    fm = {}
    fm_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).split('\n'):
            if ':' in line:
                k, v = line.split(':', 1)
                fm[k.strip()] = v.strip()

    if fm.get('status') == 'suspected':
        return None  # 未确认的事故不提炼

    # 提取各节内容
    def extract_section(name: str) -> str:
        m = re.search(rf'## {name}\s*\n(.*?)(?=\n## |\Z)', content, re.DOTALL)
        return m.group(1).strip() if m else ''

    return {
        'date':           fm.get('date', ''),
        'module':         fm.get('module', 'Other'),
        'severity':       fm.get('severity', 'medium'),
        'trigger_action': fm.get('trigger_action', ''),
        'status':         fm.get('status', 'suspected'),
        'pattern':        extract_section('潜在反模式'),
        'wrong':          extract_section('误导性默认值'),
        'correct':        extract_section('正确做法'),
        'source':         f'incidents/{filepath.name}',
    }


# ── 读取现有 AntiPatterns.md ─────────────────────────────────────────────────

def load_existing_patterns(ap_file: Path) -> dict:
    """返回 {ID: {...}} 映射。"""
    if not ap_file.exists():
        return {}
    content = ap_file.read_text(encoding='utf-8')
    patterns = {}
    for m in re.finditer(
        r'\|\s*([\w-]+)\s*\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|',
        content
    ):
        pid = m.group(1).strip()
        if pid and pid != 'ID':
            patterns[pid] = {
                'trigger':  m.group(2).strip(),
                'severity': m.group(3).strip(),
                'wrong':    m.group(4).strip(),
                'correct':  m.group(5).strip(),
                'status':   m.group(6).strip(),
                'source':   m.group(7).strip(),
            }
    return patterns


# ── 生成新 ID ─────────────────────────────────────────────────────────────────

def next_id(module: str, existing: dict) -> str:
    prefix = MODULE_PREFIX.get(module, 'UE')
    used = [int(k[len(prefix):]) for k in existing if k.startswith(prefix) and k[len(prefix):].isdigit()]
    n = max(used, default=0) + 1
    return f'{prefix}-{n:03d}'


# ── 写回 AntiPatterns.md ─────────────────────────────────────────────────────

def write_antipatterns(ap_file: Path, patterns: dict):
    """重写整个 AntiPatterns.md。"""
    header = ap_file.read_text(encoding='utf-8').split('## 条目')[0] if ap_file.exists() else ''
    if not header:
        header = '# 反模式百科\n\n> 由 /ue-antipatterns 自动提炼，人工确认后生效。\n\n'

    rows = []
    for pid, p in sorted(patterns.items()):
        rows.append(
            f'| {pid} | {p.get("trigger","")} | {p.get("severity","")} | '
            f'{p.get("wrong","")} | {p.get("correct","")} | '
            f'{p.get("status","")} | {p.get("source","")} |'
        )

    table = (
        '## 条目\n\n'
        '| ID | 触发关键词 | 风险 | 错误思路 | 正确做法 | status | 来源 |\n'
        '|----|-----------|------|---------|---------|--------|------|\n'
    ) + '\n'.join(rows) + '\n\n'

    usage = (
        '## 使用方式\n\n'
        '```bash\n'
        'python scripts/ue_antipattern_extract.py --project . --list      # 查看 pending\n'
        'python scripts/ue_antipattern_extract.py --project . --confirm BP-001\n'
        '```\n'
    )

    ap_file.write_text(header + table + usage, encoding='utf-8')


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='从 incidents/ 提炼反模式草案')
    parser.add_argument('--project', default='.', help='UE 项目路径')
    parser.add_argument('--list',    action='store_true', help='列出 pending 条目')
    parser.add_argument('--confirm', metavar='ID', help='确认某条（pending→confirmed）')
    parser.add_argument('--dry-run', action='store_true', help='只打印，不写入')
    args = parser.parse_args()

    project  = Path(args.project).resolve()
    inc_dir  = project / INCIDENTS_DIR
    ap_file  = project / ANTIPATTERNS_FILE

    # ── --list ─────────────────────────────────────────────────────────────────
    if args.list:
        patterns = load_existing_patterns(ap_file)
        pending = [(k, v) for k, v in patterns.items() if v.get('status') == 'pending']
        if not pending:
            print('没有待确认的反模式条目。')
        else:
            print(f'\n待确认条目（{len(pending)} 个）：')
            for pid, p in pending:
                print(f'  {pid}  [{p["severity"]}]  {p["trigger"]}')
                print(f'       错误：{p["wrong"][:60]}')
                print(f'       正确：{p["correct"][:60]}')
                print(f'       来源：{p["source"]}')
        return

    # ── --confirm ──────────────────────────────────────────────────────────────
    if args.confirm:
        patterns = load_existing_patterns(ap_file)
        pid = args.confirm
        if pid not in patterns:
            print(f'错误：未找到条目 {pid}', file=sys.stderr)
            sys.exit(1)
        patterns[pid]['status'] = 'confirmed'
        if not args.dry_run:
            write_antipatterns(ap_file, patterns)
        print(f'已确认：{pid} → confirmed')
        return

    # ── 扫描 incidents/ ────────────────────────────────────────────────────────
    if not inc_dir.exists():
        print(f'incidents/ 目录不存在：{inc_dir}', file=sys.stderr)
        sys.exit(2)

    existing = load_existing_patterns(ap_file)
    existing_sources = {v.get('source') for v in existing.values()}

    new_count = 0
    for inc_file in sorted(inc_dir.glob('*.md')):
        incident = parse_incident(inc_file)
        if not incident:
            continue

        source = f'incidents/{inc_file.name}'
        if source in existing_sources:
            continue  # 已提炼过

        if not incident.get('pattern'):
            print(f'  skip {inc_file.name}: 无「潜在反模式」字段')
            continue

        pid = next_id(incident['module'], existing)
        sev_map = {'high': '★★★', 'medium': '★★', 'low': '★'}
        severity = sev_map.get(incident['severity'], '★★')

        existing[pid] = {
            'trigger':  incident['trigger_action'],
            'severity': severity,
            'wrong':    incident.get('wrong', '').replace('\n', ' ')[:80],
            'correct':  incident.get('correct', '').split('\n')[0][:80],
            'status':   'pending',
            'source':   source,
        }
        existing_sources.add(source)
        print(f'  [新草案] {pid}  {incident["pattern"][:60]}')
        new_count += 1

    if new_count == 0:
        print('没有新事故文件需要处理。')
        sys.exit(1)

    if not args.dry_run:
        write_antipatterns(ap_file, existing)
        print(f'\n已生成 {new_count} 条 pending 草案 → {ap_file}')
        print('运行 --list 查看，--confirm <ID> 确认。')
    else:
        print(f'\n[dry-run] 共 {new_count} 条新草案（未写入）')


if __name__ == '__main__':
    main()
