---
description: Git diff 增量安全审计。支持 fast（极速扫描）、light（快速扫描）和 deep（深度扫描）三种模式。
argument-hint: "[--commit <hash|base..head>] [--scan-level fast|light|deep] [--with-poc] [--mode staged|unstaged|all] [--auto]"
allowed-tools: Bash, Read, Glob, Write, Grep, Task, Edit, MultiEdit, LSP, WebSearch, AskUserQuestion
---

# Git Diff 增量安全审计

> 所有面向用户的输出使用**简体中文**。禁止使用 emoji。JSON 字段名保持英文。

硬约束：
- 必须在 git 仓库中运行
- 文件列表来自 git diff，无需文件枚举
- 关联文件总数上限 = changedCodeFiles x 3

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

Fast 模式 = Light 的执行纪律化版本。检查逻辑完全复用 Light（LLM 做扫描和验证），但**必须遵守以下硬性约束**：

**A. 并行化约束（必须）**
- 阶段 1 的所有 Grep/Glob 调用（技术栈识别、Sink 粗定位、凭证检测）**必须在同一个 assistant message 内并行发起**（最多 4 个并行工具调用）。禁止按序调用。
- 阶段 2 若需要读多个变更文件查看 Sink 上下文，**必须在同一 assistant message 内发起所有 Read 调用**。禁止"Read A → 分析 → Read B"的串行模式。
- N 个变更文件 = 一批并行 Read，不是 N 轮串行 Read。

**B. 禁用轮询等待（必须）**
- ❌ 禁止使用 `sleep N && ls` 循环检查后台产物。
- ❌ 本期禁止启动任何后台 Agent（**不启动 light-scan Agent**，统一走编排器主窗口内联执行）。
- 原因：light-scan Agent 当前无独立定义文件，不同模型执行路径分叉导致 6x 耗时差异。Fast 用内联执行消除此问题。

**C. 扫描+验证合并（必须）**
- 阶段 2 产出 finding 时，**同时完成代码存在性校验**，打上 `verificationStatus: "inline-verified"` 或 `"inline-dismissed"` 标记。
- 阶段 3 完全跳过，不跑独立验证轮次。

**D. 字段 schema 约束（必须）**
- finding 必须使用以下规范字段名：
  - `riskType`（不是 `finding_type` / `findingType` / `vulnerability_type`）
  - `filePath`（不是 `file_path` / `file` / `path`）
  - `lineNumber`（不是 `line` / `lineno` / `line_number`）
  - `severity`（critical / high / medium / low）
  - `riskConfidence`（0-100 整数，Fast 模式上限 **90**）
  - `verificationStatus`（`inline-verified` / `inline-dismissed`）

**E. POC 生成（默认跳过）**
- Fast 模式默认 **不生成 POC**，仅当命令行显式传入 `--with-poc` 时才执行。

**F. 裁剪范围**
- 阶段 1 跳过：攻击面检测、防御基线（延迟到阶段 2 内联）。
- 阶段 3 完全跳过。
- 阶段 4 默认跳过 POC。
- 其他步骤（初始化、修复、报告、门禁、上报）与 Light 完全一致。

---

## 初始化

> Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/initialization.md`（仅在执行初始化时 Read，不提前加载）

按共享初始化流程依次执行 init-步骤0~5。

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

diff 模式差异：模式选择交互中的时间预估为 Light 约 1-3 分钟，Deep 约 5-15 分钟。

输出初始化摘要：
> Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/post-audit.md > 进度与摘要输出 > 阶段0: 初始化摘要`

---

## 阶段1: 探索

> 进度与摘要格式 Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/post-audit.md > 进度与摘要输出 > 阶段1: 探索`

### 探索阶段：初始化 + 获取变更

```bash
audit_batch_id="diff-${scanMode}-$(date +%Y%m%d%H%M%S)"
mkdir -p security-scan-output/$audit_batch_id/agents
```

初始化 SQLite 索引数据库：

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" init --batch-dir security-scan-output/$audit_batch_id --batch-id $audit_batch_id
```

查询长期记忆和项目结构缓存：

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" query --batch-dir security-scan-output/$audit_batch_id --preset memory-hints --project-path "$(pwd)"

