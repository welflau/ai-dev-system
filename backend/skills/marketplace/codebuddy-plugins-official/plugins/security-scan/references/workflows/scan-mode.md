# 扫描模式策略

> 引用方：commands/project.md、commands/diff.md

定义 Fast（极速扫描）、Light（快速扫描）和 Deep（深度扫描）三种模式在各阶段的执行策略差异。

---

## 模式选择交互

> 完整交互流程：Ref `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/initialization.md > init-步骤2: 模式选择`

若用户通过 `--scan-level fast`、`--scan-level light` 或 `--scan-level deep` 指定了扫描模式，则**直接采用**该模式，跳过交互。否则弹出交互让用户选择"极速扫描（Fast）"、"快速扫描（Light）"或"深度扫描（Deep）"。

> 模式选择在权限配置（init-步骤1）之后、环境准备（init-步骤3/4）之前执行。后续步骤按需准备：Fast/Light 跳过 LSP，Deep 才做 LSP 探活+安装。

记录 `scanMode = "fast" | "light" | "deep"`。

---

## Fast 模式硬性约束（必读）

> 此章节定义 Fast 模式相对于 Light 的执行纪律，基于对 Light 实际会话的耗时瓶颈分析（平均耗时 22 分钟 → Fast 目标 7 分钟）。

Fast = **Light + 纪律**。检查逻辑（LLM 做扫描和验证）与 Light 完全相同，但执行方式受以下约束：

**A. 并行化（必须）**
- 阶段 1 的 Grep/Glob（技术栈、Sink、凭证）必须同一 message 内并行发起，最多 4 个并行工具调用
- 阶段 2 多文件 Read 必须同一 message 内并行发起，N 个文件 = 一批并行 Read

**B. 禁用轮询等待（必须）**
- ❌ 禁止 `sleep N && ls` 循环检查产物
- ❌ 本期禁止启动任何后台 Agent（project 和 diff 均走编排器主窗口内联执行）
- 未来若需后台 Agent，必须使用 `Task` 的 `run_in_background=true` + `TaskOutput` 机制

**C. 扫描+验证合并（必须）**
- 阶段 2 产 finding 时同时完成代码存在性校验，打标 `verificationStatus: "inline-verified"`
- 阶段 3 完全跳过

**D. 字段 schema 约束（必须）**
- 规范字段：`riskType` / `filePath` / `lineNumber` / `severity` / `riskConfidence` / `verificationStatus`
- 即使写错，`scripts/merge_findings.py` 的 `normalize_finding_schema` 会兜底映射常见漂移（finding_type / file_path / line / riskLevel / confidence 等）

**E. POC 生成（默认跳过）**
- 默认 skip。命令行传 `--with-poc` 才启用。

**F. 裁剪范围**
- 阶段 1 跳过：攻击面/入口
- 阶段 3 跳过（默认），但 `merge-verify` bypass 路径会前置跑一次确定性 `run_pre_check` 兜底（`SECURITY_SCAN_FAST_V2=0` 可关闭）
- 阶段 4 默认跳过 POC

**G. 前置脚本化预筛（必须）**
- 阶段 1 必须在 LLM 任何 Grep 之前运行 `pattern_grep.py grep-sinks / grep-defenses / grep-secrets` 三条命令，把 Sink / 防御 / 凭证写入 `project-index.db`
- 阶段 2 必须通过 `index_db.py query --preset sinks-top-per-file --limit 3`（+ `defenses-for-file` 为每个文件拉防御）消费预筛产物；每文件 Top-K 裁剪，避免同文件同类型 Sink 触发 LLM 重复判定
- diff 模式下脚本仍跑整仓；阶段 2 用 `changedCodeFiles` 列表过滤；project 模式直接使用整仓 Sink

