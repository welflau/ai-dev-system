#!/usr/bin/env python3
"""
CSIG Code Security Skill - 数据上报脚本

该脚本用于主动上报技能使用数据到后端服务器。
通过 references/post-skill-workflow.md 定义的 hooks 工作流触发调用。

配置方式：硬编码上报服务器地址（21.214.71.122）

使用示例：
  python3 report.py load --language python --rules sec-rules-sqli.mdc
  python3 report.py code_generation --language python --rules sec-rules-sqli.mdc --code-lines 50
"""

import json
import sys
import os
import time
from datetime import datetime
from pathlib import Path
from urllib import request, error
from typing import Dict, List, Optional

# 超时时间（秒）
TIMEOUT = 15

# 最大重试次数
MAX_RETRIES = 3


def get_report_url() -> Optional[str]:
    """获取上报 URL（硬编码）"""
    # 硬编码的上报服务器地址（正确的端点）
    return "http://21.214.71.122/api/v1/security-skill/report"


def get_report_token() -> Optional[str]:
    """获取上报 Token（硬编码测试 Token）"""
    # 硬编码的测试认证 Token（根据需求文档）
    return "test-token-987654"


def get_user_info_from_storage() -> Optional[Dict[str, str]]:
    """从 CodeBuddy storage.json 获取用户信息（动态路径，跨平台兼容）"""
    home = Path.home()
    storage_paths = [
        home / "Library/Application Support/CodeBuddy CN/User/globalStorage/storage.json",  # macOS
        home / "AppData/Roaming/CodeBuddy CN/User/globalStorage/storage.json",  # Windows
        home / "AppData/Local/CodeBuddy CN/User/globalStorage/storage.json",  # Windows（备选）
        home / ".config/CodeBuddy CN/User/globalStorage/storage.json",  # Linux
    ]
    
    for path in storage_paths:
        if path.exists():
            try:
                with path.open('r', encoding='utf-8') as f:
                    storage = json.load(f)
                    user_id = storage.get("genie.userId")
                    user_name = storage.get("genie.userName")
                    
                    if user_id:
                        return {
                            "user_id": user_id,
                            "user_name": user_name or "unknown"
                        }
            except Exception as e:
                print(f"[Warning] 读取 storage.json 失败: {e}", file=sys.stderr, flush=True)
                continue
    
    return None


def get_user_id() -> str:
    """获取用户ID（优先从 storage.json，然后环境变量，最后系统用户名）"""
    # 优先从 storage.json 获取
    user_info = get_user_info_from_storage()
    if user_info:
        return user_info["user_id"]
    
    # 备选：从环境变量获取
    user_id = os.environ.get('CODEBUDDY_USER_ID')
    if user_id:
        return user_id
    
    # 最后备选：使用系统用户名
    return os.environ.get('USER', 'unknown')


def report_event(
    action: str,
    language: Optional[str] = None,
    rules_triggered: Optional[List[str]] = None,
    safe_functions_triggered: Optional[List[str]] = None,
    rule_count: int = 0,
    code_lines_generated: int = 0,
    path: Optional[str] = None
) -> bool:
    """
    上报事件数据到服务器
    
    Args:
        action: 动作类型 (load|code_generation)
        language: 编程语言
        rules_triggered: 触发的规则列表
        safe_functions_triggered: 触发的安全函数指南列表
        rule_count: 应用的规则数量
        code_lines_generated: 生成的代码行数
        path: 工作目录路径
    
    Returns:
        bool: 上报是否成功
    """
    if rules_triggered is None:
        rules_triggered = []
    if safe_functions_triggered is None:
        safe_functions_triggered = []
    
    # 构建上报数据
    # 使用本地时间（不带时区信息），后端按中国时间处理
    data = {
        "event_type": "security_skill_usage",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user_id": get_user_id(),
        "skill_name": "rules",
        "event_detail": {
            "language": language or "unknown",
            "rules_triggered": rules_triggered,
            "safe_functions_triggered": safe_functions_triggered,
            "rule_count": rule_count,
            "code_lines_generated": code_lines_generated,
            "path": path or os.getcwd()
        }
    }
    
    # 获取上报 URL 和 Token（硬编码）
    report_url = get_report_url()
    report_token = get_report_token()
    
    # 使用重试机制上报
    success = _send_report_with_retry(report_url, report_token, data)
    
    # 无论成功失败，都输出到 stdout 作为备份
    print(json.dumps(data), flush=True)
    
    return success


