---
name: 引擎编译验证
description: 调 UnrealBuildTool 编译 UE 项目，产出结构化错误列表
x-workflow:
  version: 1
  stage_id: engine_compile
  stage_name: 引擎编译验证
  consumes:
    - kind: code
      required: false
      mode: path
  produces:
    - kind: compile_log
      glob: compile_log.json
  required_traits:
    any_of:
      - engine:ue5
      - engine:ue4
  # 与 fragment engine_compile 同 id 是刻意的：compose_sop 会因重名跳过本 skill，
  # fragment 继续负责 reject_goto / ue_precompile。删 yaml 前不要改 stage_id。
  priority: 95
  pipeline_view_contrib:
    group: testing
    create_if_missing:
      name: 测试验证
      icon: 🧪
      insert_after: development
x-runner:
  version: 1
  builtin_tools:
    - ue_compile_check
    - read_file
  outputs:
    root: "artifacts/{req_short}/{ticket_short}/compile_log"
    globs:
      - compile_log.json
  budget:
    max_rounds: 4
    max_seconds: 700
    max_tokens: 40000
---

# 引擎编译验证

用插件 Action `ue_compile_check` 调 UnrealBuildTool 编译当前 UE 项目。

## 和 SOP fragment 的关系

第一版**不接管流水线位置**。`sop/fragments/engine_compile.yaml` 仍负责：

- 插在 `development` 之后
- `reject_goto: development`
- 给 development 开 `ue_precompile`

本 skill 的 `stage_id` 与 fragment 同名，组装器会跳过插入，避免出现两个编译阶段。
Godot / Unity 继续只走 fragment（本插件仅 UE）。

真正干活的类在 `plugins/ue5/actions/ue_compile_check.py`，由 `plugins.registry`
按名字 `ue_compile_check` 提供给 SkillRunner、DevAgent、自测和 CI。

## 执行步骤

1. 确认工单上下文里有 `repo_path` / `uproject_path`（没有则 Action 会从仓库推断）。
2. 调用一次 `ue_compile_check`。不要自己拼 UBT 命令。
3. 若返回 `status=success`，结束；否则把 `errors` 列表原样交给调用方，不要重试
   （重试次数由 fragment 的 `max_retries` 管）。