**H. Source 可达性三判（必须）**
- LLM 在阶段 2 产出 finding 之前，必须对每个候选 Sink 回答三个判定题；任一判定不通过即 `verificationStatus: "inline-dismissed"`，不产出 finding：
  1. **isReachableFromSource**：Sink 的关键参数是否可由外部输入（HTTP 参数、DTO 字段、路径变量、Cookie、Header、上传文件、MQ 消息、外部 API 返回）到达？
  2. **isUndefended**：基于 `defenses-for-file` 查询 + Sink 前后 30 行上下文，是否缺少有效防御（参数化查询、白名单、强类型、Bean Validation、Spring Security 注解）？
  3. **isAttackerReachable**：Sink 所在函数是否存在一条通往入口点（Controller / @RestController / HttpServlet / @MessageMapping / @KafkaListener / @Scheduled）的调用链？
- **禁止只凭 Sink 关键字命中直接产出 finding**；三判完整 prompt 与决策表见 `阶段 2: 扫描差异 > Fast 模式`。

---

## 阶段0: 初始化差异

> 完整初始化流程：Ref `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/initialization.md`

本节仅列出三种模式在初始化阶段的**策略差异**：

| 维度 | Fast | Light | Deep |
|------|------|-------|------|
| 权限检查与配置（init-步骤1） | 检查 + 自动修复 | 同 Fast | 同 Fast |
| 模式选择（init-步骤2） | 交互选择 | 同 Fast | 同 Fast |
| tree-sitter（init-步骤3） | **整体跳过** | **整体跳过** | 检测 + 自动安装 |
| LSP 探活与安装（init-步骤4） | **整体跳过** | **整体跳过** | 探活 + 自动安装二进制 + 二次探活 |
| 环境就绪确认（init-步骤5） | 直接输出就绪信息（无 pendingActions） | 同 Fast | 可能包含 LSP / tree-sitter 降级提示 |

---

## 阶段1: 探索差异

### Fast 模式

编排器内快速完成基础探索，**严格遵守 Fast 硬性约束 A + G**：所有 Grep/Glob 并行发起，且 LLM Grep 之前必须先跑脚本预筛（三条 `pattern_grep.py`）。

执行顺序：

1. `index_db.py init`（初始化 DB）
2. **脚本预筛（约束 G，不经过 LLM，串行跑完）**：
   ```bash
   python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/pattern_grep.py" grep-sinks \
     --batch-dir security-scan-output/$audit_batch_id \
     --patterns-file "${CODEBUDDY_PLUGIN_ROOT}/resource/scan-data/sink-patterns.yaml" \
     --project-path .
   python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/pattern_grep.py" grep-defenses \
     --batch-dir security-scan-output/$audit_batch_id \
     --project-path .
   python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/pattern_grep.py" grep-secrets \
     --batch-dir security-scan-output/$audit_batch_id \
     --project-path .
   ```
3. **LLM 并行补充（单 message 发起，约束 A）**：
   - 文件枚举 + 技术栈识别（Glob + Grep）
   - 凭证/密钥补充（脚本未覆盖的框架特定密钥）
   - CVE 扫描（读 `indexer-findings` 表）

跳过（瘦身）：
- 攻击面检测（entries / attack-surface）
- Sink / 凭证的 LLM 重复定位（脚本已完成）
- 框架级防御基线 LLM 扫描（脚本 `grep-defenses` 已落 DB，阶段 2 按需拉取）

产物验收：
```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" query \
  --batch-dir security-scan-output/$audit_batch_id \
  --preset sinks-by-severity --limit 100
# 预期 rows.count > 0；若为 0，说明脚本未跑或项目无 Sink，停止并排查。
```

### Light 模式

编排器内快速完成基础探索（Grep/Glob，不启动 Agent）：
1. 文件枚举 + 技术栈识别
2. Sink 粗定位、凭证/密钥检测、配置基线、CVE 扫描

### Deep 模式

先执行 Light 模式的基础探索，然后将探索结果写入索引数据库，最后启动 indexer Agent 从 indexer-步骤2 开始构建语义索引：

#### 1.1 编排器写入索引数据库（脚本化 indexer-步骤1 前置）

