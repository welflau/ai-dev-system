---
name: demo-draft
description: 按大纲写成稿（演示 skill 链的中间环节：既消费上游又产出给下游）
x-workflow:
  version: 1
  stage_id: demo_draft
  stage_name: 正文撰写
  consumes:
    - kind: content_outline
      mode: text
    - kind: style_guide
      required: false
  produces:
    - kind: draft_article
      glob: "draft.md"
  required_traits:
    any_of:
      - pipeline:content
  # priority 刻意与依赖顺序**相反**：中间
  # 只按 priority 排会得出 cover→draft→outline（错的），
  # 这让 demo 链本身成为「拓扑排序确实生效」的证据。
  priority: 50
  pipeline_view_contrib:
    group: content_pipeline
    create_if_missing:
      name: 内容流水线
      icon: 📝
      insert_after: requirement_analysis
x-runner:
  version: 1
  builtin_tools:
    - read_file
    - write_file
  outputs:
    root: "artifacts/{req_short}/{ticket_short}/draft_article"
    globs:
      - "draft.md"
  budget:
    max_rounds: 8
    max_seconds: 300
    max_tokens: 60000
---

# 正文撰写

按上游大纲把文章写完整。

## 执行步骤

1. 上游 `content_outline` 的内容已内联在「上游产物」小节（mode: text）。
   `style_guide` 是可选的 —— 缺失时按「技术博客、克制、面向工程师」的默认风格写。

2. 写入 `draft.md`，按大纲的章节结构展开 —— 用 `write_file`，或 MCP 形式的
   `mcp__skill_io__write_output`（CLI 模式下只有后者可用）。
   **不要用原生 Write/Bash**：产出目录由框架决定，原生工具写出去的文件回收不到。

3. 调 `done` 结束。

## 写作要求

- 纯 Markdown，以 `# 标题` 开头。
- 每节要有**实质内容**，不要「本节介绍了…」这类空壳。
- 代码示例用 ```语言 围栏；路径和标识符用反引号。
- 不要用 ```markdown 把整篇包起来。
- 不要附加「以下是正文」「希望对你有帮助」这类前后缀。

## 约束

- 只写 `draft.md` 这一个文件。
- 大纲缺失时不要凭空编造主题 —— 在 `done` 的 summary 里说明缺了什么。
