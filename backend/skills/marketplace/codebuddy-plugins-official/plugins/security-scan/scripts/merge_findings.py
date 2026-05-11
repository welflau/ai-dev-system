#!/usr/bin/env python3
"""
审计结果合并脚本：将多个 agent 的审计输出合并、去重、校验，减少编排器上下文消耗

子命令：
  merge-scan     合并扫描阶段所有 agent 输出（格式校验 + 去重 + 分配 findingId）
  merge-verify   合并验证阶段结果（代码存在性校验 + 攻击链验证 + 对抗审查 + 全局审计质量评估 + 置信度评分）

  别名：merge-stage2 = merge-scan, merge-stage3 = merge-verify

设计原则：
  - 完整结果写入文件，stdout 仅输出机器可读的 JSON 摘要供编排器解析
  - 日志信息输出到 stderr，不污染 stdout
  - 缺失可选输入文件时降级处理，不中断流程

Sink 分批 / 续扫模式：
  merge-scan --extra-agents vuln-scan-cont
  动态加载额外 agent 产物文件，支持 Sink 分批和续扫场景。
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from _common import (
    Colors, make_logger, stdout_json,
    load_json_file, write_json_file,
    SEVERITY_ORDER, normalize_finding, to_report_format,
)


# Fast P0：bypass 路径前置的 pre-check 兜底
# 采用函数级 lazy import，避免 verifier 模块在单元测试或非 fast 路径下被强加载
def _lazy_import_run_pre_check():
    try:
        from verifier import run_pre_check  # type: ignore
        return run_pre_check
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 风险类型中文 → slug 映射
RISK_TYPE_SLUG = {
    "SQL 注入": "sql-injection",
    "SQL注入": "sql-injection",
    "命令注入": "command-injection",
    "路径遍历": "path-traversal",
    "访问控制缺失": "access-control",
    "敏感信息泄露": "information-leak",
    "弱加密算法": "weak-crypto",
    "敏感端点暴露": "endpoint-exposure",
    "硬编码凭证": "hardcoded-secret",
    "高危漏洞": "vulnerable-dependency",
    "高危组件漏洞": "vulnerable-dependency",
    "供应链漏洞": "vulnerable-dependency",
    "vulnerable-dependency": "vulnerable-dependency",
    "CSV 注入": "csv-injection",
    "拒绝服务": "denial-of-service",
    "不安全反序列化": "insecure-deserialization",
    "insecure-deserialization": "insecure-deserialization",
    "XStream 反序列化": "insecure-deserialization",
    "XStream反序列化": "insecure-deserialization",
    "SSRF": "ssrf",
    "XSS": "xss",
    "xss": "xss",
    "反射型 XSS": "xss",
    "反射型XSS": "xss",
    "存储型 XSS": "xss",
    "存储型XSS": "xss",
    "DOM型 XSS": "xss",
    "DOM型XSS": "xss",
    "服务端请求伪造": "ssrf",
    "SSRF + JWT JKU 头部欺骗": "ssrf",
    "JWT 弱密钥 + alg=none 攻击": "jwt-security",
    # --- 以下为 agent 高频产出的中文 riskType 归一化映射 ---
    "硬编码密钥": "hardcoded-secret",
    "硬编码秘钥": "hardcoded-secret",
    "hardcoded-secret": "hardcoded-secret",
    "缺少认证机制": "missing-auth",
    "缺少认证": "missing-auth",
    "认证缺失": "missing-auth",
    "missing-auth": "missing-auth",
    "缺少安全头": "missing-security-headers",
    "missing-security-headers": "missing-security-headers",
    "缺少速率限制": "missing-rate-limit",
    "missing-rate-limit": "missing-rate-limit",
    "不安全的npm源": "insecure-npm-registry",
    "不安全的puppeteer配置": "insecure-puppeteer-config",
    "不安全的Puppeteer配置": "insecure-puppeteer-config",
    "弱密码学": "weak-crypto",
    "weak-cryptography": "weak-crypto",
    "信息泄露": "information-disclosure",
    "information-disclosure": "information-disclosure",
    "不安全配置": "insecure-configuration",
    "insecure-configuration": "insecure-configuration",
    "ssrf": "ssrf",
    "command-injection": "command-injection",
    "ssrf-defense-disabled": "ssrf-defense-disabled",
    "SSRF防御禁用": "ssrf-defense-disabled",
    "SSRF防御被禁用": "ssrf-defense-disabled",
    # --- scanner 高频产出的中文 riskType 归一化映射 ---
    "CSRF 保护全局禁用": "csrf-disabled",
    "CSRF保护全局禁用": "csrf-disabled",
    "csrf-disabled": "csrf-disabled",
    "CSRF": "csrf",
    "csrf": "csrf",
    "安全响应头全局禁用": "missing-security-headers",
    "安全响应头禁用": "missing-security-headers",
    "明文密码存储": "insecure-password-storage",
    "明文密码存储（NoOpPasswordEncoder）": "insecure-password-storage",
    "NoOpPasswordEncoder": "insecure-password-storage",
    "insecure-password-storage": "insecure-password-storage",
    "缺失功能级访问控制": "missing-access-control",
    "missing-access-control": "missing-access-control",
    "IDOR": "idor",
    "idor": "idor",
    "越权访问": "idor",
    "水平越权": "idor",
    "垂直越权": "idor",
    "JWT 签名密钥硬编码": "hardcoded-secret",
    "JWT签名密钥硬编码": "hardcoded-secret",
    "JWT KID 参数 SQL 注入": "sql-injection",
    "密码重置链接劫持": "host-header-injection",
    "密码重置链接通过 Host Header 注入劫持": "host-header-injection",
    "Host Header 注入": "host-header-injection",
    "host-header-injection": "host-header-injection",
    "Cookie 认证使用可逆弱编码": "weak-crypto",
    "Cookie 认证使用可逆弱编码而非加密签名": "weak-crypto",
    "会话 ID 生成使用可预测": "insecure-session",
    "会话ID生成使用可预测": "insecure-session",
    "会话 ID 生成使用可预测的顺序递增算法": "insecure-session",
    "insecure-session": "insecure-session",
    "会话劫持": "insecure-session",
    "会话固定": "insecure-session",
    "认证绕过": "authentication-bypass",
    "authentication-bypass": "authentication-bypass",
    "Actuator 端点未授权访问": "endpoint-exposure",
    "Actuator端点未授权访问": "endpoint-exposure",
    "JWT Refresh Token 劫持": "jwt-security",
    "JWT Refresh Token 流程": "jwt-security",
    "JWT Refresh Token 流程中信任过期 Token 的 Claims": "jwt-security",
    "jwt-security": "jwt-security",
    "JWT 弱密钥": "jwt-security",
    "JWT弱密钥": "jwt-security",
    "JWT 签名密钥硬编码": "hardcoded-secret",
    "JWT签名密钥硬编码": "hardcoded-secret",
    "JWT 签名密钥硬编码且强度不足": "hardcoded-secret",
    "WebWolf POST 端点": "endpoint-exposure",
    "允许未认证访问": "endpoint-exposure",
    "开放重定向": "open-redirect",
    "open-redirect": "open-redirect",
    "日志注入": "log-injection",
    "log-injection": "log-injection",
    "客户端价格篡改": "business-logic",
    "优惠券折扣逻辑缺陷": "business-logic",
    "服务端未验证订单总价": "business-logic",
    "business-logic": "business-logic",
    "XXE": "xxe",
    "xxe": "xxe",
    "XXE注入": "xxe",
    "XXE 外部实体注入": "xxe",
    "不安全随机数": "insecure-random",
    "insecure-random": "insecure-random",
    "不安全的随机数生成": "insecure-random",
    "Cookie 安全属性缺失": "insecure-cookie",
    "insecure-cookie": "insecure-cookie",
    "Cookie安全属性缺失": "insecure-cookie",
    "Cookie 缺少 Secure 标志": "insecure-cookie",
    "Cookie 缺少 HttpOnly 标志": "insecure-cookie",
    "弱哈希算法": "weak-hash",
    "弱哈希算法（密码存储）": "weak-hash",
    "weak-hash": "weak-hash",
    "MD5 哈希": "weak-hash",
    "SHA1 哈希": "weak-hash",
}

SLUG_RISK_TYPE = {v: k for k, v in RISK_TYPE_SLUG.items()}

# 语义分析 agent（需要检查 traceMethod）
SEMANTIC_AGENTS = {"vuln-scan", "logic-scan", "red-team"}

# 语义分析 agent 去重优先级（值越大越优先保留）
AGENT_PRIORITY = {
    "vuln-scan": 3,
    "logic-scan": 3,
    "red-team": 3,
    "light-inline": 2,
    "indexer-findings": 1,
    "pattern-matching": 0,
}


# ---------------------------------------------------------------------------
# attackChain 验证
# ---------------------------------------------------------------------------


def _is_valid_chain_node(node):
    """Check if a chain node (source/sink) is valid.

    Accepts two formats:
      - string: non-empty string (e.g. "src/routes.js:39")
      - object: dict with at least a 'file' key (e.g. {"file": "src/routes.js", "line": 39, "code": "..."})
    """
    if isinstance(node, str):
        return bool(node.strip())
    if isinstance(node, dict):
        return bool(node.get('file'))
    return False


def validate_attack_chain(chain):
    """Validate attackChain conforms to schema. Returns (valid, reason).

    source/sink accept both string and object {"file", "line", "code"} formats,
    since scanner produces structured objects while pattern-matching uses strings.
    """
    if not isinstance(chain, dict):
        return False, "attackChain is not a dict"
    source = chain.get('source')
    if not _is_valid_chain_node(source):
        return False, "missing or empty source"
    propagation = chain.get('propagation')
    if not isinstance(propagation, list):
        return False, "propagation is not a list"
    sink = chain.get('sink')
    if not _is_valid_chain_node(sink):
        return False, "missing or empty sink"
    trace = chain.get('traceMethod')
    if not trace or not isinstance(trace, str):
        return False, "missing traceMethod"
    return True, ""


# ---------------------------------------------------------------------------
# 日志工具
# ---------------------------------------------------------------------------

log_info, log_ok, log_warn, log_error = make_logger("merge")


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def _extract_scan_mode_from_batch_id(batch_id):
    """从 batch_id 推导扫描模式。

    batch_id 格式: {command}-{mode}-{timestamp}, 如 "project-deep-20260324152056"
    """
    if not batch_id:
        return 'unknown'
    parts = batch_id.split('-')
    known_modes = {'deep', 'light', 'fast'}
    if len(parts) >= 2 and parts[1] in known_modes:
        return parts[1]
    if len(parts) >= 1 and parts[0] in known_modes:
        return parts[0]
    return 'unknown'

def normalize_severity(level):
    """标准化风险等级为 critical/high/medium/low 四级"""
    if not level:
        return ""
    level_lower = str(level).lower().strip()
    if level_lower in ('critical', '严重'):
        return 'critical'
    elif level_lower in ('high', '高'):
        return 'high'
    elif level_lower in ('medium', 'moderate', '中', '中等'):
        return 'medium'
    elif level_lower in ('low', '低'):
        return 'low'
    return level_lower


def normalized_severity_rank(sev):
    """获取严重性排序值（高值优先），先标准化再排序"""
    return SEVERITY_ORDER.get(normalize_severity(sev), 0)


def lower_severity(sev):
    """降低一级严重性"""
    s = normalize_severity(sev)
    if s == 'critical':
        return 'high'
    elif s == 'high':
        return 'medium'
    elif s == 'medium':
        return 'low'
    return 'low'


def raise_severity(sev):
    """提升一级严重性"""
    s = normalize_severity(sev)
    if s == 'low':
        return 'medium'
    elif s == 'medium':
        return 'high'
    elif s == 'high':
        return 'critical'
    return 'critical'


def group_findings_by_file(findings):
    """按文件路径分组 findings"""
    by_file = {}
    for f in findings:
        fp = f.get('filePath', '')
        if fp:
            by_file.setdefault(fp, []).append(f)
    return by_file


def detect_vulnerability_chains(findings):
    """标记潜在漏洞链候选：同一文件存在 ≥2 个不同类型的漏洞时，标记为链候选。
    返回 chain_candidates 列表，每项包含 file、findingIds、riskTypes。
    """
    by_file = group_findings_by_file(findings)
    chain_candidates = []
    for file_path, file_findings in by_file.items():
        risk_types = set(f.get('riskType', '') for f in file_findings)
        if len(file_findings) >= 2 and len(risk_types) >= 2:
            chain_candidates.append({
                "file": file_path,
                "findingIds": [f.get('findingId', '') for f in file_findings],
                "riskTypes": list(risk_types),
            })
    return chain_candidates


def risk_type_to_slug(risk_type):
    """将风险类型转换为 slug。

    匹配策略（按优先级）：
      1. 精确匹配 RISK_TYPE_SLUG
      2. 大小写无关精确匹配
      3. 截取 " — " / " - " 前缀后重新匹配（处理描述性 riskType）
      4. 关键词包含匹配（riskType 包含某个已知 key）
      5. 自动生成 slug（兜底）
    """
    if not risk_type:
        return "unknown"
    # 1. 精确匹配
    slug = RISK_TYPE_SLUG.get(risk_type)
    if slug:
        return slug
    # 2. 大小写无关精确匹配
    rt_lower = risk_type.lower().strip()
    for cn, sl in RISK_TYPE_SLUG.items():
        if rt_lower == cn.lower() or rt_lower == sl:
            return sl
    # 3. 截取分隔符前缀后重新匹配（scanner 常见格式："IDOR — 水平越权查看..."）
    for sep in (' — ', ' - ', '（', '—'):
        if sep in risk_type:
            prefix = risk_type.split(sep)[0].strip()
            slug = RISK_TYPE_SLUG.get(prefix)
            if slug:
                return slug
            prefix_lower = prefix.lower()
            for cn, sl in RISK_TYPE_SLUG.items():
                if prefix_lower == cn.lower():
                    return sl
    # 4. 关键词包含匹配（riskType 中包含已知关键词）
    for cn, sl in RISK_TYPE_SLUG.items():
        if len(cn) >= 2 and cn in risk_type:
            return sl
    # 5. 自动生成 slug（兜底）
    return rt_lower.replace(' ', '-').replace('_', '-')


# ---------------------------------------------------------------------------
# 阶段 2 合并逻辑
# ---------------------------------------------------------------------------

def extract_findings_from_agent(data, agent_name):
    """从 agent 输出中提取 findings 列表并标记来源。

    当 finding 包含 affectedFiles[] 时，为每个 affected file 自动生成
    一个派生 finding（继承 riskType、severity、attackChain 等字段，
    但 filePath 和 lineNumber 更新为 affected file 的信息）。
    """
    if data is None:
        return []

    findings = []
    # 兼容裸数组 [...] 和对象 {"findings": [...]} 两种格式
    if isinstance(data, list):
        raw_findings = data
    else:
        raw_findings = data.get('findings', [])

    for f in raw_findings:
        # 使用集中归一化函数统一字段名
        normalized = normalize_finding(f, source_agent=agent_name)

        findings.append(normalized)

        # --- affectedFiles 自动展开 ---
        affected_files = f.get('affectedFiles', [])
        if isinstance(affected_files, list) and affected_files:
            parent_file = normalized['filePath']
            for af in affected_files:
                af_path = af if isinstance(af, str) else (af.get('filePath') or af.get('file') or '')
                af_line = 0 if isinstance(af, str) else (af.get('lineNumber') or af.get('line') or 0)
                if not af_path or af_path == parent_file:
                    continue  # 跳过空路径或与父 finding 相同的文件
                derived = dict(normalized)
                derived['filePath'] = af_path
                derived['lineNumber'] = int(af_line) if af_line else 1
                derived['_derivedFrom'] = normalized.get('filePath', '')
                derived['_derivedFromLine'] = normalized.get('lineNumber', 0)
                # 移除原始的 affectedFiles，避免派生 finding 再次被展开
                derived.pop('affectedFiles', None)
                # description 标记为派生
                parent_detail = normalized.get('description', '')
                derived['description'] = f"[同类漏洞，派生自 {parent_file}] {parent_detail}"
                findings.append(derived)
            log_info(f"  affectedFiles 展开：{parent_file} → {len(affected_files)} 个派生 finding")

    return findings


def extract_findings_from_pattern_scan(data):
    """从 pattern-scan-results.json 提取 findings"""
    if data is None:
        return []

    findings = []

    # 提取 cveFindings
    for f in data.get('cveFindings', []):
        dependency_file = (
            f.get('dependencyFile') or f.get('manifestFile') or
            f.get('declFile') or f.get('filePath') or f.get('file') or ''
        )
        line_number = (
            f.get('declarationLine') or f.get('lineNumber') or f.get('line') or 1
        )
        component = f.get('component') or f.get('package') or ''
        version = f.get('currentVersion') or f.get('version') or ''
        cve = f.get('cve') or f.get('advisoryId') or ''
        code_snippet = f.get('code') or f.get('RiskCode') or f.get('codeSnippet') or ''
        if not code_snippet and component:
            code_snippet = f"{component}:{version}" if version else component
        desc = f.get('description') or f.get('RiskDetail') or f.get('riskDetail') or ''
        if not desc and component:
            parts = [component]
            if version:
                parts.append(version)
            if cve:
                parts.append(cve)
            desc = " / ".join(parts)

        raw_finding = dict(f)
        raw_finding.update({
            'filePath': dependency_file,
            'lineNumber': int(line_number),
            'riskType': f.get('type') or f.get('riskType') or '高危组件漏洞',
            'severity': f.get('severity') or 'medium',
            'codeSnippet': code_snippet,
            'description': desc,
        })
        findings.append(normalize_finding(raw_finding, source_agent='pattern-matching'))

    # 提取 configFindings
    for f in data.get('configFindings', []):
        raw_finding = dict(f)
        raw_finding.update({
            'riskType': f.get('type') or f.get('pattern') or f.get('riskType') or '',
        })
        findings.append(normalize_finding(raw_finding, source_agent='pattern-matching'))

    # 提取 findings（通用数组，部分 pattern-matching 直接用这个字段）
    for f in data.get('findings', []):
        findings.append(normalize_finding(f, source_agent='pattern-matching'))

    return findings


def validate_finding(finding):
    """校验 finding 必需字段，返回 (valid, reason)"""
    if not finding.get('filePath'):
        return False, "missing filePath"
    if not finding.get('lineNumber'):
        return False, "missing lineNumber"
    if not finding.get('riskType'):
        return False, "missing riskType"
    if not finding.get('severity'):
        return False, "missing severity"
    return True, ""


# --- Agent 字段名漂移兼容映射（覆盖日志观察到的所有漂移场景） ---
# 背景：不同模型（glm/opus 等）产出 finding 时字段命名风格不一致（snake_case / camelCase / 别名），
# 导致 validate_finding 丢弃正常 finding 后触发编排器手工修复，平均每次故障省 1-2 分钟。
# 此处在 validate_finding 之前统一归一化字段名，覆盖 light/fast/未来所有模式。
#
# 设计原则：仅保留语义明确、低歧义的别名。刻意不加入 'type' / 'path' / 'level'
# 这三个在代码中含义泛化的字段名，避免误吃 Deep 模式 Agent 输出中表达其他含义的字段
# （例如 indexer-findings 的 'type' 可能指 secret/config/cve 的子分类）。
# 实际丢弃案例如仍发现 `type` 等字段遗漏，通过新增具体别名逐条扩展，不要放开通用名。
_FIELD_ALIASES = {
    'riskType': ['riskType', 'finding_type', 'findingType',
                 'vulnerability_type', 'vulnType', 'vulnerabilityType',
                 'category', 'issueType'],
    'filePath': ['filePath', 'file_path', 'FilePath', 'file',
                 'source_file', 'sourceFile'],
    'lineNumber': ['lineNumber', 'line', 'line_number', 'LineNumber',
                   'lineno', 'lineNo', 'startLine', 'start_line'],
    'severity': ['severity', 'riskLevel', 'severity_level',
                 'risk_level', 'Severity'],
    'riskConfidence': ['riskConfidence', 'confidence', 'RiskConfidence',
                       'score', 'confidenceScore', 'confidence_score'],
}


def normalize_finding_schema(finding):
    """归一化 finding 字段名，将各类漂移别名映射为规范字段。

    仅在目标字段缺失/为空时才从备选字段取值，避免污染原本正确的字段。
    就地修改 finding 字典并返回，方便链式调用。

    覆盖场景（日志 8/10 故障）：
      - finding_type / findingType / vulnerability_type → riskType
      - file_path / file / FilePath → filePath
      - line / lineno / line_number → lineNumber
      - riskLevel / severity_level / risk_level → severity
      - confidence / score → riskConfidence

    注意：刻意不吃 'type'/'path'/'level' 等通用名，避免与 Deep 模式
    Agent 的其他含义字段冲突（见上方 _FIELD_ALIASES 设计原则注释）。
    """
    if not isinstance(finding, dict):
        return finding
    for canonical, aliases in _FIELD_ALIASES.items():
        if finding.get(canonical) not in (None, '', 0):
            continue
        for alias in aliases:
            if alias == canonical:
                continue
            val = finding.get(alias)
            if val not in (None, '', 0):
                finding[canonical] = val
                break
    return finding


def dedup_key(finding):
    """生成去重键（riskType 归一化为 slug 后再去重）"""
    return (
        str(finding.get('filePath', '')),
        int(finding.get('lineNumber', 0)),
        risk_type_to_slug(finding.get('riskType', '')),
    )


def merge_stage2(batch_dir, prefix='', output_path=None, extra_agents=''):
    """执行阶段 2 合并。

    v3.2.0 架构：通过 --extra-agents 加载各 agent 产物（vuln-scan, logic-scan, red-team 等）。
    兼容模式：如果存在旧版 scanner.json / pattern-scan-results.json 也会加载。

    extra_agents: 逗号分隔的 agent 名称（如 'indexer-findings,vuln-scan,logic-scan,red-team'），
                  这是 v3.2.0 主要的 agent 产物加载方式。也支持续扫实例如 'vuln-scan-cont'。
    """
    batch_path = Path(batch_dir)
    agents_dir = batch_path / 'agents'

    all_findings = []
    loaded_agents = []
    current_pipeline_loaded = False

    # --- 主要加载路径：--extra-agents 指定的 agent 产物 ---
    if extra_agents:
        for agent_name in extra_agents.split(','):
            agent_name = agent_name.strip()
            if not agent_name:
                continue
            # pattern-matching 使用专用加载函数
            if agent_name == 'pattern-matching':
                ps_data = load_json_file(batch_path / f'{prefix}pattern-scan-results.json')
                if ps_data is not None:
                    findings = extract_findings_from_pattern_scan(ps_data)
                    all_findings.extend(findings)
                    loaded_agents.append('pattern-matching')
                    current_pipeline_loaded = True
                    log_info(f"pattern-matching: {len(findings)} findings")
                else:
                    log_warn(f"{prefix}pattern-scan-results.json 不存在或为空，跳过")
                continue
            # 避免重复加载
            if agent_name in loaded_agents:
                log_warn(f"跳过重复的 agent: {agent_name}")
                continue
            # indexer-findings 使用 batch 根目录
            if agent_name == 'indexer-findings':
                agent_file = batch_path / f'{prefix}{agent_name}.json'
            else:
                agent_file = agents_dir / f'{prefix}{agent_name}.json'
            agent_data = load_json_file(agent_file)
            # 兼容 fork agent 输出的 {agent}-findings.json 文件名
            if agent_data is None:
                alt_file = agents_dir / f'{prefix}{agent_name}-findings.json'
                agent_data = load_json_file(alt_file)
            if agent_data is not None:
                findings = extract_findings_from_agent(agent_data, agent_name)
                all_findings.extend(findings)
                loaded_agents.append(agent_name)
                current_pipeline_loaded = True
                log_info(f"{agent_name}: {len(findings)} findings")
            else:
                log_warn(f"{agent_name}.json 不存在或为空，跳过")

    # --- 兼容加载：旧版 pattern-scan-results.json（如果尚未通过 extra-agents 加载）---
    if 'pattern-matching' not in loaded_agents:
        pattern_data = load_json_file(batch_path / f'{prefix}pattern-scan-results.json')
        if pattern_data is not None:
            findings = extract_findings_from_pattern_scan(pattern_data)
            all_findings.extend(findings)
            loaded_agents.append('pattern-matching')
            current_pipeline_loaded = True
            log_info(f"pattern-matching (兼容加载): {len(findings)} findings")

    # --- 兼容加载：旧版 scanner.json（如果尚未通过 extra-agents 加载）---
    if 'scanner' not in loaded_agents:
        scanner_data = load_json_file(agents_dir / f'{prefix}scanner.json')
        if scanner_data is not None:
            findings = extract_findings_from_agent(scanner_data, 'scanner')
            all_findings.extend(findings)
            loaded_agents.append('scanner')
            current_pipeline_loaded = True
            log_info(f"scanner (兼容加载): {len(findings)} findings")

    # --- 兼容加载：light-scan.json（Light 模式编排器未传 --extra-agents 时的防御性兜底）---
    if 'light-scan' not in loaded_agents:
        light_data = load_json_file(agents_dir / f'{prefix}light-scan.json')
        # 兼容 fork agent 输出的 light-scan-findings.json 文件名
        if light_data is None:
            light_data = load_json_file(agents_dir / f'{prefix}light-scan-findings.json')
        if light_data is not None:
            findings = extract_findings_from_agent(light_data, 'light-scan')
            all_findings.extend(findings)
            loaded_agents.append('light-scan')
            current_pipeline_loaded = True
            log_info(f"light-scan (兼容加载): {len(findings)} findings")

    log_info(f"合计加载 {len(all_findings)} 个原始 findings (来自 {len(loaded_agents)} 个 agent)")

    # 格式校验（先统一归一化 agent 字段漂移，再校验）
    valid_findings = []
    discarded_count = 0
    discarded_by_agent = {}
    discarded_findings = []
    normalized_count = 0
    for f in all_findings:
        before_keys = set(f.keys())
        normalize_finding_schema(f)
        if set(f.keys()) != before_keys:
            normalized_count += 1
        valid, reason = validate_finding(f)
        if valid:
            valid_findings.append(f)
        else:
            discarded_count += 1
            agent = f.get('sourceAgent', 'unknown')
            discarded_by_agent[agent] = discarded_by_agent.get(agent, 0) + 1
            discarded_findings.append({
                'filePath': f.get('filePath', '?'),
                'lineNumber': f.get('lineNumber', '?'),
                'riskType': f.get('riskType', '?'),
                'sourceAgent': agent,
                'discardReason': reason,
            })
            log_warn(
                f"丢弃不完整 finding: {reason} — "
                f"agent={agent} file={f.get('filePath', '?')}:{f.get('lineNumber', '?')} "
                f"riskType={f.get('riskType', '?')}"
            )

    if normalized_count > 0:
        log_info(f"normalize_finding_schema 修复 {normalized_count} 个 finding 的字段漂移")

    if discarded_count > 0:
        log_warn(f"共丢弃 {discarded_count} 个格式不完整的 finding")
        for agent, cnt in sorted(discarded_by_agent.items(), key=lambda x: -x[1]):
            log_warn(f"  {agent}: {cnt} 个丢弃")
        # 写入丢弃记录供调试
        discard_log_path = batch_path / f'{prefix}discarded-findings.json'
        write_json_file(discard_log_path, {
            'discardedCount': discarded_count,
            'byAgent': discarded_by_agent,
            'findings': discarded_findings,
        })
        log_info(f"丢弃记录已写入 {discard_log_path}")

    # traceMethod 检查（仅语义分析 agent）
    trace_fixed = 0
    for f in valid_findings:
        if f.get('sourceAgent') in SEMANTIC_AGENTS:
            if not f.get('traceMethod') and not f.get('attackChain', {}).get('traceMethod'):
                # 语义分析 agent 默认使用 Grep+Read
                f['traceMethod'] = 'Grep+Read'
                trace_fixed += 1
    if trace_fixed > 0:
        log_warn(f"为 {trace_fixed} 个语义分析 finding 补充 traceMethod（按 agent 类型推断）")

    # attackChain 合约校验（仅语义分析 agent）
    chain_invalid = 0
    for f in valid_findings:
        if f.get('sourceAgent') in SEMANTIC_AGENTS:
            chain = f.get('attackChain')
            if chain:
                ok, reason = validate_attack_chain(chain)
                if not ok:
                    chain_invalid += 1
                    log_warn(
                        f"attackChain 不合规 ({reason}): "
                        f"{f.get('filePath', '?')}:{f.get('lineNumber', '?')} [{f.get('riskType', '?')}]"
                    )
                    # 标记为不完整，供 finding-validator 识别并执行完整追踪
                    f.setdefault('_chainIncomplete', True)
    if chain_invalid > 0:
        log_warn(f"共 {chain_invalid} 个语义分析 finding 的 attackChain 不符合合约")

    # 去重（按 file+line+riskType，语义分析优先 > 最高 severity）
    dedup_groups = {}
    for f in valid_findings:
        key = dedup_key(f)
        if key in dedup_groups:
            existing = dedup_groups[key]
            existing_sev = normalized_severity_rank(existing['severity'])
            new_sev = normalized_severity_rank(f['severity'])
            existing_prio = AGENT_PRIORITY.get(existing.get('sourceAgent', ''), 0)
            new_prio = AGENT_PRIORITY.get(f.get('sourceAgent', ''), 0)
            # 优先保留规则：
            # 1. 如果 severity 不同，保留更高 severity 的
            # 2. 如果 severity 相同，保留语义分析 agent 优先级更高的
            if new_sev > existing_sev:
                dedup_groups[key] = f
            elif new_sev == existing_sev and new_prio > existing_prio:
                dedup_groups[key] = f
        else:
            dedup_groups[key] = f

    deduplicated_count = len(valid_findings) - len(dedup_groups)
    merged_findings = list(dedup_groups.values())

    if deduplicated_count > 0:
        log_info(f"去重移除 {deduplicated_count} 个重复 finding")

    # --- 文件存在性全量网关（反幻觉硬门禁）---
    # 对所有 findings 做 file_exists 检查，移除指向不存在文件的幽灵 finding。
    # 这是代码级确定性逻辑，不依赖 prompt 层的反幻觉合约。
    ghost_count = 0
    for f in merged_findings:
        fp = f.get('filePath', '')
        if fp and not Path(fp).is_file():
            f['_ghost'] = True
            ghost_count += 1

    if ghost_count > 0:
        ghost_rate = ghost_count / len(merged_findings) if merged_findings else 0
        log_warn(f"文件存在性网关：检测到 {ghost_count} 个 finding 指向不存在的文件（{ghost_rate:.0%}）")
        if ghost_rate > 0.5:
            log_error(f"幽灵率 {ghost_rate:.0%} 超过 50%，审计质量堪忧，请检查 Agent 输出")
        merged_findings = [f for f in merged_findings if not f.get('_ghost')]
        log_info(f"文件存在性网关移除 {ghost_count} 个幽灵 finding，剩余 {len(merged_findings)} 个")

    # 分配统一的 findingId 格式: f-{3位序号}
    # 无论 Light 还是 Deep 模式，都使用相同的序号格式
    for i, f in enumerate(merged_findings, 1):
        f['findingId'] = f"f-{i:03d}"

    # 统计
    by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    by_risk_type = {}
    for f in merged_findings:
        sev = normalize_severity(f['severity'])
        by_severity[sev] = by_severity.get(sev, 0) + 1
        slug = risk_type_to_slug(f['riskType'])
        by_risk_type[slug] = by_risk_type.get(slug, 0) + 1

    # 写入 merged-scan.json
    output_data = {
        "mergedAt": datetime.now(timezone.utc).isoformat(),
        "totalFindings": len(merged_findings),
        "byRiskType": by_risk_type,
        "bySeverity": by_severity,
        "deduplicatedCount": deduplicated_count,
        "discardedCount": discarded_count,
        "loadedAgents": loaded_agents,
        "findings": merged_findings,
    }
    out_file = output_path or (batch_path / f'{prefix}merged-scan.json')
    write_json_file(out_file, output_data)
    log_ok(f"已写入 {out_file} ({len(merged_findings)} findings)")

    # 漏洞链检测
    chain_candidates = detect_vulnerability_chains(merged_findings)
    if chain_candidates:
        log_info(f"检测到 {len(chain_candidates)} 个潜在漏洞链候选")
        output_data["chainCandidates"] = chain_candidates

    # stdout 摘要
    stdout_json({
        "status": "ok",
        "totalFindings": len(merged_findings),
        "criticalCount": by_severity.get("critical", 0),
        "bySeverity": by_severity,
        "byRiskType": by_risk_type,
        "deduplicatedCount": deduplicated_count,
        "discardedCount": discarded_count,
        "ghostRemovedCount": ghost_count,
        "chainCandidates": len(chain_candidates),
        "outputFile": str(out_file.name),
    })


# ---------------------------------------------------------------------------
# 阶段 3 合并逻辑
# ---------------------------------------------------------------------------

def build_finding_index(findings):
    """构建 finding 索引（findingId → finding, file+line+riskType → finding）"""
    by_id = {}
    by_key = {}
    for f in findings:
        fid = f.get('findingId')
        if fid:
            by_id[fid] = f
        key = dedup_key(f)
        by_key[key] = f
    return by_id, by_key


def match_finding(by_id, by_key, ref):
    """匹配 finding：先按 findingId（带文件一致性校验），再按 filePath+lineNumber+riskType"""
    ref_file = ref.get('filePath') or ref.get('FilePath') or ref.get('file') or ref.get('file_path') or ''

    # 尝试 findingId（需校验文件路径一致性，防止重新编号后错配）
    fid = ref.get('findingId')
    if fid and fid in by_id:
        candidate = by_id[fid]
        candidate_file = candidate.get('filePath', '')
        if not ref_file or not candidate_file or ref_file == candidate_file:
            return candidate
        # findingId 匹配但文件不一致，说明 findingId 已重新编号，回退到 key 匹配

    # 尝试 filePath+lineNumber+riskType
    line_val = ref.get('lineNumber') or ref.get('LineNumber') or ref.get('line') or ref.get('line_number') or 0
    rt_val = ref.get('riskType') or ref.get('RiskType') or ref.get('type') or ref.get('category') or ''
    key = (str(ref_file), int(line_val), risk_type_to_slug(str(rt_val)))
    if key in by_key:
        return by_key[key]

    # 最后尝试仅按文件路径匹配（当 lineNumber/riskType 不可用时）
    if ref_file and not line_val and not rt_val:
        for f in by_id.values():
            f_file = f.get('filePath', '')
            if f_file == ref_file:
                return f
    return None


def _normalize_vf(vf):
    """将扁平 verification output 归一化为 output-schemas.md 嵌套格式。

    verification agent 可能输出三种格式：
    1. 嵌套格式：antiHallucination{}, verification{}, confidence{}
    2. 扁平格式：ahAction, verificationStatus, riskConfidence 等直接挂在 finding 上
    3. step 格式：step1Existence{}, step2AttackChain{}, step3AdversarialReview{}, step5Confidence{}
    此函数兼容三种格式，确保下游逻辑统一消费嵌套结构。
    """
    # --- step 格式 → 标准嵌套格式 ---
    step1 = vf.get('step1Existence')
    step2 = vf.get('step2AttackChain')
    step3 = vf.get('step3AdversarialReview')
    step5 = vf.get('step5Confidence')

    if step1 and 'antiHallucination' not in vf and 'ahAction' not in vf:
        vf['antiHallucination'] = {
            'ahAction': step1.get('ahAction', 'pass'),
            'fileExists': step1.get('fileExists'),
            'lineValid': step1.get('lineInRange', step1.get('lineValid')),
            'codeMatches': step1.get('codeMatch', step1.get('codeMatches')),
        }

    if step2 and 'verification' not in vf and 'verificationStatus' not in vf:
        trace_method = step2.get('traceMethod', '')
        if not trace_method:
            # 从 step5 推断 traceMethod（step5 包含 traceMethodCap 和 highConfidenceGate 描述）
            if step5:
                gate_text = str(step5.get('highConfidenceGate', ''))
                cap = step5.get('traceMethodCap')
                if 'Grep+Read' in gate_text or step5.get('grepReadExemption'):
                    trace_method = 'Grep+Read'
                elif 'LSP' in gate_text:
                    trace_method = 'LSP'
                elif cap == 100:
                    trace_method = 'LSP'
                elif cap is not None:
                    trace_method = 'Grep+Read'
            if not trace_method:
                trace_method = 'unknown'
        vf['verification'] = {
            'verificationStatus': step2.get('verificationStatus', 'unverified'),
            'challengeVerdict': step3.get('challengeVerdict', '') if step3 else '',
            'traceMethod': trace_method,
        }

    if step5 and 'confidence' not in vf and 'riskConfidence' not in vf and 'RiskConfidence' not in vf:
        vf['confidence'] = {
            'RiskConfidence': step5.get('finalConfidence', step5.get('rawScore', 50)),
            'confidenceBreakdown': {
                'reachability': step5.get('reachability', 0),
                'defense': step5.get('defense', 0),
                'dataSource': step5.get('dataSource', 0),
            },
        }

    # --- 扁平格式 → 标准嵌套格式 ---
    if 'antiHallucination' not in vf and 'ahAction' in vf:
        phase_a_detail = vf.get('phaseADetail', {})
        vf['antiHallucination'] = {
            'ahAction': vf.get('ahAction', 'pass'),
            'fileExists': phase_a_detail.get('fileExists', vf.get('fileExists')),
            'lineValid': phase_a_detail.get('lineValid', vf.get('lineValid')),
            'codeMatches': phase_a_detail.get('codeMatches', vf.get('codeMatches')),
        }
    if 'verification' not in vf and 'verificationStatus' in vf:
        vf['verification'] = {
            'verificationStatus': vf.get('verificationStatus'),
            'challengeVerdict': vf.get('challengeVerdict', ''),
            'traceMethod': (vf.get('attackChain') or {}).get('traceMethod',
                           vf.get('traceMethod', 'unknown')),
        }
    if 'confidence' not in vf and ('riskConfidence' in vf or 'RiskConfidence' in vf):
        vf['confidence'] = {
            'RiskConfidence': vf.get('RiskConfidence') or vf.get('riskConfidence'),
        }
        if vf.get('confidenceBreakdown'):
            vf['confidence']['confidenceBreakdown'] = vf['confidenceBreakdown']
    return vf


def _apply_finding_validator(fv_data, findings, by_id, by_key, ah_actions):
    """从 finding-validator.json 统一格式中提取并应用三阶段验证结果。
    返回 (removed_by_ah, downgraded_by_ah, removed_by_challenge, downgraded_by_rv, escalated_by_rv)。
    """
    removed_by_ah = 0
    downgraded_by_ah = 0
    removed_by_challenge = 0
    downgraded_by_rv = 0
    escalated_by_rv = 0
    confidence_applied = 0

    # 兼容 validatedFindings / findings 两种键名
    validated = fv_data.get('validatedFindings', fv_data.get('findings', []))
    for vf in validated:
        vf = _normalize_vf(vf)
        # 先尝试 findingId 匹配，再尝试全字段匹配
        ref = dict(vf)  # 传递所有字段以便 match_finding 做多策略匹配
        if 'findingId' not in ref:
            ref['findingId'] = ''
        finding = match_finding(by_id, by_key, ref)
        if finding is None:
            log_warn(f"finding-validator 引用未知 finding: {vf.get('findingId', '?')} "
                     f"file={vf.get('filePath', '?')} "
                     f"riskType={vf.get('riskType', '?')}")
            continue

        fid = finding.get('findingId', '')

        # --- 步骤一: 代码存在性校验 ---
        ah = vf.get('antiHallucination', {})
        ah_action = ah.get('ahAction', 'pass')
        ah_actions[fid] = ah_action

        if ah_action == 'remove':
            finding['_removed'] = True
            finding['_removed_by'] = 'finding-validator:anti-hallucination'
            removed_by_ah += 1
            continue  # 已移除，跳过后续阶段
        elif ah_action == 'downgrade':
            current_conf = finding.get('confidence', 50)
            finding['confidence'] = max(0, int(current_conf) - 20)
            downgraded_by_ah += 1

        # --- 步骤二/三: 攻击链验证 + 对抗审查 ---
        verif = vf.get('verification', {})
        finding['verificationStatus'] = verif.get('verificationStatus', 'unverified')
        finding['traceMethod'] = verif.get('traceMethod', finding.get('traceMethod', 'unknown'))

        verdict = verif.get('challengeVerdict', '')
        finding['challengeVerdict'] = verdict

        if finding['verificationStatus'] == 'false_positive':
            finding['_removed'] = True
            finding['_removed_by'] = 'finding-validator:false_positive'
            removed_by_challenge += 1
            continue
        elif verdict == 'dismissed':
            finding['_removed'] = True
            finding['_removed_by'] = 'finding-validator:dismissed'
            removed_by_challenge += 1
            continue
        elif verdict == 'downgraded':
            finding['severity'] = lower_severity(finding.get('severity', 'medium'))
            downgraded_by_rv += 1
        elif verdict == 'escalated':
            finding['severity'] = raise_severity(finding.get('severity', 'medium'))
            escalated_by_rv += 1

        # --- 步骤五: 置信度评分 ---
        conf = vf.get('confidence', {})
        if 'RiskConfidence' in conf:
            finding['confidence'] = conf['RiskConfidence']
            confidence_applied += 1
        if 'confidenceBreakdown' in conf:
            finding['confidenceBreakdown'] = conf['confidenceBreakdown']

    log_info(
        f"finding-validator: AH 移除 {removed_by_ah}, AH 降级 {downgraded_by_ah}, "
        f"验证移除 {removed_by_challenge}, 验证降级 {downgraded_by_rv}, 升级 {escalated_by_rv}, "
        f"置信度赋值 {confidence_applied}"
    )

    # P2 修复：验证覆盖率告警 — 当有 findings 但所有操作均为 0 时，说明 schema 可能不匹配
    total_effects = (removed_by_ah + downgraded_by_ah + removed_by_challenge +
                     downgraded_by_rv + escalated_by_rv + confidence_applied)
    if len(validated) > 0 and total_effects == 0:
        log_warn("⚠ finding-validator 未对任何 finding 产生效果，可能存在 schema 不匹配")

    return removed_by_ah, downgraded_by_ah, removed_by_challenge, downgraded_by_rv, escalated_by_rv


def _collect_verifier_files(agents_dir, prefix=''):
    """收集所有 verifier 实例产出文件。

    查找顺序：
      1. agents/verifier-*.json（并行分片模式）
      2. agents/finding-validator.json（单实例模式）
      3. agents/verifier.json（单实例回退）

    Returns:
        list of (path, data) tuples
    """
    collected = []

    # 1. 并行模式：verifier-{group}.json
    parallel_files = sorted(agents_dir.glob(f'{prefix}verifier-*.json'))
    for vf_path in parallel_files:
        data = load_json_file(vf_path)
        if data is not None:
            collected.append((vf_path, data))
            log_info(f"加载并行 verifier 产出: {vf_path.name}")

    if collected:
        return collected

    # 2. 单实例模式：finding-validator.json
    fv_path = agents_dir / f'{prefix}finding-validator.json'
    data = load_json_file(fv_path)
    if data is not None:
        log_info(f"加载单实例 verifier 产出: {fv_path.name}")
        return [(fv_path, data)]

    # 3. 回退：verifier.json
    v_path = agents_dir / f'{prefix}verifier.json'
    data = load_json_file(v_path)
    if data is not None:
        log_info(f"加载单实例 verifier 回退: {v_path.name}")
        return [(v_path, data)]

    return []


def merge_stage3(batch_dir, prefix=''):
    """执行阶段 3 合并。prefix 用于分批模式（如 'batch-1-'）。

    支持两种验证模式：
      - 并行模式：从 verifier-*.json 加载
      - 单实例模式：从 finding-validator.json / verifier.json 加载

    可选集成：
      - score-results.json（verifier.py score 产出的确定性置信度评分）
      - quality-assessment.json（verifier.py quality 产出的质量评估）
      - chain-verify-results.json（verifier.py chain-verify 产出的攻击链索引验证）
      - challenge-results.json（verifier.py challenge 产出的确定性对抗审查）
    """
    batch_path = Path(batch_dir)
    agents_dir = batch_path / 'agents'

    # 加载 merged-scan.json（必选）
    stage2_data = load_json_file(batch_path / f'{prefix}merged-scan.json')
    if stage2_data is None:
        log_error(f"{prefix}merged-scan.json 不存在，无法执行阶段 3 合并")
        stdout_json({"status": "error", "message": f"{prefix}merged-scan.json not found"})
        sys.exit(1)

    findings = stage2_data.get('findings', [])
    input_count = len(findings)
    log_info(f"加载 {input_count} 个 stage2 findings")

    # 构建索引
    by_id, by_key = build_finding_index(findings)

    # 跟踪每个 finding 的 anti-hallucination action
    ah_actions = {}  # findingId → action

    # ===== Fast P0：bypass 路径前置的 pre-check 兜底 =====
    # 触发条件（全部满足才运行）：
    #   1. scan_mode == "fast"
    #   2. 既无 pre-check-results.json 也无分片 pre-check-results-*.json
    #      （说明上游未执行 verifier.py pre-check）
    #   3. 环境变量 SECURITY_SCAN_FAST_V2 != "0"
    # 成功后 run_pre_check 会落 pre-check-results.json，下方 1118 行起的
    # 原有加载逻辑会自然读取并应用，无需在此重复实现 match_finding 循环。
    import os as _os
    _fast_plan = load_json_file(batch_path / 'batch-plan.json')
    _fast_scan_mode = (_fast_plan or {}).get('scan_mode', 'deep') if _fast_plan else 'deep'
    _fast_v2_enabled = _os.environ.get('SECURITY_SCAN_FAST_V2', '1') != '0'
    _existing_pc = (batch_path / 'pre-check-results.json').exists() \
        or any(batch_path.glob('pre-check-results-*.json'))
    if _fast_scan_mode == 'fast' and _fast_v2_enabled and not _existing_pc:
        _run_pre_check = _lazy_import_run_pre_check()
        if _run_pre_check is None:
            log_info("fast-v2: verifier.run_pre_check 不可用，跳过 bypass 前置兜底")
        else:
            try:
                log_info("fast-v2: bypass 路径前置执行 pre-check 兜底（基于 merged-scan.json）")
                _run_pre_check(str(batch_path))
            except SystemExit:
                log_info("fast-v2: pre-check 兜底 SystemExit，保持 bypass 原行为")
            except Exception as _e:
                log_info(f"fast-v2: pre-check 兜底异常 {_e}，保持 bypass 原行为")
    # ===== 结束 Fast P0 兜底 =====

    # --- 应用 verifier.py pre-check 结果（如果存在）---
    # 支持分片模式：聚合所有 pre-check-results-*.json 分片 + 标准 pre-check-results.json
    pre_check_data = None
    pre_check_shards = sorted(batch_path.glob('pre-check-results-*.json'))
    if pre_check_shards:
        # 流式验证模式：聚合多个分片
        log_info(f"检测到 {len(pre_check_shards)} 个 pre-check 分片，聚合应用")
        pre_check_data = {
            'metrics': {'input': 0, 'grade_static': 0, 'grade_degraded': 0,
                        'grade_verifiable': 0, 'removed': 0},
            'grade_static': [],
            'grade_degraded': [],
            'grade_verifiable': [],
            'removed': [],
        }
        for shard_path in pre_check_shards:
            shard = load_json_file(shard_path)
            if not shard:
                continue
            log_info(f"  聚合分片: {shard_path.name}")
            for key in ('grade_static', 'grade_degraded', 'grade_verifiable', 'removed'):
                pre_check_data[key].extend(shard.get(key, []))
            shard_metrics = shard.get('metrics', {})
            for mkey in ('input', 'grade_static', 'grade_degraded', 'grade_verifiable', 'removed'):
                pre_check_data['metrics'][mkey] = pre_check_data['metrics'].get(mkey, 0) + shard_metrics.get(mkey, 0)
    else:
        # 标准模式：单个 pre-check-results.json
        pre_check_data = load_json_file(batch_path / 'pre-check-results.json')
    stage1_removed = 0
    stage1_downgraded = 0
    if pre_check_data:
        log_info("检测到 pre-check-results.json，应用确定性验证结果")
        # 标记 removed findings
        for rf in pre_check_data.get('removed', []):
            matched = match_finding(by_id, by_key, rf)
            if matched:
                matched['_removed'] = True
                matched['ahAction'] = rf.get('ahAction', 'remove')
                stage1_removed += 1
        # 应用 grade_degraded 降级
        for tf in pre_check_data.get('grade_degraded', []):
            matched = match_finding(by_id, by_key, tf)
            if matched:
                matched['ahAction'] = 'downgrade'
                if tf.get('confidence') is not None:
                    matched['confidence'] = tf['confidence']
                elif tf.get('RiskConfidence') is not None:
                    matched['confidence'] = tf['RiskConfidence']
                stage1_downgraded += 1
        # 标记 grade_static 的 verificationStatus
        for tf in pre_check_data.get('grade_static', []):
            matched = match_finding(by_id, by_key, tf)
            if matched:
                matched['_verificationGrade'] = 'grade_static'
                if not matched.get('verificationStatus'):
                    matched['verificationStatus'] = 'static'
        log_info(f"pre-check 应用完成: 移除 {stage1_removed}，降级 {stage1_downgraded}，"
                 f"grade_static {len(pre_check_data.get('grade_static', []))}，"
                 f"grade_verifiable {len(pre_check_data.get('grade_verifiable', []))}")

    # --- 收集 verifier 产出（支持并行多实例 + 单实例回退）---
    verifier_files = _collect_verifier_files(agents_dir, prefix)
    if not verifier_files:
        # Light/Fast 模式兼容：检查 scan_mode，允许无 verifier 产出时跳过验证合并
        # Fast 模式复用 Light 的 bypass 路径（因为扫描阶段已内联完成校验）
        batch_plan = load_json_file(batch_path / 'batch-plan.json')
        scan_mode = batch_plan.get('scan_mode', 'deep') if batch_plan else 'deep'
        if scan_mode in ('light', 'fast'):
            log_info(f"{scan_mode} 模式下无 verifier 产出，跳过阶段 3 验证合并，直接使用 stage2 结果")
            final_findings = [f for f in findings if not f.get('_removed')]
            final_count = len(final_findings)
            # 直接输出 merged-scan.json 的内容作为最终结果
            output = {
                'metadata': stage2_data.get('metadata', {}),
                'findings': final_findings,
                'stats': {
                    'input': input_count,
                    'output': final_count,
                    'removed_by_ah': stage1_removed,
                    'downgraded_by_ah': stage1_downgraded,
                }
            }
            write_json_file(batch_path / f'{prefix}merged-verified.json', output)

            # 生成 summary.json（与 Deep 模式保持一致，确保 gate_evaluator 能正确读取分级统计）
            by_severity_light = {"critical": 0, "high": 0, "medium": 0, "low": 0}
            risk_file_set_light = set()
            for f in final_findings:
                sev = normalize_severity(f.get('severity', 'low'))
                if sev in by_severity_light:
                    by_severity_light[sev] += 1
                else:
                    by_severity_light['low'] += 1
                fp = f.get('filePath', '')
                if fp:
                    risk_file_set_light.add(fp)

            total_files_light = 0
            if batch_plan:
                total_files_light = batch_plan.get('total_files', 0)

            light_summary = {
                "batchId": batch_path.name,
                "scanMode": scan_mode,
                "command": "project" if "project" in batch_path.name else "diff",
                "totalFiles": total_files_light,
                "riskFiles": len(risk_file_set_light),
                "totalFindings": final_count,
                "criticalRisk": by_severity_light.get("critical", 0),
                "highRisk": by_severity_light.get("high", 0),
                "mediumRisk": by_severity_light.get("medium", 0),
                "lowRisk": by_severity_light.get("low", 0),
            }
            write_json_file(batch_path / 'summary.json', light_summary)
            log_ok(f"已写入 summary.json ({final_count} findings, {scan_mode} bypass)")

            stdout_json({
                'status': 'ok',
                'mode': f'{scan_mode}-bypass',
                'totalFindings': final_count,
                'bySeverity': by_severity_light,
                'message': f'{scan_mode} mode: no verifier files, using stage2 results directly'
            })
            return
        log_error(f"未找到任何 verifier 产出文件，无法执行阶段 3 合并")
        stdout_json({"status": "error", "message": "no verifier output files found"})
        sys.exit(1)

    # 依次应用所有 verifier 实例的结果
    total_removed_by_ah = 0
    total_downgraded_by_ah = 0
    total_removed_by_challenge = 0
    total_downgraded_by_rv = 0
    total_escalated_by_rv = 0

    for vf_path, fv_data in verifier_files:
        r_ah, d_ah, r_ch, d_rv, e_rv = \
            _apply_finding_validator(fv_data, findings, by_id, by_key, ah_actions)
        total_removed_by_ah += r_ah
        total_downgraded_by_ah += d_ah
        total_removed_by_challenge += r_ch
        total_downgraded_by_rv += d_rv
        total_escalated_by_rv += e_rv

    removed_by_ah = total_removed_by_ah
    downgraded_by_ah = total_downgraded_by_ah
    removed_by_challenge = total_removed_by_challenge
    downgraded_by_rv = total_downgraded_by_rv
    escalated_by_rv = total_escalated_by_rv

    # --- 应用 verifier.py score 结果（确定性置信度评分，如果存在）---
    score_data = load_json_file(batch_path / 'score-results.json')
    score_applied = 0
    if score_data:
        log_info("检测到 score-results.json，应用确定性置信度评分")
        score_findings = score_data.get('findings', [])
        score_by_id = {}
        score_by_key = {}
        for sf in score_findings:
            fid = sf.get('findingId', '')
            if fid:
                score_by_id[fid] = sf
            fp = str(sf.get('filePath', ''))
            ln = int(sf.get('lineNumber', 0))
            rt = risk_type_to_slug(sf.get('riskType', ''))
            score_by_key[(fp, ln, rt)] = sf

        for f in findings:
            if f.get('_removed'):
                continue
            fid = f.get('findingId', '')
            # 匹配 score 结果
            scored = score_by_id.get(fid)
            if not scored:
                key = dedup_key(f)
                scored = score_by_key.get(key)
            if scored:
                # 仅当 score 给出有效的更高置信度时才覆盖
                # 避免覆盖 verifier agent 的精确评分
                if scored.get('confidence') is not None:
                    scored_conf = scored.get('confidence', 0)
                    current_conf = f.get('confidence', 0)
                    # 仅当 score 的置信度更高或首次设置时才应用
                    if scored_conf > current_conf or current_conf == 0:
                        f['confidence'] = scored_conf
                if scored.get('confidenceBreakdown'):
                    f['confidenceBreakdown'] = scored['confidenceBreakdown']
                score_applied += 1
        log_info(f"确定性评分应用完成: {score_applied} 个 findings 更新置信度")

    # 移除标记删除的 findings
    findings = [f for f in findings if not f.get('_removed')]

    # 重建索引
    by_id, by_key = build_finding_index(findings)

    # --- traceMethod 分级上限兜底 ---
    # verification agent 应已执行置信度上限，此处做最终兜底
    # Grep+Read 上限 90（LSP 不可用时的最高置信度）
    GREP_READ_CAP = 90
    trace_capped = 0
    for f in findings:
        confidence = f.get('confidence', 0)
        trace_method = (f.get('traceMethod') or
                        (f.get('attackChain') or {}).get('traceMethod', 'unknown'))

        if trace_method == 'unknown' and confidence > 70:
            f['confidence'] = 70
            trace_capped += 1
        elif trace_method == 'Grep+Read' and confidence > GREP_READ_CAP:
            f['confidence'] = GREP_READ_CAP
            trace_capped += 1

    if trace_capped > 0:
        log_info(f"traceMethod 分级上限: {trace_capped} 个 finding 置信度被上限约束")

    # --- 高置信度门禁 ---
    # finding-validator 已做门禁，此处做最终兜底校验
    gate_demoted = 0
    for f in findings:
        confidence = f.get('confidence', 0)
        if confidence >= 90:
            verified = f.get('verificationStatus') == 'verified'
            confirmed = f.get('challengeVerdict') in ('confirmed', 'escalated')
            ah_pass = ah_actions.get(f.get('findingId', ''), 'pass') == 'pass'

            if not (verified and confirmed and ah_pass):
                f['confidence'] = GREP_READ_CAP - 1  # 降至 Grep+Read 上限以下
                gate_demoted += 1

    if gate_demoted > 0:
        log_info(f"高置信度门禁: {gate_demoted} 个 finding 置信度降至 {GREP_READ_CAP - 1}")

    # --- 步骤 5: 按风险类型分组输出 finding-{slug}.json ---
    final_count = len(findings)
    groups = {}
    for f in findings:
        slug = risk_type_to_slug(f.get('riskType', ''))
        if slug not in groups:
            groups[slug] = []
        groups[slug].append(f)

    finding_files = []
    by_severity_final = {"critical": 0, "high": 0, "medium": 0, "low": 0}

    for slug, group_findings in sorted(groups.items()):
        # 构建标准输出格式
        risk_list = []
        critical = high = medium = low = 0
        for f in group_findings:
            sev = normalize_severity(f.get('severity', 'medium'))
            if sev == 'critical':
                critical += 1
            elif sev == 'high':
                high += 1
            elif sev == 'medium':
                medium += 1
            else:
                low += 1
            by_severity_final[sev] = by_severity_final.get(sev, 0) + 1

            # 使用集中式转换函数生成报告格式
            risk_item = to_report_format(f)

            risk_list.append(risk_item)

        cn_name = SLUG_RISK_TYPE.get(slug, slug)
        file_name = f"finding-{slug}.json"
        finding_data = {
            "metadata": {
                "riskTypeSlug": slug,
                "riskTypeName": cn_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": "1.0",
            },
            "summary": {
                "totalIssues": len(risk_list),
                "criticalRisk": critical,
                "highRisk": high,
                "mediumRisk": medium,
                "lowRisk": low,
            },
            "StatInfo": {"RiskNum": len(risk_list)},
            "RiskList": risk_list,
        }
        write_json_file(batch_path / file_name, finding_data)
        finding_files.append(file_name)
        log_info(f"  {file_name} — {cn_name}（{len(risk_list)} 个风险）")

    # --- 步骤 6: 写 summary.json ---
    # 从 batch-plan.json 读取扫描文件总数（由编排器生成）
    total_files = 0
    batch_plan_path = batch_path / 'batch-plan.json'
    if batch_plan_path.exists():
        batch_plan = load_json_file(batch_plan_path)
        if batch_plan:
            total_files = batch_plan.get('total_files', 0)
    # 收集涉及风险的文件数
    risk_file_set = set()
    for f in findings:
        fp = f.get('filePath', '')
        if fp:
            risk_file_set.add(fp)
    risk_files = len(risk_file_set)

    # 从 batch_id 推导 scanMode
    batch_name = batch_path.name
    _scan_mode = _extract_scan_mode_from_batch_id(batch_name)

    summary = {
        "batchId": batch_name,
        "scanMode": _scan_mode,
        "command": "project" if "project-audit" in batch_name else "diff",
        "totalFiles": total_files,
        "riskFiles": risk_files,
        "totalFindings": final_count,
        "criticalRisk": by_severity_final.get("critical", 0),
        "highRisk": by_severity_final.get("high", 0),
        "mediumRisk": by_severity_final.get("medium", 0),
        "lowRisk": by_severity_final.get("low", 0),
        "mergeMetrics": {
            "inputFindings": input_count,
            "removedByAntiHallucination": removed_by_ah,
            "removedByChallenge": removed_by_challenge,
            "downgradedByAntiHallucination": downgraded_by_ah,
            "downgradedByVerification": downgraded_by_rv,
            "escalatedByVerification": escalated_by_rv,
            "highConfidenceGateDemoted": gate_demoted,
            "scoreApplied": score_applied,
            "finalFindings": final_count,
        },
    }

    # 集成 quality-assessment.json（如果存在）
    quality_data = load_json_file(batch_path / 'quality-assessment.json')
    if quality_data:
        summary["qualityAssessment"] = {
            "coveragePercent": quality_data.get('coveragePercent', 0),
            "coveredDimensions": quality_data.get('coveredDimensions', 0),
            "totalDimensions": quality_data.get('totalDimensions', 0),
            "blindSpotCount": quality_data.get('blindSpotCount', 0),
            "inconsistencyCount": quality_data.get('inconsistencyCount', 0),
            "qualityVerdict": quality_data.get('qualityVerdict', 'unknown'),
        }
        log_info(f"质量评估集成: 覆盖率 {quality_data.get('coveragePercent', 0)}%, "
                 f"判定 {quality_data.get('qualityVerdict', 'unknown')}")

    write_json_file(batch_path / 'summary.json', summary)
    log_ok(f"已写入 summary.json ({final_count} findings)")

    # stdout 摘要
    stdout_json({
        "status": "ok",
        "inputFindings": input_count,
        "removedByAntiHallucination": removed_by_ah,
        "removedByChallenge": removed_by_challenge,
        "downgraded": downgraded_by_ah + downgraded_by_rv,
        "highConfidenceGateDemoted": gate_demoted,
        "scoreApplied": score_applied,
        "finalFindings": final_count,
        "criticalCount": by_severity_final.get("critical", 0),
        "bySeverity": by_severity_final,
        "findingFiles": finding_files,
        "summaryFile": "summary.json",
    })


# ---------------------------------------------------------------------------
# audit-stats: 产物质量统计
# ---------------------------------------------------------------------------

def audit_stats(batch_path, source='merged'):
    """统计产物质量：attackChain、recommendation、fixedCode 覆盖率。"""
    # 加载 findings
    findings = []
    if source == 'merged':
        merged_file = batch_path / 'merged-scan.json'
        data = load_json_file(merged_file)
        if data is None:
            log_error(f"merged-scan.json 不存在: {merged_file}")
            stdout_json({"status": "error", "message": "merged-scan.json not found"})
            return
        findings = data.get('findings', []) if isinstance(data, dict) else data
    else:
        import glob as _glob
        for fp in sorted(batch_path.glob('finding-*.json')):
            data = load_json_file(fp)
            if data is None:
                continue
            issues = data.get('RiskList', data.get('issues', []))
            findings.extend(issues)

    if not findings:
        log_warn("未找到任何 findings")
        stdout_json({"status": "ok", "totalFindings": 0})
        return

    total = len(findings)

    # 统计各字段覆盖
    has_chain = 0
    has_rec = 0
    has_fixed = 0
    by_severity = {}
    by_risk_type = {}

    for f in findings:
        sev = normalize_severity(f.get('severity', f.get('RiskLevel', 'low')))
        rtype = f.get('riskType', f.get('RiskType', '未知'))

        chain = f.get('attackChain')
        rec = f.get('recommendation', f.get('Suggestions', ''))
        fixed = f.get('fixedCode', f.get('FixedCode', ''))

        has_chain_flag = bool(chain)
        has_rec_flag = bool(rec and len(str(rec)) > 5)
        has_fixed_flag = bool(fixed and len(str(fixed)) > 5)

        if has_chain_flag:
            has_chain += 1
        if has_rec_flag:
            has_rec += 1
        if has_fixed_flag:
            has_fixed += 1

        # 按 severity 统计
        entry = by_severity.setdefault(sev, {"total": 0, "chain": 0, "rec": 0, "fixed": 0})
        entry["total"] += 1
        if has_chain_flag:
            entry["chain"] += 1
        if has_rec_flag:
            entry["rec"] += 1
        if has_fixed_flag:
            entry["fixed"] += 1

        # 按 riskType 统计
        entry2 = by_risk_type.setdefault(rtype, {"total": 0, "chain": 0, "rec": 0, "fixed": 0})
        entry2["total"] += 1
        if has_chain_flag:
            entry2["chain"] += 1
        if has_rec_flag:
            entry2["rec"] += 1
        if has_fixed_flag:
            entry2["fixed"] += 1

    def _pct(n, t):
        return f"{n}/{t} ({round(n * 100 / t)}%)" if t else "0/0"

    # 日志输出
    log_info(f"产物质量统计 ({total} findings)")
    log_info(f"  attackChain 覆盖: {_pct(has_chain, total)}")
    log_info(f"  recommendation 覆盖: {_pct(has_rec, total)}")
    log_info(f"  fixedCode 覆盖: {_pct(has_fixed, total)}")

    for sev in ('critical', 'high', 'medium', 'low'):
        e = by_severity.get(sev)
        if not e:
            continue
        log_info(f"  [{sev}] chain={_pct(e['chain'], e['total'])} rec={_pct(e['rec'], e['total'])} fixed={_pct(e['fixed'], e['total'])}")

    # JSON 输出
    stdout_json({
        "status": "ok",
        "totalFindings": total,
        "coverage": {
            "attackChain": {"count": has_chain, "total": total, "pct": round(has_chain * 100 / total) if total else 0},
            "recommendation": {"count": has_rec, "total": total, "pct": round(has_rec * 100 / total) if total else 0},
            "fixedCode": {"count": has_fixed, "total": total, "pct": round(has_fixed * 100 / total) if total else 0},
        },
        "bySeverity": by_severity,
        "byRiskType": by_risk_type,
    })


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="审计结果合并脚本：合并多 agent 输出、去重、校验",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
子命令说明：
  merge-scan     合并扫描阶段所有 agent 输出（格式校验 + 去重 + findingId 分配 + 漏洞链检测）
  merge-verify   合并验证阶段结果，生成最终 finding-*.json 和 summary.json
  audit-stats    统计产物质量（attackChain/recommendation/fixedCode 覆盖率）

  别名：merge-stage2 = merge-scan, merge-stage3 = merge-verify

示例：
  %(prog)s merge-scan --batch-dir security-scan-output/project-audit-20250302120000
  %(prog)s merge-verify --batch-dir security-scan-output/project-audit-20250302120000
  %(prog)s audit-stats --batch-dir security-scan-output/project-audit-20250302120000
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # merge-scan + merge-stage2 (别名)
    scan_help = '合并扫描阶段 agent 输出（格式校验 + 去重 + findingId 分配 + 漏洞链检测）'
    for cmd_name in ('merge-scan', 'merge-stage2'):
        sp = subparsers.add_parser(cmd_name, help=scan_help)
        sp.add_argument('--batch-dir', required=True,
                        help='审计批次目录路径（如 security-scan-output/project-audit-xxx）')
        sp.add_argument('--prefix', default='',
                        help='agent 输出文件名前缀（分批模式用，如 batch-1-）')
        sp.add_argument('--extra-agents', default='',
                        help='逗号分隔的 agent 名称（如 indexer-findings,vuln-scan,logic-scan,red-team），'
                             'v3.2.0 主要 agent 产物加载方式')
        sp.add_argument('--output', '-o',
                        help='输出文件路径（默认 batch-dir/merged-scan.json）')

    # merge-verify + merge-stage3 (别名)
    verify_help = '合并验证阶段结果，生成 finding-*.json 和 summary.json'
    for cmd_name in ('merge-verify', 'merge-stage3'):
        sp = subparsers.add_parser(cmd_name, help=verify_help)
        sp.add_argument('--batch-dir', required=True,
                        help='审计批次目录路径（如 security-scan-output/project-audit-xxx）')
        sp.add_argument('--prefix', default='',
                        help='agent 输出文件名前缀（分批模式用，如 batch-1-）')
        sp.add_argument('--output', '-o',
                        help='输出文件路径（默认按风险类型分文件）')

    # audit-stats
    sp = subparsers.add_parser('audit-stats', help='统计产物质量（attackChain/recommendation/fixedCode 覆盖率）')
    sp.add_argument('--batch-dir', required=True,
                    help='审计批次目录路径')
    sp.add_argument('--source', choices=['merged', 'summary'], default='merged',
                    help='数据源：merged（merged-scan.json）或 summary（finding-*.json）')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # 校验 batch-dir 存在
    batch_dir = Path(args.batch_dir)
    if not batch_dir.is_dir():
        log_error(f"批次目录不存在: {batch_dir}")
        stdout_json({"status": "error", "message": f"batch dir not found: {batch_dir}"})
        sys.exit(1)

    prefix = getattr(args, 'prefix', '')
    output_file = getattr(args, 'output', None)
    extra_agents = getattr(args, 'extra_agents', '')

    if args.command in ('merge-scan', 'merge-stage2'):
        merge_stage2(batch_dir, prefix=prefix, output_path=Path(output_file) if output_file else None,
                     extra_agents=extra_agents)
    elif args.command in ('merge-verify', 'merge-stage3'):
        merge_stage3(batch_dir, prefix=prefix)
    elif args.command == 'audit-stats':
        audit_stats(batch_dir, source=args.source)


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