基础探索完成后，编排器通过脚本批量执行 indexer-步骤1 的确定性工作，并将结果写入 `project-index.db`：

```bash
# 1. 初始化索引数据库
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" init --batch-dir security-scan-output/{audit_batch_id}

# 2. 检测项目框架（确定性）
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/orchestration_helper.py" detect-framework --project-path .

# 3. 写入项目元数据 + 文件清单（编排器已有的枚举结果）
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" write --batch-dir security-scan-output/{audit_batch_id} --data '{
  "phase": "phase1",
  "meta": {
    "framework": "{framework}",
    "file_count": "{fileCount}",
    "total_lines": "{totalLines}",
    "language": "{primaryLanguage}"
  },
  "table": "files",
  "rows": [{fileRows}]
}'

# 4. 脚本化 Sink grep（替代手动 Grep 循环）
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/pattern_grep.py" grep-sinks \
  --batch-dir security-scan-output/{audit_batch_id} \
  --patterns-file "${CODEBUDDY_PLUGIN_ROOT}/resource/scan-data/sink-patterns.yaml" \
  --project-path .

# 5. 脚本化入口点检测
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/pattern_grep.py" grep-entries \
  --batch-dir security-scan-output/{audit_batch_id} \
  --project-path .

# 6. 脚本化攻击面检测
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/pattern_grep.py" grep-attack-surface \
  --batch-dir security-scan-output/{audit_batch_id} \
  --project-path .

# 7. 脚本化防御检测（基础）
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/pattern_grep.py" grep-defenses \
  --batch-dir security-scan-output/{audit_batch_id} \
  --project-path .

# 8. 脚本化敏感信息检测
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/pattern_grep.py" grep-secrets \
  --batch-dir security-scan-output/{audit_batch_id} \
  --project-path .

# 9. 写入框架隐式行为（编排器探索阶段检测到的）
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" write --batch-dir security-scan-output/{audit_batch_id} --data '{
  "phase": "phase1",
  "table": "framework_behaviors",
  "rows": [{behaviorRows}]
}'

# 10. 标记 phase1 完成（触发增量扫描启动）
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" write --batch-dir security-scan-output/{audit_batch_id} --data '{"phase":"phase1","phase_status":"completed"}'
```

> **脚本化优势**：步骤 4-8 由 `pattern_grep.py` 确定性执行（无 LLM 参与），结果直接写入 DB。
> 编排器无需手动构造 Grep 命令、解析输出、拼装 JSON、写入 DB，减少 5-8 个 LLM turns。

#### 1.2 启动 indexer Agent（从 indexer-步骤2 开始）

```
Task(indexer):
  prompt:
    构建项目语义索引（SQLite 数据库）。
    [batch-dir] security-scan-output/{audit_batch_id}
    [lspStatus] {lspStatus}
    [db-tool] ${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py
    [ts-parser] ${CODEBUDDY_PLUGIN_ROOT}/scripts/ts_parser.py
    [memory-hints] {memory_hints_json}
    [structureCache] {structureCache_json}
    [scan-mode] deep
    {scope == "diff" ? "[scope] diff\n[changed-files] {changedCodeFiles}\n[related-files-limit] {limit}" : ""}
  max_turns: 30
  mode: bypassPermissions
```

indexer Agent 启动后检测到 indexer-步骤1 已由编排器完成（`phases.phase1 == "completed"`），自动跳过 indexer-步骤1，从 indexer-步骤2 开始执行：
- **indexer-步骤2**（AST 精化，双引擎）：tree-sitter 引导安装 + 批量解析持久化（persist）+ Sink AST 验证；结果缓存到 SQLite（ast_functions、ast_calls、ast_refined_sinks 等），后续阶段通过 cached-query 复用
- **indexer-步骤3**（LSP 语义精化）：端点精化、Sink 调用追踪、调用图构建、防御映射

---

## 阶段2: 扫描差异

