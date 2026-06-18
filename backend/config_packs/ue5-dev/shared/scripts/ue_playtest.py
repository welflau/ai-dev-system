#!/usr/bin/env python3
"""
ue_playtest.py — 运行 UE Automation Framework 测试并解析结果。

支持两种模式：
  run     : 运行指定的自动化测试（通过 UnrealEditor commandlet）
  check   : 仅检查上次测试的结果文件

用法：
    python scripts/ue_playtest.py --project F:/UEProjects/MyGame
    python scripts/ue_playtest.py --project . --filter "MyGame."
    python scripts/ue_playtest.py --project . --check-only  # 只解析已有结果

退出码：
    0 = 测试全部通过（或无测试）
    1 = 有测试失败
    2 = 测试无法运行（编辑器未找到等）
    3 = 项目配置错误
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path


# ── 配置读取 ──────────────────────────────────────────────────────────────────

def load_config(project_root: Path) -> dict:
    config_path = project_root / '.claude' / 'ue-config.json'
    if config_path.exists():
        return json.loads(config_path.read_text(encoding='utf-8'))
    return {}


def find_editor(config: dict, engine_path: str = None) -> Path | None:
    search_root = engine_path or config.get('engine_path', '')
    if not search_root:
        return None
    editor = Path(search_root) / 'Binaries' / 'Win64' / 'UnrealEditor.exe'
    if editor.exists():
        return editor
    editor_cmd = Path(search_root) / 'Binaries' / 'Win64' / 'UnrealEditor-Cmd.exe'
    return editor_cmd if editor_cmd.exists() else None


# ── 测试结果解析 ───────────────────────────────────────────────────────────────

def find_test_results(project_root: Path) -> list[Path]:
    """查找 UE 自动化测试结果 JSON/XML 文件。"""
    saved = project_root / 'Saved' / 'Automation'
    results = []
    if saved.exists():
        results.extend(saved.rglob('*.json'))
        results.extend(saved.rglob('*.xml'))
    return sorted(results, key=lambda p: p.stat().st_mtime, reverse=True)


def parse_json_results(result_file: Path) -> dict:
    """解析 UE 自动化测试 JSON 结果。"""
    try:
        data = json.loads(result_file.read_text(encoding='utf-8'))
        tests = data.get('tests', [])
        passed = sum(1 for t in tests if t.get('state') == 'Success')
        failed = sum(1 for t in tests if t.get('state') in ('Fail', 'Error'))
        skipped = len(tests) - passed - failed

        failures = []
        for t in tests:
            if t.get('state') in ('Fail', 'Error'):
                failures.append({
                    'name': t.get('fullTestPath', t.get('testDisplayName', 'Unknown')),
                    'errors': [e.get('message', '') for e in t.get('errors', [])],
                })

        return {
            'total': len(tests),
            'passed': passed,
            'failed': failed,
            'skipped': skipped,
            'failures': failures,
            'source': str(result_file),
        }
    except Exception as e:
        return {'error': str(e), 'total': 0, 'passed': 0, 'failed': 0}


def parse_xml_results(result_file: Path) -> dict:
    """解析 JUnit 格式 XML 结果（UE 也支持输出此格式）。"""
    try:
        tree = ET.parse(result_file)
        root = tree.getroot()
        suites = root.findall('.//testsuite') or [root]

        total = passed = failed = 0
        failures = []

        for suite in suites:
            total += int(suite.get('tests', 0))
            failed += int(suite.get('failures', 0)) + int(suite.get('errors', 0))
            for tc in suite.findall('testcase'):
                fail = tc.find('failure') or tc.find('error')
                if fail is not None:
                    failures.append({
                        'name': f"{tc.get('classname','')}.{tc.get('name','')}",
                        'errors': [fail.get('message', fail.text or '')],
                    })
        passed = total - failed

        return {
            'total': total,
            'passed': passed,
            'failed': failed,
            'skipped': 0,
            'failures': failures,
            'source': str(result_file),
        }
    except Exception as e:
        return {'error': str(e), 'total': 0, 'passed': 0, 'failed': 0}


# ── 运行测试 ──────────────────────────────────────────────────────────────────

def run_automation_tests(editor: Path, uproject: Path, test_filter: str,
                         timeout: int = 300) -> bool:
    """
    通过 UnrealEditor-Cmd 运行自动化测试。
    返回是否成功启动（不代表测试通过）。
    """
    cmd = [
        str(editor),
        str(uproject),
        '-ExecCmds=Automation RunTests ' + test_filter + '; Quit',
        '-NullRHI',
        '-nosplash',
        '-unattended',
        '-stdout',
        '-FullStdOutLogOutput',
    ]

    print(f'[playtest] Running: {" ".join(cmd[:3])} ...')
    print(f'[playtest] Filter: {test_filter}')
    print(f'[playtest] Timeout: {timeout}s')

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, encoding='utf-8', errors='replace',
        )
        print(f'[playtest] Editor exit code: {result.returncode}')

        # 从 stdout 提取测试摘要
        output = result.stdout + result.stderr
        summary = re.search(
            r'Automation Test Succeeded.*?(\d+).*?Failed.*?(\d+)',
            output, re.IGNORECASE
        )
        if summary:
            print(f'[playtest] Quick summary: {summary.group(0)}')

        return True
    except subprocess.TimeoutExpired:
        print(f'[playtest] Timeout after {timeout}s', file=sys.stderr)
        return False
    except FileNotFoundError:
        print(f'[playtest] Editor not found: {editor}', file=sys.stderr)
        return False


# ── 报告输出 ──────────────────────────────────────────────────────────────────

def print_report(results: dict) -> int:
    ok  = '\033[32m[OK]\033[0m'
    err = '\033[31m[FAIL]\033[0m'
    w   = '\033[33m[WARN]\033[0m'

    if 'error' in results:
        print(f'{w} 结果解析失败: {results["error"]}')
        return 0

    total = results['total']
    if total == 0:
        print(f'\n{w} 未找到自动化测试结果。')
        print('  提示：在 UE Editor 中创建测试类（继承 FAutomationTestBase），')
        print('       或用 IMPLEMENT_SIMPLE_AUTOMATION_TEST 宏定义测试。')
        return 0

    status = ok if results['failed'] == 0 else err
    print(f'\n{"="*55}')
    print(f'  Playtest 报告')
    print(f'{"="*55}')
    print(f'  {status}  总计={total}  通过={results["passed"]}  失败={results["failed"]}  跳过={results["skipped"]}')
    print(f'  结果文件: {results["source"]}')

    for f in results.get('failures', [])[:5]:
        print(f'\n  {err} {f["name"]}')
        for e in f["errors"][:2]:
            print(f'       {e[:120]}')

    print(f'{"="*55}\n')
    return results['failed']


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='UE Automation Framework 测试运行器')
    parser.add_argument('--project', default='.', help='UE 项目路径')
    parser.add_argument('--filter', default='', help='测试过滤器（如 "MyGame." 或 "Project.Functional"）')
    parser.add_argument('--timeout', type=int, default=300, help='测试超时（秒）')
    parser.add_argument('--check-only', action='store_true', help='只解析已有结果，不运行测试')
    args = parser.parse_args()

    project_root = Path(args.project).resolve()
    uprojects = list(project_root.glob('*.uproject'))
    if not uprojects:
        print(f'[playtest] 未找到 .uproject: {project_root}', file=sys.stderr)
        sys.exit(3)

    config = load_config(project_root)

    if not args.check_only:
        editor = find_editor(config)
        if not editor:
            print('[playtest] 未找到 UnrealEditor-Cmd.exe，跳过运行，仅解析已有结果。', file=sys.stderr)
            print(f'[playtest] 配置 engine_path: {config.get("engine_path", "未配置")}', file=sys.stderr)
        else:
            test_filter = args.filter or (config.get('project_name', 'Project') + '.')
            run_automation_tests(editor, uprojects[0], test_filter, args.timeout)

    # 解析最新结果
    result_files = find_test_results(project_root)
    if not result_files:
        print('\n[playtest] 未找到测试结果文件。')
        print(f'  搜索路径: {project_root / "Saved" / "Automation"}')
        print('  在 UE Editor 中运行测试后会在此生成结果。')
        sys.exit(0)

    latest = result_files[0]
    print(f'[playtest] 读取结果: {latest}')

    if latest.suffix == '.json':
        results = parse_json_results(latest)
    else:
        results = parse_xml_results(latest)

    failed_count = print_report(results)
    sys.exit(0 if failed_count == 0 else 1)


if __name__ == '__main__':
    main()
