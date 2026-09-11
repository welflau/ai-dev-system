# Memory MCP Server

给 AI agent 使用的项目记忆服务器。Markdown 是真源，SQLite 是索引，MCP 默认只暴露两个工具：`memory_read` 和 `memory_write`。

高级维护能力走 CLI：重建、诊断、备份、压缩、快照、谱系、治理、LLM enhance。

---

## 1. 项目说明

- **定位**：跨会话项目记忆。用于保存事实、决策、观察、任务节点、错误摘要、交接信息。
- **真源**：`memory-bank/**/*.md`。SQLite、compiled 文档、runtime digest、cache 都是可重建派生数据。
- **目录**
  - `memory-bank/`：项目记忆，建议入版本管理。
  - `.ai-context/`：当前任务热上下文，不入版本管理。
  - `.ai-memory/`：配置、索引、备份、审计、缓存，不入版本管理；`.ai-memory/config.json` 可入版本管理。
- **工具表面**：普通 agent 只使用 `memory_read` / `memory_write`。
- **多人模式**：始终开启。`activeContext` 按用户分文件，`teamContext` / `progress` / `techContext` / `systemPatterns` 只沉淀共享或发布记录。
- **维护策略**：guard 超限、总预算超限、索引过期、事件膨胀、冷数据 retention 都由 auto-maintenance 处理。
- **测试状态**：`tests/memory_server` 当前通过 `703 passed`。

实现代码在 `servers/memory_server/`。

---

## 2. 安装方式

约定：

- `<MemoryRoot>`：本目录，即包含本 README 的 Memory MCP 目录。
- `<RepoRoot>`：目标项目根目录。

`<RepoRoot>` 解析顺序：`-RepoRoot` 参数 → `MEMORY_REPO_ROOT` → 向上查找 `.git` / `.svn` / `.hg` / `*.uproject` / `*.code-workspace` / `*.sln` → 兜底到 `<MemoryRoot>/../..`。

### 2.1 一键 bootstrap（推荐）

```powershell
powershell -ExecutionPolicy Bypass -File <MemoryRoot>/scripts/bootstrap.ps1
```

自动完成：

- 创建 venv。
- 安装依赖。
- 设置稳定 user id。
- 写入 `<MemoryRoot>/user_config.local.json` 的 `user_name`。
- 合并 `<RepoRoot>/.vscode/mcp.json` 的 `project-memory-mcp` 配置。
- 执行一次 health 检查。

自动检测项目根失败时显式传入：

```powershell
powershell -ExecutionPolicy Bypass -File <MemoryRoot>/scripts/bootstrap.ps1 -RepoRoot <RepoRoot>
```

### 2.1.1 仅部署 venv + 依赖（`deploy.bat` / `deploy.ps1`）

只安装 Python 环境，不改 VS Code 配置：

```bat
cd <MemoryRoot>
deploy.bat
deploy.bat -ForceRecreate
deploy.bat -PythonExe "C:\Py311\python.exe"
deploy.bat -InstallDevDeps
deploy.bat -RegisterVSCode
deploy.bat -SkipInstall
deploy.bat -NoVerify
```

PowerShell 版本参数一致：

```powershell
powershell -ExecutionPolicy Bypass -File <MemoryRoot>/deploy.ps1
```

Python 版本要求与 `vendor/` wheel 标签一致，当前是 cp311。解释器查找顺序：

1. `-PythonExe`
2. UE 自带 Python
3. `py -3.11`
4. PATH 中的 `python` / `python3`

### 2.2 手动注册到非 VS Code 客户端

Codex 示例：`%USERPROFILE%\.codex\config.toml`

```toml
[mcp_servers.project-memory-mcp]
command = '<RepoRoot>/<MemoryRelToRepo>/.venv/Scripts/python.exe'
args = ['-m', 'servers.memory_server', '--root', '<RepoRoot>']
env = { PYTHONPATH = '<RepoRoot>/<MemoryRelToRepo>', PYTHONUTF8 = '1' }
```

修改 MCP 配置后重启客户端或新开会话。

### 2.3 验证

```powershell
# 启动 MCP server
powershell -ExecutionPolicy Bypass -File <MemoryRoot>/scripts/run_memory_server.ps1

# 跑全部测试
powershell -ExecutionPolicy Bypass -File <MemoryRoot>/scripts/run_memory_all_tests.ps1

# 检查当前记忆状态
$env:PYTHONPATH = '<MemoryRoot>'
<MemoryRoot>/.venv/Scripts/python.exe -m servers.memory_server.cli --root <RepoRoot> health --pretty
```

