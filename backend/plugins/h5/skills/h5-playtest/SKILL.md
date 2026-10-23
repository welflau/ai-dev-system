---
name: H5 试玩
description: vite build 后打开产物页，收集 Phaser 运行时错误
x-workflow:
  version: 1
  stage_id: h5_playtest
  stage_name: H5 试玩
  consumes:
    - kind: typecheck_log
      required: false
      mode: path
    - kind: code
      required: false
      mode: path
  produces:
    - kind: playtest_log
      glob: playtest_log.json
  required_traits:
    any_of:
      - framework:phaser
  # 与 fragment h5_playtest 同 id 是刻意的：compose_sop 因重名跳过本 skill，
  # fragment 继续负责 reject_goto: development。删 yaml 前不要改 stage_id。
  priority: 86
  pipeline_view_contrib:
    group: testing
    create_if_missing:
      name: 测试验证
      icon: 🧪
      insert_after: development
x-runner:
  version: 1
  builtin_tools:
    - h5_playtest
    - read_file
  outputs:
    root: "artifacts/{req_short}/{ticket_short}/playtest_log"
    globs:
      - playtest_log.json
  budget:
    max_rounds: 3
    max_seconds: 200
    max_tokens: 20000
---

# H5 试玩

用插件 Action `h5_playtest` 对**当前 git 仓库**做一次运行时门禁。

不是 GameBox 那套独立 Vite 沙箱：不另开 DATA_DIR，不常驻 Dev Server。

## 和 SOP fragment 的关系

`sop/fragments/h5_playtest.yaml` 负责插在 development 之后（priority 低于 tsc）、`reject_goto: development`。本 skill 与 fragment 同 `stage_id`，组装器跳过插入。

## 执行步骤

1. 确认 `repo_path` 有 `package.json` / `index.html`。
2. 调用一次 `h5_playtest`。不要自己起 Vite、不要自己拼 http.server。
3. `status=success` 结束；`playtest_failed` 把 `errors` 交回，不要在本阶段重试。
4. `runtime_skipped` 表示没装 Playwright，只保证 build 过。
