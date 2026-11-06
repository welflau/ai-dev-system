---
name: director-clip-trial
description: 只生成片段 1，等人确认画面与音色
x-workflow:
  version: 1
  stage_id: director_clip_trial
  stage_name: 片段1 试生成
  human_gate: true
  consumes:
    - kind: shot_prompts
      mode: path
    - kind: voice_plan
      mode: path
    - kind: video_brief
      mode: path
  produces:
    - kind: clip_trial
      glob: "*/video/片段01.mp4"
    - kind: voice_anchor
      glob: "*/voices/*.wav"
  required_traits:
    all_of:
      - category:video
      - pipeline:video
  required_ticket_type:
    none_of: [bug-fix, rollback, polish]
  priority: 60
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
      - "*/video/片段01.mp4"
      - "*/voices/*.wav"
  budget:
    max_rounds: 8
    max_seconds: 1200
    max_tokens: 40000
---

# 片段 1 试生成

先 `probe_backend`。不可用就停，不要改 Prompt，不要换后端。

只调用一次 `gen_video`，filename=`片段01.mp4`，work_slug 与 brief 一致，duration 默认 15，resolution=720p。Drama 不要传 1080p。

缺 Key / CLI 时工具会失败：停止，不要改 Prompt 重试。成功后 `confirm_video_gate`（gate=clip，preview 含该 mp4），然后 done。
