---
name: demo-outline
description: 从工单简报产出内容大纲（演示 skill 链的源头：消费框架内置的 ticket_brief）
x-workflow:
  version: 1
  stage_id: demo_outline
  stage_name: 大纲规划
  consumes:
    - kind: ticket_brief
      mode: text
  produces:
    - kind: content_outline
      glob: "outline.md"
  required_traits:
    any_of:
      - pipeline:content
  # priority 刻意与依赖顺序**相反**：最低 —— 它却必须第一个跑（依赖优先于 priority）
  # 只按 priority 排会得出 cover→draft→outline（错的），
  # 这让 demo 链本身成为「拓扑排序确实生效」的证据。
  priority: 20
  pipeline_view_contrib:
    group: content_pipeline
    create_if_missing:
      name: 内容流水线
      icon: 📝
      insert_after: requirement_analysis
x-runner:
  version: 1
  builtin_tools:
    - write_file
  outputs:
    root: "artifacts/{req_short}/{ticket_short}/content_outline"
    globs:
      - "outline.md"
  budget:
    max_rounds: 6
    # 真实 CLI 实测：240s 贴边（模型写完大纲没来得及回调 done 就被掐断，
    # 见 dev-notes/2026-10-16_01）。放宽到 300s，与 demo-draft 对齐。
    max_seconds: 300
    max_tokens: 40000
---

# 大纲规划

把工单需求拆成一份可直接下笔的大纲。

## 执行步骤

1. `ticket_brief`（工单简报 JSON）已内联在「上游产物」小节，包含
   title / description / type / project_traits。

2. 写入 `outline.md` —— 用 `write_file`，或 MCP 形式的
   `mcp__skill_io__write_output`（CLI 模式下只有后者可用）。
   **不要用原生 Write/Bash**：产出目录由框架决定，原生工具的相对路径
   基于仓库根，写出去的文件回收不到。

3. 调 `done` 结束。

## 大纲格式

```
# <文章标题>

## 读者与目标
- 读者：谁会看
- 读完能做什么

## 章节
1. <章节名> — 要点 A / 要点 B
2. ...

## 关键术语
- <术语>：一句话解释
```

## 约束

- 3-6 个章节，每节至少两个要点 —— 下游 `demo-draft` 直接按这个结构展开。
- 只写 `outline.md` 这一个文件。
- 要点要具体（「讲清 X 和 Y 的区别」），不要写「介绍背景」这种空标签。
