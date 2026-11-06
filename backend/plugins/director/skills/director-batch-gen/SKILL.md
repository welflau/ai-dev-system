---
name: director-batch-gen
description: 从片段 2 起批量生成并下载
x-workflow:
  version: 1
  stage_id: director_batch_gen
  stage_name: 批量生成
  consumes:
    - kind: shot_prompts
      mode: path
    - kind: clip_trial
      mode: path
    - kind: voice_plan
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
    none_of: [bug-fix, rollback, polish]
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
    - gen_video_batch
    - download_video
    - read_file
  outputs:
    root: "works"
    write_mode: repo
    allowed_exts: ["md", "json", "txt"]
    globs:
      - "*/video/片段*.mp4"
  budget:
    max_rounds: 6
    max_seconds: 2400
    max_tokens: 40000
---

# 批量生成

跳过片段 1。其余片段一次调用 `gen_video_batch`。缺 Key 或任一片段没有成功终态就停止，已成功的文件保留。不要让模型自己轮询。