### Fast 模式: 编排器内联扫描 + 内联验证（纪律化）

沿用 Light 的内联扫描逻辑（LLM 在主窗口读 Sink 上下文、判断防御、产出 finding），但增加以下约束：

**1. Sink 清单驱动扫描**（约束 G 续）

扫描开始前先拉 DB，使用 **每文件 Top-K** 裁剪策略避免同文件多 Sink 重复判定（默认 k=3）：

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" query \
  --batch-dir security-scan-output/{audit_batch_id} \
  --preset sinks-top-per-file --limit 3
```

得到 `{sinks: [...], count: N, k_per_file: 3}`。`sinks` 按 `severity_level` 全局排序、同文件连续，便于 LLM 按文件批量 Read + 批量判定。

- diff 模式下与 `changedCodeFiles` 求交集
- 按 `severity_level ASC`（S1 → S3）处理，前 k 个文件（建议 k 文件 ≤ 30）进入 LLM 判定队列
- **回滚说明**：环境变量 `SECURITY_SCAN_FAST_V2=0` **仅关闭 `merge_findings.py` 的 pre-check 兜底**；Top-K 裁剪和批量三判由本文档定义，LLM 执行时感知不到环境变量。若需完全回退到 Fast P0 基线行为，请 `git revert` 本次 A+B 改动（恢复旧 prompt 和旧 preset 名）

**2. Source 可达性三判**（约束 H，文件内批量）

三判规则不变。**默认采用文件内批量模式**：LLM Read 一个文件后，对该文件**所有候选 Sink** 一次性输出 verdict 数组，避免同文件 N 个 Sink 触发 N 次 LLM 往返。

**逐字** prompt（文件级批量）：

```
对以下同一文件内的 {N} 个 Sink，逐个执行三判再一次性输出 verdict 数组：
  [文件] {file}
  [Defenses-for-file] {defenses JSON from index_db query}
  [Sinks]
    1. line={L1} type={T1} snippet={S1}
    2. line={L2} type={T2} snippet={S2}
    ...

判定 1 (isReachableFromSource)
  Sink 关键参数是否可由外部输入（HTTP 参数、DTO 字段、路径变量、Cookie、Header、上传文件、MQ 消息、外部 API 返回）到达？
    - 字面量 / 配置常量 / 枚举 → "no"
    - 从 HTTP 参数 / DTO / Controller 透传 → "yes"
    - 无法追溯 / 不确定 → "maybe"

判定 2 (isUndefended)
  基于 Defenses-for-file + Sink 前后 30 行上下文，是否缺少有效防御？
    - PreparedStatement / 参数化查询 → "no（已防御）"
    - 白名单 / 强类型 enum / @Pattern @Size / Bean Validation → "no（已防御）"
    - 仅字符串替换（replaceAll(',', '')）/ 黑名单 → "yes（不充分）"
    - 无任何防御 → "yes"

判定 3 (isAttackerReachable)
  Sink 所在函数是否存在一条通往入口点（Controller / @RestController / HttpServlet / @MessageMapping / @KafkaListener / @Scheduled）的调用链？
    - private 工具 + 仅被单元测试调用 → "no"
    - 从 Controller 透传到 Service/DAO → "yes"
    - 未能判断 → "maybe"

输出 JSON 数组（每个 Sink 一条，顺序与 Sinks 列表一致）：
  {
    "verdicts": [
      {
        "line": {L1},
        "isReachableFromSource": "yes|maybe|no",
        "isUndefended": "yes|no",
        "isAttackerReachable": "yes|maybe|no",
        "action": "report | downgrade | dismiss",
        "reasonBrief": "<= 30 字中文原因"
      },
      ...
    ]
  }

action 决策表：
  三判全 yes         → report     → verificationStatus=inline-verified, riskConfidence ≤ 90
  一个 maybe 其它 yes → downgrade  → verificationStatus=inline-verified, severity 降一级 或 riskConfidence -= 20
  任一 no           → dismiss    → verificationStatus=inline-dismissed, 不入 light-inline.json（记日志备审）
