#!/usr/bin/env python3
"""
ue_skill_extract.py — 从成功的 /ue-run 操作中提炼可复用 Skill 草案。

工作方式：
  1. 读取 .claude/ue-runtime/PROGRESS.md 中的操作记录
  2. 分析哪些 Python 代码片段值得复用
  3. 生成 Skill 草案到 .claude/ue-runtime/pending_skills/
  4. 提示用户确认后可升级为正式 Skill

用法：
    python scripts/ue_skill_extract.py --project F:/UEProjects/MyGame
    python scripts/ue_skill_extract.py --project . --session-log session.txt

参考：ADS 系统自进化-Skill自动沉淀方案
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(os.path.abspath(__file__)).parent


# ── 价值判断标准（参考 ADS SkillExtractorAction）────────────────────────────────

EXTRACTABLE_PATTERNS = [
    # (pattern_name, regex, description)
    ('actor_batch_op',
     r'for\s+\w+\s+in\s+.*get_all_level_actors.*:\s*\n.*set_editor_property',
     '批量修改 Actor 属性'),
    ('asset_import',
     r'AssetImportTask.*fill.*destination_path.*import_asset_tasks',
     '资产导入流程'),
    ('blueprint_create',
     r'BlueprintFactory.*set_editor_property.*parent_class.*create_asset.*Blueprint',
     'Blueprint 类创建'),
    ('datatable_readwrite',
     r'export_data_table_to_json.*json\.loads|json\.dumps.*fill_data_table_from_json',
     'DataTable 读写（JSON 中转）'),
    ('material_instance',
     r'MaterialEditingLibrary.*set_material_instance.*save_asset',
     '材质实例配置'),
    ('level_actor_spawn',
     r'spawn_actor_from_class.*ScopedEditorTransaction.*set_actor_label',
     'Actor 批量放置'),
]


# ── 从 PROGRESS.md 提取代码片段 ───────────────────────────────────────────────

def extract_from_progress(progress_file: Path) -> list[dict]:
    """从 PROGRESS.md 的「已完成」节提取有价值的操作记录。"""
    if not progress_file.exists():
        return []

    content = progress_file.read_text(encoding='utf-8')
    entries = []

    # 匹配 [timestamp] 操作记录
    for line in content.split('\n'):
        m = re.match(r'-\s*\[(.+?)\]\s*(.+)', line)
        if m:
            ts, desc = m.group(1), m.group(2)
            entries.append({'timestamp': ts, 'description': desc})

    return entries


# ── 从 session log 提取代码 ────────────────────────────────────────────────────

def extract_from_session_log(log_file: Path) -> list[dict]:
    """从会话日志中提取成功执行的 Python 代码块。"""
    if not log_file.exists():
        return []

    content = log_file.read_text(encoding='utf-8', errors='ignore')
    blocks = []

    # 提取 ue_python.py 调用的代码块
    pattern = re.compile(
        r'ue_python\.py["\s]+["\'](.*?)["\']',
        re.DOTALL
    )
    for m in pattern.finditer(content):
        code = m.group(1).strip()
        if len(code) > 50:  # 过滤太短的代码
            blocks.append({'code': code, 'source': 'session_log'})

    return blocks


# ── 判断代码是否值得提炼 ─────────────────────────────────────────────────────

def is_worth_extracting(code: str) -> tuple[bool, str]:
    """
    判断代码是否值得提炼为 Skill。
    返回 (worth, reason)。
    """
    # 过短的代码不值得
    if len(code) < 100:
        return False, '代码太短'

    # 只有 print 或简单查询的不值得
    if re.match(r'^import unreal\s*\n\s*print', code):
        return False, '只是简单查询'

    # 检查是否匹配任何高价值模式
    for name, pattern, description in EXTRACTABLE_PATTERNS:
        if re.search(pattern, code, re.DOTALL | re.IGNORECASE):
            return True, f'匹配模式：{description}'

    # 包含事务和多步操作的代码值得提炼
    if 'ScopedEditorTransaction' in code and code.count('\n') > 10:
        return True, '包含多步事务操作'

    return False, '未匹配到高价值模式'


# ── 生成 Skill 草案 ───────────────────────────────────────────────────────────

def generate_skill_draft(code: str, reason: str, name: str = None) -> dict:
    """生成 Skill 草案结构。"""
    # 提取代码的核心功能描述
    lines = [l.strip() for l in code.split('\n') if l.strip() and not l.strip().startswith('#')]
    first_meaningful = next((l for l in lines if 'import' not in l and l), '')

    auto_name = name or re.sub(r'\W+', '_', first_meaningful[:30]).lower() or 'ue_operation'
    timestamp = datetime.now().strftime('%Y-%m-%d')

    return {
        'name': f'ue_{auto_name}',
        'status': 'draft',
        'extracted_at': timestamp,
        'reason': reason,
        'code': code,
        'template': f"""# UE Skill: {auto_name}