### 2.4 Agent 规则配置（团队接入必做）

目标仓库的 agent 规则文件需要固定 Memory MCP 使用方式，例如 `AGENTS.md`、`.github/copilot-instructions.md`、`.cursorrules`。规则内容以 [3.2 推荐工作流](#32-推荐工作流) 的可复制提示词为准，不要在多个文档维护不同版本。

### 2.5 Git/SVN ignore（团队接入必做）

```gitignore
# === Memory MCP ===
.ai-memory/
.ai-context/
memory-bank/compiled/
memory-bank/.tmp*
!.ai-memory/config.json
.vscode/settings.json
!.vscode/mcp.json
MCP/Memory/user_config.local.json
```

SVN 团队不要对 `teamContext.md` / `progress.md` / `techContext.md` / `systemPatterns.md` / `projectbrief.md` 加锁。服务端对共享文档使用 append-only 或 generated rebuild 策略。

---

## 3. 使用方式

### 3.1 MCP 工具表面

| 工具 | 用途 |
|---|---|
| `memory_read` | 读取任务上下文、读取文件、搜索、检索上下文、获取重要记忆、获取最新记忆、读取 runtime digest |
| `memory_write` | 写入 raw record、observation、checkpoint |

`memory_read(operation="task_context")` 是会话入口，返回 `context_token`、`task_id`、`task_run_id`、`active_context`、`current_task`。`current_task` 来自 `.ai-context/current-task/{user}/{context_token}.md`，不是全局单文件。`memory_write` 只写结构化记忆，不做文件维护。guard、health、backup、compact、rebuild、snapshot、lineage、conflict、LLM enhance 等管理能力走 CLI。

读侧 MCP 响应默认保持紧凑：`task_context` 会去掉派生文档生成头和文件系统 `meta`；`retrieve_context` / `important_memories` / `latest_memories` / `search_records` 只返回继续任务所需的记忆正文、摘要和最小元数据。预算报告、召回 pipeline、prefilter stats、候选丢弃原因、完整 provenance 等诊断字段仅在 `include_diagnostics=true` 时返回。向量 / embedding 类 payload 即使在诊断模式也不会透出。

`latest_memories` 用于“当前项目中当前用户最新记忆”场景：显式 `user` 优先；否则使用 `context_token` 绑定的用户；再否则使用当前配置用户。返回按 `occurred_at` / `valid_from` / `updated_at` / `created_at` 倒序排列的结构化记录。默认可见范围包含当前用户的 `personal` / `session` / `user_private` 记录，以及项目共享记录；若只想看本人私有记录，传 `include_scopes=["personal","session","user_private"]`。如果记录的 `author` 是 agent 名但带有 `task_id`，服务端会从 task context 反查该 task 是否属于当前用户。无法可靠归属的孤立 agent-authored private 记录不会默认归入当前用户。

### 3.2 推荐工作流

1. **开始前取上下文**：调用 `memory_read(operation="task_context")`，保存 `context_token`。
2. **执行中按需读取**：需要项目背景、历史决策、验证结果时，用同一个 `context_token` 调 `retrieve_context`、`important_memories`、`latest_memories` 或 `search_records`。
3. **结束后写结果**：用 `memory_write(operation="record")` 写一条结构化总结；任务节点再写 `checkpoint`。
4. **管理动作走 CLI**：不要通过普通 MCP 写文件或维护派生文档。

### 3.2.A LLM 辅助 metadata 对齐（opt-in，§15.2-B）

为了在 agent 习惯性传入业务领域 tag（如 `ljc` / `wall_prefab`）时仍能把记忆落地，`memory_write(operation="record")` 与 `memory_read(operation="task_context")` 各暴露一个 **opt-in** 参数，默认关闭，启用且 LLM 已配置时生效，LLM 不可用时降级为原有行为且永远不静默改写。

- `memory_write(operation="record", llm_normalize_tags=True, ...)`：仅当请求 `tags` 含有不在受控词表中的值时触发。服务端会调用 `classify_record` 拿到合规 tag 建议，将 `requested ∩ allowed` 与 LLM 建议合并写入；被拒绝的业务词拼成 `tag1.tag2` 形态写到 `system_area`（仅当调用方未显式提供 `system_area` 时）。写入成功后返回字段：
  - `metadata_suggestion`：`{status: "ok"|"llm_unavailable"|"llm_failed"|"skipped", applied, requested_tags, accepted_tags, rejected_tags, final_tags, suggested_tags, suggested_record_kind, suggested_scope, suggested_system_area, confidence, rationale, model, message}`。
  - `warnings`：当且仅当真正发生归一化（`status == "ok"` 且存在 `rejected_tags`）时追加一条 `{code: "metadata_normalized_by_llm", from_tags, to_tags, rejected_tags, system_area, rationale}`。
  - LLM 不可用 / 调用失败时不改写 args，返回原 `invalid_input`，并附带 `metadata_suggestion` 帮调用方诊断。
- `memory_read(operation="task_context", llm_suggest_metadata=True, user_goal=..., active_files=[...])`：在原返回结构上额外追加 `suggested_metadata`（与上面同构），便于 agent 在动手前预先对齐 `record_kind` 与 tag。

设计要点：保持两工具 MCP 表面不变；不引入 `memory_enhance`；LLM 永远只是“建议器”，最终 tag 仍由服务端 schema 校验保证 ⊆ `tag_schema.allowed_tags`。

无 LLM 或未启用 `llm_normalize_tags` 时，调用方必须自行只传受控 tag；未知业务词不会被静默改写，会按原 schema 校验返回 `invalid_input`。当前项目可用 tag 由 `.ai-memory/config.json` 的 `tag_schema.allowed_tags` 配置，内置默认值由 `servers/memory_server/memory_config.py` 的 `DEFAULT_ALLOWED_TAGS` 提供。默认完整词表为：

当 `memory_write(operation="record")` 因未知 tag 被拒绝时，`invalid_input` 响应会附带 `invalid_field="tags"`、`rejected_tags`、`allowed_tags`、`tag_schema_version` 与 `hint`，便于 agent 直接重试，不必再翻 README 或配置文件。

```text
archive_candidate
asset_pipeline
build
handoff_ready
high_value
material
mcp
needs_validation
skill_possible
texture
ui
validation
workflow
```

业务领域、资产名、模块名、玩法名等非词表信息不要塞进 `tags`；优先写入 `system_area`、`asset_paths`、`module_names` 或正文。例如 `ljc` / `wall_prefab` 这类业务词应进入 `system_area="ljc.wall_prefab"` 或正文说明，`tags` 只保留 `asset_pipeline`、`material`、`workflow` 等受控分类。

给 agent 的保守规则：**不会选 tag 时直接省略 `tags`，不要发明 tag**。`tags` 只是受控分类，不是关键词检索字段；业务关键词放正文或 `system_area`。常用合法组合：

| 场景 | `record_kind` | 推荐 `tags` |
|---|---|---|
| 普通实现交接 / 任务完成总结 | `handoff` | `["handoff_ready", "high_value"]` |
| 架构 / 技术决策 | `decision` | `["high_value"]` |
| 测试 / 验证结果 | `validation_result` | `["validation"]` |
| 可复用流程 | `procedure` | `["workflow", "high_value"]` |
| 构建 / 工具链事实 | `note` 或 `decision` | `["build"]` |
| MCP / Memory 系统自身变更 | `handoff` / `decision` / `procedure` | `["mcp", "high_value"]` |
| 资产 / 材质 / UI 相关事实 | `note` | 从 `["asset_pipeline", "material", "texture", "ui"]` 中只选匹配项 |
| 仍需验证的问题 / 事故根因 | `incident` | `["needs_validation"]` |

### 3.2.B 失效 `context_token` 的正文抢救

`memory_write(operation="record"|"observation")` 如果收到失效 `context_token` 但正文非空，会先尝试从同一 user / workspace / agent 的任务上下文中按 `system_area`、正文关键词、active files、任务目标、最近活跃时间推断任务线：

- 高置信匹配（当前阈值 0.85）：自动重绑到推断出的 `context_token`，返回 `context_recovery.mode="rebound"` 与 `warnings[].code="context_token_invalid_rebound"`。
- 置信不足或无候选：正文仍写入 `task_id="recovered_invalid_context"` 的 raw record/observation，返回 `context_recovery.mode="orphan"` 与 `warnings[].code="context_token_invalid_recovered"`；原 token 会写入 `source_refs` 便于审计。
- 空正文或 `checkpoint`：继续返回 `invalid_context_token`，因为没有可抢救内容。

恢复写入的任务归属是推断结果，不应当作强身份事实；调用方应检查 `context_recovery`，必要时重新调用 `memory_read(operation="task_context")` 获取当前 token 后补写更精确记录。

`checkpoint` 的主语义是阶段触发，不是正文存储。若调用方误把 `content_markdown` / `content` 放进 `checkpoint`，服务端会先把正文保存为一条 structured record，再返回 warning 提醒下次应先 `record` 再 `checkpoint`；这样重要记忆不会因为误用而丢失。

可复制到 agent 规则的提示词：

```markdown
Before any development task, call `memory_read(operation="task_context", user_goal=<current request>, agent_id=<agent name>, active_files=<relevant files>)`, keep the returned `context_token`, and reuse it for every task-scoped memory read or write; during the task, read memory only when project background, prior decisions, root causes, or validation results are needed; before finishing, write one structured summary with `memory_write(operation="record", context_token=...)` covering outcome, changed files, validation, and remaining risk, then send `memory_write(operation="checkpoint", task_phase="task_done", context_token=...)` without a body; choose `record_kind` by meaning: `decision` for architecture or technical decisions, `handoff` or `note` for implementation handoff, `validation_result` for test or verification results, `incident` for bug/root-cause notes, and `procedure` for reusable workflow; prefer the default personal scope unless the caller explicitly needs a shared raw record, because high-signal personal decisions/handoffs/procedures can be auto-settled into derived `project_shared` summaries; tags are optional, so omit `tags` when unsure instead of inventing labels; when tags are useful, use only `.ai-memory/config.json` `tag_schema.allowed_tags` (default full set: `archive_candidate`, `asset_pipeline`, `build`, `handoff_ready`, `high_value`, `material`, `mcp`, `needs_validation`, `skill_possible`, `texture`, `ui`, `validation`, `workflow`); common safe choices are implementation handoff `record_kind="handoff", tags=["handoff_ready", "high_value"]`, decision `record_kind="decision", tags=["high_value"]`, validation `record_kind="validation_result", tags=["validation"]`, workflow/procedure `record_kind="procedure", tags=["workflow", "high_value"]`, build/tooling `tags=["build"]`, and MCP/Memory work `tags=["mcp", "high_value"]`; put business-domain words, asset names, module names, and feature names in `system_area`, typed metadata fields, or the record body instead of `tags`; if an LLM is configured and the tool schema exposes it, `llm_normalize_tags=True` may be used as an opt-in safety net for accidental non-vocabulary tags, but do not depend on it for normal writes; never store secrets, credentials, tokens, or private user data; never edit `activeContext/{user}.md`, `teamContext.md`, `progress.md`, `techContext.md`, or `systemPatterns.md` directly; use the CLI for administrative work.
```

### 3.3 派生文档与自动维护

### 3.3.1 Raw Record Packing

默认按日期 pack 写 raw record。即使旧项目的 `.ai-memory/config.json` 没有 `record_packing` 段，结构化写入也会按目标目录追加到日期 pack 文件。没有任务信号时，personal 记录仍写入用户每日 pack，例如 `memory-bank/people/alice/packs/20260512-001.md`；带 `task_id` 或 `branch` 时，personal 记录按任务/分支分桶，例如 `memory-bank/people/alice/packs/task-123/20260512-001.md`。shared 记录按 `author + task_id/branch` 分桶，例如 `memory-bank/shared/packs/alice/task-123/20260512-001.md`。

这个策略用于平衡多人/多 agent 冲突和碎片数量：不同任务不会争抢同一个用户每日 pack；同一任务内的多个写入仍合并到同一个日期 pack，避免按 agent run 或单条 record 生成大量碎片文件。每条记录仍保留独立 Front Matter 和 `id`，读取、`search_records`、key-doc rebuild、lineage/governance 会把 pack 内条目展开为逻辑记录。

配置示例：

```json
{
  "record_packing": {
    "max_record_chars": 2000,
    "max_pack_chars": 64000,
    "archive_after_days": 90,
    "archive_pack_max_chars": 1048576,
    "max_active_pack_files": 500,
    "max_single_record_files": 2000,
    "max_archive_pack_files": 2000
  }
}
```

`max_record_chars` 是诊断/调参参考值，不再决定是否打包。写入只受 `max_pack_chars` 限制；当前 pack 超过 `max_pack_chars` 时滚动到 `YYYYMMDD-002.md`。单条记录本身超过 `max_pack_chars` 会被拒绝并返回诊断错误，避免重新生成无限增长的独立 record 文件。

长期维护：

```powershell
# 预览：把历史单条小记录合并到日期 pack
python -m servers.memory_server.cli pack-existing-records

# 执行迁移
python -m servers.memory_server.cli pack-existing-records --apply

# 预览：把超过 archive_after_days 的日期 pack 合并到 1 MiB 归档 pack
python -m servers.memory_server.cli compact-record-packs

# 执行归档合并
python -m servers.memory_server.cli compact-record-packs --apply

# 查看 / 清空异步关键文档重建队列
python -m servers.memory_server.cli key-doc-jobs
python -m servers.memory_server.cli key-doc-jobs --drain --max-jobs 5
```

归档 pack 写在 `memory-bank/archive/record-packs/YYYYMM-001.md`，仍属于 `memory-bank` 真源，`search_records`、runtime digest、key-doc rebuild 仍能读取；只是物理文件数量从“每天/每用户/每目录”继续合并到“每月若干个 1 MiB 文件”。

关键文档是派生视图：

- `memory-bank/activeContext/{user}.md`
- `memory-bank/teamContext.md`
- `memory-bank/progress.md`
- `memory-bank/techContext.md`
- `memory-bank/systemPatterns.md`

它们由 raw record、snapshot、observation 重建。人工编辑会在 rebuild 前归档到 `memory-bank/archive/manual-edits/`。

`activeContext` 是 user-scoped 暖上下文：

- 写 `memory-bank/activeContext.md` 会重定向到 `memory-bank/activeContext/{user}.md`。
- 超过 guard 阈值时自动归档完整原文。
- live 文件会被压缩到预算内。
- 归档保留在 `memory-bank/archive/activeContext/{user}/`。
- `rebuild-key-docs --target activeContext --user <user>` 只重建该用户的 activeContext，不覆盖顶层 `activeContext.md`。

`teamContext` / `progress` / `techContext` / `systemPatterns` 是团队共享沉淀：

- 只从 `scope=shared|project_shared|org_shared` 或 published 记录生成。
- `personal` / `session` / `user_private` 默认不会进入团队文档。
- 高价值个人记录（如 `decision` / `handoff` / `procedure` / `incident` / `validation_result`，或带 `high_value` / `mcp` / `workflow` 等团队标签）会自动生成一条派生 `project_shared` 摘要，再进入团队文档。
- `session` / `user_private` / candidate / distilled / 含明显密钥信号的记录不会自动提升。
- 需要共享完整 raw 时，写入时显式使用共享 scope，或通过 validate/publish 流程提升。

自动沉淀默认开启：

- 成功结构化写入达到阈值后重建关键文档。
- checkpoint 命中 `phase_triggers` 时可立即重建。
- `auto_team_settlement` 会先判断是否需要派生团队摘要；LLM 可用时参与判断和摘要，失败时回落 deterministic。
- LLM 可用时也可参与是否重建 key documents 的 gate；失败时回落 deterministic。
- 自动重建路径默认 `async=true`：MCP 写入只把 rebuild job 持久化到 `.ai-memory/key_document_rebuild_jobs.json`，立即返回；key documents 是最终一致派生视图。
- 异步 job 按 user/renderer/guard 策略合并 pending targets；drain 时使用单 worker lock，避免旧慢任务覆盖新任务。
- job 带 source watermark；若 rebuild 期间有新 raw 写入，完成时标记 `stale_at_publish=true` 并自动补排一个最新 job。
- 自动重建路径默认 `guard_prefer_llm=false`：若派生文档超出 guard 预算，MCP 自动路径使用 deterministic 压缩；显式 CLI rebuild 仍可使用 LLM guard 压缩。

### 3.4 多人协作

多人安全模式始终开启。

用户解析优先级：

1. `MEMORY_MCP_USER`
2. `<MemoryRoot>/user_config.local.json["user_name"]`
3. `.vscode/settings.json["memory-mcp.userName"]`（旧配置兼容）
4. `USERNAME` / `USER`
5. `unknown`

推荐把稳定 user id 放在 Memory 项目根目录的本地配置中，和 LLM 本地配置并列：

```powershell
Copy-Item <MemoryRoot>/user_config.example.json <MemoryRoot>/user_config.local.json
```

```json
{
  "user_name": "alice"
}
```

未配置稳定 user id 时，结构化读写会返回 `user_not_configured`，除非 `.ai-memory/config.json` 设置：

```json
{
  "mcp": {
    "allow_unknown_user": true
  }
}
```

并发策略：

- 每个写目标有跨进程文件锁。
- 写入使用同目录临时文件 + atomic replace。
- `if_match` 支持 SHA-256 乐观锁。
- shared key documents 使用 append-only 或 generated rebuild。
- personal / user_private 记录按 author 隔离。
- task hot context 按 `context_token` 分文件，避免多个 agent 共享全局 `.ai-context/current-task.md`。

### 3.5 LLM 接入（可选）

LLM 不在主路径上。没有 LLM 时，写入、FTS 检索、deterministic rebuild、guard、auto-maintenance 都正常工作。

配置：

```powershell
Copy-Item <MemoryRoot>/llm_config.example.json <MemoryRoot>/llm_config.local.json
```

也可使用环境变量：

- `MEMORY_LLM_API_KEY`
- `MEMORY_LLM_BASE_URL`
- `MEMORY_LLM_MODEL`

LLM 接入点：

- `memory_write(operation="record", distill=true)`
- `memory_write(operation="record")` 的 `auto_team_settlement` gate/summary
- `memory_read(operation="retrieve_context", summarize=true)`
- `memory_read(..., rewrite_query=true)`
- CLI `rebuild-key-docs --renderer auto|llm`
- CLI `weekly-snapshot-rebuild --narrative`
- CLI `monthly-snapshot-rebuild --narrative`
- CLI `enhance`
- guard 超限压缩中的 `guard_compaction`（CLI / 显式 rebuild 默认可用；MCP 自动重建默认不用 LLM）

LLM 输出只进入 distilled / generated / summary 层，不覆盖 raw 真源。

---

## 4. 项目设计思想

1. **真源可读**：记忆是 Markdown 文件，不绑定数据库。
2. **派生可重建**：索引、digest、关键文档、快照都能从 raw 重新生成。
3. **写入可审计**：写入路径统一做校验、锁、预算、备份、原子替换、事件记录。
4. **上下文有预算**：guard 控制热上下文、关键文档和总预算；超限自动压缩。
5. **多人默认安全**：user-scoped activeContext、teamContext 共享沉淀、shared append-only、author isolation 是默认行为。
6. **LLM 是增强层**：LLM 可摘要、压缩、重写查询、生成快照说明；不能改 raw 真源。
7. **普通工具少**：agent 只需要 `memory_read` / `memory_write`；管理动作走 CLI。
8. **失败可降级**：LLM、embedding、索引、cache 失败时回落 deterministic 或 FTS，不阻断主链路。

LLM 能力边界：

| 非 LLM | LLM | Hybrid |
|---|---|---|
| raw 写入 | 摘要 | guard 压缩 |
| Front Matter / Schema | query rewrite | key-doc rebuild |
| lock / backup / event | snapshot narrative | conflict explanation / team settlement gate |
| FTS / scoring / lineage / budget | classify / extract / merge | retrieve summary |

---

## 5. 开发状态与计划

当前已具备：

- 两工具 MCP 表面：`memory_read` / `memory_write`。
- CLI 管理面。
- Markdown raw 真源。
- SQLite FTS。
- CJK bigram / trigram 检索。
- metadata facet 预筛。
- budget-first retrieval。
- key documents rebuild。
- auto-maintenance。
- guard 单文件和总预算治理。
- LLM capability runner。
- query rewrite / summarize recall / snapshot narrative。
- local ONNX embedding provider。
- deterministic hash embedding fallback。
- multi-user always-on。
- lock lease metadata。
- retention archive。
- Windows legacy stdout UTF-8 fallback。

当前维护重点：

1. 统一剩余低频 CLI 写路径的 `file_lock + atomic_write`。
2. 为 baseline 更新增加确认策略或 LLM 建议策略。
3. 补 snapshot 显式回滚目录。
4. 在真实模型下载后运行 `scripts/eval_recall.py` 建立 local-onnx 召回基线。
5. 达到规模阈值后再启动 RAG Phase 3：GPU EP / 量化 / HNSW。

规模阈值：

- `chunks >= 100000`
- 全量向量重建 `>= 10min`
- 检索负载 `>= 20 QPS`