```

**批量约束**：
- 每个文件一次 prompt，对该文件 N 个 Sink 一并输出
- 多个文件在同一 assistant message 内并行（约束 A，≤4 并发）
- Read 与 verdict 输出合并到单一 message，避免往返开销
- **严禁遗漏**：verdicts 数组长度必须等于 Sinks 列表 N；若 LLM 判断 dismiss 仍需输出 verdict 条目并记录 reason，仅在转写 `light-inline.json` 时过滤

**注意**：本批量三判 prompt 是本文档的**硬性规范**，由 LLM 主动遵循，无环境变量可切换。`SECURITY_SCAN_FAST_V2=0` 仅关闭 pre-check 兜底，不影响此 prompt。若需完全回退到单 Sink 模式，请 `git revert` 本次改动。

**3. 防御查询脚本化**

为每个涉及文件执行：

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" query \
  --batch-dir security-scan-output/{audit_batch_id} \
  --preset defenses-for-file --filter-file <path>
```

结果注入判定 2 的 prompt，减少 LLM 自行 Grep 防御。

**4. 并行 Read + 批量三判合并**（约束 A）

同一 assistant message 内：Read 多个文件（≤ 4 并发）→ 对每个文件的所有 Sink 输出 verdict 数组（文件内批量，见约束 H）。Read 与 verdict 输出合并为单一 message，避免往返开销。仅对 `action=report` / `downgrade` 的 Sink 进入 `light-inline.json`；`dismiss` 的条目只出现在 verdict 日志中。

**5. 字段 schema 规范**

`riskType` / `filePath` / `lineNumber` / `severity` / `riskConfidence`（Fast 上限 90） / `verificationStatus`（即使写错，`merge_findings.py` 的 `normalize_finding_schema` 会兜底）。

**产物**：`agents/light-inline.json`（`sourceAgent: "light-inline"`）

**合并命令**：
```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/merge_findings.py" merge-scan \
  --batch-dir security-scan-output/{audit_batch_id} \
  --extra-agents indexer-findings,light-inline

python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/merge_findings.py" merge-verify \
  --batch-dir security-scan-output/{audit_batch_id}
# Fast 模式 merge-verify 会：
#   1) 检测 scan_mode == "fast" 且无 verifier 产出 → 走 bypass 路径
#   2) bypass 路径前置执行 verifier.run_pre_check 兜底
#      - 校验文件存在 / 行号范围 / 代码片段模糊匹配
#      - 不通过的 finding 打 _removed，从 merged-verified.json 中剔除
#      - 代码片段模糊匹配失败不删除，仅降级（扣置信度）
#   3) SECURITY_SCAN_FAST_V2=0 可回滚关闭兜底
```

置信度上限 **90**。

**Source 可达性三判 决策表**（速查）：

| isReachableFromSource | isUndefended | isAttackerReachable | action | verificationStatus |
|---|---|---|---|---|
| yes | yes | yes | report | inline-verified |
| maybe | yes | yes | downgrade | inline-verified |
| yes | yes | maybe | downgrade | inline-verified |
| no  | *   | *   | dismiss | inline-dismissed |
| *   | no  | *   | dismiss | inline-dismissed |
| *   | *   | no  | dismiss | inline-dismissed |

### Light 模式: 编排器内联扫描

不启动独立 Agent，编排器在主窗口内执行：

1. **导出 indexer findings**（密钥/配置/CVE）：

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" query --batch-dir security-scan-output/{audit_batch_id} --preset indexer-findings
```

2. **Sink 风险评估**：

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" query --batch-dir security-scan-output/{audit_batch_id} --preset sinks-by-severity --limit 30
```

对 S1（critical 优先级）Sink 执行轻量分析：
- Read Sink 所在代码上下文（+/-20 行）
- 检查是否存在直接防御（参数化查询、白名单、编码等）
- 产出 finding（`sourceAgent: "light-inline"`，`confidence` 上限 90）