> 状态：草案（待确认）
> 提炼时间：{timestamp}
> 提炼原因：{reason}

## 功能描述

<!-- 请描述此 Skill 的用途 -->

## 代码

```python
{code}
```

## 使用示例

```
/ue-run <描述>
# 执行上述代码逻辑
```

## 注意事项

- 确认代码中的路径和参数适用于当前项目
- 测试后删除 `status: draft` 标记，移动到 skills/ 目录
""",
    }


# ── 保存草案 ──────────────────────────────────────────────────────────────────

def save_draft(project_root: Path, draft: dict) -> Path:
    """保存 Skill 草案到 pending_skills 目录。"""
    pending_dir = project_root / '.claude' / 'ue-runtime' / 'pending_skills'
    pending_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{draft['name']}_{draft['extracted_at'].replace('-','')}.md"
    output = pending_dir / filename
    output.write_text(draft['template'], encoding='utf-8')

    # 更新草案索引
    index_file = pending_dir / 'INDEX.json'
    index = []
    if index_file.exists():
        try:
            index = json.loads(index_file.read_text(encoding='utf-8'))
        except Exception:
            pass

    index.append({
        'name': draft['name'],
        'file': filename,
        'status': 'draft',
        'extracted_at': draft['extracted_at'],
        'reason': draft['reason'],
    })
    index_file.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding='utf-8')

    return output


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='从成功操作提炼 UE Skill 草案')
    parser.add_argument('--project', default='.', help='UE 项目路径')
    parser.add_argument('--session-log', help='会话日志文件路径')
    parser.add_argument('--list', action='store_true', help='列出已有草案')
    args = parser.parse_args()

    project_root = Path(args.project).resolve()
    pending_dir = project_root / '.claude' / 'ue-runtime' / 'pending_skills'

    # 列出草案
    if args.list:
        index_file = pending_dir / 'INDEX.json'
        if not index_file.exists():
            print('没有待确认的 Skill 草案。')
            return
        index = json.loads(index_file.read_text(encoding='utf-8'))
        print(f'\n待确认的 Skill 草案（{len(index)} 个）：')
        for item in index:
            print(f'  [{item["status"]}] {item["name"]}  {item["extracted_at"]}  — {item["reason"]}')
        print(f'\n文件位置: {pending_dir}')
        print('确认后移动到 skills/ 目录，删除 status: draft 标记。')
        return

    drafts_created = 0

    # 从 session log 提取
    if args.session_log:
        log_path = Path(args.session_log)
        blocks = extract_from_session_log(log_path)
        print(f'从 session log 提取 {len(blocks)} 个代码块...')
        for b in blocks:
            worth, reason = is_worth_extracting(b['code'])
            if worth:
                draft = generate_skill_draft(b['code'], reason)
                path = save_draft(project_root, draft)
                print(f'  [draft] {draft["name"]} → {path.name}')
                drafts_created += 1

    # 从 PROGRESS.md 提取
    progress_file = project_root / '.claude' / 'ue-runtime' / 'PROGRESS.md'
    entries = extract_from_progress(progress_file)
    if entries:
        print(f'PROGRESS.md 中有 {len(entries)} 条记录（仅作参考，不自动提炼）')

    if drafts_created == 0 and not args.session_log:
        print('\n使用方法：')
        print(f'  python {__file__} --project . --session-log <会话日志>')
        print('  python {__file__} --project . --list  # 查看已有草案')
    else:
        print(f'\n共生成 {drafts_created} 个 Skill 草案，位于: {pending_dir}')
        print('运行 --list 查看详情，确认后移动到 skills/ 目录。')


if __name__ == '__main__':
    main()
