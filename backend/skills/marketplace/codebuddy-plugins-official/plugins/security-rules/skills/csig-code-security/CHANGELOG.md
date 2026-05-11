# CSIG Code Security Skill - 变更日志

版本：3.0.0  
日期：2026-04-19

## 概述

本次更新将数据上报机制从**触发脚本（Trigger Script）**改为**Hooks 工作流（Workflow Hooks）**，与 security-scan 插件保持一致的上报架构。

---

## 1. 上报机制改造（核心变更）

### 原有方式（触发脚本）
- 在 SKILL.md 提示词中嵌入 `execute_command` 指令
- 依赖 AI 模型在推理过程中主动执行上报命令
- 硬编码上报 URL（`http://21.214.71.122/api/v1/security-skill/report`）和 Token（`test-token-987654`）
- 上报可靠性依赖 AI 是否正确理解并执行指令

### 新方式（Hooks 工作流）
- 新增 `references/post-skill-workflow.md` 定义上报工作流钩子
- SKILL.md 通过 `Ref:` 引用工作流文件，上报作为流水线固定步骤
- 上报 URL 和 Token 保持硬编码方式
- 与 security-scan 插件的 `post-audit-workflow.md` 保持一致的模式

### 变更的文件
| 文件 | 变更说明 |
|------|---------|
| `.codebuddy-plugin/plugin.json` | 添加 `references` 目录声明，版本升级至 1.7.0 |
| `references/post-skill-workflow.md` | **新增** hooks 工作流定义文件 |
| `skills/csig-code-security/SKILL.md` | 移除触发脚本指令，改为引用 hooks 工作流 |
| `scripts/report.py` | URL/Token 从硬编码改为环境变量，未配置时静默跳过 |
| `skills/csig-code-security/DATA_REPORTING_GUIDE.md` | 重写，更新为 hooks 方案文档 |
| `README.md` | 更新插件说明，添加上报和插件结构描述 |

## 2. 上报方式改进

- **触发方式升级**：从依赖 AI 推理执行的触发脚本方式，改为 hooks 工作流固定步骤，提升上报可靠性
- **配置保持不变**：上报 URL 和 Token 继续硬编码在 `report.py` 中（环境变量方案待后续确定）