python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/index_db.py" query --batch-dir security-scan-output/$audit_batch_id --preset cached-structure --project-path "$(pwd)"
```

记录 `structureCache`。diff 模式下结构缓存尤为有价值：有缓存时可直接定位变更文件涉及的入口点和已知 Sink，加速影响范围分析。

获取 git diff 文件列表：

```bash
git diff <base> <head> --name-only --diff-filter=ACMR    # commit range (base..head)
git diff <hash>^ <hash> --name-only --diff-filter=ACMR   # single commit
git diff HEAD --name-only --diff-filter=ACMR              # --mode all (default)
git diff --cached --name-only --diff-filter=ACMR           # --mode staged
git diff --name-only --diff-filter=ACMR                    # --mode unstaged
```

**`--commit` 参数解析规则**：
- `--commit abc1234..def5678` → commit 范围，使用 `git diff abc1234 def5678`
- `--commit abc1234~1..def5678` → 带 `~N` 的范围语法，同上
- `--commit abc1234` → 单个 commit，使用 `git diff abc1234^ abc1234`

**参数自动修正**（防御性校验）：
- `--mode staged` 但 `git diff --cached --name-only` 为空 → 自动修正为 `--commit HEAD`，并向用户说明原因（暂存区已清空，可能是 commit 后触发的被动扫描）
- `--mode all` 但 `git diff HEAD --name-only` 为空 → 自动修正为 `--commit HEAD`，并向用户说明原因

**空文件列表快速退出**：

> **`--auto` 模式**：空文件列表时生成"无变更"空报告并正常结束流程。创建 `batch-plan.json`（`total_files: 0`）、生成空的 `summary.json` 和 `gate-result.json`（`gateStatus: "pass"`），然后自动结束。不弹出任何提示。

正常模式下：

```
**未检测到任何代码变更**，无需执行安全扫描。
请确认：
  - 当前分支是否有未提交的修改（`git status` 查看）
  - 或指定具体 commit：`/security-scan:diff --commit <hash>`
```

**变更文件分类**：
- **代码文件**：`.java`、`.py`、`.go`、`.js`、`.ts` 等
- **依赖文件**：`pom.xml`、`package.json`、`go.mod` 等
- **配置文件**：`application.yml`、`.env` 等
- **运维文件**：`Dockerfile`、`docker-compose.yml` 等

输出任务摘要：

```
  **[1.1]** 变更获取完成
    变更文件：**{changedFiles}** 个（代码 **{codeFiles}**，配置 **{configFiles}**，依赖 **{depFiles}**，运维 **{opsFiles}**）
```

### 探索阶段：判断是否需要执行完整 diff 流水线

```
hasCodeChanges = true?
  -> true  -> 完整 diff 流水线
  -> false -> 纯配置/依赖变更快速通道（1.3c）
```

### 1.3a 基础探索（hasCodeChanges = true）

**【Fast 模式必须 - 约束 G】前置脚本化预筛**：仅 `scanMode == "fast"` 时执行。在 `audit_batch_id` 建立且 `index_db.py init` 完成后、**任何 LLM Grep 之前**，按顺序跑以下三条命令（同一 Bash 会话）。diff 模式下脚本**仍跑整仓**——以便捕获变更文件调用到的既有文件 Sink / 防御；阶段 2 再用 `changedCodeFiles` 求交集。Light / Deep 模式跳过此步骤，沿用既有探索流程。

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

编排器内 LLM 并行补充（单 message，符合约束 A）：
1. **技术栈识别**：Glob + Grep 确认框架
2. **变更文件 Sink 检测**：
   - Fast 模式：不再逐关键字 Grep，改为 `index_db.py query --preset sinks-top-per-file --limit 3` 拉取脚本预筛结果（每文件 Top-3 裁剪），与变更文件列表求交集
   - Light / Deep 模式：沿用既有逻辑，对变更代码文件 Grep Sink 模式
3. **凭证/密钥检测**：
   - Fast 模式：已由脚本写入 `indexer_findings` 表，LLM 仅补充框架特定密钥
   - Light / Deep 模式：沿用既有逻辑，对变更文件 Grep 密钥模式
4. **配置基线检查**：对变更配置文件检查不安全默认值

输出任务摘要：

```
  **[1.3a]** 基础探索完成
    技术栈：**{framework}**
    变更文件 Sink：**{sinkCount}** 个候选 Sink（脚本预筛 ∩ 变更文件）
    凭证检测：**{secretCount}** 个疑似硬编码密钥（脚本预筛）
    配置基线：**{configIssueCount}** 个不安全配置项
