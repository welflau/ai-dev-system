#!/usr/bin/env python3
"""
ue_rules_bridge.py — 轻量 MCP Server：按动作关键词检索 PSP 和反模式条目。

解决的问题：
  - AI 执行关键操作前需要查询 PSP.md 和 AntiPatterns.md
  - 全量读取文件浪费 token，且 AI 需要自己做关键词匹配
  - 本 MCP 提供精准检索：输入动作关键词，返回命中的条目

工具列表：
  get_ue_rules(action, project_root)
    → 返回命中的 PSP 条目 + 反模式条目列表

运行方式（MCP stdio 模式）：
  python scripts/ue_rules_bridge.py

在 .claude/ue-config.json 的 MCP 配置：
  {
    "mcpServers": {
      "ue-rules-bridge": {
        "command": "python",
        "args": ["F:/A_Works/UnrealECC/scripts/ue_rules_bridge.py"]
      }
    }
  }
"""

import json
import re
import sys
from pathlib import Path


# ── 解析文件 ──────────────────────────────────────────────────────────────────

def parse_psp(psp_file: Path) -> list[dict]:
    """解析 PSP.md 主表，返回条目列表。"""
    if not psp_file.exists():
        return []
    content = psp_file.read_text(encoding='utf-8')
    entries = []
    for m in re.finditer(
        r'\|\s*(PSP-\d+)\s*\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|',
        content
    ):
        pid, trigger, risk, wrong, correct, ref = [x.strip() for x in m.groups()]
        if pid == 'ID':
            continue
        entries.append({
            'id': pid, 'trigger': trigger, 'risk': risk,
            'wrong': wrong, 'correct': correct, 'ref': ref,
        })
    return entries


def parse_antipatterns(ap_file: Path) -> list[dict]:
    """解析 AntiPatterns.md，只返回 confirmed 条目。"""
    if not ap_file.exists():
        return []
    content = ap_file.read_text(encoding='utf-8')
    entries = []
    for m in re.finditer(
        r'\|\s*([\w-]+)\s*\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|',
        content
    ):
        pid, trigger, risk, wrong, correct, status, source = [x.strip() for x in m.groups()]
        if pid in ('ID', '') or status != 'confirmed':
            continue
        entries.append({
            'id': pid, 'trigger': trigger, 'risk': risk,
            'wrong': wrong, 'correct': correct, 'status': status,
        })
    return entries


# ── 关键词匹配 ────────────────────────────────────────────────────────────────

def match_entries(entries: list[dict], action: str) -> list[dict]:
    """按动作关键词模糊匹配条目。"""
    action_lower = action.lower()
    hits = []
    for entry in entries:
        trigger_lower = entry.get('trigger', '').lower()
        # 触发词里任意一个词命中动作描述，或动作描述包含触发词
        triggers = re.split(r'[/,，、\s]+', trigger_lower)
        if any(t and t in action_lower for t in triggers):
            hits.append(entry)
        elif any(word in trigger_lower for word in action_lower.split()):
            hits.append(entry)
    return hits


# ── MCP 协议处理 ──────────────────────────────────────────────────────────────

def find_project_root(hint: str = '') -> Path:
    """查找项目根目录（含 ue-config.json）。"""
    if hint:
        p = Path(hint)
        if (p / '.claude' / 'ue-config.json').exists():
            return p
    # 从当前目录向上查找
    for parent in [Path.cwd()] + list(Path.cwd().parents):
        if (parent / '.claude' / 'ue-config.json').exists():
            return parent
    return Path.cwd()


def handle_get_ue_rules(params: dict) -> dict:
    action       = params.get('action', '')
    project_root = find_project_root(params.get('project_root', ''))

    psp_file = project_root / '.claude' / 'ue-runtime' / 'PSP.md'
    ap_file  = project_root / '.claude' / 'ue-runtime' / 'AntiPatterns.md'

    psp_entries = parse_psp(psp_file)
    ap_entries  = parse_antipatterns(ap_file)

    psp_hits = match_entries(psp_entries, action)
    ap_hits  = match_entries(ap_entries, action)

    result_lines = []
    if psp_hits:
        result_lines.append(f'[PSP 命中 {len(psp_hits)} 条]')
        for e in psp_hits:
            result_lines.append(
                f'  {e["id"]} ({e["risk"]}): {e["trigger"]}\n'
                f'    错误做法: {e["wrong"][:80]}\n'
                f'    正确做法: {e["correct"][:80]}'
            )
    if ap_hits:
        result_lines.append(f'[反模式命中 {len(ap_hits)} 条]')
        for e in ap_hits:
            result_lines.append(
                f'  {e["id"]} ({e["risk"]}): {e["trigger"]}\n'
                f'    错误: {e["wrong"][:80]}\n'
                f'    正确: {e["correct"][:80]}'
            )
    if not psp_hits and not ap_hits:
        result_lines.append(f'未命中 PSP/反模式，动作「{action}」走通用做法。')

    return {
        'content': [{'type': 'text', 'text': '\n'.join(result_lines)}],
        'psp_hits':         [e['id'] for e in psp_hits],
        'antipattern_hits': [e['id'] for e in ap_hits],
        'total_hits':       len(psp_hits) + len(ap_hits),
    }


def run_mcp_server():
    """运行 MCP stdio 服务器主循环。"""
    # 发送 capabilities
    capabilities = {
        'jsonrpc': '2.0', 'id': 1,
        'result': {
            'protocolVersion': '2024-11-05',
            'capabilities': {'tools': {}},
            'serverInfo': {'name': 'ue-rules-bridge', 'version': '1.0'},
        }
    }

    tools_list = {
        'tools': [{
            'name': 'get_ue_rules',
            'description': '按动作关键词检索 PSP 项目特化做法和反模式条目。AI 执行关键操作前调用。',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'description': '本次要执行的动作，如「创建 Blueprint」「编译项目」「修改蓝图资产」',
                    },
                    'project_root': {
                        'type': 'string',
                        'description': 'UE 项目根目录（可选，默认自动查找）',
                    },
                },
                'required': ['action'],
            },
        }]
    }

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get('method', '')
        req_id = req.get('id')

        if method == 'initialize':
            resp = {'jsonrpc': '2.0', 'id': req_id, 'result': capabilities['result']}
        elif method == 'tools/list':
            resp = {'jsonrpc': '2.0', 'id': req_id, 'result': tools_list}
        elif method == 'tools/call':
            tool = req.get('params', {}).get('name', '')
            args = req.get('params', {}).get('arguments', {})
            if tool == 'get_ue_rules':
                result = handle_get_ue_rules(args)
                resp = {'jsonrpc': '2.0', 'id': req_id, 'result': result}
            else:
                resp = {'jsonrpc': '2.0', 'id': req_id,
                        'error': {'code': -32601, 'message': f'Unknown tool: {tool}'}}
        elif method == 'notifications/initialized':
            continue
        else:
            resp = {'jsonrpc': '2.0', 'id': req_id,
                    'error': {'code': -32601, 'message': f'Unknown method: {method}'}}

        print(json.dumps(resp), flush=True)


# ── 独立测试模式 ──────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        # 独立测试：直接查询
        action = ' '.join(sys.argv[2:]) or '创建 Blueprint'
        project_root = find_project_root()
        print(f'查询动作：{action}')
        print(f'项目根目录：{project_root}')
        result = handle_get_ue_rules({'action': action})
        print(result['content'][0]['text'])
    else:
        run_mcp_server()


if __name__ == '__main__':
    main()