3. **合并结果**：

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/merge_findings.py" merge-scan --batch-dir security-scan-output/{audit_batch_id} --extra-agents indexer-findings,light-inline
```

> **diff 模式 Light 扫描注意**：diff 命令的 Light 模式启动 `light-scan` Agent（而非 project 的 `light-inline` 内联），合并时必须指定 `--extra-agents light-scan`。merge-scan 脚本也有兼容兜底：即使编排器遗漏 `--extra-agents`，脚本会自动发现 `agents/light-scan.json` 并加载。

### Deep 模式: 三 Agent 并行扫描

#### 2.0 增量门控：根据 phase 状态渐进式启动扫描 Agent

扫描 Agent 依赖 indexer 产出的语义索引数据。编排器通过脚本检查 phase 状态，**渐进式启动** Agent：

```bash
# 脚本化门控检查（替代手动 SQL 查询和 if/else 判断）
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/orchestration_helper.py" should-launch-agent \
  --batch-dir security-scan-output/{audit_batch_id} \
  --agent vuln-scan
# 返回: {"action": "launch|wait|already_run", "reason": "...", ...}
```

**Phase 与 Agent 启动对应关系**：

| Phase 完成 | 可启动的 Agent | 数据可用性 |
|-----------|---------------|----------|
| phase1 | vuln-scan, red-team | 有 coarse sink，但无 AST/LSP |
| phase1_5 | 触发已启动 agent 的 re-run | 有 AST 数据（精确行号+函数范围） |
| phase2 | logic-scan | endpoints/call_graph/defenses 可用 |
| phase2 | 触发所有 agent final re-run | LSP 数据完整，traceMethod=LSP |

**Re-run 机制**：

```bash
# 检查是否需要 re-run（检测 phase 更新）
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/orchestration_helper.py" should-rerun-agent \
  --batch-dir security-scan-output/{audit_batch_id} \
  --agent vuln-scan
# 返回: {"action": "rerun|no_action|skip", "reason": "New data available: phase1 → phase1_5", "instruction": "rm agents/vuln-scan.json && relaunch"}
```

Re-run 时删除 agent 输出文件，让 agent 重新查询最新 DB 数据。每个 agent 最多 re-run 2 次。

**增量扫描时序**：

```
时间轴
│ phase1 完成
├─→ 启动 vuln-scan-v1 (phase1 sink)
├─→ 启动 red-team-v1 (phase1 数据)
│
│ phase1_5 完成
├─→ 检查 should-rerun-agent vuln-scan → rerun
├─→ 检查 should-rerun-agent red-team → rerun
├─→ vuln-scan-v2 (AST 数据)
├─→ red-team-v2 (AST 数据)
│
│ phase2 完成
├─→ 启动 logic-scan (endpoints 可用)
├─→ 检查 should-rerun-agent vuln-scan → rerun
├─→ 检查 should-rerun-agent red-team → rerun
├─→ vuln-scan-v3 (LSP 完整数据)
├─→ red-team-v3 (LSP 完整数据)
│
│ 所有 agent 完成
└─→ 启动验证流程
```

> **重要**：logic-scan 的 `min_phase` 为 `phase2`（依赖 endpoints 表），不在 phase1 时启动。
> vuln-scan 和 red-team 可在 phase1 启动，但产出的 findings 置信度上限为 90（Grep+Read fallback）。
> phase2 后的 final re-run 使 findings 获得 LSP 数据支持，置信度上限提升至 100。

#### 2.0a 进度监控

编排器通过脚本监控整体进度：

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/orchestration_helper.py" summarize-progress \
  --batch-dir security-scan-output/{audit_batch_id}
# 返回: {"progress": "5/8", "progress_pct": 63, "next_actions": [...], ...}
```

`next_actions` 字段给出下一步操作建议（launch_agent / rerun_agent / start_verification / wait）。

