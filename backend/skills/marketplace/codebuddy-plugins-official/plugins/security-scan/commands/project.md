---
description: 全项目代码安全审计。支持 fast（极速扫描）、light（快速扫描）和 deep（深度扫描）三种模式，支持 --auto 无人值守自动化。
argument-hint: "[file_path...] [--scan-level fast|light|deep] [--with-poc] [--auto] [--include *.py,*.js] [--exclude node_modules,dist]"
allowed-tools: Bash, Read, Glob, Write, Grep, Task, Edit, MultiEdit, LSP, WebSearch, AskUserQuestion
---

# 全项目安全审计

> 所有面向用户的输出使用**简体中文**。禁止使用 emoji。JSON 字段名保持英文。

---

## 自动模式（--auto）

当指定 `--auto` 参数时，进入无人值守模式，跳过所有用户交互：

| 交互点 | 正常模式 | --auto 模式 |
|--------|---------|------------|
| 权限白名单确认（init-步骤1） | AskUserQuestion | 自动执行配置/更新 |
| 模式选择（init-步骤2） | AskUserQuestion | 使用 `--scan-level` 参数（默认 light） |
| 环境就绪确认（init-步骤5） | AskUserQuestion | 自动选择「跳过，继续扫描（降级模式）」 |
| 高风险未验证确认 | AskUserQuestion | 跳过，直接继续 |
| 修复交互 | AskUserQuestion | **跳过修复**，直接进入报告生成 |
| 下一步操作 | AskUserQuestion | 跳过，自动结束 |

`--auto` 模式下的完整流水线：
1. 初始化（跳过交互）→ 2. 探索 → 3. 扫描 → 4. 验证 → 5. 报告生成 → 6. 上报 → 7. 门禁评估 → 8. 门禁通知 → 自动结束

**安全红线**：`--auto` 模式**绝不**执行自动修复（不修改用户代码）。

---

## 编排器核心原则

> Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/contracts/orchestrator-contract.md`（仅在执行到编排调度时 Read，不提前加载）

---

## Fast 模式硬性约束（仅当 `scanMode == "fast"` 时生效）

Fast 模式 = Light 的执行纪律化版本。检查逻辑完全复用 Light（LLM 做扫描和验证），但**必须遵守以下硬性约束**，用以消除 Light 模式下观察到的真实耗时热点：

**A. 并行化约束（必须）**
- 阶段 1 的所有 Grep/Glob 调用（技术栈识别、Sink 粗定位、凭证检测）**必须在同一个 assistant message 内并行发起**（最多 4 个并行工具调用）。禁止按序调用。
- 阶段 2 若需要读多个文件查看 Sink 上下文，**必须在同一 assistant message 内发起所有 Read 调用**。禁止"Read A → 分析 → Read B"的串行模式。
- 50 个文件 = 一批并行 Read，不是 50 轮串行 Read。

**B. 禁用轮询等待（必须）**
- ❌ 禁止使用 `sleep N && ls` 循环检查后台产物。
- ❌ 本期禁止启动任何后台 Agent（不调用 Task 工具的 `run_in_background=true`，也不调用普通 Task）。
- ✅ Fast 模式统一走**编排器主窗口内联执行**（无论 project 还是 diff）。
- 若未来需要后台 Agent，必须使用 `Task` 工具的 `run_in_background=true` + `TaskOutput` 机制，禁止 sleep 轮询。

**C. 扫描+验证合并（必须）**
- 阶段 2 产出 finding 时，**同时完成代码存在性校验**（Read Sink 上下文时顺手确认行号/代码片段匹配）。
- 每条 finding 打上 `verificationStatus: "inline-verified"` 或 `"inline-dismissed"` 标记。
- 阶段 3 完全跳过，不跑独立验证轮次。

**D. 字段 schema 约束（必须）**
- finding 必须使用以下规范字段名（其他字段名虽有 `normalize_finding_schema` 兜底，但仍应正确输出以降低歧义）：
  - `riskType`（不是 `finding_type` / `findingType` / `vulnerability_type`）
  - `filePath`（不是 `file_path` / `file` / `path`）
  - `lineNumber`（不是 `line` / `lineno` / `line_number`）
  - `severity`（critical / high / medium / low；不是 `riskLevel` / `level`）
  - `riskConfidence`（0-100 整数，Fast 模式上限 **90**）
  - `verificationStatus`（`inline-verified` / `inline-dismissed`）

**E. POC 生成（默认跳过）**
- Fast 模式默认 **不生成 POC**，阶段 4 跳过 POC 生成步骤。
- 仅当命令行显式传入 `--with-poc` 时，才执行 POC 生成（参见阶段 4）。

**F. 裁剪范围**
- 阶段 1 跳过：攻击面检测（entries/attack-surface）、防御基线（grep-defenses，延迟到阶段 2 内联完成）。
- 阶段 3 完全跳过。
- 阶段 4 默认跳过 POC。
- 所有其他步骤（初始化、修复、报告、门禁、上报）与 Light 完全一致。

---


## 初始化

> Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/initialization.md`（仅在执行初始化时 Read，不提前加载）

