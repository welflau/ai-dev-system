#!/usr/bin/env python3
"""
ue_runtime_init.py — 初始化 UE 项目的运行时状态目录 .claude/ue-runtime/

在 /ue-init 时调用，如目录已存在则跳过（不覆盖已有状态）。

用法：
    python scripts/ue_runtime_init.py --project D:/UEProjects/MyGame
    python scripts/ue_runtime_init.py  # 使用当前目录
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


RUNTIME_DIR    = '.claude/ue-runtime'
INCIDENTS_DIR  = '.claude/ue-runtime/incidents'

TEMPLATES = {
    'PROJECT_MAP.md': '''\
# {project_name} 项目地图

> 生成时间：{date}
> 运行 `/ue-run 更新项目地图` 刷新此文件

## 技术栈

- 引擎版本：{engine_version}
- 源码版本：{has_source_label}
- 主要语言：C++ + Blueprint

## C++ 模块

<!-- 运行 /ue-project-init 自动填充 -->

## 核心蓝图

| Blueprint | 父类 | 引用数 |
|-----------|------|--------|
| <!-- 待填充 --> | | |

## 资产概况

| 类型 | 数量 |
|------|------|
| <!-- 待填充 --> | |

## DataTable 配置表

| 表名 | 行数 | 用途 |
|------|------|------|
| <!-- 待填充 --> | | |

## 已扩展的引擎子系统

<!-- /ue-extend 完成后自动追加 -->
''',

    'SUBSYSTEMS.md': '''\
# 已扩展的引擎子系统

> 通过 `/ue-extend` 打通的子系统，文档存放于 `.claude/ue-knowledge/`

| 子系统 | 状态 | 扩展时间 | 能力文档 |
|--------|------|---------|---------|
| <!-- /ue-extend 完成后自动追加 --> | | | |

## 说明

- **状态**：✅ 完整 / ⚠️ 部分（商店版引擎限制）
- **能力文档**：`.claude/ue-knowledge/<module>-capability.md`
''',

    'DECISIONS.md': '''\
# 技术决策日志

> 记录本项目的关键架构决策，防止重复讨论已决定的事项

| 日期 | 决策 | 原因 | 影响范围 |
|------|------|------|---------|
| {date} | 接入 UnrealECC | AI 辅助 UE 开发 | 全局 |

''',

    'PROGRESS.md': '''\
# 开发进度

> 跨会话记录当前开发状态，每次会话结束自动更新

## 当前阶段

<!-- 手动填写或由 /ue-auto 自动更新 -->

## 已完成

- [{date}] UnrealECC 初始化

## 待完成

<!-- 在此记录待做事项 -->

## 已知问题

<!-- 记录未解决的 Bug 或限制 -->
''',

    'PSP.md': '''\
# {project_name} 项目特化做法清单（PSP）

> 生成时间：{date}
> **P-Start 协议**：AI 在每个阶段执行关键操作前必须查此表。
> 命中 → 按「正确做法」执行；未命中 → 走通用做法，并在 P4 评估是否补条目。

## 主表

| ID | 关键词触发 | 风险 | 错误做法（训练数据默认）| 正确做法 | 参考文档 |
|----|-----------|------|---------------------|---------|---------|
| PSP-001 | 创建 DataTable | ★★★ | Python new DataTable() | `unreal.UECCExtensions.create_data_table()` | ue-knowledge/datatable-capability.md |
| PSP-002 | 修改蓝图资产 / 创建 Blueprint | ★★★ | 手动操作 UE Editor | 通过 `/ue-run` 脚本操作 | rules/ue-python.md |
| PSP-003 | 编译项目 / 构建 | ★★★ | make / cmake / 直接 UBT | `node {ue_build_script}` | ue-config.json |
| PSP-004 | 连接 UE Editor / 执行 Python | ★★★ | 自己写 socket 代码 | `python {ue_python_script}` | ue-config.json |
| PSP-005 | 生成纹理 / 生成 Mesh | ★★ | 直接调 DALL-E/Meshy API | `python {generate_texture_script}` 或 `generate_mesh_script` | ue-config.json |
| PSP-006 | unreal.Color 颜色设置 | ★★★ | `Color(255,0,0,255)` = 红色 | 必须关键字参数 `Color(r=255,g=0,b=0,a=255)` | rules/ue-python.md |
| PSP-007 | ScopedEditorTransaction | ★★★ | 认为异常会自动回滚 | 事务块内提前验证所有参数 | rules/ue-python.md |
| PSP-008 | 多 UE Editor 并存 | ★★ | 连接任意响应的 Editor | 从 UE 项目目录运行 Claude，依赖 project_root 匹配 | docs/DevLog |

## P-Start 汇报格式

```
[P-Start] 已查 PSP：
  动作关键词：<本次动作>
  命中条目：PSP-00X（<描述>）/ 未命中
  执行方式：<按 PSP 指引 / 走通用做法>
```

## 维护说明

- 新踩坑 → 先写 `incidents/<date>_<keyword>.md`
- 运行 `/ue-antipatterns` → 自动提炼为 `AntiPatterns.md` 条目
- 高频高风险条目 → 升级到本表
''',

    'AntiPatterns.md': '''\
# {project_name} 反模式百科

> 生成时间：{date}
> 由 `/ue-antipatterns` 从 incidents/ 自动提炼，人工确认后生效。
> status=pending 需 owner 确认；status=confirmed 已验证生效。

## 条目

| ID | 触发关键词 | 风险 | 错误思路 | 正确做法 | status | 来源 |
|----|-----------|------|---------|---------|--------|------|
| BP-001 | ScopedEditorTransaction | ★★★ | Python 异常会自动回滚 C++ 事务 | 事务块内提前验证所有参数 | confirmed | incidents/20260516_bp_transaction.md |
| BP-002 | unreal.Color | ★★★ | Color(255,0,0,255) 是红色 | 必须用关键字参数 r=/g=/b= | confirmed | incidents/20260516_color_bgra.md |
| UE-001 | 多 Editor / 连接 Editor | ★★ | 连接任意响应的 Editor | 从项目目录运行 Claude | confirmed | incidents/20260515_multi_editor.md |
| CI-001 | ue_build / UBT 编译 | ★★ | -Project="$path" 嵌套引号 | -Project=$path 不加引号 | confirmed | incidents/20260517_build_quote.md |
| PY-001 | Python 脚本路径解析 | ★★ | Path(__file__).parent 是相对路径 | os.path.abspath(__file__) | confirmed | incidents/20260516_abspath.md |

## 使用方式

```bash
/ue-antipatterns          # 扫描 incidents/ 生成新草案
/ue-antipatterns --list   # 查看 pending 条目
/ue-antipatterns --confirm BP-003  # 确认某条
```
''',
}


def init_runtime(project_root: Path, config: dict):
    runtime_dir   = project_root / RUNTIME_DIR
    incidents_dir = project_root / INCIDENTS_DIR
    knowledge_dir = project_root / '.claude' / 'ue-knowledge'

    created = []

    for dirname in [runtime_dir, incidents_dir, knowledge_dir]:
        if not dirname.exists():
            dirname.mkdir(parents=True)
            created.append(str(dirname))

    date_str = datetime.now().strftime('%Y-%m-%d')
    ctx = {
        'project_name':            config.get('project_name', 'UnknownProject'),
        'engine_version':          config.get('engine_version', '5.x'),
        'has_source_label':        '源码版' if config.get('has_source') else '商店版',
        'date':                    date_str,
        'ue_python_script':        config.get('ue_python_script', 'scripts/ue_python.py'),
        'ue_build_script':         config.get('ue_build_script', 'scripts/ue_build.js'),
        'generate_texture_script': config.get('generate_texture_script', 'scripts/generate_texture.py'),
        'generate_mesh_script':    config.get('generate_mesh_script', 'scripts/generate_mesh.py'),
    }

    for filename, template in TEMPLATES.items():
        dest = runtime_dir / filename
        if not dest.exists():
            dest.write_text(template.format(**ctx), encoding='utf-8')
            created.append(str(dest))
        else:
            print(f'  skip   {RUNTIME_DIR}/{filename} (already exists)')

    return created


def main():
    parser = argparse.ArgumentParser(description='初始化 UE 项目运行时状态目录')
    parser.add_argument('--project', default='.', help='UE 项目根目录（默认当前目录）')
    args = parser.parse_args()

    project_root = Path(args.project).resolve()
    config_path = project_root / '.claude' / 'ue-config.json'

    if not config_path.exists():
        print(f'错误：未找到 {config_path}，请先运行 install-ue.js --target', file=sys.stderr)
        sys.exit(1)

    config = json.loads(config_path.read_text(encoding='utf-8'))

    print(f'\n初始化 ue-runtime 目录：{project_root / RUNTIME_DIR}')
    created = init_runtime(project_root, config)

    if created:
        print(f'\n新建文件：')
        for f in created:
            print(f'  {f}')
    print('\nue-runtime 初始化完成')


if __name__ == '__main__':
    main()
