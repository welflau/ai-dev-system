---
name: director-script
description: 按 Mode 写讲稿或剧情拆解
x-workflow:
  version: 1
  stage_id: director_script
  stage_name: 讲稿与拆解
  human_gate: true
  consumes:
    - kind: video_brief
      mode: path
  produces:
    - kind: narration_script
      glob: "*/旁白.md"
    - kind: drama_breakdown
      glob: "*/片段表.md"
  required_traits:
    all_of:
      - category:video
      - pipeline:video
  required_ticket_type:
    none_of: [bug-fix, rollback, polish]
  priority: 30
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
    - confirm_video_gate
  outputs:
    root: "works"
    write_mode: repo
    allowed_exts: ["md", "json", "txt"]
    globs:
      - "*/旁白.md"
      - "*/片段表.md"
  budget:
    max_rounds: 12
    max_seconds: 400
    max_tokens: 40000
---

# 讲稿与拆解

读 `video_brief.json` 的 mode。两个文件都要写，避免流水线缺产物：

- explainer / storytime：把定稿讲稿写入 `works/<slug>/旁白.md`；`片段表.md` 注明「本 Mode 不适用剧情拆解」。
- cinematic-drama：把片段表写入 `片段表.md`（每片段：开场状态、结束状态、定稿对白、出场角色、场景）；`旁白.md` 注明「本 Mode 不适用旁白」。

必须先读对应 Mode 的 workflow。15 秒口播中文尽量 59–61 字。不得在用户确认前进入视觉阶段。

写完后 `confirm_video_gate`（gate=script），然后 done。
