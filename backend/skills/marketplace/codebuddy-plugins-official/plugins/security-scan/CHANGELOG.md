# 版本更新日志

本文档记录 Security-Scan 插件的版本变更历史。

---

## v3.5.0（2026-04-20）

### Fast 扫描模式 + 全链路 Auto 模式 + POC 多维差异验证 + 字段规范化兜底 + 报告验证指引重构

> 引入 Fast 极速模式与执行纪律；--auto 模式覆盖所有交互点实现全流程无人值守；POC 模板全面升级为多维差异验证架构；报告验证指引从文本描述重构为结构化步骤；新增字段规范化兜底覆盖 Agent 字段漂移。

#### 1. 新增 Fast 扫描模式 + 字段规范化兜底

基于 Light 10 份会话日志分析（平均 wall 22m），新增 Fast 模式（目标 ~7m）。

- **Fast = Light + 执行纪律**：强制并行 Read、禁 sleep 轮询、禁后台 Agent、扫描+验证合并、默认跳过 POC（`--with-poc` 启用）。置信度上限 90，适用 Git Hook / CI 轻量门禁
- **字段规范化兜底**（惠及所有模式）：`merge_findings.py` 新增 `normalize_finding_schema`，归一化 Agent 字段漂移（`finding_type` → `riskType` 等），覆盖日志 8/10 故障场景
- **Git Hook 默认扫描模式改为 Fast**：已配置 `scan_level=light/deep` 的用户无影响；阻断模式选项扩展为 Fast/Light/Deep 三选一
- **枚举兼容**：全链路脚本（`_common`、`merge_findings`、`generate_report`、`gate_evaluator`、`git_commit_detector`）识别 `project-fast-*` / `diff-fast-*` 批次

#### 2. 全链路 --auto 无人值守模式

- **project.md 新增 `--auto` 参数**：`/security-scan:project --auto` 与 diff 命令保持一致的无人值守支持
- **初始化交互全覆盖**：权限白名单（自动配置）、模式选择（使用 `--scan-level` 参数）、环境就绪确认（自动降级继续）三个交互点在 auto 模式下全部自动跳过
- **修复交互跳过**：auto 模式下绝不执行自动修复（安全红线），跳过修复交互和下一步操作选择
- **空文件列表优雅处理**：diff 命令 auto 模式下空变更列表生成空报告 + gate-result (pass) 并正常结束
- **MANDATORY 步骤明确化**：project.md 阶段4 的报告生成 / 门禁评估 / 门禁通知明确为 MANDATORY-1/2/3，auto 模式完成后自动结束
- **setup 联动说明**：setup 配置完成输出增加 auto 模式可用命令提示，说明通过 setup 提前配置后 auto 模式可完全无交互执行

#### 3. POC 验证脚本全面升级（1389 行重写）

- **多维差异验证架构**：所有 POC 模板从单一 payload 探测升级为 baseline 对比 + 多维差异确认
  - SQL 注入：baseline + 布尔盲注真/假差异 + 时间盲注延迟 + 错误注入特征
  - XSS：唯一标记反射检测 + HTML 编码分析 + Content-Type 校验 + CSP 检查
  - 命令注入：唯一标记 echo + baseline 对比 + 多种拼接方式交叉验证
  - SSRF：baseline 对比 + 云元数据特征检测 + 响应差异分析 + 带外回调
  - 路径遍历：已知文件指纹匹配 + baseline 差异对比 + 多编码绕过
  - IDOR：认证 vs 匿名对比 + 跨 ID 数据泄露检测 + 权限边界测试
  - 开放重定向：Location 头域名控制检测 + 多绕过方式
  - XXE：外部实体文件读取 + 已知文件指纹匹配
  - CSRF：正常请求 vs 无 token 请求对比 + 跨域 Origin 检测 + 状态变更确认
- **新增 4 种漏洞类型模板**：code-execution（代码执行）、access-control（认证缺失）、auth-bypass（认证绕过）、race-condition（竞态条件）
- **智能模板匹配**：新增 `_infer_template_from_finding()` 函数，当 riskType 无法直接匹配模板时，根据 finding 的描述和特征智能推断最佳模板
- **verdict 结论机制**：每个 POC 函数返回结构化 `verdict`（confirmed / likely / inconclusive / error）+ `confirmed_techniques` 列表 + 详细 `evidence`

#### 4. HTML 报告验证指引重构（744 行变更）

- **结构化步骤替代文本描述**：验证指引从单段文本重构为编号步骤列表，每个步骤包含描述和可执行命令
- **三层验证策略**：新增 `_build_poc_verification_steps()`（有 POC 脚本时）、`_build_manual_verification_steps()`（需手动验证时）、`_build_static_verification_steps()`（静态类漏洞）三个生成函数
- **POC manifest 集成**：验证指引生成时读取 `poc-manifest.json`，关联实际的 POC 函数名和验证方法
- **视觉标识**：漏洞验证指引标题增加 POC 脚本验证 / 手动验证 badge 标识
- **CSS 样式升级**：验证步骤新增编号标识、命令代码块、步骤间距等样式

