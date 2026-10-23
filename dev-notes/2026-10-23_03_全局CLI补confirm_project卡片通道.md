# 全局 CLI 补 confirm_project 卡片通道

2026-10-23

前作：`dev-notes/2026-10-23_02_H5试玩门禁不对仓库另开沙箱.md`

## 起因

用 codebuddy 全局聊天建 Phaser H5 项目时，模型说「这就出卡片」，界面没有确认卡。它后来自己诊断：CLI 只看到 ads-data MCP 的 `confirm_requirement` / `confirm_bug` / `confirm_direct_ticket`，没有 `confirm_project`；口头 `[ACTION:]` 也没走到解析器。

## 实现

不跳过确认卡、不直接 POST `/api/projects`。

1. `ads-data` 增加 `confirm_project`，POST `/api/chat/mcp-action`
2. 该端点跑 `ConfirmProjectAction`，只产草稿
3. QueryEngine `_synthesize_confirm_action` 识别 `mcp__ads-data__confirm_project`，流式 `ActionEvent` 出卡
4. 全局 prompt 禁止「出卡片却不调工具」和「跳过卡片直接建项目」

## 怎么测

新开一条全局对话，说「新建 Phaser H5 贪吃蛇，直接出确认卡片」。应出现确认卡，traits 含 `framework:phaser`。点确认后再开工单测 `h5_typecheck` / `h5_playtest`。