按共享初始化流程依次执行 init-步骤0~5（**插件根目录解析**、权限、模式选择、tree-sitter、LSP、环境确认）。

**参数解析约定**：
- `--scan-level fast|light|deep`：解析后记录为编排器变量 `scanMode`，未指定时通过 init-步骤2 交互选择
- `--with-poc`：仅影响 **Fast 模式** 的 POC 生成行为（Fast 默认跳过 POC，传入 `--with-poc` 才启用）。Light / Deep 模式的 POC 生成行为与既有流程一致，**不受此 flag 影响**

> **init-步骤0 必须最先执行**，且必须使用以下命令解析插件根目录，**禁止**用 `find`、`ls` 等方式手动搜索：

```bash
python3 -c "
import json, sys; from pathlib import Path
try:
  home = Path.home()
  s = json.loads((home/'.codebuddy'/'settings.json').read_text())
  km = json.loads((home/'.codebuddy'/'plugins'/'known_marketplaces.json').read_text())
  mid = [k.split('@',1)[1] for k,v in s.get('enabledPlugins',{}).items() if v and k.startswith('security-scan@')]
  if not mid: raise KeyError('not in enabledPlugins')
  loc = km[mid[0]]['installLocation']
  src = next((p['source'] for p in km[mid[0]].get('manifest',{}).get('plugins',[]) if p.get('name')=='security-scan'), './plugins/security-scan')
  root = str((Path(loc)/src).resolve())
  assert (Path(root)/'.codebuddy-plugin'/'plugin.json').exists()
  print(root)
except Exception as e:
  print('FALLBACK:' + str(e), file=sys.stderr); sys.exit(1)
"
```

将输出记录为 `CODEBUDDY_PLUGIN_ROOT`。后续所有 Bash 调用插件脚本前必须 `export CODEBUDDY_PLUGIN_ROOT="<路径>"`。
若 exit 1，Read `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/initialization.md > 方法二` 执行 Glob 兜底。

project 模式无额外差异，完整按 initialization.md 执行。

输出初始化摘要：
> Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/post-audit.md > 进度与摘要输出 > 阶段0: 初始化摘要`

---

## 阶段1: 探索

> 进度与摘要格式 Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/post-audit.md > 进度与摘要输出 > 阶段1: 探索`

### 探索阶段：初始化工作目录和检测历史扫描记忆

```bash
audit_batch_id="project-${scanMode}-$(date +%Y%m%d%H%M%S)"
mkdir -p security-scan-output/$audit_batch_id/agents
```

初始化 SQLite 索引数据库 + 长期记忆库：

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" init --batch-dir security-scan-output/$audit_batch_id --batch-id $audit_batch_id
```

查询长期记忆（如有历史扫描）：

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" query --batch-dir security-scan-output/$audit_batch_id --preset memory-hints --project-path "$(pwd)"
```

查询项目结构缓存（如有历史扫描的结构快照）：

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" query --batch-dir security-scan-output/$audit_batch_id --preset cached-structure --project-path "$(pwd)"
```

记录 `structureCache`（`cached-structure` 返回的 JSON）。

**缓存复用规则**：
- `structureCache.cached == true` → indexer-1.2 改为增量模式：通过 `content_hash` 比对识别新增/变更/删除的文件，对变更文件重新执行 Sink + 入口点 Grep，技术栈通过标记文件 Glob 校验后决定复用或重检
- `structureCache.cached == false` → 正常执行 indexer-1.2 全量枚举

输出任务摘要：

```
  **[1.1]** 工作目录已初始化：`security-scan-output/{audit_batch_id}`
  {hasMemoryHints ? "历史扫描记忆已加载，共 **" + memoryCount + "** 条提示" : "无历史扫描记忆"}
  {structureCache.cached ? "项目结构缓存命中：**" + structureCache.fileCount + "** 个文件，**" + structureCache.entryPointCount + "** 个入口点（将增量更新）" : "无结构缓存，将执行全量枚举"}