```

### 1.3b Deep 模式深度探索（hasCodeChanges = true）

> **仅 Deep 模式执行**。Light 模式跳过，直接进入阶段2。

先执行 1.3a 的基础探索，然后启动 indexer Agent，`[scope] = diff`：
> Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/scan-mode.md > 阶段1: 探索差异 > Deep 模式`

indexer 在 diff 模式下额外执行**影响范围扩展**：
> Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/diff-mode.md > 变更影响范围分析策略`

输出任务摘要：

```
  **[1.3b]** 深度探索完成（indexer Agent）
    语义索引已构建：`project-index.db`
    关联文件：**{relatedFiles}** 个（L1 **{a}**，L2 **{b}**，L3 **{c}**）
    端点：**{endpointCount}** 个 API 端点
    调用图：**{callGraphEdges}** 条调用关系
    防御映射：**{defenseCount}** 个防御点
```

### 1.3c 纯配置/依赖快速通道（hasCodeChanges = false）

```
  **[1.3c]** 探索完成：变更文件 **{n}** 个（均为配置/依赖文件，无代码变更）
  启用**配置快速通道**：仅执行密钥检测 + CVE 扫描 + 配置基线检查
```

编排器内联执行密钥检测 + CVE 扫描 + 配置基线，跳转到阶段4报告生成。

### 探索阶段：探索阶段摘要

输出探索阶段完成摘要（diff 模式）：
> Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/post-audit.md > 进度与摘要输出 > 阶段1: 探索 > 阶段完成摘要 > diff 模式`

### 探索阶段：生成扫描计划

生成 `batch-plan.json` 以保障审计元数据完整性（供后续 generate_report.py 使用）：

```bash
python3 << 'PYTHON_INLINE_SCRIPT'
import json
import os

batch_dir = "security-scan-output/${audit_batch_id}"

batch_plan = {
    "total_files": {changedFiles},
    "changed_files": {changedFiles},
    "code_files": {codeFiles},
    "config_files": {configFiles},
    "dep_files": {depFiles},
    "scan_mode": "${scanMode}",
    "framework": "{framework}",
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

---

## 阶段2: 扫描

> 进度与摘要格式 Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/post-audit.md > 进度与摘要输出 > 阶段2: 扫描`
> 扫描策略 Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/scan-mode.md > 阶段2: 扫描差异`（仅在执行扫描阶段时 Read，不提前加载）

按 scanMode 执行对应的扫描策略。diff 模式的 Deep Agent 提示词需附加变更上下文：
> Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/diff-mode.md > Agent 提示词注入模板`

- **Fast 模式**：**不启动任何 Agent**，编排器主窗口内联执行，严格遵守 **"Fast 模式硬性约束"** 章节（并行 Read + 扫描内联校验 + 字段 schema 规范 + **Source 可达性三判（文件内批量）**）。
  - 扫描前先 `index_db.py query --preset sinks-top-per-file --limit 3` 拉取每文件 Top-3 Sink 清单，与 `changedCodeFiles` 求交集；再 `--preset defenses-for-file --filter-file <path>` 为每个命中文件拉防御映射。**按 Sink 清单驱动 + 文件内批量三判**（详见 `workflows/scan-mode.md > 阶段 2 Fast`）：LLM 同一 message 内 Read 文件 + 对该文件所有 Sink 输出 verdict 数组。
  - 回滚说明：`SECURITY_SCAN_FAST_V2=0` **仅关闭 `merge_findings.py` 的 pre-check 兜底**；Top-K 裁剪和批量三判由 scan-mode.md 定义，LLM 执行时不读环境变量。完整回退需 `git revert` 本次 A+B 改动。
  - 置信度上限 90。产出 `agents/light-inline.json`（`sourceAgent: "light-inline"`）。
- **Light 模式**：启动 light-scan Agent（编排器动态生成 Task）。
- **Deep 模式**：三 Agent 并行（vuln-scan + logic-scan + red-team）。

> **Deep 模式关键**：并行启动 vuln-scan + logic-scan + red-team 三个 Agent Task 后，主窗口**不空转等待**——先执行前置工作（导出 indexer findings、加载知识文件），再检查各 Agent 产物是否落盘。详见 `workflows/scan-mode.md > Deep 模式 > 2.2 等待期间前置工作 + 流式处理`。

