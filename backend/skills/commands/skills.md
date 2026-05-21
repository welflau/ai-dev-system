---
description: 查看当前已加载的 Skills 和全局 Rules（来源 + 标签）
args_hint: ""
requires_project: false
---

# /skills

列出当前 session 已加载的所有 Skill 和生效的全局 Rule。

**输出内容**：

1. **Skills**：当前 ChatAssistant 可用的 Skill 列表（名称 / 来源 / 描述）
2. **全局 Rules**：当前注入系统提示的规则（always/scene/traits 标签）
3. **项目规则来源**：检测到的 CLAUDE.md / ADS.md / .claude/rules/ / .ads/rules/

**示例输出**：

```
Skills（5 个）
  • UE Python 执行 [built-in] — 在运行中的 UE Editor 执行 Python
  • Blueprint 生成 [built-in] — 根据描述生成 Blueprint

全局 Rules（3 条）
  • global [always] — 全项目通用规范（语言一致性 / 命名 / 文档 / 安全）
  • ue5 [traits] — UE5 项目专属规范
  • cpp [paths] — C++ 文件专属规范

项目规则来源：CLAUDE.md, .claude/rules/, .ads/rules/
```
