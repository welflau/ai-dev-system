---
name: director-visual
description: 锁定 style、人物参考与音色计划
x-workflow:
  version: 1
  stage_id: director_visual
  stage_name: 视觉与声音
  human_gate: true
  consumes:
    - kind: video_brief
      mode: path
    - kind: narration_script
      mode: path
    - kind: drama_breakdown
      mode: path
  produces:
    - kind: character_bible
      glob: "*/character-bible.md"
    - kind: voice_plan
      glob: "*/voice-plan.md"
    - kind: scene_bible
      glob: "*/scene-bible.md"
    - kind: character_ref
      glob: "*/refs/characters/*.png"
  required_traits:
    all_of:
      - category:video
      - pipeline:video
  required_ticket_type:
    none_of: [bug-fix, rollback, polish]
  priority: 40
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
    - check_mode_assets
    - confirm_video_gate
  outputs:
    root: "works"
    write_mode: repo
    allowed_exts: ["md", "json", "txt"]
    globs:
      - "*/character-bible.md"
      - "*/voice-plan.md"
      - "*/scene-bible.md"
      - "*/refs/characters/*.png"
  budget:
    max_rounds: 16
    max_seconds: 900
    max_tokens: 40000
---

# 视觉与声音

读 Mode 文档与 `director-knowledge/references/character-reference-image-guide.md`。

- Explainer 允许没有关键人物，仍要写 `character-bible.md`（可写「无关键人物」）。覆盖工作包模板，不要留「Drama 必填」字样。
- Storytime 讲述者默认关键人物，至少一张 `refs/characters/*.png`。
- Drama：填 `scene-bible.md`、`continuity-matrix.md`（Markdown 表）、角色表与音色计划；场景图进 `refs/scenes/`，人物图进 `refs/characters/`。非剧情 Mode 把 scene-bible / 矩阵写成「本 Mode 不适用」。

需要参考图时用 `gen_image`，filename 放到 skill 产出约定内，并在 bible 里记录路径。音色计划写入 `voice-plan.md`。

生图若失败（API key / 引擎 / LightAI 报错）：**禁止重试 gen_image，禁止 confirm_video_gate**。把已写好的文本留下，立即 `done`。这是环境问题，由人工处理。

先 `check_mode_assets`（gate=visual）。有缺口就补，不要发确认卡。通过后 `confirm_video_gate`（gate=visual），然后 done。