#### 5. 编排文档统一

- **initialization.md**：新增「自动模式对初始化的影响」章节，权限白名单/模式选择/环境就绪确认三个交互点的 auto 处理规则
- **post-audit.md**：高风险未验证确认和下一步操作增加 auto 模式跳过规则
- **diff.md**：auto 模式交互跳过表从 4 行扩展为 6 行，空文件列表优雅处理
- **setup.md**：概述和配置完成输出增加 auto 模式关系说明

---

## v3.4.3（2026-04-17）

### Stop Hook 报告上报 + Transcript 扫描架构统一 + 多项修复

> 报告上报迁移至 Stop Hook 架构，统一 transcript 扫描流程，修复 verifier/通知/severity 等多个问题。

#### 1. 报告上报迁移至 Stop Hook

- **新增 `report_upload_hook.py`**：报告上报逻辑从编排器内联迁移至独立 Stop Hook 脚本，解耦扫描与上报
- **共享逻辑提取**：`_common.py` 提取公共工具函数，供 hook 和编排器复用
- **移除 `git_op_recorder.py`**：不再需要独立的 Git 操作录制脚本

#### 2. Transcript 扫描架构统一

- **统一 `git_commit_detector.py`**：重构 transcript 扫描架构（640 行重写），新增 blocking 模式支持
- **Hook 配置修复**：`hooks.json` 调整触发规则和配置项（23 行变更）
- **Hook reason 优化**：改善 hook 触发提示文案，确保模型正确执行扫描

#### 3. Bug 修复

- **企微通知分级统计为 0**：修复 `merge_findings.py` 中漏洞分级统计逻辑，确保 severity 正确聚合
- **Verifier 覆盖维度 0/10**：修复 `verifier.py` 精简输出导致评分维度丢失的问题
- **Severity 字段兼容性**：修复 severity 字段在不同 Agent 输出间的兼容性问题
- **空调用图防御**：增加调用图为空时的防御性处理

#### 4. 其他改进

- **插件根目录解析统一**：重构为 Python 脚本统一解析，增强跨平台兼容性
- **Setup/Diff/Project 命令更新**：配合 Hook 架构调整更新编排流程
- **权限白名单调整**：`permissions-allowlist.yaml` 更新权限规则
- **新增测试**：`test_severity_stats_fixes.py`（611 行），覆盖 severity 统计修复场景

---

## v3.4.2（2026-04-14）

### 腾讯云安全基线 + Git Hook 优化

> 新增腾讯云安全基线知识库，扩展云安全风险类型，优化 Git Hook 触发策略。

#### 1. 腾讯云安全基线支持

- **新增知识库**：`resource/knowledge/tencent-cloud-security.yaml`（310 行），覆盖 COS/S3 公开访问、IAM/CAM 过度授权、安全组暴露、SCF 无鉴权、CDB 公网暴露、IMDS 元数据泄露
- **风险类型扩展**：`risk-type-taxonomy.yaml` 新增 `cloud_security` 大类，包含 6 种云安全风险类型：`cloud-imds`、`iam-overprivilege`、`public-bucket`、`security-group-open`、`serverless-no-auth`、`cloud-db-exposed`
- **logic-scan 增强**：新增 C7.6 云安全审计章节，覆盖 COS/S3 公开访问、IAM/CAM 过度授权、安全组暴露、SCF 无鉴权、CDB 公网暴露、腾讯 CDB 硬编码连接串、COS 预签名 URL 过期检测
- **SSRF 知识更新**：`ssrf.yaml` 补充腾讯云元数据端点（`metadata.tencentyun.com`）

#### 2. Git Hook 触发策略优化

- **Push 不再触发扫描**：`git push` 不再触发 hook 自动扫描，仅 `git commit` 触发，减少重复扫描开销
- **提示文案简化**：精简 Git Hook 自动扫描触发的提示信息，减少对用户的干扰

#### 3. 其他改进

- **密钥检测增强**：`secret-detection-patterns.yaml` 新增检测模式
- **POC 生成器**：`poc_generator.py` 小幅增强

---

## v3.4.1（2026-04-10）

### 安全门禁 + Git Hook 自动化

> 分层配置架构 + 自动扫描模式 + Push 门禁告警，实现从扫描到通知的全链路自动化。

- **分层配置**：用户级（`~/.codebuddy/security-scan/config.json`）+ 项目级（`.codebuddy/security-scan/config.json`），项目级 > 用户级 > 默认值
- **自动扫描**：`/security-scan:diff --auto` 无人值守模式，跳过所有交互，绝不自动修复代码
- **Git Hook**：`git commit` 后自动触发扫描，`git push` 前检查门禁状态并告警通知
- **通知增强**：`--source` 区分 scan / hook-auto / push 三种来源，匹配 `on_scan` / `on_push` / `both` 触发策略
- **setup 重构**：简化 `/security-scan:setup` 配置流程，分层写入用户级通知 + 项目级门禁策略

---

## v3.3.0（2026-04-07）

