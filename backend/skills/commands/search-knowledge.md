---
description: 搜索项目 wiki + 系统知识库（FTS）；支持关键词与标签过滤
args_hint: "<关键词> [feature:xxx] [type:xxx]"
requires_project: true
---

# /search-knowledge <关键词> [过滤器]

搜索知识并返回摘要。**优先项目 wiki**，同时查询系统 FTS 知识库（`docs/` / `dev-notes/` / 全局与项目文档）。

**支持的过滤器**（仅作用于 wiki）：
- `feature:mass-npc` — 按功能域过滤
- `type:bugfix` — 按文档类型过滤
- `role:programmer` — 按职能过滤

**示例**：
```
/search-knowledge LOD 切换
/search-knowledge unreal
/search-knowledge 网络同步 feature:mass-npc
/search-knowledge 崩溃 type:bugfix
```

**数据来源**：
1. `.ads/wiki/**/*.md`（项目 wiki，有 frontmatter）
2. 系统知识库（DB `knowledge_index` / FTS5）

FTS 命中以 `[标题](ads-kb:ID)` 输出，可在主舞台点击打开。无 wiki 时不再报错退出，直接走 FTS。
