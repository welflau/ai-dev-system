# 开发日志 — 2026-05-07 UE MCP Phase 2：Editor 进程控制 + 构建日志持久化

## 功能概述

在 v0.20 UE MCP Phase 1-5 基础上，完善了「交付 & 环境」页面的 UE 工作流体验。

**验收截图**：

Editor 进程卡片显示「编译」+「启动 Editor」双按钮，最近构建列表正常出现 ubt_compile 记录。

---

## 交付内容

### 1. Editor 进程卡片双按钮

**截图中效果**：Editor 进程卡片底部显示 `▲ 编译` + `▶ 启动 Editor` 两个按钮。

**状态逻辑**：
- `dll_exists=false`：`[🔨 编译]`（可点）+ `[▶ 启动 Editor]`（禁用灰色）
- `dll_exists=true`：`[🔨 编译]`（可点）+ `[▶ 启动 Editor]`（蓝色可点）
- `ucp_connected=true`：显示 `● 已连接（UCP 9876）`

**后端**（`ci/strategies/ue.py`）：
`editor_live` 环境状态新增 `dll_exists` 字段，检测 `Binaries/Win64/UnrealEditor-*.dll`。

### 2. 启动 Editor 带 SSE 日志

点「▶ 启动 Editor」后，实时日志面板推进度：
```
[editor] 正在启动 UE Editor: UnrealEditor.exe TestTPS.uproject
[editor] 引擎版本: UE 5.7.2 [launcher]
[editor] 首次加载约 30-120 秒（shader 编译），请耐心等待…
[editor] 等待 Editor 加载… (25s)
✅ [editor] UE Editor 已就绪！UCP 插件已连接（9876），编辑态 AI 控制可用
```

后台 `_poll_ucp_ready()` 每 5 秒探测 9876，连上后推 `ue_editor_connected` SSE 事件 → 前端 Toast 通知 + 自动刷新页面。

**后端**（`api/ue_framework.py`）：
- `POST /ue-framework/editor-launch`：后台 Popen 启动 Editor + SSE 推日志 + 异步轮询 UCP

### 3. 基线编译走 CI 策略（在最近构建里留记录）

原来「跑基线编译」直接跑 `UECompileCheckAction`，不留记录。

**修改后**：委托给 `CI策略.trigger_build("ubt_compile")`，与手动点「UBT 编译」按钮完全一致——结果出现在「最近构建」，可点「详情」查日志。

### 4. 构建完整日志持久化

原来 `raw_output_tail` 只存最后 8KB，日志"被冲掉"。

**修改后**：
- `ci_builds` 加 `log_file_path` 列
- 构建完成后把完整 stdout 写到 `data/build_logs/{build_id}.log`
- 新增 `GET /ci/builds/{id}/log` 端点
- 详情弹窗底部加「📄 完整日志」链接（新 Tab 打开）

### 5. UCP 插件安装流程完整跑通

- `propose_ue_framework` 卡片加「🤖 启用编辑态 AI 控制（UCP 插件）」复选框
- `InstantiateUETemplateAction` 从 `backend/ue_plugins/` 快照 copy 到 `Plugins/`
- `InstantiateRequest` 加 `install_ucp: bool` 字段（之前漏了，今天修复）

### 6. main.py 启动时清除所有 __pycache__

反复遇到旧 `.pyc` 缓存导致代码改了不生效的问题。

**修改**：`main.py` 启动时自动 `shutil.rmtree(__pycache__)` 所有目录，彻底解决。

---

## 问题排查

### 问题：install_ucp 不生效

**现象**：勾选 UCP 复选框确认生成后，Plugins 目录没有 UCP。

**根因**：`InstantiateRequest` Pydantic 模型里没有 `install_ucp` 字段，前端发的参数被忽略了；context 构建时也没透传。

**修复**：在 `InstantiateRequest` 加字段，在 context 里加 `"install_ucp": req.install_ucp`。

### 问题：旧 .pyc 导致修复不生效

**现象**：改代码、重启服务器，日志里还是旧行为。每次都需要手动删除对应 `.pyc` 才生效。

**根因**：`uvicorn --reload` 有时不会清除旧 `.pyc`，Python 直接用字节码缓存。

**修复**：`main.py` 启动时自动清除所有 `__pycache__`。

### 问题：基线编译 3s「up to date」但 Editor 仍报模块加载失败

**现象**：UBT 编译 3s 就完成了（up to date），但启动 Editor 时报「game module could not be loaded」。

**根因**：加入 UCP 插件后，项目的构建配置变化，但 UBT 检查认为已是最新（可能是 hash 匹配逻辑）。DLL 实际上是在没有 UCP 的状态下编译的，Editor 加载时发现不一致。

**解决**：先点「编译」按钮跑一次完整编译，重新生成包含 UCP 依赖的 DLL，再启动 Editor。

---

## 文件变更

| 文件 | 变更 |
|---|---|
| `backend/main.py` | 启动时清除所有 `__pycache__` |
| `backend/api/ue_framework.py` | `InstantiateRequest` 加 `install_ucp`；`baseline-compile` 走 CI 策略；新增 `editor-launch`（含日志+轮询）|
| `backend/ci/strategies/ue.py` | `editor_live` 状态加 `dll_exists`；构建完整 log 写文件 |
| `backend/database.py` | `ci_builds` 加 `log_file_path` 列 |
| `backend/api/ci.py` | 新增 `GET /ci/builds/{id}/log` 端点 |
| `frontend/app.js` | Editor 卡片双按钮；`ue_editor_connected` SSE 监听；完整日志链接 |

## commits

- `c29ee0e` feat: CI 构建完整日志持久化 + 详情面板「完整日志」按钮
- `4bd0d19` feat: Editor 进程卡片加「启动 Editor」按钮
- `b5174ed` feat: Editor 启动 SSE 日志 + UCP 就绪通知
- `006888a` feat: Editor 进程卡片加「编译」+「启动」双按钮
