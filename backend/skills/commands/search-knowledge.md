---
description: 搜索项目 wiki 知识库（支持关键词 + 标签过滤）
args_hint: "<关键词> [feature:xxx] [type:xxx]"
requires_project: true
---

# /search-knowledge <关键词> [过滤器]

在项目 `.ads/wiki/` 目录下全文搜索，返回匹配的知识条目摘要。

**支持的过滤器**：
- `feature:mass-npc` — 按功能域过滤
- `type:bugfix` — 按文档类型过滤
- `role:programmer` — 按职能过滤

**示例**：
```
/search-knowledge LOD 切换
/search-knowledge 网络同步 feature:mass-npc
/search-knowledge 崩溃 type:bugfix
```

**数据来源**：
1. `.ads/wiki/**/*.md`（项目 wiki，有 frontmatter）
2. 系统知识库（DB `knowledge_index` 表，现有功能）

结果按相关度排序，最多返回 5 条。