### POC 验证脚本输出

> 验证阶段完成后自动生成可独立执行的 POC 验证脚本，支持用户配置目标地址和凭据后对实际服务发送探测性请求验证漏洞。

**核心改动**：

#### 1. 新增 `scripts/poc_generator.py`

POC 验证脚本生成器，两个子命令：
- `generate`：读取审计结果，为每个漏洞生成 POC 函数，输出 `poc-scripts.py`（独立可执行）+ `poc-manifest.json`（清单）
- `run`：通过子进程执行 `poc-scripts.py`，收集验证结果

支持 11 种漏洞类型的专用 POC 模板（SQL 注入、XSS、命令注入、SSRF、路径遍历、IDOR、开放重定向、XXE、CSRF、硬编码密钥、不安全配置）+ 通用 fallback 模板。

#### 2. 字段归一化扩展

- `_common.py` 的 `normalize_finding()` 增加 `pocMethod`/`pocRequestType` 字段归一化
- `to_report_format()` 增加 POC 字段保留

#### 3. 报告集成

- `generate_report.py` 的 JSON 报告 `issue_entry` 增加 `pocMethod`/`pocRequestType` 字段
- HTML 报告 issue 卡片增加「POC 验证方式」展示区域（位于调用链和风险代码之间）

#### 4. 流程集成

- `verification.md` 新增 Stage 6（POC 脚本生成）
- `post-audit.md` 在报告生成前增加 POC 生成步骤
- `project.md` / `diff.md` 编排器更新阶段4执行顺序
- `output-schemas.md` 目录结构增加 `poc-scripts.py` / `poc-manifest.json` / `poc-results.json`

#### 5. 使用方式

```bash
# 自动生成（审计流程中自动执行）
python3 poc_generator.py generate --batch-dir security-scan-output/{batch}

# 用户手动验证
python3 security-scan-output/{batch}/poc-scripts.py --base-url http://target:8080
python3 security-scan-output/{batch}/poc-scripts.py --base-url http://target:8080 --cookie "session=abc" --header "Authorization: Bearer <token>"
```

---

## v3.2.0（2026-03-25）

### 5 Agent 专业化架构 + 混合验证

> 5 Agent 专业化架构（indexer + vuln-scan + logic-scan + red-team + verifier）配合确定性脚本验证，兼顾扫描深度与验证效率。

**核心改动**：

#### 1. 5 Agent 专业化分工

| Agent | 职责 |
|-------|------|
| indexer | 构建项目语义索引（SQLite） |
| vuln-scan | C1 注入类 Source→Sink 数据流追踪 |
| logic-scan | C3 授权 + C7 业务逻辑审计 |
| red-team | 3 核心问题（Q1 自造轮子/Q2 异常路径/Q3 跨边界信任） |
| verifier | LLM 深度验证（攻击链 + 对抗审查） |

#### 2. 混合验证架构

5 层验证流水线：
- **Stage 1-3（脚本）**：pre-check → chain-verify → challenge（零 LLM turns）
- **Stage 4（LLM）**：verifier Agent 深度验证，支持按 sourceAgent 并行分片（verifier-vuln / verifier-logic / verifier-redteam）
- **Stage 5（脚本）**：score + quality（零 LLM turns）

---

## v3.1.6（2026-03-24）

### 缓存增量漏检修复：content_hash 变更检测 + 防御过期清理

> 修复 Light 模式缓存命中时，已有文件中新增的 Sink/入口点被跳过的漏检风险，并增加防御过期标注防止历史防御信息误导分析。

**改动**：

- **`commands/project.md`**：步骤 1.2 缓存命中逻辑重构——增量文件检查增加 `content_hash` 比对，Sink/入口点检测扩展为「新增 + 内容变更文件」
- **`agents/indexer.md`**：Phase 1 缓存加速同步上述变更
- **`scripts/index_db.py`**：`known_defenses` 表新增 `last_confirmed`/`stale` 字段，`memory-sync` 增加过期清理

---

## 早期版本摘要

| 版本 | 日期 | 要点 |
|------|------|------|
| v3.1.5 | 2026-03-23 | 长期记忆扩展：项目结构缓存持久化到 `project-memory.db` |
| v3.1.4 | 2026-03-23 | 移除伪控制预算体系；merge_findings.py 修复；Grep+Read 上限 75→90 |
| v3.1.3 | 2026-03-23 | 全局逻辑审查；shared-initialization.md 抽取；双引擎 AST 架构 |
| v3.1.1 | 2026-03-23 | 内置 AST 精化集成（ts_parser.py）；indexer Phase 1.5 |
| v3.1.0 | 2026-03-23 | Light/Deep 双模式扫描架构；Reference 文件大幅精简 |
| v3.0.0 | 2026-03-22 | 架构重构：SQLite 语义索引 + 并行审计；5 Agent 体系建立 |
| v2.x | 2026-03 | 初始架构迭代：6 Agent → 分级扫描 → 断点恢复 → Critical 级别 |

> 完整历史变更详见 git log。
