# CSIG Code Security Skill - 数据上报实现指南

## 📋 目录
- [概述](#概述)
- [上报时机](#上报时机)
- [实现方案：Hooks 工作流](#实现方案hooks-工作流)
- [上报服务配置](#上报服务配置)
- [测试验证](#测试验证)

---

## 概述

本技能通过 `report.py` 脚本自动上报使用数据到后端服务器。上报过程对用户透明，在后台静默执行。

### 核心原则
- ✅ **自动化**：通过 hooks 工作流自动触发上报，无需手动操作
- ✅ **非阻塞**：上报失败不影响技能正常功能
- ✅ **环境变量配置**：上报服务地址和 Token 硬编码在 `report.py` 中，如需修改直接编辑对应函数
- ✅ **hooks 驱动**：上报由 `references/post-skill-workflow.md` 定义的工作流钩子触发，是流水线的固定组成部分

### 与 security-scan 插件的上报方式对齐

本插件的上报方式参照 `security-scan` 插件的 hooks 模式设计：

| 维度 | security-rules (hooks) | security-scan (hooks) |
|------|------------------------|----------------------|
| **触发机制** | `post-skill-workflow.md` 定义的 Hook 1/Hook 2 | `post-audit-workflow.md` 定义的审计后工作流 |
| **触发时机** | 技能加载完成 / 代码生成完成 | 审计完成后阶段 3 |
| **URL 配置** | 硬编码在 `report.py` 的 `get_report_url()` 中 | 环境变量 `YD_CODEBUDDY_REPORT_URL` |
| **Token 配置** | 硬编码在 `report.py` 的 `get_report_token()` 中 | 环境变量 `YD_CODEBUDDY_REPORT_TOKEN` |
| **失败处理** | 静默跳过，不阻断主流程 | 静默跳过，不阻断主流程 |

---

## 上报时机

### 1️⃣ 技能加载时上报（Hook 1：on_skill_load）

**触发条件**：当 AI 开始应用安全规则时（第 1 层通用规则加载完成后）

**上报内容**：
- 编程语言
- 加载的安全规则列表
- 工作目录路径

**执行命令**：
```bash
python3 "$plugin_root/scripts/report.py" load \
  --language <语言> \
  --rules <规则1>,<规则2> \
  --path <工作目录>
```

---

### 2️⃣ 代码生成时上报（Hook 2：on_code_generated）

**触发条件**：当 AI 生成代码完成时（第 2 层代码生成完成后）

**上报内容**：
- 编程语言
- 应用的安全规则
- 应用的安全函数指南(如果有)
- 生成的代码行数
- 工作目录路径

**执行命令**：
```bash
python3 "$plugin_root/scripts/report.py" code_generation \
  --language <语言> \
  --rules <规则列表> \
  --safe-functions <安全函数指南> \
  --code-lines <行数> \
  --path <工作目录>
```

---

## 上报服务配置

### 硬编码配置

上报服务地址和认证 Token 硬编码在 `scripts/report.py` 中：

| 配置项 | 函数 | 当前值 |
|-------|------|--------|
| 上报 URL | `get_report_url()` | `http://21.214.71.122/api/v1/security-skill/report` |
| 认证 Token | `get_report_token()` | 硬编码测试 Token |

### 修改方式

如需修改上报地址或 Token，直接编辑 `scripts/report.py` 中对应函数。

---

## 测试验证

### 1. 验证上报功能

```bash
# 测试技能加载上报
python3 scripts/report.py load \
  --language python \
  --rules sec-rules-sqli.mdc

# 测试代码生成上报
python3 scripts/report.py code_generation \
  --language python \
  --rules sec-rules-sqli.mdc,sec-rules-xss.mdc \
  --code-lines 50
```

---

**最后更新**：2026-04-19  
**版本**：3.0.0
