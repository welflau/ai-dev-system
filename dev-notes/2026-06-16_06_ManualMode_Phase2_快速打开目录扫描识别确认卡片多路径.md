# ManualMode Phase2 — 快速打开目录：扫描识别 + 确认卡片 + 多路径配置

> 日期：2026-06-16
> 系列：ManualMode
> 关联文档：`docs/20260616_02_手动挡模式与多路径项目设计方案.md`
> 前置：`dev-notes/2026-06-16_05_ManualMode_Phase1_...`

---

## 验证截图

![打开本地目录确认卡片](assets/manual-mode-open-dir-20260616.png)

用户在 AI 助手发送 `F:\A_Works\BigShot`，系统自动识别：
- 项目名：**Bigbanana Ai Director**（从 package.json 读取）
- Git 仓库：`https://git.woa.com/AnimResearch/AI/BigShot.git`
- 检测到路径：`F:\A_Works\BigShot`（git 管理）
- 运行模式选择器：手动挡 / 自动挡
- 预计组装展示 SOP 流程 + Skill 注入 + MCP

弹出橙色确认卡片，用户点击「✅ 确认创建」即完成项目创建。

---

## 背景

Phase 1 搭建了 P4管理器、VCS检测、手动挡开关基础设施。
Phase 2 实现「快速打开目录」：用户在 AI 助手对话框发送路径，系统自动识别项目信息，弹出确认卡片，一键创建手动挡项目。

---

## 新增端点

### `POST /api/projects/scan-directory`

接收 `{"path": "F:\\ADS_Projects\\MyGame"}`，返回：

```json
{
  "already_exists": false,
  "path": "F:/ADS_Projects/MyGame",
  "project_name": "MyGame",
  "root_vcs": "p4",
  "git_repo_path": null,
  "p4_info": {"client": "MyWorkspace", "server": "perforce:1666"},
  "extra_paths": [
    {"path": "F:/ADS_Projects/MyGame/Source", "vcs": "git", "auto_detected": true, "writable": true},
    {"path": "F:/ADS_Projects/MyGame/Content", "vcs": "p4", "auto_detected": false, "writable": true},
    {"path": "F:/UE5/Engine", "vcs": "git", "auto_detected": true, "writable": false, "label": "UE 引擎 (5.4)"}
  ],
  "engine_path": "F:/UE5/Engine",
  "traits": ["platform:desktop", "category:game", "engine:ue5", "lang:cpp"],
  "suggested_preset": "ue5-game",
  "tech_stack": "Unreal Engine 5, C++",
  "suggested_mode": "manual"
}
```

如果路径已是现有项目，返回 `{"already_exists": true, "project_id": "...", "project_name": "..."}`。

识别逻辑（按优先级）：
1. 项目名：`.uproject` 文件名 > `package.json.name` > 目录名
2. VCS：`detect_vcs()` 检测根目录
3. 多路径：`scan_project_paths()` 扫描 Source/Content/Config/Plugins 子目录
4. UE 引擎路径：从 `.uproject` 的 `EngineAssociation` 读取，搜索常见安装位置
5. traits：调用现有 `ProjectTypeDetectorAction`
6. 推荐模式：有现有代码 → manual，否则 → auto

### `PATCH /api/projects/{id}/mode`

切换项目运行模式：`{"mode": "manual"}` 或 `{"mode": "auto"}`。

### `PATCH /api/projects/{id}/extra-paths`

更新多路径配置：`{"extra_paths": [...]}`。

---

## 改动文件

### `backend/actions/chat/confirm_project.py`

扩展 `ConfirmProjectAction`，支持两种使用场景：

**场景1：打开本地目录**（新增）
- `local_path` 有值时，调用 `scan-directory` API 自动识别
- 如果已有项目，返回 `switch_project` 类型动作
- 否则返回含 `mode / extra_paths / p4_info / engine_path_warning` 的 `confirm_project` 卡片

**场景2：新建项目**（原有逻辑保留）
- `git_remote_url` 必填，traits 必填

`tool_schema` 的 `required` 改为空数组，两种场景都能触发。

### `backend/actions/chat/create_project.py`

`proj_data` 新增 `mode` 和 `extra_paths` 字段，从 context 读取并存库。

