---
name: director-deliver
description: 汇总交付清单 video_package
x-workflow:
  version: 1
  stage_id: director_deliver
  stage_name: 成片交付
  consumes:
    - kind: video_clip
      mode: path
    - kind: video_brief
      mode: path
    - kind: shot_prompts
      mode: path
  produces:
    - kind: video_package
      glob: "video_package.json"
    - kind: video_cover
      glob: "video_cover.png"
  required_traits:
    all_of:
      - category:video
      - pipeline:video
  required_ticket_type:
    none_of: [bug-fix, rollback, polish]
  priority: 80
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
    - gen_image
  outputs:
    root: "works/{work_slug}"
    write_mode: repo
    allowed_exts: ["md", "json", "txt"]
    globs:
      - "video_package.json"
      - "video_cover.png"
  budget:
    max_rounds: 6
    max_seconds: 600
    max_tokens: 20000
---

# 成片交付

列出 `works/<slug>/video/` 下全部 mp4，写入 `works/<slug>/video_package.json`：mode、backend、clips[{filename,path,bytes}]、missing[]。不要自动拼接。提示用户到剪辑软件里拼接。

Animated Explainer：读 `director-knowledge/modes/animated-explainer/video-cover-image-guide.md`，用 `gen_image` 生成封面，保存为 `works/<slug>/video_cover.png`（沿用已确认人物与 style）。其他 Mode 可跳过封面。
