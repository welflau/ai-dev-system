---
name: director-brief
description: 选定 Mode / style，初始化作品工作包，产出 video_brief
x-workflow:
  version: 1
  stage_id: director_brief
  stage_name: 视频简报
  human_gate: true
  consumes:
    - kind: ticket_brief
      mode: text
  produces:
    - kind: video_brief
      glob: "*/video_brief.json"
  required_traits:
    all_of:
      - category:video
      - pipeline:video
  required_ticket_type:
    none_of: [bug-fix, rollback, polish]
  priority: 20
  pipeline_view_contrib:
    group: video_pipeline
    create_if_missing:
      name: 视频制片
      icon: 🎬
      insert_after: requirement_analysis
x-runner:
  version: 1
  builtin_tools:
    - init_work_package
    - write_file
    - read_file
    - confirm_video_gate
    - probe_backend
  outputs:
    root: "works"
    write_mode: repo
    allowed_exts: ["md", "json", "txt"]
    globs:
      - "*/video_brief.json"
  budget:
    max_rounds: 8
    max_seconds: 300
    max_tokens: 40000
---

# 视频简报

1. 读 `ticket_brief`，判断 Mode：`animated-explainer` / `storytime-animation` / `cinematic-drama`。无法判断就停，向用户提问。未支持类型明确拒绝。
2. 用 `read_file`（CLI：`mcp__skill_io__read_repo_file`）读 `director-knowledge/modes/<mode>/workflow.md` 确认适用边界。
3. `init_work_package`（CLI：`mcp__skill_io__init_work_package`，title 用工单标题），记下返回的 `slug`。
4. 把简报写入 `works/<slug>/video_brief.json`（CLI：`mcp__skill_io__write_repo_file`），字段至少包括：`mode`、`style`（可先空）、`ratio`、`duration_per_clip`、`language`、`backend`（默认 lightai）、`resolution`（默认 720p）、`slug`。用户指定 LibTV / 即梦才改 backend，不要因为 LightAI 缺 Key 就改。
5. 调用 `confirm_video_gate`（CLI：`mcp__skill_io__confirm_video_gate`，title=确认 Mode 与简报，work_slug=slug，gate=brief，preview_paths 含该 json），然后 `mcp__skill_io__done`。

**禁止**搜索或打开 `D:\A_Works\director`、`~/.codebuddy/projects`、用户主目录里的 director 源仓。不要用原生 Write / Glob / Bash 满盘搜 skill。知识只走 `director-knowledge/` 前缀。