### `backend/api/chat.py`

`ConfirmCreateProjectRequest` 新增两个可选字段：
- `mode: str = "auto"`
- `extra_paths: List[Dict] = []`
- `git_remote_url` 改为可选（手动挡打开本地目录时可能无远程 URL）

### `frontend/app.js`

**`_renderConfirmProjectCard(action)` 全面扩展**：
- 手动挡卡片左边框改为橙黄色（`--warning`），更直观区分
- 展示多路径列表（git绿/p4橙/none灰色标签，只读标注）
- 展示 P4 client 和 server 信息
- 引擎路径未找到时显示警告
- 新增模式选择器（单选：手动挡/自动挡）
- `data-extra-paths` 和 `data-mode` 属性存储识别结果

**`doConfirmProject(cardId)` 扩展**：
- 读取用户选择的 mode（从 radio button）
- 提交时携带 `mode` 和 `extra_paths`
- Toast 提示包含模式信息

---

## 用户体验流程

```
用户输入：F:\ADS_Projects\MyGame
    ↓ AI 识别到路径，调用 confirm_project(local_path=...)
    ↓ 后端 scan-directory 扫描（~1-2秒）
    ↓ 前端渲染橙色卡片：
      「📂 检测到本地项目，是否创建？」
       项目名：MyGame
       本地路径：F:\ADS_Projects\MyGame
       P4 Client: MyWorkspace · perforce:1666
       路径：Content (p4) / Source (git, 自动识别) / Engine (git, 只读)
       Traits: platform:desktop, category:game, engine:ue5...
       模式：● 手动挡  ○ 自动挡
      [✅ 确认创建]  [✗ 取消]
    ↓ 用户点击确认
    ↓ 项目创建，mode=manual，extra_paths 存库
    ↓ 进入项目，对话中直接修改文件，不自动 commit
```

---

## 验证

重启服务后：
```bash
curl -X POST http://localhost:8000/api/projects/scan-directory \
  -H "Content-Type: application/json" \
  -d '{"path": "F:/ADS_Projects/MyGame"}'
```
返回识别结果，包含 traits、extra_paths、suggested_mode。

前端：在 AI 助手输入 `F:\ADS_Projects\MyGame` → 出现橙色确认卡片 → 点击创建 → 项目 mode=manual。

---

## 调试过程中的 Bug 修复

### Bug 1：CLI 模式 system prompt 被截断为 500 字
**文件**：`backend/llm_client.py` `_messages_to_prompt()`  
**原因**：`system_text = content[:500]` 截掉了所有判断规则  
**修复**：去掉截断，完整传入 system prompt

### Bug 2：QueryEngine CLI 分支完全忽略 system 参数
**文件**：`backend/query_engine/engine.py`  
**原因**：CLI 分支调用 `_call_cli_stream(current_messages)` 时没有把 `system` 拼入 messages  
**修复**：
```python
cli_messages = [{"role": "system", "content": system}] + current_messages
async for ev in self.llm._call_cli_stream(cli_messages, ...):
```

### Bug 3：路径识别触发后前端不显示卡片
**文件**：`backend/api/chat.py` + `frontend/app.js`  
**原因1**：后端 `_asyncio` 未 import 就使用，导致 UnboundLocalError  
**原因2**：前端气泡设置了 `display:none`，只有收到 `text_delta` 才显示，纯 action 响应时气泡一直隐藏  
**修复**：
- 后端：在路径拦截分支里先 `import asyncio`，save_message 移到 yield 前
- 前端：`finalAction` 存在时强制 `bubbleWrapper.style.display = ''`

### Bug 4：chat.py f-string 中反斜杠导致 SyntaxError
**文件**：`backend/agents/chat_assistant.py`  
**原因**：system prompt f-string 里写了 `F:\MyGame`，`\M` 被 Python 解析为 unicode 转义  
**修复**：改为 `F:/MyGame`（正斜杠示例）

### 最终方案：后端预处理拦截路径
CLI 模式不支持 tool_use，AI 无法主动调用 `confirm_project`。  
最终改为**后端在接收消息时正则检测路径**，直接调 `scan-directory` 返回 action 卡片，**不经过 LLM 判断**，100% 可靠。
