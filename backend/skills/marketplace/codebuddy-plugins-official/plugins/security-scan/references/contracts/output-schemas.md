# 输出合约

> 引用方：所有 agent、commands/

---

## 风险发现 JSON 格式

按风险类型拆分，每种类型一个文件：`finding-{risk-type-slug}.json`。

> Ref: `${CODEBUDDY_PLUGIN_ROOT}/resource/risk-type-taxonomy.yaml`（标准类型映射）

```json
{
  "metadata": {
    "fileName": "src/dao/UserDao.java",
    "timestamp": "ISO 8601",
    "auditBatchId": "{command}-{mode}-{timestamp}"
  },
  "summary": {
    "totalIssues": 2,
    "criticalRisk": 0, "highRisk": 1, "mediumRisk": 1, "lowRisk": 0
  },
  "RiskList": [
    {
      "FilePath": "src/dao/UserDao.java",
      "RiskType": "SQL 注入",
      "RiskLevel": "critical",
      "LineNumber": 45,
      "RiskCode": "String sql = \"SELECT * FROM users WHERE id = \" + userId;",
      "RiskConfidence": 95,
      "RiskDetail": "...",
      "Suggestions": "...",
      "FixedCode": "...",
      "auditedBy": ["vuln-scan", "verifier"],
      "verificationStatus": "verified"
    }
  ]
}
```

---

## Agent 输出必需字段

每个 agent 输出必须包含：
- `agent`: agent 名称
- `status`: completed / partial / failed
- `findings[]`: 发现列表
- `writeCount`: 写入次数
- `lastCheckpoint`: 最后检查点
- `_integrity`: { expectedFindingsCount, actualFindingsCount, allPhasesCompleted, lastWriteTimestamp }

### findings[] 中每个 finding 的字段规范

**使用扁平字段，禁止嵌套 location 对象。** 下游脚本（merge_findings.py / verifier.py / generate_report.py）均按以下字段名解析：

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| FilePath | string | 是 | 源文件相对路径（从项目根目录起）。别名：filePath |
| LineNumber | int | 是 | 风险代码行号（单行号，非范围）。别名：lineNumber |
| RiskType | string | 是 | 风险类型 slug（如 sql-injection）。别名：riskType |
| RiskLevel | string | 是 | 严重级别：critical / high / medium / low。别名：severity |
| RiskCode | string | 是 | 风险代码片段（必须来自 Read 输出）。别名：codeSnippet |
| RiskConfidence | int | 是 | 置信度 0-100。别名：confidence |
| RiskDetail | string | 是 | 风险描述。别名：description |
| Suggestions | string | 否 | 修复建议。别名：remediation |
| FixedCode | string | 否 | 修复后代码 |
| attackChain | object | 是 | 攻击链（见 agent-rules.md 第 3 节） |
| traceMethod | string | 是 | 追踪方式：LSP / Grep+Read / unknown |
| auditDimension | string | 否 | 审计维度：C1-C10 |

**禁止使用的格式**（会导致字段丢失）：
```json
// 错误：嵌套 location 对象
{ "location": { "file": "...", "startLine": 88 } }

// 正确：扁平字段
{ "FilePath": "...", "LineNumber": 88 }
```

> `normalize_finding()` 提供防御性兼容：即使 Agent 使用了 location.startLine 等非规范格式，也能正确提取。但 Agent 应始终使用上述规范字段名，避免依赖兼容层。

---

## 输出目录结构

```
security-scan-output/{batch}/
  project-index.db              # 语义索引（SQLite）
  agents/
    indexer.json
    vuln-scan.json              # Deep 模式（vuln-scan Agent 产出）
    logic-scan.json             # Deep 模式（logic-scan Agent 产出）
    red-team.json               # Deep 模式（red-team Agent 产出）
    verifier-vuln.json          # Deep 模式（verifier 分片产出）
    verifier-logic.json         # Deep 模式（verifier 分片产出）
    verifier-redteam.json       # Deep 模式（verifier 分片产出）
    light-inline.json           # Light 模式
    remediation.json
  pre-check-results.json        # verifier.py pre-check 产出
  filtered-findings.json        # grade_verifiable findings
  filtered-findings-vuln.json   # verifier.py split 产出（vuln-scan findings）
  filtered-findings-logic.json  # verifier.py split 产出（logic-scan findings）
  filtered-findings-redteam.json # verifier.py split 产出（red-team findings）
  chain-verify-results.json     # verifier.py chain-verify 产出（攻击链索引验证）
  challenge-results.json        # verifier.py challenge 产出（确定性对抗审查）
  score-results.json            # verifier.py score 产出（确定性置信度评分）
  quality-assessment.json       # verifier.py quality 产出（确定性质量评估）
  stage1-context.json
  merged-scan.json
  merged-verified.json          # Deep 模式
  finding-{slug}.json
  summary.json
  security-scan-report.html
  poc-scripts.py                # POC 验证脚本（独立可执行，仅依赖 requests）
  poc-manifest.json             # POC 清单（验证方式、端点信息、使用说明）
  poc-results.json              # POC 验证结果（用户执行 poc-scripts.py 后产出）
```

---

## summary.json

```json
{
  "batchId": "...",
  "command": "project | diff",
  "scanMode": "fast | light | deep",
  "totalFindings": 0,
  "criticalRisk": 0, "highRisk": 0, "mediumRisk": 0, "lowRisk": 0,
  "executionMetrics": {
    "lspStatus": "available | unavailable | skipped",
    "totalDuration": "120s"
  }
}
```
