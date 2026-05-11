# Agent 通用规则

> 引用方：所有 agent

---

## 1. 反幻觉约束

**宁可漏报也不误报**。FilePath/RiskCode 必须来自工具输出（Grep/Read/Glob/LSP），防御搜索是强制前置步骤。

**必须 Read** 完整合约文件获取具体规则条目（共 5 条硬规则）：
`${CODEBUDDY_PLUGIN_ROOT}/resource/anti-hallucination-rules.yaml`

## 2. 增量写入

**任何已完成的分析结果必须在 3 个工具调用周期内写入磁盘。**

### 写入触发条件（满足任一）

1. 完成一个完整 finding
2. 完成一个 Phase / 子任务
3. 累积未写入数据超过 2000 tokens
4. 连续 10 次工具调用未写入

### 写入方式

> ⚠️ **严格使用 Read/Write 工具操作 Agent JSON 输出文件。禁止使用 `python3 -c` 读写 JSON 文件。**

1. **Read** 工具读取当前输出文件（获取已有 findings + writeCount）
2. 在 LLM 内部合并新 findings 到已有数据
3. **Write** 工具写入完整 JSON（覆盖写入）
4. 确保更新 `meta.status`、`meta.lastCheckpoint`、`meta.writeCount`

**工具选择规则**：
- 读文件 → **Read 工具**（免授权，直接读取文件内容）
- 写文件 → **Write 工具**（白名单已覆盖 `security-scan-output/*`）
- 查数据库 → **`index_db.py query`**（preset 或自定义 SQL）
- **禁止**用 `python3 -c` 做文件读写 — 这不是数据处理，是工具层已覆盖的基础操作

### 恢复协议

Agent 启动时检查输出文件：
- 已存在且 `status != "completed"` -> 从 `lastCheckpoint` 继续
- 不存在 -> 从头开始

### 各 Agent 写入节奏

| Agent | 写入时机 |
|-------|---------|
| indexer | indexer-步骤1 完成后批量写入（indexer-1.写入）；indexer-步骤2 每完成一个子步骤增量写入；indexer-步骤3 每完成一个子步骤增量写入 |
| vuln-scan | 第 1 个 finding 后立即写入；之后每完成 1 个追加 |
| logic-scan | 第 1 个 finding 后立即写入；之后每完成 1 个追加 |
| red-team | 第 1 个 finding 后立即写入；之后每完成 1 个追加 |
| verifier | 第 1 个 finding 验证后立即写入；之后每完成 1 个追加 |

### 资源预算

真正的硬约束是 `max_turns`（Task 工具参数），插件层面无法改变。Agent 只需遵循以下简单规则：

1. **立即写入，禁止积攒** — 每完成一个 finding 立即追加写入
2. **预算紧张时保结果** — 感觉快到限制时，停止新探索，写入已完成结果
3. **设置正确的退出状态** — 全部完成 `completed`，未完成 `partial`（含 `earlyTermination`）

LSP 结果复用：同一方法的 incomingCalls/outgoingCalls 结果在本次审计中有效，不重复调用。

收尾模式触发条件（任一）：
1. 输出被截断
2. 当前 turn 数接近 max_turns（剩余 <= 2 turns）

收尾动作：停止新探索 -> 写入已完成结果 -> 设置 status（`completed` 或 `partial`）

### 增量写入实现模板

Agent 使用 `_common.py` 提供的辅助函数完成增量写入。以下为标准流程：

**1. 启动时初始化输出文件**

```python
# Agent 启动后立即执行（步骤0 加载索引之前）
existing, checkpoint = init_agent_output(output_path, 'vuln-scan')
if existing:
    # 续扫模式：从 checkpoint 继续，跳过已完成的 findings
    completed_ids = {f.get('findingId') for f in existing.get('findings', [])}
```

**2. 每完成一个 finding 后立即追加**

```python
# 完成一个 finding 后立即写入（禁止积攒）
finding = { "FilePath": "...", "LineNumber": 42, ... }
incremental_write_findings(
    path=output_path,
    new_findings=[finding],
    agent_name='vuln-scan',
    checkpoint='sink-3',      # 当前进度标识
    status='partial',         # 尚未全部完成
)
```

**3. 全部完成后标记 completed**

```python
# 最后一个 finding 写入时设置 status='completed'
incremental_write_findings(
    path=output_path,
    new_findings=[last_finding],
    agent_name='vuln-scan',
    checkpoint='done',
    status='completed',
)
```

**关键要求：**
- `write_json_file()` 使用 temp + rename 原子操作，中途崩溃不会损坏文件
- 并发读取者始终看到完整有效的 JSON
- Agent 超时后，已写入的 findings 会被 merge_findings.py 正常处理

## 3. 攻击链合约

所有 finding 必须包含 `attackChain`：

```json
{
  "source": "entry point or user input",
  "propagation": ["intermediate call 1", "call 2"],
  "sink": "dangerous operation",
  "traceMethod": "LSP | Grep+Read | unknown"
}
```

## 4. 严重级别规则

四级：**Critical > High > Medium > Low**。

