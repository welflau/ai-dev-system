---
name: demo-cover
description: 为成稿生成一张封面图（演示 skill 链的二进制产物与生图工具接入）
x-workflow:
  version: 1
  stage_id: demo_cover
  stage_name: 封面配图
  consumes:
    - kind: draft_article
      mode: text
  produces:
    - kind: cover_image
      glob: "images/*.png"
  required_traits:
    any_of:
      - pipeline:content
  # priority 刻意与依赖顺序**相反**：最高 —— 它却必须最后跑（consumes draft_article）
  # 只按 priority 排会得出 cover→draft→outline（错的），
  # 这让 demo 链本身成为「拓扑排序确实生效」的证据。
  priority: 90
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
    - "gen_image:images"
  outputs:
    root: "artifacts/{req_short}/{ticket_short}/cover_image"
    globs:
      - "images/*.png"
  # 生图单次 30-300 秒，预算必须给足 —— 默认 300s 只够一张且没有重试余量
  budget:
    max_rounds: 6
    max_seconds: 900
    max_tokens: 40000
---

# 封面配图

读上游成稿，为它生成**一张**封面图。

## 执行步骤

1. 上游产物 `draft_article` 的正文已内联在「上游产物」小节里（mode: text）。
   若只给了路径，用 `read_file`（或 `mcp__skill_io__read_repo_file`）读取。

2. 从正文提炼封面要素，调 **一次** `gen_image`
   （MCP 形式：`mcp__skill_io__gen_image`）：
   - `filename`：固定用 `cover.png`
   - `prompt`：英文，包含四要素 —— 主体 / 风格 / 构图 / 光线
   - `aspect_ratio`：`16:9`

3. 调 `done` 结束。

## 约束

- **只生成一张图**。`gen_image` 单次耗时 30-300 秒并且花钱，
  同一张图重复调用会把预算耗光且产出重复文件。
- 图片由工具自动保存到产出目录，**不要**再用其它工具写文件，
  也**不要用原生 Write/Bash** —— 产出目录由框架决定。
- prompt 用英文；不要在 prompt 里出现文字/字幕要求（模型渲染文字效果差）。
- 若 `gen_image` 返回错误，**不要重试**，直接 `done` 并在 summary 里说明原因。
