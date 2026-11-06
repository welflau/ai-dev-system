---
name: director-polish
description: 只重跑某一个已有片段，不重走简报和讲稿
x-workflow:
  version: 1
  stage_id: director_polish
  stage_name: 单片段重做
  human_gate: true
  consumes:
    - kind: ticket_brief
      mode: text
    - kind: video_brief
      required: false
      mode: path
    - kind: shot_prompts
      required: false
      mode: path
  produces:
    - kind: video_clip
      glob: "*/video/片段*.mp4"
  required_traits:
    all_of:
      - category:video
      - pipeline:video
  required_ticket_type:
    any_of: [polish]
  priority: 70
  pipeline_view_contrib:
    group: video_pipeline
    create_if_missing:
      name: 视频制片
      icon: 🎬
      insert_after: requirement_analysis
x-runner:
  version: 1
  builtin_tools:
    - gen_video
    - probe_backend
    - read_file
    - confirm_video_gate
  outputs:
    root: "works"
    write_mode: repo
    allowed_exts: ["md", "json", "txt"]
    globs:
      - "*/video/片段*.mp4"
  budget:
    max_rounds: 6
    max_seconds: 1200
    max_tokens: 20000
---

# 单片段重做

只处理 polish 工单。从工单标题/描述里读出要重做的片段编号（如 片段03）。

1. `probe_backend`，不可用就停。
2. 读该片段的 `works/<slug>/prompts/片段NN.md` 与 `current-assets-manifest.md`。
3. 只调用一次 `gen_video`，filename 必须是那个片段，不要批量。
4. Drama 保持 720p / ≤15s。
5. 成功后 `confirm_video_gate`（preview 含新 mp4），然后 done。
