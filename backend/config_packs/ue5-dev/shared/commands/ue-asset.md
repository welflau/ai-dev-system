---
description: 用 AI 生成图片并导入 UE，或将资产库中已有图片导入 UE Content Browser
---

# /ue-asset

管理 AI 生图与 UE 资产导入的全流程。支持两种模式：
- **生成并导入**：描述画面 → AI 生图（LightAI）→ 自动导入 UE
- **导入已有资产**：从 `art_assets` 库中选取已生成的图片，导入 UE Content Browser

## 用法

```
/ue-asset generate <图片描述> [--ue-path <路径>] [--name <资产名>] [--engine gemini|jimeng|midjourney]
/ue-asset import <asset_id> [--ue-path <路径>] [--name <资产名>]
/ue-asset list [--type ai_generated|pexels] [--limit 10]
```

## 行为

### 模式一：generate（生成并导入）

1. 调用 `POST /api/image-gen` 提交生图请求，引擎默认 `gemini`
2. 轮询 `GET /api/image-gen/{req_id}` 直到 `status=done`（超时 300s）
3. 取得 `result` 中的 `asset_id`，调用 MCP tool `ue_import_asset`：
   ```
   ue_import_asset(
     asset_id  = <req_id>,
     project_id = <当前项目 ID>,
     ue_dest_path = <--ue-path 参数，默认 /Game/Textures/AI>,
     asset_name   = <--name 参数，默认自动生成 T_{短ID}>,
   )
   ```
4. 展示导入结果（UE 内部路径 + 本地文件路径）

### 模式二：import（导入已有资产）

1. 若未指定 `asset_id`，调用 `GET /api/art-assets?source=ai_generated&limit=10` 列出最近生成的图片供选择
2. 调用 MCP tool `ue_import_asset`：
   ```
   ue_import_asset(
     asset_id  = <asset_id>,
     project_id = <当前项目 ID>,
     ue_dest_path = <--ue-path 参数，默认 /Game/Textures/AI>,
     asset_name   = <--name 参数>,
   )
   ```
3. 展示 UE 内部路径

### 模式三：list（查看可导入资产）

调用 `GET /api/art-assets?source=ai_generated` 列出资产库中 AI 生成的图片，显示：
- asset_id、文件名、生成时间
- `ue_path`（非空表示已导入 UE，显示路径）

## 前提条件

- UE Editor 已启动
- Editor 已启用 Remote Execution Server：  
  `Project Settings → Plugins → Python → Enable Remote Execution Server`
- `ART_ASSETS_LOCAL_PATH` 已配置（图片需有本地文件才能导入）

## 资产命名规范

遵循 `rules.md` 中 UE 资产命名约定：
- 纹理：`T_<描述>_<类型后缀>`（如 `T_Forest_D`、`T_UI_Button_01`）
- 留空时系统自动生成 `T_{asset_id 前8位}`

## 示例

```
# 生成一张森林场景纹理并导入
/ue-asset generate 茂密森林地面，湿润土壤与落叶，俯视图 --ue-path /Game/Environment/Textures --name T_Forest_Ground_D

# 生成 UI 背景图并导入
/ue-asset generate 赛博朋克风格 HUD 背景，深蓝色渐变 --ue-path /Game/UI/Textures --engine jimeng

# 导入已有资产（知道 ID）
/ue-asset import IMG-abc12345 --ue-path /Game/Textures/Characters

# 列出最近 AI 生成的图片
/ue-asset list --limit 20

# 查看哪些资产已导入 UE
/ue-asset list --type ai_generated
```

## 错误处理

| 错误 | 原因 | 解决方式 |
|------|------|----------|
| `UE Editor 未启动` | Editor 未运行或 Remote Execution 未开 | 先启动 Editor，开启 Remote Execution Server |
| `资产无本地文件` | `ART_ASSETS_LOCAL_PATH` 未配置 | 在 `.env` 中配置 `ART_ASSETS_LOCAL_PATH` |
| `ue_dest_path 须以 /Game/ 开头` | 路径格式错误 | 改为 `/Game/Textures/AI` 等合法路径 |
| `导入超时` | 大文件或 Editor 繁忙 | 等待片刻后重试，或手动拖入 Content Browser |
