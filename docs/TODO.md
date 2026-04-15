# AI Dev System — 待办清单

> 最后更新: 2026-04-15

---

## 盲审修复（优先）

| 优先级 | Agent | 问题 | 修复内容 |
|--------|-------|------|---------|
| P0 | ProductAgent 拆单 | 不看已有代码就拆单 | 注入 existing_files/code，拆单时参考已有架构 |
| P0 | ReviewAgent | 完全盲审，不读代码 | 读取实际代码内容 + ActionNode + SOP 配置 |
| P1 | DevAgent WriteCode | 读代码但不看文件列表 | 补充 existing_files 传入 |
| P1 | DevAgent SelfTest | 不读实际代码内容 | 检查 Git 仓库中文件而非只看内存 files |
| P2 | DeployAgent | 不读代码，部署配置通用化 | 读取项目类型生成针对性部署配置 |
| P2 | ArchitectAgent | 缺 SOP 配置读取 | 使用 sop_config 中的参数 |
| P2 | TestAgent | 缺 ActionNode + SOP | 迁移到 ActionNode，读取 SOP 测试配置 |

## 架构改进

| 优先级 | 项目 | 说明 |
|--------|------|------|
| P1 | Agent REACT 模式 | 完善 LLM 动态选择下一步 Action 的实现 |
| P1 | 前端 SOP 拖拽编辑器 | 可视化编辑流程，不用手改 YAML |
| P2 | 剩余 Agent 迁移 ActionNode | TestAgent/ReviewAgent/DeployAgent |
| P2 | Memory 持久化索引 | cause_by 索引目前在内存，重启丢失 |

## Phase 3: v0.15 — 智能增强

| 优先级 | 版本 | 内容 | 状态 |
|--------|------|------|------|
| P0 | v0.15.0 | 多 LLM 支持（Ollama + 降级链） | 待开发 |
| P1 | v0.15.1 | 并发调度（多工单并行） | 待开发 |
| P1 | v0.15.2 | ResearchAgent 竞品分析 | 待开发 |
| P2 | v0.15.3 | 前端 SOP 拖拽编辑器 | 待开发 |

## Phase 4: v0.16 — 平台化

| 优先级 | 版本 | 内容 | 状态 |
|--------|------|------|------|
| P1 | v0.16.0 | 插件市场 | 待开发 |
| P2 | v0.16.1 | 多项目协作 | 待开发 |
| P2 | v0.16.2 | Data Interpreter | 待开发 |

## Bug 修复记录（已完成）

| 日期 | 问题 | 根因 | 修复 |
|------|------|------|------|
| 04-15 | 工单卡在 success 状态 | ActionResult.to_dict() 覆盖 data 中的 status | 不覆盖已有 status |
| 04-15 | 验收死循环 53 次 | BY_ORDER files 覆盖 + 盲审 | 修 files 合并 + 加 max_retries 5 |
| 04-15 | 产出文件在仓库找不到 | BY_ORDER 后续 Action 覆盖前面的 files | pop files 后再 update |
| 04-15 | 验收说缺 index.html 但实际存在 | 验收只看 dev_result 不看仓库 | 传入 existing_files + code |
| 04-14 | 分支没创建 | subtasks 字符串/dict 格式不兼容 | 兼容两种格式 |
| 04-14 | LLM 返回截断 | max_tokens=4096 不够 | 提升到 16000 + 精简 prompt |
| 03-30 | 删除项目失败 | ci_builds 未级联删除 + DB locked | 加 ci_builds 删除 + busy_timeout |
| 03-30 | llm_conversations ticket_id 为 NULL | 全局单例 context 并发覆盖 | 改用 contextvars |

## 新功能想法

- ReportAgent：每日自动汇总项目进展生成日报
- 安全扫描 Agent：检查代码安全漏洞
- 性能测试 Agent：页面加载速度、API 响应时间
- 数据库迁移路径更新工具：换机器时批量更新 git_repo_path

---

*待办清单由 AI Dev System 团队维护*