def _send_report_with_retry(url: str, token: str, data: Dict) -> bool:
    """
    带重试机制的上报（指数退避）
    
    Args:
        url: 目标URL
        token: 认证 Token
        data: 要发送的数据
    
    Returns:
        bool: 是否成功
    """
    for attempt in range(MAX_RETRIES):
        success = _send_report(url, token, data)
        if success:
            return True
        
        # 最后一次不需要等待
        if attempt < MAX_RETRIES - 1:
            wait_time = 2 ** attempt  # 指数退避：1s, 2s
            print(f"[Warning] 第 {attempt + 1} 次上报失败，{wait_time}s 后重试...",
                  file=sys.stderr, flush=True)
            time.sleep(wait_time)
    
    print(f"[Error] 上报失败，已重试 {MAX_RETRIES} 次", file=sys.stderr, flush=True)
    return False


def _send_report(url: str, token: str, data: Dict) -> bool:
    """
    发送上报数据到指定URL
    
    Args:
        url: 目标URL
        token: 认证 Token
        data: 要发送的数据
    
    Returns:
        bool: 是否成功
    """
    try:
        # 构建请求
        req = request.Request(
            url,
            data=json.dumps(data, ensure_ascii=False).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'X-API-Token': token,
                'User-Agent': 'CSIG-Security-Skill/1.0'
            },
            method='POST'
        )
        
        # 发送请求
        with request.urlopen(req, timeout=TIMEOUT) as response:
            if response.status in (200, 201):
                return True
            elif response.status == 409:
                # 去重冲突，视为成功
                return True
            else:
                print(f"[Warning] Report failed with status {response.status}", 
                      file=sys.stderr, flush=True)
                return False
    
    except error.HTTPError as e:
        if e.code == 409:
            # 去重冲突，视为成功
            return True
        print(f"[Warning] HTTP error during report: {e.code} {e.reason}", 
              file=sys.stderr, flush=True)
        return False
    
    except error.URLError as e:
        print(f"[Warning] Network error during report: {e.reason}", 
              file=sys.stderr, flush=True)
        return False
    
    except Exception as e:
        print(f"[Warning] Unexpected error during report: {str(e)}", 
              file=sys.stderr, flush=True)
        return False


def main():
    """命令行入口"""
    if len(sys.argv) < 2:
        print("Usage: report.py <action> [options]", file=sys.stderr)
        print("Example: report.py load", file=sys.stderr)
        print("Example: report.py code_generation --language c --rules sec-rules-sqli.mdc", 
              file=sys.stderr)
        sys.exit(1)
    
    action = sys.argv[1]
    
    # 解析命令行参数
    language = None
    rules_triggered = []
    safe_functions_triggered = []
    rule_count = 0
    code_lines_generated = 0
    path = None
    
    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        
        if arg == '--language' and i + 1 < len(sys.argv):
            language = sys.argv[i + 1]
            i += 2
        elif arg == '--rules' and i + 1 < len(sys.argv):
            rules_triggered = sys.argv[i + 1].split(',')
            rule_count = len(rules_triggered)
            i += 2
        elif arg == '--safe-functions' and i + 1 < len(sys.argv):
            safe_functions_triggered = sys.argv[i + 1].split(',')
            i += 2
        elif arg == '--code-lines' and i + 1 < len(sys.argv):
            code_lines_generated = int(sys.argv[i + 1])
            i += 2
        elif arg == '--path' and i + 1 < len(sys.argv):
            path = sys.argv[i + 1]
            i += 2
        else:
            i += 1
    
    # 如果没有通过参数传入 path,尝试从环境变量或当前工作目录获取
    if not path:
        # 优先从环境变量获取工作目录
        path = os.environ.get('PWD') or os.getcwd()
    
    # 执行上报
    success = report_event(
        action=action,
        language=language,
        rules_triggered=rules_triggered,
        safe_functions_triggered=safe_functions_triggered,
        rule_count=rule_count,
        code_lines_generated=code_lines_generated,
        path=path
    )
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
