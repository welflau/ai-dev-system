#!/usr/bin/env python3
"""
批量模式匹配工具 — 从 YAML 模式文件读取 Grep 模式，执行匹配，结果直接写入 project-index.db

跨平台：Python3 内置模块 + pyyaml（可选降级到正则解析），零编译依赖。

子命令：
  1. grep-sinks          — 批量 Sink grep → sinks 表
  2. grep-entries         — 入口点检测 → files(is_entry=1)
  3. grep-defenses        — 防御模式检测 → defenses 表
  4. grep-secrets         — 敏感信息检测 → indexer_findings 表
  5. grep-attack-surface  — 攻击面检测 → attack_surface 表

设计原则：
  - 替代 Agent 中的手动 Grep 循环，确保一致性
  - 结果直接写入 DB（INSERT OR IGNORE 避免重复）
  - stdout 输出 JSON 统计摘要，供 Agent 日志记录
  - 支持 ripgrep (rg) 加速，降级到 grep -rn
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ─── YAML 解析（零依赖降级） ─────────────────────────────────

def _load_yaml(path):
    """加载 YAML 文件，优先用 pyyaml，降级到简单解析"""
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        return _parse_yaml_simple(path)


def _parse_yaml_simple(path):
    """简单 YAML 解析器（仅支持本项目的 sink-patterns.yaml 格式）"""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    result = {"sink_types": []}
    current_type = None
    current_patterns = []

    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if stripped.startswith("- type:"):
            if current_type:
                result["sink_types"].append({"type": current_type, "patterns": current_patterns})
            current_type = stripped.split(":", 1)[1].strip().strip("'\"")
            current_patterns = []
        elif stripped.startswith("- '") or stripped.startswith('- "'):
            pattern = stripped[2:].strip().strip("'\"")
            current_patterns.append(pattern)

    if current_type:
        result["sink_types"].append({"type": current_type, "patterns": current_patterns})

    return result


# ─── Grep 执行引擎 ───────────────────────────────────────────

def _detect_grep_tool():
    """检测可用的 grep 工具"""
    for tool in ["rg", "grep"]:
        try:
            subprocess.run([tool, "--version"], capture_output=True, timeout=5)
            return tool
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def _run_grep(pattern, project_path, grep_tool, file_globs=None):
    """执行 grep，返回 [(file, line_num, matched_text), ...]"""
    results = []

    if grep_tool == "rg":
        cmd = ["rg", "-n", "--no-heading", "--no-filename", "-e", pattern]
        if file_globs:
            for g in file_globs:
                cmd.extend(["--glob", g])
        cmd.append(str(project_path))
        # rg 使用 --no-filename 会影响输出，改用带文件名格式
        cmd = ["rg", "-n", "--no-heading", "-e", pattern]
        if file_globs:
            for g in file_globs:
                cmd.extend(["--glob", g])
        cmd.append(str(project_path))
    else:
        cmd = ["grep", "-rn", "-E", pattern, str(project_path)]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            env={**os.environ, "LANG": "C"}
        )
        for line in proc.stdout.split("\n"):
            if not line.strip():
                continue
            # 格式: file:line:text
            parts = line.split(":", 2)
            if len(parts) >= 3:
                filepath = parts[0]
                try:
                    line_num = int(parts[1])
                except ValueError:
                    continue
                text = parts[2].strip()
                # 过滤测试/构建产物
                if _should_skip_file(filepath):
                    continue
                results.append((filepath, line_num, text))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return results


def _should_skip_file(filepath):
    """过滤非源代码文件、测试文件和构建产物"""
    skip_patterns = [
        "/test/", "/tests/", "/spec/", "/__test__/",
        "/node_modules/", "/vendor/", "/target/", "/build/", "/dist/",
        "/.git/", "/.mvn/", "/.gradle/",
        "/security-scan-output/",
        "Test.java", "Tests.java", "Spec.js", ".test.", ".spec.",
        "package-lock.json", "yarn.lock", ".min.js", ".min.css",
    ]
    if any(p in filepath for p in skip_patterns):
        return True
    # 仅保留源代码文件，排除配置/构建/脚本等非代码文件
    _SOURCE_CODE_EXTENSIONS = {
        ".java", ".kt", ".kts", ".scala", ".groovy",
        ".py", ".pyx",
        ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte",
        ".go",
        ".rb", ".erb",
        ".php",
        ".cs",
        ".rs",
        ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp",
        ".swift", ".m", ".mm",
        ".lua", ".pl", ".pm", ".r", ".R",
    }
    ext = os.path.splitext(filepath)[1].lower()
    if not ext or ext not in _SOURCE_CODE_EXTENSIONS:
        return True
    return False


def _make_relative(filepath, project_path):
    """将绝对路径转为项目相对路径"""
    try:
        return str(Path(filepath).relative_to(project_path))
    except ValueError:
        return filepath


# ─── DB 连接 ─────────────────────────────────────────────────

def _connect_db(batch_dir):
    """连接 project-index.db，带重试机制"""
    db_path = str(Path(batch_dir) / "project-index.db")
    if not os.path.exists(db_path):
        print(json.dumps({"error": f"Database not found: {db_path}"}))
        sys.exit(1)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=15000")
            return conn
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < max_retries - 1:
                import time
                time.sleep(1 * (attempt + 1))
                continue
            raise


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Sink 类型 → severity_level 映射 ─────────────────────────

SINK_SEVERITY = {
    "SQL 注入": 1, "命令注入": 1, "反序列化": 1, "代码执行": 1,
    "JNDI": 1, "表达式注入": 1,
    "SSRF": 2, "文件操作": 2, "模板注入": 2, "XSS": 2,
    "开放重定向": 2, "NoSQL 注入": 2, "LDAP 注入": 2, "原型链污染": 2,
    "支付/金额": 2, "密码存储": 2,
    "CRLF 注入": 3, "日志注入": 3, "Session 固定": 3,
    "Mass Assignment": 3, "不安全随机数": 3, "Cookie 安全属性缺失": 3,
    "弱哈希算法（密码存储）": 3, "CSV 注入": 3,
    "拒绝服务": 3, "PostMessage": 3, "WebSocket": 3,
}


# ─── 命令: grep-sinks ────────────────────────────────────────

def cmd_grep_sinks(args):
    """从 sink-patterns.yaml 读取模式，批量 grep 写入 sinks 表"""
    patterns_data = _load_yaml(args.patterns_file)
    sink_types = patterns_data.get("sink_types", [])
    grep_tool = _detect_grep_tool()
    project_path = Path(args.project_path).resolve()

    if not grep_tool:
        print(json.dumps({"error": "No grep tool found (rg or grep)"}))
        sys.exit(1)

    conn = _connect_db(args.batch_dir)
    total_found = 0
    by_type = {}
    by_severity = {"S1": 0, "S2": 0, "S3": 0, "S4": 0}

    try:
        for sink_type_def in sink_types:
            type_name = sink_type_def["type"]
            patterns = sink_type_def.get("patterns", [])
            severity = SINK_SEVERITY.get(type_name, 3)
            type_count = 0

            for pattern in patterns:
                matches = _run_grep(pattern, str(project_path), grep_tool)
                for filepath, line_num, snippet in matches:
                    rel_path = _make_relative(filepath, str(project_path))
                    # 截断 snippet 到 200 字符
                    snippet_trimmed = snippet[:200] if snippet else ""

                    conn.execute("""
                        INSERT OR IGNORE INTO sinks
                        (file_path, line, type, severity_level, code_snippet, defense_status, trace_status)
                        VALUES (?, ?, ?, ?, ?, 'unknown', 'pending')
                    """, (rel_path, line_num, type_name, severity, snippet_trimmed))
                    type_count += 1

            total_found += type_count
            if type_count > 0:
                by_type[type_name] = type_count
                sev_key = f"S{severity}" if severity <= 4 else "S4"
                by_severity[sev_key] = by_severity.get(sev_key, 0) + type_count

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    finally:
        conn.close()

    result = {
        "status": "completed",
        "command": "grep-sinks",
        "total_sinks_found": total_found,
        "by_type": by_type,
        "by_severity": by_severity,
        "grep_tool": grep_tool,
        "patterns_file": args.patterns_file
    }
    print(json.dumps(result, ensure_ascii=False))


# ─── 命令: grep-entries ──────────────────────────────────────

# 入口点模式（按框架分类）
ENTRY_PATTERNS = {
    "java-spring": [
        r"@(RestController|Controller|RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)",
        r"@(WebServlet|WebFilter|WebListener)",
        r"@(MessageMapping|SubscribeMapping)",
        r"@(Scheduled|EventListener)",
    ],
    "java-servlet": [
        r"extends\s+HttpServlet",
        r"implements\s+Filter\b",
        r"implements\s+ServletContextListener",
    ],
    "python-django": [
        r"urlpatterns\s*=",
        r"class\s+\w+View\(",
        r"def\s+(get|post|put|delete|patch)\s*\(",
    ],
    "python-flask": [
        r"@app\.(route|get|post|put|delete)\(",
        r"@blueprint\.\w+\(",
    ],
    "python-fastapi": [
        r"@app\.(get|post|put|delete|patch)\(",
        r"@router\.(get|post|put|delete|patch)\(",
    ],
    "node-express": [
        r"(app|router)\.(get|post|put|delete|patch|all|use)\s*\(",
    ],
    "go": [
        r"(HandleFunc|Handle|Get|Post|Put|Delete)\s*\(",
        r"func\s+\w+Handler\(",
    ],
}


def cmd_grep_entries(args):
    """检测入口点文件，更新 files.is_entry=1"""
    grep_tool = _detect_grep_tool()
    project_path = Path(args.project_path).resolve()

    if not grep_tool:
        print(json.dumps({"error": "No grep tool found"}))
        sys.exit(1)

    conn = _connect_db(args.batch_dir)
    entry_files = set()

    try:
        for framework, patterns in ENTRY_PATTERNS.items():
            for pattern in patterns:
                matches = _run_grep(pattern, str(project_path), grep_tool)
                for filepath, _, _ in matches:
                    rel_path = _make_relative(filepath, str(project_path))
                    entry_files.add(rel_path)

        # 更新 files 表
        updated = 0
        for rel_path in entry_files:
            cursor = conn.execute(
                "UPDATE files SET is_entry = 1 WHERE path = ?", (rel_path,)
            )
            if cursor.rowcount > 0:
                updated += 1
            else:
                # 文件不在 files 表中，可能还没被枚举；跳过不插入
                pass

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    finally:
        conn.close()

    result = {
        "status": "completed",
        "command": "grep-entries",
        "entry_files_detected": len(entry_files),
        "files_updated": updated,
        "entry_files": sorted(entry_files)[:50],  # 最多返回 50 个
    }
    print(json.dumps(result, ensure_ascii=False))


# ─── 命令: grep-defenses ─────────────────────────────────────

DEFENSE_PATTERNS = {
    "global-filter": {
        "patterns": [
            r"@EnableWebSecurity",
            r"FilterRegistrationBean",
            r"OncePerRequestFilter",
            r"CsrfFilter",
            r"XssFilter",
            r"helmet\(",
            r"csrf\(\)",
            r"cors\(\)",
        ],
        "scope": "global",
    },
    "framework": {
        "patterns": [
            r"@PreAuthorize\(",
            r"@Secured\(",
            r"@RolesAllowed\(",
            r"hasRole\(",
            r"hasAuthority\(",
            r"@RequiresPermissions\(",
            r"@RequiresRoles\(",
            r"@Valid\b",
            r"@Validated\b",
            r"@Pattern\(",
            r"@Size\(",
            r"@NotBlank",
            r"@NotNull",
        ],
        "scope": "method",
    },
    "parameterization": {
        "patterns": [
            r"PreparedStatement",
            r"setString\(",
            r"setInt\(",
            r"setParameter\(",
            r"createQuery\(",
            r"@Param\(",
            r"#\{[^}]+\}",  # MyBatis parameterized
        ],
        "scope": "method",
    },
    "encoding": {
        "patterns": [
            r"HtmlUtils\.htmlEscape",
            r"StringEscapeUtils\.",
            r"URLEncoder\.encode",
            r"encodeURIComponent\(",
            r"escape\(",
            r"sanitize",
        ],
        "scope": "method",
    },
    "rate-limiting": {
        "patterns": [
            r"@RateLimiter",
            r"RateLimiter\.",
            r"rateLimit\(",
            r"throttle\(",
            r"Bucket4j",
        ],
        "scope": "method",
    },
}


def cmd_grep_defenses(args):
    """检测防御模式，写入 defenses 表"""
    grep_tool = _detect_grep_tool()
    project_path = Path(args.project_path).resolve()

    if not grep_tool:
        print(json.dumps({"error": "No grep tool found"}))
        sys.exit(1)

    conn = _connect_db(args.batch_dir)
    total_found = 0
    by_type = {}

    try:
        for defense_type, config in DEFENSE_PATTERNS.items():
            scope = config["scope"]
            type_count = 0

            for pattern in config["patterns"]:
                matches = _run_grep(pattern, str(project_path), grep_tool)
                for filepath, line_num, snippet in matches:
                    rel_path = _make_relative(filepath, str(project_path))
                    # 从 snippet 提取防御名称
                    defense_name = _extract_defense_name(snippet, pattern)

                    conn.execute("""
                        INSERT OR IGNORE INTO defenses
                        (type, name, file_path, line, scope, detail)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (defense_type, defense_name, rel_path, line_num, scope, snippet[:200]))
                    type_count += 1

            total_found += type_count
            if type_count > 0:
                by_type[defense_type] = type_count

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    finally:
        conn.close()

    result = {
        "status": "completed",
        "command": "grep-defenses",
        "total_defenses_found": total_found,
        "by_type": by_type,
    }
    print(json.dumps(result, ensure_ascii=False))


