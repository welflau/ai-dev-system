# ClaudeCompat Phase D — .claude/agents/ 支持

> 日期：2026-05-21
> 提交：`3db5042`
> 系列：ClaudeCompat（ADS 兼容 Claude Code 目录结构）

---

## 目标

扫描 `.claude/agents/*.md`，将项目自定义 Agent 定义注入 `get_memory_prompt()`，供 Orchestrator 调度时参考。

---

## 改动文件

`backend/agents/base.py`

---

## 实现

新增 `_load_project_agent_defs(agents_dir)` 模块级函数，解析每个 `.md` 文件：

- **有 frontmatter**：提取 `name:` 和 `description:` 字段
- **无 frontmatter**：用文件名作为 name，第一行内容作为 description

生成的摘要注入 `get_memory_prompt()` 末尾：

```markdown
## 项目自定义 Agent（.claude/agents/）

- **DeployAgent**：负责生产环境部署的 Agent
- **ReviewAgent**：代码审查专家
```

---

## Agent 定义文件格式（Claude Code 标准）

```markdown
---
name: DeployAgent
description: 负责生产环境部署，包含回滚流程
---

你是一个专门负责生产环境部署的 Agent...
```

---

## 效果

Orchestrator 在 `memory_prompt` 中看到项目有哪些自定义 Agent，可以在拆分子任务时将特定类型的工单分派给它们。
