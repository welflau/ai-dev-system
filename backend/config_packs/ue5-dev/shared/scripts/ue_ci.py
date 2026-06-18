#!/usr/bin/env python3
"""
ue_ci.py — UE 项目 CI 流水线：编译检查 + 静态分析 + 报告

流程：
  L1 静态规则（< 1s）  → 7 条 UE 特定规则，拦截常见错误
  L2 UBT 编译（3-5min）→ 增量编译，报告 error/warning 统计
  L3 资产验证（< 30s） → 检查命名规范、必要插件、基础结构

用法：
    python scripts/ue_ci.py --project F:/UEProjects/MyGame
    python scripts/ue_ci.py --project . --skip-compile   # 只做静态检查
    python scripts/ue_ci.py --project . --level l1       # 只跑 L1

退出码：
    0 = 全部通过
    1 = 有 error（阻断）
    2 = 只有 warning（可继续）
    3 = 项目配置错误
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


# ── L1 静态规则（参考 ADS DevAgent_UE项目自测方案）────────────────────────────

L1_RULES = [
    # 规则名, 文件 glob, 正则, 错误描述
    ('missing_generated_body',
     '**/*.h',
     r'UCLASS\s*\(|USTRUCT\s*\(',
     None,  # 需要配对检查
     'UCLASS/USTRUCT 缺少 GENERATED_BODY()'),

    ('log_temp_usage',
     '**/*.cpp',
     r'UE_LOG\s*\(\s*LogTemp\s*,',
     r'UE_LOG\s*\(\s*LogTemp\s*,',
     '禁止使用 LogTemp，请定义专用 LogCategory'),

    ('stl_containers',
     '**/*.{cpp,h}',
     r'\bstd::(vector|map|string|unordered_map|set)\b',
     r'\bstd::(vector|map|string|unordered_map|set)\b',
     '禁止使用 STL 容器，改用 TArray/TMap/FString'),

    ('modify_generated_h',
     '*.generated.h',
     r'.',
     r'.',
     '禁止修改 .generated.h 文件'),

    ('null_ptr_deref_risk',
     '**/*.cpp',
     r'->(?!IsValid\(\)|Get\(\))',
     None,
     None),  # 仅统计，不报错

    ('missing_include_order_version',
     '*.Build.cs',
     r'IncludeOrderVersion',
     None,  # 检查是否有
     'Build.cs 建议添加 IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_3'),

    ('raw_new_delete',
     '**/*.cpp',
     r'\bnew\s+U[A-Z]|\bdelete\s+\w+',
     r'\bnew\s+U[A-Z]|\bdelete\s+\w+',
     '禁止对 UObject 使用 new/delete，使用 NewObject<>/GC'),
]


def run_l1(source_dir: Path) -> dict:
    """L1 静态规则检查，返回 {errors, warnings}"""
    results = {'errors': [], 'warnings': []}

    # ── 规则1：UCLASS/USTRUCT 缺少 GENERATED_BODY ──────────────────────────
    for f in source_dir.rglob('*.h'):
        if '.generated.' in f.name:
            continue
        try:
            content = f.read_text(encoding='utf-8', errors='ignore')
            # 同时有 UCLASS(/USTRUCT( 但缺少 GENERATED_BODY
            if re.search(r'UCLASS\s*\(|USTRUCT\s*\(', content):
                if 'GENERATED_BODY()' not in content and 'GENERATED_UCLASS_BODY()' not in content:
                    results['errors'].append({
                        'rule': 'missing_generated_body',
                        'file': str(f.relative_to(source_dir)),
                        'message': 'UCLASS/USTRUCT 缺少 GENERATED_BODY()',
                    })
        except Exception:
            pass

    # ── 规则2：禁止 LogTemp ──────────────────────────────────────────────────
    for f in source_dir.rglob('*.cpp'):
        try:
            content = f.read_text(encoding='utf-8', errors='ignore')
            if re.search(r'UE_LOG\s*\(\s*LogTemp\s*,', content):
                results['errors'].append({
                    'rule': 'log_temp_usage',
                    'file': str(f.relative_to(source_dir)),
                    'message': '禁止使用 LogTemp，请定义专用 LogCategory',
                })
        except Exception:
            pass

    # ── 规则3：禁止 STL 容器 ─────────────────────────────────────────────────
    for f in list(source_dir.rglob('*.cpp')) + list(source_dir.rglob('*.h')):
        if '.generated.' in f.name:
            continue
        try:
            content = f.read_text(encoding='utf-8', errors='ignore')
            m = re.search(r'\bstd::(vector|map|string|unordered_map|set)\b', content)
            if m:
                results['errors'].append({
                    'rule': 'stl_containers',
                    'file': str(f.relative_to(source_dir)),
                    'message': f'禁止使用 STL 容器 std::{m.group(1)}，改用 TArray/TMap/FString',
                })
        except Exception:
            pass

    # ── 规则4：禁止对 UObject 使用 new/delete ─────────────────────────────────
    for f in source_dir.rglob('*.cpp'):
        try:
            content = f.read_text(encoding='utf-8', errors='ignore')
            if re.search(r'\bnew\s+U[A-Z]\w+\s*[({]', content):
                results['errors'].append({
                    'rule': 'raw_new_uobject',
                    'file': str(f.relative_to(source_dir)),
                    'message': '禁止对 UObject 使用 new，使用 NewObject<>',
                })
        except Exception:
            pass

    # ── 规则5：Build.cs IncludeOrderVersion（warning）────────────────────────
    for f in source_dir.rglob('*.Build.cs'):
        try:
            content = f.read_text(encoding='utf-8', errors='ignore')
            if 'IncludeOrderVersion' not in content:
                results['warnings'].append({
                    'rule': 'missing_include_order_version',
                    'file': str(f.relative_to(source_dir)),
                    'message': '建议添加 IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_3',
                })
        except Exception:
            pass

    return results


# ── L2 UBT 编译 ───────────────────────────────────────────────────────────────

def run_l2(project_root: Path, ue_build_script: str) -> dict:
    """调用 ue_build.js 编译，解析输出。"""
    start = time.time()
    result = subprocess.run(
        ['node', ue_build_script, '--project', str(project_root)],
        capture_output=True, timeout=600,
    )
    elapsed = time.time() - start

    # 用 errors='replace' 避免 GBK/UTF-8 混合输出导致崩溃
    stdout = result.stdout.decode('utf-8', errors='replace') if result.stdout else ''
    stderr = result.stderr.decode('utf-8', errors='replace') if result.stderr else ''
    output = stdout + stderr
    errors   = re.findall(r'error [A-Z]\d+:.*|error:.*', output, re.IGNORECASE)
    warnings = re.findall(r'warning [A-Z]\d+:.*', output, re.IGNORECASE)

    return {
        'success':  result.returncode == 0,
        'elapsed':  f'{elapsed:.1f}s',
        'errors':   errors[:10],
        'warnings': warnings[:5],
        'output':   output[-500:] if not result.returncode == 0 else '',
    }


# ── L3 资产验证 ───────────────────────────────────────────────────────────────

def run_l3(project_root: Path) -> dict:
    """验证 .uproject、必要插件、Content 目录结构。"""
    issues = []

    # 检查 .uproject
    uprojects = list(project_root.glob('*.uproject'))
    if not uprojects:
        issues.append({'level': 'error', 'message': '未找到 .uproject 文件'})
        return {'issues': issues}

    try:
        uproject = json.loads(uprojects[0].read_text(encoding='utf-8'))
    except Exception as e:
        issues.append({'level': 'error', 'message': f'.uproject 解析失败: {e}'})
        return {'issues': issues}

    # 检查必要插件
    plugins = {p['Name']: p.get('Enabled', False)
               for p in uproject.get('Plugins', [])}
    required = {'PythonScriptPlugin': 'Python Editor Script Plugin（/ue-run 需要）'}
    for name, desc in required.items():
        if not plugins.get(name):
            issues.append({'level': 'warning', 'message': f'插件未启用：{name}（{desc}）'})

    # 检查 Source 目录
    source = project_root / 'Source'
    if not source.exists():
        issues.append({'level': 'error', 'message': 'Source/ 目录不存在'})
    else:
        targets = list(source.glob('*.Target.cs'))
        if len(targets) < 2:
            issues.append({'level': 'error',
                           'message': f'Target.cs 数量不足（{len(targets)}/2），需要 Game + Editor 两个'})

    # 检查 Config
    for cfg in ['DefaultGame.ini', 'DefaultEngine.ini']:
        if not (project_root / 'Config' / cfg).exists():
            issues.append({'level': 'warning', 'message': f'Config/{cfg} 不存在'})

    return {'issues': issues}


# ── 报告输出 ──────────────────────────────────────────────────────────────────

def print_report(l1, l2, l3, elapsed_total):
    # 纯 ASCII，避免 Windows GBK 终端编码问题
    e = '[FAIL]'
    w = '[WARN]'
    ok = '[OK]  '

    print(f'\n{"="*60}')
    print(f'  UnrealECC CI 报告  （总耗时 {elapsed_total:.1f}s）')
    print(f'{"="*60}')

    # L1
    l1_e = len(l1['errors'])
    l1_w = len(l1['warnings'])
    status = ok if l1_e == 0 else e
    print(f'\nL1 静态检查  {status}  error={l1_e}  warning={l1_w}')
    for v in l1['errors'][:5]:
        print(f'   {e} [{v["rule"]}] {v["file"]}: {v["message"]}')
    for v in l1['warnings'][:3]:
        print(f'   {w} [{v["rule"]}] {v["file"]}: {v["message"]}')

    # L2
    if l2:
        status = ok if l2['success'] else e
        print(f'\nL2 UBT 编译  {status}  耗时={l2["elapsed"]}  error={len(l2["errors"])}  warning={len(l2["warnings"])}')
        for err in l2['errors'][:3]:
            print(f'   {e} {err[:100]}')
        if not l2['success'] and l2['output']:
            # strip 非 ASCII 字符，避免 Windows GBK 终端编码问题
            safe_out = l2['output'][-200:].encode('ascii', errors='replace').decode('ascii')
            print(f'   Last output: {safe_out}')

    # L3
    l3_e = [i for i in l3['issues'] if i['level'] == 'error']
    l3_w = [i for i in l3['issues'] if i['level'] == 'warning']
    status = ok if not l3_e else e
    print(f'\nL3 资产验证  {status}  error={len(l3_e)}  warning={len(l3_w)}')
    for i in l3_e:
        print(f'   {e} {i["message"]}')
    for i in l3_w:
        print(f'   {w} {i["message"]}')

    # 总结
    total_errors = l1_e + (0 if not l2 else (0 if l2['success'] else 1)) + len(l3_e)
    print(f'\n{"="*60}')
    if total_errors == 0:
        print(f'  {ok}  全部通过')
    else:
        print(f'  {e}  发现 {total_errors} 个 error，需要修复')
    print(f'{"="*60}\n')

    return total_errors


# ── testing_tier 推荐 ─────────────────────────────────────────────────────────

def recommend_testing_tier(source_dir: Path, l1_result: dict) -> dict:
    """
    根据改动分析推荐 testing_tier（full / light / none）。
    参考 IG3C workflow testing_tier 3 档逻辑。

    返回 {'tier': str, 'reasons': list, 'hard_rule_hit': bool}
    """
    reasons = []
    hard_rule_hit = False

    # 统计 .cpp / .h 文件数（改动估算）
    cpp_files = list(source_dir.rglob('*.cpp')) + list(source_dir.rglob('*.h'))
    file_count = len(cpp_files)

    # ── 强制 full 的 5 条硬规则 ──────────────────────────────────────────────
    # 硬规则1: L1 有 error（反模式命中）
    if l1_result['errors']:
        rules_hit = [v['rule'] for v in l1_result['errors']]
        reasons.append(f'L1 error 命中反模式规则：{", ".join(set(rules_hit))}')
        hard_rule_hit = True

    # 硬规则2: 反射符号改动（UFUNCTION / UPROPERTY 变化）
    reflection_changed = False
    for f in cpp_files:
        try:
            content = f.read_text(encoding='utf-8', errors='ignore')
            if re.search(r'UFUNCTION\s*\(|UPROPERTY\s*\(', content):
                reflection_changed = True
                break
        except Exception:
            pass
    if reflection_changed:
        reasons.append('项目含 UFUNCTION/UPROPERTY（反射符号可能变化）')
        hard_rule_hit = True

    # 硬规则3: 文件数 >= 5
    if file_count >= 5:
        reasons.append(f'Source 文件数={file_count} (>=5)')
        hard_rule_hit = True

    # 硬规则4: 含网络相关代码
    for f in cpp_files:
        try:
            content = f.read_text(encoding='utf-8', errors='ignore')
            if re.search(r'DOREPLIFETIME|GetLifetimeReplicatedProps|RPC|_Implementation\b', content):
                reasons.append('含网络复制代码（Replicated/RPC）')
                hard_rule_hit = True
                break
        except Exception:
            pass

    if hard_rule_hit:
        return {'tier': 'full', 'reasons': reasons, 'hard_rule_hit': True}

    # ── none 判定（全部满足）────────────────────────────────────────────────
    # 无 L1 error/warning，无反射符号，文件数 < 3
    if not l1_result['errors'] and not l1_result['warnings'] and file_count < 3:
        reasons.append(f'无 L1 问题，文件数={file_count}(<3)，改动影响小')
        return {'tier': 'none', 'reasons': reasons, 'hard_rule_hit': False}

    # ── 默认 light ───────────────────────────────────────────────────────────
    reasons.append(f'文件数={file_count}，无硬规则命中（默认中间档）')
    return {'tier': 'light', 'reasons': reasons, 'hard_rule_hit': False}


def print_tier_recommendation(rec: dict):
    """输出 testing_tier 推荐报告。"""
    tier = rec['tier']
    tier_desc = {
        'full':  '完整 TC + 自动化测试（新功能/系统改造/★ AP 命中）',
        'light': '验收清单（bug 修复/单一行为/1-3 文件）',
        'none':  '无测试需要（纯重构/typo/注释）',
    }
    print(f'\n{"="*60}')
    print(f'  testing_tier 推荐: {tier.upper()}')
    print(f'  {tier_desc.get(tier, "")}')
    print(f'\n  分析依据:')
    for r in rec['reasons']:
        print(f'    - {r}')
    if rec['hard_rule_hit']:
        print(f'\n  [!] 命中硬规则，无法降档至 light/none')
    print(f'\n  接受: continue | 升档: full | 降档: light/none')
    print(f'{"="*60}\n')


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='UE 项目 CI 流水线')
    parser.add_argument('--project', default='.', help='UE 项目路径（默认当前目录）')
    parser.add_argument('--level', choices=['l1', 'l2', 'l3', 'all'], default='all')
    parser.add_argument('--skip-compile', action='store_true', help='跳过 L2 编译')
    args = parser.parse_args()

    project_root = Path(args.project).resolve()
    source_dir   = project_root / 'Source'

    # 读取 ue-config.json 获取工具路径
    config_path = project_root / '.claude' / 'ue-config.json'
    ue_build = None
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding='utf-8'))
            ue_build = cfg.get('ue_build_script')
        except Exception:
            pass

    if not ue_build:
        # 回退到同目录查找
        ue_build = str(Path(__file__).parent / 'ue_build.js')

    start = time.time()
    print(f'\n[CI] 项目：{project_root}')
    print(f'[CI] 层级：{args.level}')

    l1_result = {'errors': [], 'warnings': []}
    l2_result = None
    l3_result = {'issues': []}

    if args.level in ('l1', 'all') and source_dir.exists():
        print('[CI] L1 静态检查...')
        l1_result = run_l1(source_dir)

    if not args.skip_compile and args.level in ('l2', 'all'):
        print('[CI] L2 UBT 编译（可能需要 3-5 分钟）...')
        l2_result = run_l2(project_root, ue_build)

    if args.level in ('l3', 'all'):
        print('[CI] L3 资产验证...')
        l3_result = run_l3(project_root)

    total_errors = print_report(l1_result, l2_result, l3_result, time.time() - start)

    # testing_tier 推荐（L1 完成后给出）
    if source_dir.exists() and args.level in ('l1', 'all'):
        tier_rec = recommend_testing_tier(source_dir, l1_result)
        print_tier_recommendation(tier_rec)

    sys.exit(0 if total_errors == 0 else 1)


if __name__ == '__main__':
    main()