def _extract_defense_name(snippet, pattern):
    """从匹配行提取防御名称"""
    # 尝试提取注解名或函数名
    m = re.search(r"@(\w+)", snippet)
    if m:
        return m.group(1)
    m = re.search(r"(\w+(?:Filter|Security|Limiter|Validator|Sanitizer))", snippet)
    if m:
        return m.group(1)
    # 降级：使用 snippet 的前 30 字符
    return snippet[:30].strip()


# ─── 命令: grep-secrets ──────────────────────────────────────

SECRET_PATTERNS = [
    {
        "pattern": r"(password|passwd|pwd|secret|token|api[_-]?key)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
        "type": "secret",
        "severity": "high",
        "title": "硬编码凭证",
    },
    {
        "pattern": r"(AKIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASIA)[0-9A-Z]{16}",
        "type": "secret",
        "severity": "critical",
        "title": "AWS Access Key",
    },
    {
        "pattern": r"ghp_[0-9a-zA-Z]{36}",
        "type": "secret",
        "severity": "critical",
        "title": "GitHub Personal Access Token",
    },
    {
        "pattern": r"-----BEGIN (RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----",
        "type": "secret",
        "severity": "critical",
        "title": "Private Key",
    },
    {
        "pattern": r"(jdbc|mysql|postgresql|mongodb)://\w+:\w+@",
        "type": "config",
        "severity": "high",
        "title": "数据库连接串含凭证",
    },
    {
        "pattern": r"(http\.csrf\(\)\.disable|csrf\s*=\s*false|csrf_enabled.*false)",
        "type": "config",
        "severity": "medium",
        "title": "CSRF 保护已禁用",
    },
    {
        "pattern": r"(allowedOrigins\(\"\*\"|Access-Control-Allow-Origin.*\*|cors.*origin.*\*)",
        "type": "config",
        "severity": "medium",
        "title": "CORS 配置为通配符",
    },
]