```

### 探索阶段：基础探索

> 基础探索逻辑的权威定义：`agents/indexer.md > indexer-步骤1`。
> Light 模式由编排器内联执行 indexer-步骤1 逻辑，Deep 模式由 indexer Agent 完整执行（编排器仍先执行基础探索，indexer 在此基础上构建完整语义索引）。

在编排器内按 `agents/indexer.md > indexer-步骤1` 的流程快速完成基础枚举：

- `structureCache.cached == true` → 增量模式（详见 `agents/indexer.md > indexer-1.0a 缓存加速`）
- `structureCache.cached == false` → 全量枚举

基础探索包含：文件枚举 + 技术栈识别、入口点粗定位、Sink 粗定位、凭证/密钥检测、配置基线、CVE 扫描。

**【Fast 模式必须 - 约束 G】前置脚本化预筛**：仅 `scanMode == "fast"` 时执行。在 `audit_batch_id` 建立且 `index_db.py init` 完成后、**任何 LLM Grep 之前**，按顺序跑以下三条命令，把 Sink / 防御 / 凭证确定性写入 `project-index.db`。后续 LLM 从"按 Sink 清单扫描"替代"全文件翻页"。Light / Deep 模式跳过此步骤，沿用既有探索流程。

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

脚本已内置测试/构建产物过滤；结果进入 `sinks` / `defenses` / `indexer_findings` 表。Fast 模式下 LLM Grep 仅用于补充脚本未覆盖的框架特定模式；Light / Deep 模式沿用既有探索流程，本章节预筛不影响其行为。

输出任务摘要：

```
  **[1.2]** 基础探索完成
    文件枚举：**{fileCount}** 个源文件，**{totalLines}** 行代码
    技术栈：**{framework}**
    入口点文件：**{entryPointFiles}** 个
    Sink 粗定位：**{sinkCount}** 个候选 Sink
    凭证检测：**{secretCount}** 个疑似硬编码密钥
    配置基线：**{configIssueCount}** 个不安全配置项
    依赖安全：**{cveCount}** 个已知 CVE
```

### 探索阶段：Deep 模式深度探索

> **仅 Deep 模式执行**。Light 模式跳过，直接进入阶段2。
> Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/scan-mode.md > 阶段1: 探索差异 > Deep 模式`

启动 indexer Agent 构建完整语义索引。

输出任务摘要：

```
  **[1.3]** 深度探索完成（indexer Agent）
    语义索引已构建：`project-index.db`
    端点：**{endpointCount}** 个 API 端点
    调用图：**{callGraphEdges}** 条调用关系
    防御映射：**{defenseCount}** 个防御点
```

### 探索阶段：生成扫描计划

生成 `batch-plan.json` 以保障扫描元数据完整性（供后续 merge_findings.py 和 generate_report.py 使用）：

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" query --batch-dir security-scan-output/$audit_batch_id --preset summary > /tmp/summary_out.json 2>/dev/null

# 提取必要的扫描数据并生成 batch-plan.json
python3 << 'PYTHON_INLINE_SCRIPT'
import json
import os

batch_dir = "security-scan-output/${audit_batch_id}"
summary_out = json.loads(open("/tmp/summary_out.json").read())

# 计算源文件总数（从索引数据库或环保存的fileCount）
file_count = summary_out.get("fileCount", 0)
if file_count == 0:
    # Fallback: 从 git ls-files 快速统计
    import subprocess
    try:
        result = subprocess.run(
            "git ls-files --cached --others --exclude-standard | grep -E '\\.(java|kt|kts|py|go|js|ts|jsx|tsx|php|rb|cs|cpp|c|rs|swift|vue)$' | wc -l",
            shell=True, capture_output=True, text=True
        )
        file_count = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
    except:
        file_count = 0

batch_plan = {
    "total_files": file_count,
    "scan_mode": "${scanMode}",
    "framework": summary_out.get("framework", "unknown"),
    "entry_points": summary_out.get("entryPointCount", 0),
    "scan_timestamp": "$(date -Iseconds)",
    "options": {
        # withPoc 必须是 shell 小写字面量 true/false，由编排器在解析 --with-poc 时设置
        "withPoc": ${withPoc:-false}
    }
}

batch_plan_file = os.path.join(batch_dir, "batch-plan.json")
with open(batch_plan_file, 'w') as f:
    json.dump(batch_plan, f, ensure_ascii=False, indent=2)

print(f"已生成 {batch_plan_file}")
PYTHON_INLINE_SCRIPT
```

### 探索阶段：探索阶段摘要

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" query --batch-dir security-scan-output/$audit_batch_id --preset summary
```

**条件规则加载**：按技术栈加载框架安全知识。
> Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/orchestration.md > 条件规则加载`

输出探索阶段完成摘要（project 模式）：
> Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/post-audit.md > 进度与摘要输出 > 阶段1: 探索 > 阶段完成摘要 > project 模式`

---

## 阶段2: 扫描

> 进度与摘要格式 Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/post-audit.md > 进度与摘要输出 > 阶段2: 扫描`
> 扫描策略 Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/scan-mode.md > 阶段2: 扫描差异`（仅在执行扫描阶段时 Read，不提前加载）

