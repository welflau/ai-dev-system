---
name: director-prompts
description: 逐片段编写视频 Prompt
x-workflow:
  version: 1
  stage_id: director_prompts
  stage_name: 分镜 Prompt
  consumes:
    - kind: video_brief
      mode: path
    - kind: character_bible
      mode: path
    - kind: voice_plan
      mode: path
    - kind: narration_script
      required: false
      mode: path
    - kind: drama_breakdown
      required: false
      mode: path
    - kind: scene_bible
      required: false
      mode: path
  produces:
    - kind: shot_prompts
      glob: "*/shot_prompts.md"
  required_traits:
    all_of:
      - category:video
      - pipeline:video
  required_ticket_type:
    none_of: [bug-fix, rollback, polish]
  priority: 50
  pipeline_view_contrib:
    group: video_pipeline
    create_if_missing:
      name: 视频制片
      icon: 🎬
      insert_after: requirement_analysis
x-runner:
  version: 1
  builtin_tools:
    - write_file
    - read_file
  outputs:
    root: "works"
    write_mode: repo
    allowed_exts: ["md", "json", "txt"]
    globs:
      - "*/shot_prompts.md"
  budget:
    max_rounds: 16
    max_seconds: 400
    max_tokens: 40000
---

# 分镜 Prompt

读 `director-knowledge/references/video-generation-prompt-guide.md` 与当前 Mode 的 Prompt 指南。每个片段另存 `works/<slug>/prompts/片段NN.md`，并写一份索引 `works/<slug>/shot_prompts.md` 列出全部路径、时长、出场人物。

Drama 必须对照 `continuity-matrix.md`：每个 Prompt 自包含开场状态，禁止写「承接上一片段」。

相邻镜头默认硬切。不要在 Prompt 里写分辨率或 duration。