#### 2.1 启动扫描 Agent（增量启动）

根据 2.0 的门控结果，分阶段启动 Agent。每个 Agent 在输出中记录 `metadata.index_phase`，供 re-run 判断使用：

```
Task(vuln-scan):
  prompt:
    执行 Source→Sink 数据流追踪漏洞审计（C1 注入类）。
    [batch-dir] security-scan-output/{audit_batch_id}
    [scan-mode] deep
    [db-tool] ${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py
    [输出文件] agents/vuln-scan.json
    [index-phase] {current_phase}  # phase1 | phase1_5 | phase2
  max_turns: 25
  mode: bypassPermissions

Task(logic-scan):  # 仅在 phase2 完成后启动
  prompt:
    执行认证授权（C3）+ 业务逻辑（C7）安全审计。
    [batch-dir] security-scan-output/{audit_batch_id}
    [scan-mode] deep
    [db-tool] ${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py
    [输出文件] agents/logic-scan.json
    [index-phase] {current_phase}
  max_turns: 25
  mode: bypassPermissions

Task(red-team):
  prompt:
    以红队视角执行 3 核心猎杀问题深度审计（Q1 自造轮子、Q2 异常路径、Q3 信任穿越）。
    [batch-dir] security-scan-output/{audit_batch_id}
    [scan-mode] deep
    [db-tool] ${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py
    [输出文件] agents/red-team.json
    [index-phase] {current_phase}
  max_turns: 25
  mode: bypassPermissions
```

> **Agent 输出 metadata 要求**：每个 Agent 必须在 JSON 输出中包含 `metadata.index_phase` 字段：
> ```json
> {
>   "metadata": {
>     "index_phase": "phase1",  // 运行时的 phase 状态
>     "rerun_count": 0          // re-run 次数
>   },
>   "findings": [...]
> }
> ```
> 此字段使 `should-rerun-agent` 脚本能判断是否有新数据可用。

#### 2.2 等待期间前置工作 + 流式处理

启动 Agent 后，编排器执行前置工作（不空等）：

1. **导出 indexer findings**（密钥/配置/CVE 检测结果）：

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" query --batch-dir security-scan-output/{audit_batch_id} --preset indexer-findings
```

2. **加载框架知识文件**（按技术栈）

3. **等待扫描 Agent 完成**：编排器通过检查 `security-scan-output/{audit_batch_id}/agents/` 目录下各 Agent 的 JSON 产物是否落盘来判断完成状态。

#### 2.3 续扫处理

对 `status: "partial"` 且有 `pendingSinks`/`pendingEndpoints` 的 Agent：
- vuln-scan：启动续扫实例（max_turns: 15），仅处理 `pendingSinks`
- logic-scan：启动续扫实例（max_turns: 12），仅处理 `pendingEndpoints`

#### 2.4 合并扫描结果

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/merge_findings.py" merge-scan --batch-dir security-scan-output/{audit_batch_id} --extra-agents indexer-findings,vuln-scan,logic-scan,red-team
```

#### 2.5 WebSearch 情报增强（Deep 模式专属）

> Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/orchestration.md > WebSearch 情报增强`（完整场景、预算控制和降级策略见该节）

跳过条件：无 `webSearchCandidate: true` 的 CVE 条目且无 `auditDimension: "C7.7"` 的条目。

---

## 阶段3: 验证差异

> 完整验证流程：Ref `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/verification.md`

本节仅列出三种模式在验证阶段的**策略差异**：

- **Fast**：**完全跳过独立阶段 3**。阶段 2 已在产出 finding 时内联完成代码存在性校验（`verificationStatus: inline-verified`）。`merge_findings.py` 自动走 `scan_mode == "fast"` 的 bypass 分支，直接使用 stage2 结果。置信度上限 90。
- **Light**：仅验证 Critical + High，编排器内联验证（代码存在性 + 基础防御检查），置信度上限 90
- **Deep**：验证全部 findings，5 层混合验证（脚本 3 层 + verifier Agent + 脚本评分 2 层），置信度上限 100

---

## 阶段4: 修复差异

| 维度 | Fast | Light | Deep |
|------|------|-------|------|
| 自动修复 | 同 Light | 受限（置信度上限 90，需满足门控条件） | 完整支持（confidence >= 90 可自动修复） |
| POC 生成 | **默认跳过**，`--with-poc` 才启用 | 执行 | 执行 |
| 报告生成输入 | `merged-scan.json`（fallback） | `merged-scan.json`（无 `finding-*.json`，`generate_report.py` 自动 fallback） | `finding-*.json` + `summary.json`（由 `merge-verify` 生成） |
| 修复 finding 来源 | 同 Light | `merged-scan.json`（`confidence >= 90`，跳过 `challengeVerdict` 检查） | `score-results.json` 或 `agents/verifier-*.json`（完整资格检查） |

---

## 错误处理

### Fast 模式

1. 基础探索失败 → 终止审计，提示用户重试
2. 编排器内联分析异常 → 基于已有 indexer findings 继续生成报告（同 Light 兜底）
3. 字段漂移 → `normalize_finding_schema` 自动兜底，不阻断流程

### Light 模式

1. 基础探索失败 -> 终止审计，提示用户重试
2. 编排器内联分析异常 -> 基于已有 indexer findings 继续生成报告

### Deep 模式

1. **indexer 失败**：终止审计，提示用户重试
2. **扫描 Agent 失败**：检查 `agents/{agent-name}.json` 是否有部分产物，有则纳入合并
3. **verifier Agent 失败**：跳过该分片，使用脚本验证结果
4. **确定性脚本失败（score/quality）**：脚本失败不阻断流程，仍可生成报告

产物完整性检查（Deep 模式）：

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/checkpoint_verify.py" verify-artifacts --batch-dir security-scan-output/{audit_batch_id} --agents vuln-scan,logic-scan,red-team
```

---

## 模式对比

| 维度 | Fast（极速扫描） | Light（快速扫描） | Deep（深度扫描） |
|------|-----------------|------------------|-----------------|
| 定位 | Light + 执行纪律（并行 Read / 禁 sleep / 禁后台 Agent） | 标准轻量扫描 | 全语义索引深度扫描 |
| 探索 | 基础探索（Grep/Glob 强制并行，瘦身版） | 基础探索（Grep/Glob） | 基础探索 + 编排器写入索引 DB + indexer 语义索引（indexer-步骤2 AST + indexer-步骤3 LSP） |
| tree-sitter 检测与安装 | 跳过 | 跳过 | 检测 + 自动安装 |
| LSP | 跳过 | 跳过 | 探活 + 语义追踪 |
| AST 精化 | 跳过 | 跳过 | indexer-步骤2 双引擎，结果持久化到 SQLite |
| 扫描 | 编排器内联 + 内联校验合并 | 编排器内联 | vuln-scan + logic-scan + red-team 并行 |
| 验证 | 阶段 3 完全跳过（阶段 2 内联已完成） | 轻量验证 | 脚本验证（pre-check → chain-verify → challenge）+ verifier Agent + 脚本评分（score → quality） |
| 后台 Agent | 本期禁用（避免 sleep 轮询） | 允许（diff 启 light-scan） | 必须（三 Agent 并行）|
| WebSearch 情报增强 | 无 | 无 | 有（CVE 实时验证 + 0day 情报感知） |
| 置信度上限 | 90 | 90 | 100 |
| 自动修复 | 同 Light（受限） | 受限 | 完整支持 |
| POC 生成 | 默认跳过（`--with-poc` 开启） | 执行 | 执行 |
| 预期耗时 | 3-12 分钟 | 5-58 分钟（抖动大） | 15-60 分钟 |
| 典型场景 | Git Hook / IDE 自动扫描 / CI 轻量门禁 | 日常快速自检 | 正式安全审计 / 发版前门禁 |
