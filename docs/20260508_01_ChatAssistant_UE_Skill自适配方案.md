# ChatAssistant × UE Skill 自适配方案

> 日期：2026-05-08
> 前置文档：`20260506_UE_MCP_实施方案.md`
> 状态：设计确定，待实现

---

## 背景

`backend/ue_plugins/UnrealClientProtocol/Skills/` 目录下有 21 个 SKILL.md，覆盖 UE Editor 的 Actor 管理、蓝图编辑、材质、Niagara、建模等操作。这些 Skill 原本是为 Claude Code CLI 设计的（Claude 读文件 + 调 Bash 执行 UCP.py），不在当前 Python 后端的 `skills.json` 体系内，无法被聊天助手使用。

---

## 问题根因

现有设计把「知识」和「执行」绑定在一起：

```
知识  →  写 prompt.md + 注册 skills.json   （每个 Skill 都要）
执行  →  写 Action + tool_schema            （每个新操作都要）
```

每来一个新 Skill 都需要开发适配，无法扩展。

---

## 解决思路：知识与执行解耦

```
知识  →  AI 运行时动态读取 SKILL.md（不预注册，按需加载）
执行  →  少数几个通用工具覆盖大类操作（一次实现，永久复用）
```

### 核心逻辑

用户说「用这个 Skill 帮我列出场景里的 Actor」，AI 自己完成三步：

```
① read_local_file(skill路径)  → 读到 SKILL.md 内容
② 从文档里理解 API（object / function / params）
③ ue_call(object, function, params)  → 执行并返回结果
```

整个过程不需要为每个新 Skill 写代码，AI 自己做适配。

---

## 需要新增的两个工具

### 1. `ReadLocalFileAction`

让 ChatAssistant 能读取本地文件（Skill 文档、项目配置等）。

```python
tool_schema = {
    "name": "read_local_file",
    "description": "读取本地文件内容，用于加载 Skill 文档、配置文件等",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件绝对路径"}
        },
        "required": ["path"]
    }
}
```

**安全约束**：只允许读白名单目录（`ue_plugins/`、项目 `docs/`、`skills/` 等），禁止读 `.env`、凭证文件。

### 2. `UECallAction`

让 ChatAssistant 能执行任意 UCP 命令（通用执行层）。

```python
tool_schema = {
    "name": "ue_call",
    "description": "向正在运行的 UE Editor 发送 UCP 命令（需 Editor 开着且 UCP 插件已启用）",
    "input_schema": {
        "type": "object",
        "properties": {
            "object":   {"type": "string", "description": "UObject 路径，如 /Script/UnrealEd.Default__EditorActorSubsystem"},
            "function": {"type": "string", "description": "UFunction 名，如 GetAllLevelActors"},
            "params":   {"type": "object", "description": "参数（可选）"}
        },
        "required": ["object", "function"]
    }
}
```

内部复用 `UEEditorControlAction` 的 TCP 逻辑（`_ucp_call`），`editor_not_running` 时返回友好提示。

---

## 完整数据流

```
用户："用 F:\...\unreal-actor-editing\SKILL.md 列出场景里所有 Actor"
        ↓
AI 调 read_local_file(path) → 读到 SKILL.md 全文
        ↓
AI 理解：GetAllLevelActors 在 /Script/UnrealEd.Default__EditorActorSubsystem
        ↓
AI 调 ue_call(
    object  = "/Script/UnrealEd.Default__EditorActorSubsystem",
    function= "GetAllLevelActors"
)
        ↓
UECallAction → TCP → UCP 9876 → UE Editor
        ↓
返回 Actor 列表 → AI 整理成中文回答
```

---

## 扩展性

这个模式对同类协议的所有 Skill 都适用，无需重复开发：

| Skill 类型 | 执行工具 | 新增开发成本 |
|---|---|---|
| 所有 UCP Skill（现在 21 个，未来更多） | `ue_call` | 一次 |
| HTTP API 类 Skill | `fetch_url`（已有） | 零 |
| Git 操作类 Skill | `git_*`（已有） | 零 |
| 新协议类 Skill | 加对应通用工具 | 一次 |

---

## 实现步骤

| # | 任务 | 文件 | 工时 |
|---|---|---|---|
| 1 | 新建 `ReadLocalFileAction`（含安全白名单） | `actions/chat/read_local_file.py` | 2h |
| 2 | 新建 `UECallAction`（复用 TCP 逻辑） | `actions/chat/ue_call.py` | 3h |
| 3 | 注册到 `ChatAssistantAgent.action_classes` | `agents/chat_assistant.py` | 0.5h |
| 4 | traits 过滤：`ue_call` 仅 engine:ue5/ue4 暴露 | `agents/chat_assistant.py` | 0.5h |
| 5 | `editor_not_running` 友好提示 | `actions/chat/ue_call.py` | 0.5h |
| 6 | 联调测试 | — | 1h |

**合计约 1 天**。

---

## 与现有 DevAgent/TestAgent 的关系

`UEEditorControlAction`（已有）继续供 DevAgent/TestAgent 使用，走工单流程。`UECallAction`（新建）是 ChatAssistant 专用，走对话流程。两者共享 TCP 通信逻辑，不冲突。
