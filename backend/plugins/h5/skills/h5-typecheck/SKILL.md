---
name: H5 类型检查
description: 对 Phaser + TypeScript 仓库跑 tsc --noEmit，产出结构化错误
x-workflow:
  version: 1
  stage_id: h5_typecheck
  stage_name: H5 类型检查
  consumes:
    - kind: code
      required: false
      mode: path
  produces:
    - kind: typecheck_log
      glob: typecheck_log.json
  required_traits:
    any_of:
      - framework:phaser
  # 与 fragment h5_typecheck 同 id 是刻意的：compose_sop 因重名跳过本 skill，
  # fragment 继续负责 reject_goto: development。删 yaml 前不要改 stage_id。
  priority: 94
  pipeline_view_contrib:
    group: testing
    create_if_missing:
      name: 测试验证
      icon: 🧪
      insert_after: development
x-runner:
  version: 1
  builtin_tools:
    - h5_typecheck
    - read_file
  outputs:
    root: "artifacts/{req_short}/{ticket_short}/typecheck_log"
    globs:
      - typecheck_log.json
  budget:
    max_rounds: 3
    max_seconds: 120
    max_tokens: 20000
---

# H5 类型检查

用插件 Action `h5_typecheck` 对当前仓库跑 `tsc --noEmit`。

## 和 SOP fragment 的关系

第一版**不接管流水线位置**。`sop/fragments/h5_typecheck.yaml` 仍负责：

- 插在 `development` 之后
- `reject_goto: development`

本 skill 的 `stage_id` 与 fragment 同名，组装器会跳过插入，避免两个类型检查阶段。

## 执行步骤

1. 确认 `repo_path` 下有 `tsconfig.json`。没有则先让调用方跑 `instantiate_h5_template`。
2. 调用一次 `h5_typecheck`。不要自己拼 tsc 命令。
3. `status=success` 结束；`typecheck_failed` 把 `errors` / `hints` 原样交回，不要在本阶段重试。