**漏洞链检测**（diff 模式尤为重要）：
> Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/diff-mode.md > 漏洞链检测重点`

---

## 阶段3: 验证

> 进度与摘要格式 Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/post-audit.md > 进度与摘要输出 > 阶段3: 验证`

按 scanMode 执行对应的验证策略。

> **完整流程** Read: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/verification.md`（仅在执行验证阶段时 Read，不提前加载）
>
> - **Fast 模式**：**完全跳过独立阶段 3**。阶段 2 已内联完成代码存在性校验（`verificationStatus: inline-verified`）。直接执行下方 Fast 合并步骤。
> - **Light 模式**：轻量验证，仅代码存在性校验（置信度上限 90）
> - **Deep 模式**：确定性脚本验证（Stage 1-3）→ verifier Agent 深度验证（Stage 4）→ 评分 + 质量评估（Stage 5）→ merge-verify 合并

### Fast 模式合并步骤（MANDATORY）

Fast 模式阶段 2 编排器内联扫描完成后，**必须**调用 merge 脚本将内联产物导入标准管线。不可跳过。

**步骤 3.1：合并 light-inline 产物**

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/merge_findings.py" merge-scan \
  --batch-dir security-scan-output/"$audit_batch_id" \
  --extra-agents light-inline
```

验证：`security-scan-output/{batch}/merged-scan.json` 已创建。

**步骤 3.2：执行 merge-verify（Fast bypass 模式）**

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/merge_findings.py" merge-verify \
  --batch-dir security-scan-output/"$audit_batch_id"
```

Fast 模式下 merge-verify 会自动检测 `batch-plan.json > scan_mode == "fast"` 并跳过 verifier 产物加载，复用 Light 的 bypass 路径，直接使用 stage2 结果生成 `finding-*.json` 和 `summary.json`。

### Light 模式验证步骤（MANDATORY）

light-scan Agent 完成后，**必须**调用 merge 脚本将 agent 产物导入标准管线。不可跳过此步骤，否则下游报告、上报、门禁、通知全部失效。

**步骤 3.1：合并 light-scan 产物**

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/merge_findings.py" merge-scan \
  --batch-dir security-scan-output/"$audit_batch_id" \
  --extra-agents light-scan
```

验证：`security-scan-output/{batch}/merged-scan.json` 已创建且 `totalFindings > 0`。

**步骤 3.2：执行 merge-verify（Light bypass 模式）**

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/merge_findings.py" merge-verify \
  --batch-dir security-scan-output/"$audit_batch_id"
```

Light 模式下 merge-verify 会自动检测 `batch-plan.json > scan_mode == "light"` 并跳过 verifier 产物加载，直接使用 stage2 结果生成 `finding-*.json` 和 `summary.json`。

---

## 阶段4: 修复

> 进度与摘要格式 Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/post-audit.md > 进度与摘要输出 > 阶段4: 修复`

### 修复阶段：修复方案生成

> Ref: `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/post-audit.md > 内联修复执行`

### 修复阶段：POC 生成 + 报告生成 + 记忆同步 + 门禁评估 + 门禁通知 + 摘要 + 用户交互

> 按 `${CODEBUDDY_PLUGIN_ROOT}/references/workflows/post-audit.md` 依次执行：POC 验证脚本生成 → 报告生成 → 长期记忆同步 → 门禁评估 → 门禁通知 → 审计摘要 → 用户交互。
> 以下步骤为**必须执行（MANDATORY）**，不可跳过。即使上游步骤失败或输出为空，下游步骤仍需尝试执行（best effort）。
> **Fast 模式例外**：**POC 验证脚本生成** 在 `scanMode == "fast"` 且 `batch-plan.json.options.withPoc != true` 时**必须跳过**，不视为违反 MANDATORY（Fast 模式默认不生成 POC 是设计意图）。具体判定逻辑见 `post-audit.md > POC 验证脚本生成`。
> **注意**：审计报告上报由 Stop Hook 自动完成（`report_upload_hook.py`），无需在编排中手动执行。

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

diff 模式额外降级策略：indexer 失败时，基于基础探索结果的变更文件列表仍可用，编排器内联执行轻量扫描作为降级。