**严格约束：只有可直接造成入侵或大量数据泄漏的风险才能标记为 Critical/High，其他一律归入 Medium/Low。**

### Critical（严重）— 可直接远程入侵
仅限以下场景：
- 无认证直接 RCE（命令注入、代码执行、反序列化、JNDI 注入、SSTI、表达式注入）
- 已知恶意/投毒依赖包（malicious-package）
- 在野被积极利用的 CVE（存在公开 PoC，列入 CISA KEV）

### High（高危）— 可直接入侵或造成大量数据泄漏
仅限以下场景：
- SQL 注入 / NoSQL 注入（可导致大量数据泄漏）
- 认证绕过（auth-bypass，可直接获取未授权访问）
- 硬编码凭证/后门（hardcoded-secret，可直接拿凭证入侵）
- 可 RCE 的调试端点暴露（如 Flask Debugger、Node.js Debug 端口、Jolokia）
- 可导致大量内存数据泄漏的端点（如 heapdump）

### Medium（中危）— 需要上下文或链式利用
- SSRF、路径穿越、XXE、XSS、CSRF、IDOR、文件上传
- LDAP 注入、访问控制缺陷、明文密码、JWT 问题
- 各类端点暴露（Actuator、pprof、phpinfo 等）
- DoS 类（ReDoS、XML 炸弹、Zip 炸弹）
- 前端安全问题（PostMessage、CORS 反射、WebSocket 劫持）
- 敏感数据日志泄露、依赖混淆、云安全配置问题（CAM/IAM 策略过宽、COS/S3 公开存储桶、云函数无认证）

### Low（低危）— 信息泄露/配置/辅助性问题
- 信息泄露、不安全配置、弱加密、缺少安全头
- CSV 注入、弱密码哈希、审计缺失、暴力破解防护缺失
- Swagger/GraphQL 暴露、CSRF 禁用、CORS 配置问题
- 日志注入、缺少锁定文件

**禁止**：不得仅因「理论上可能」或「最坏情况下」就提升到 Critical/High。必须基于实际攻击链的可达性和直接危害判定。

## 5. LSP 降级规则

> 完整降级策略和错误处理表：Ref `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/initialization.md > LSP 降级规则`。

摘要：S1/S2 Sink 必须至少尝试 1 次 LSP；失败仅该 Sink 回退；`lspStatus: "unavailable"` 时全部使用 Grep+Read。

## 6. Read 规范

- 禁止全文件 Read，必须用 `offset` + `limit`
- Sink/finding 上下文：目标行号 +-30 行
- 同文件最多 Read 3 次
- 大文件(>500行)先用 LSP documentSymbol 定位

## 7. 反隧道视野

- 同一 RiskType 多文件出现 -> 合并为 1 个 finding + `affectedFiles[]`
- 单一维度不超过总预算 40%

## 8. Bash 使用规则

### 单行命令强制约束

**所有 Bash 命令必须为单行格式，禁止在命令中插入换行符。** 多行命令会导致权限白名单通配符匹配失败，触发不必要的手动授权弹窗。

常见场景：
- `wc -l` 后跟多个文件路径 → 所有路径写在同一行，用空格分隔
- `sqlite3` 后跟 SQL 语句 → SQL 压缩为单行（去除换行和多余空格）
- `python3 -c "..."` 内联脚本 → 代码写在同一行，用 `;` 分隔语句

> **数据库查询优先使用 `index_db.py query`**（`--preset`/`--sql`），覆盖绝大多数场景。仅当 preset 无法满足需求时才用 `python3 -c` 内联 SQLite，且必须为**单行格式**（用 `;` 分隔语句）。

### 允许/禁止列表

- **允许**：调用插件 Python 脚本（`python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/{script_name}" {subcommand} {args}`）
- **允许**：带 export 前缀的 Python 脚本调用（`export CODEBUDDY_PLUGIN_ROOT=... && python3 ...`）
- **允许**：内联 Python 数据处理（`python3 -c "..."`，**仅限**SQLite 查询、数据转换等轻量操作）
- **允许**：Git 只读操作（`git ls-files`/`diff`/`log`/`status`/`rev-parse`）
- **允许**：目录列表查看（`ls`）、回显验证（`echo`）
- **允许**：延时等待（`sleep N && ...`，用于等待上游 Agent 完成后执行查询/检查）
- **禁止**：用 `python3 -c` 读写文件（**必须用 Read/Write 工具**，免授权且更高效）
- **禁止**：`bash grep`/`find`/`cat` 做安全分析（必须使用工具层 Grep/Read/Glob）
- **禁止**：`pip install`/`brew install`/`npm install` 等包管理器命令（由 `ts_parser.py setup` 内部处理）
- **禁止**：内联 Python 中执行网络请求、修改项目源代码、安装包或执行危险子进程
- **禁止**：使用 `for`/`while` 等 Shell 循环
- **禁止**：在 Bash 命令中插入换行符（所有命令必须为单行）

## 9. 通用注意事项

- 不执行攻击，不修改项目源文件
- 所有文件路径和行号必须来自工具输出
- 排除测试数据和示例
- 每完成一个阶段必须立即写入，禁止积攒
