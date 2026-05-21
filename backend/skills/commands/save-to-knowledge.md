---
description: 将当前对话内容归档为项目 wiki 知识条目（LLM 自动生成 frontmatter）
args_hint: "[标题或描述]"
requires_project: true
---

# /save-to-knowledge [描述]

从当前对话中提取技术知识，归档为 `.ads/wiki/` 目录下的结构化 wiki 条目。

**流程**：
1. LLM 从对话中提取核心知识点
2. 自动生成 Frontmatter（feature/role/type/tags 三轴标签）
3. 检查是否有同类条目（选择追加或新建）
4. 写入 `.ads/wiki/{feature}/` 目录
5. 重新生成 `_wiki_index.md`

**Frontmatter 三轴**：
- `feature`：功能域（mass-npc / network-sync / rendering / ui / gameplay 等）
- `role`：目标职能（programmer / designer / artist / pm）
- `type`：文档类型（technical-design / bugfix / howto / decision）

**示例**：
```
/save-to-knowledge Mass NPC LOD 切换闪现修复
```