按 scanMode 执行对应的扫描策略：
- **Fast 模式**：编排器内联（与 Light 相同路径），但受 **"Fast 模式硬性约束"** 章节约束（并行 Read + 扫描内联校验 + 字段 schema 规范 + **Source 可达性三判（文件内批量）**）。
  - 扫描前先通过 `index_db.py query --preset sinks-top-per-file --limit 3` 拉取每文件 Top-3 Sink 清单（按 severity_level ASC，优先 S1/S2）；对每个涉及文件用 `--preset defenses-for-file --filter-file <path>` 拉防御映射。**按 Sink 清单驱动 + 文件内批量三判**（详见 `workflows/scan-mode.md > 阶段 2 Fast`）：LLM 同一 message 内 Read 文件 + 对该文件所有 Sink 输出 verdict 数组。
  - 回滚说明：`SECURITY_SCAN_FAST_V2=0` **仅关闭 `merge_findings.py` 的 pre-check 兜底**；Top-K 裁剪和批量三判由 scan-mode.md 定义，LLM 执行时不读环境变量。完整回退需 `git revert` 本次 A+B 改动。
  - 置信度上限 90。
- **Light 模式**：编排器内联扫描，置信度上限 90。
- **Deep 模式**：三 Agent 并行（vuln-scan + logic-scan + red-team）。

> **Deep 模式关键**：并行启动 vuln-scan + logic-scan + red-team 三个 Agent。启动后主窗口**不空转等待**——先执行前置工作（导出 indexer findings、加载知识文件），再检查各 Agent 产物是否落盘。详见 `workflows/scan-mode.md > Deep 模式 > 2.2 等待期间前置工作 + 流式处理`。

---

## 阶段3: 验证

> 进度与摘要格式 Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/post-audit.md > 进度与摘要输出 > 阶段3: 验证`

按 scanMode 执行对应的验证策略。

> **完整流程** Read: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/verification.md`（仅在执行验证阶段时 Read，不提前加载）
>
> - **Fast 模式**：**完全跳过独立阶段 3**。阶段 2 已内联完成代码存在性校验（`verificationStatus: inline-verified`），置信度上限 90。
> - **Light 模式**：轻量验证，仅代码存在性校验（置信度上限 90）
> - **Deep 模式**：确定性脚本验证（Stage 1-3）→ verifier Agent 深度验证（Stage 4）→ 评分 + 质量评估（Stage 5）→ merge-verify 合并

---

## 阶段4: 修复

> 进度与摘要格式 Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/post-audit.md > 进度与摘要输出 > 阶段4: 修复`

### 修复阶段：修复方案生成

> Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/post-audit.md > 内联修复执行`

### 修复阶段：POC 生成 + 报告生成 + 记忆同步 + 门禁评估 + 门禁通知 + 摘要 + 用户交互

> 按 `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/post-audit.md` 依次执行：POC 验证脚本生成 → 报告生成 → 长期记忆同步 → 门禁评估 → 门禁通知 → 审计摘要 → 用户交互。
> **注意**：审计报告上报由 Stop Hook 自动完成（`report_upload_hook.py`），无需在编排中手动执行。
> 以下步骤为**必须执行（MANDATORY）**，不可跳过。
> **Fast 模式例外**：**POC 验证脚本生成** 在 `scanMode == "fast"` 且 `batch-plan.json.options.withPoc != true` 时**必须跳过**，不视为违反 MANDATORY（Fast 模式默认不生成 POC 是设计意图）。具体判定逻辑见 `post-audit.md > POC 验证脚本生成`。

**MANDATORY-1：报告生成**

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/generate_report.py" \
  --input security-scan-output/"$audit_batch_id" \
  --audit-batch-id "$audit_batch_id" \
  --format html \
  --output security-scan-output/"$audit_batch_id"/report.html
```

**MANDATORY-2：门禁评估**

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/gate_evaluator.py" evaluate \
  --batch-dir security-scan-output/"$audit_batch_id"
```

评估失败不阻塞流程。验证 `gate-result.json` 已创建。

**MANDATORY-3：门禁通知**

`--auto` 模式下 `notifySource="hook-auto"`，否则 `notifySource="scan"`。

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/gate_reminder.py" notify \
  --batch-dir security-scan-output/"$audit_batch_id" \
  --source "$notifySource"
```

通知失败不阻塞流程。未配置通知渠道时自动跳过。

**`--auto` 模式**：MANDATORY-1/2/3 执行完成后，输出审计摘要，**跳过修复交互和下一步操作选择**，自动结束。

正常模式下：用户选择修复时，按 `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/post-audit.md > 内联修复执行` 执行。
用户选择预览时，使用 `open` 命令打开 HTML 报告。

---

## 错误处理

> Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/scan-mode.md > 错误处理`（仅在遇到错误时 Read，不提前加载）