def cmd_grep_secrets(args):
    """检测硬编码凭证和危险配置，写入 indexer_findings 表"""
    grep_tool = _detect_grep_tool()
    project_path = Path(args.project_path).resolve()

    if not grep_tool:
        print(json.dumps({"error": "No grep tool found"}))
        sys.exit(1)

    conn = _connect_db(args.batch_dir)
    total_found = 0
    by_type = {}

    try:
        for secret_def in SECRET_PATTERNS:
            pattern = secret_def["pattern"]
            matches = _run_grep(pattern, str(project_path), grep_tool)

            for filepath, line_num, snippet in matches:
                rel_path = _make_relative(filepath, str(project_path))

                # 排除注释中的假阳性
                stripped = snippet.strip()
                if stripped.startswith("//") or stripped.startswith("#") or stripped.startswith("*"):
                    # 简单注释过滤（非 100% 准确，但减少噪音）
                    continue

                # 排除示例/文档文件
                if any(ext in rel_path.lower() for ext in [".md", ".txt", ".rst", ".example"]):
                    continue

                conn.execute("""
                    INSERT OR IGNORE INTO indexer_findings
                    (type, severity, file_path, line, title, detail, evidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    secret_def["type"],
                    secret_def["severity"],
                    rel_path,
                    line_num,
                    secret_def["title"],
                    f"Pattern: {pattern}",
                    snippet[:200],
                ))
                total_found += 1
                by_type[secret_def["type"]] = by_type.get(secret_def["type"], 0) + 1

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    finally:
        conn.close()

    result = {
        "status": "completed",
        "command": "grep-secrets",
        "total_findings": total_found,
        "by_type": by_type,
    }
    print(json.dumps(result, ensure_ascii=False))


# ─── 命令: grep-attack-surface ───────────────────────────────

ATTACK_SURFACE_PATTERNS = {
    "file-upload": [
        r"MultipartFile",
        r"@RequestParam.*MultipartFile",
        r"multer\(",
        r"move_uploaded_file",
        r"FileUpload",
    ],
    "websocket": [
        r"@ServerEndpoint\(",
        r"WebSocketServer",
        r"ws\.on\(",
        r"@MessageMapping",
    ],
    "cron": [
        r"@Scheduled\(",
        r"CronTrigger",
        r"node-cron",
        r"schedule\.scheduleJob",
    ],
    "mq": [
        r"@RabbitListener",
        r"@KafkaListener",
        r"@JmsListener",
        r"amqplib",
        r"kafkajs",
    ],
    "rpc": [
        r"@GrpcService",
        r"@DubboService",
        r"Feign",
        r"@FeignClient",
    ],
    "graphql": [
        r"@QueryMapping",
        r"@MutationMapping",
        r"GraphQL",
        r"graphqlHTTP",
    ],
}


def cmd_grep_attack_surface(args):
    """检测攻击面，写入 attack_surface 表"""
    grep_tool = _detect_grep_tool()
    project_path = Path(args.project_path).resolve()

    if not grep_tool:
        print(json.dumps({"error": "No grep tool found"}))
        sys.exit(1)

    conn = _connect_db(args.batch_dir)
    total_found = 0
    by_type = {}

    try:
        for surface_type, patterns in ATTACK_SURFACE_PATTERNS.items():
            type_count = 0
            for pattern in patterns:
                matches = _run_grep(pattern, str(project_path), grep_tool)
                for filepath, line_num, snippet in matches:
                    rel_path = _make_relative(filepath, str(project_path))

                    conn.execute("""
                        INSERT OR IGNORE INTO attack_surface
                        (type, file_path, line, detail)
                        VALUES (?, ?, ?, ?)
                    """, (surface_type, rel_path, line_num, snippet[:200]))
                    type_count += 1

            total_found += type_count
            if type_count > 0:
                by_type[surface_type] = type_count

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    finally:
        conn.close()

    result = {
        "status": "completed",
        "command": "grep-attack-surface",
        "total_items": total_found,
        "by_type": by_type,
    }
    print(json.dumps(result, ensure_ascii=False))


# ─── CLI 入口 ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="批量模式匹配工具 — Sink/入口点/防御/敏感信息/攻击面检测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 批量 Sink grep
  %(prog)s grep-sinks \\
    --batch-dir security-scan-output/project-deep-xxx \\
    --patterns-file resource/scan-data/sink-patterns.yaml \\
    --project-path .

  # 入口点检测
  %(prog)s grep-entries \\
    --batch-dir security-scan-output/project-deep-xxx \\
    --project-path .

  # 防御模式检测
  %(prog)s grep-defenses \\
    --batch-dir security-scan-output/project-deep-xxx \\
    --project-path .

  # 敏感信息检测
  %(prog)s grep-secrets \\
    --batch-dir security-scan-output/project-deep-xxx \\
    --project-path .

  # 攻击面检测
  %(prog)s grep-attack-surface \\
    --batch-dir security-scan-output/project-deep-xxx \\
    --project-path .
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # grep-sinks
    p_sinks = subparsers.add_parser("grep-sinks", help="批量 Sink grep")
    p_sinks.add_argument("--batch-dir", required=True, help="扫描批次目录")
    p_sinks.add_argument("--patterns-file", required=True, help="sink-patterns.yaml 路径")
    p_sinks.add_argument("--project-path", required=True, help="项目根目录")

    # grep-entries
    p_entries = subparsers.add_parser("grep-entries", help="入口点检测")
    p_entries.add_argument("--batch-dir", required=True, help="扫描批次目录")
    p_entries.add_argument("--project-path", required=True, help="项目根目录")

    # grep-defenses
    p_defenses = subparsers.add_parser("grep-defenses", help="防御模式检测")
    p_defenses.add_argument("--batch-dir", required=True, help="扫描批次目录")
    p_defenses.add_argument("--project-path", required=True, help="项目根目录")

    # grep-secrets
    p_secrets = subparsers.add_parser("grep-secrets", help="敏感信息检测")
    p_secrets.add_argument("--batch-dir", required=True, help="扫描批次目录")
    p_secrets.add_argument("--project-path", required=True, help="项目根目录")

    # grep-attack-surface
    p_surface = subparsers.add_parser("grep-attack-surface", help="攻击面检测")
    p_surface.add_argument("--batch-dir", required=True, help="扫描批次目录")
    p_surface.add_argument("--project-path", required=True, help="项目根目录")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "grep-sinks": cmd_grep_sinks,
        "grep-entries": cmd_grep_entries,
        "grep-defenses": cmd_grep_defenses,
        "grep-secrets": cmd_grep_secrets,
        "grep-attack-surface": cmd_grep_attack_surface,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
