# ChatAssistant × UCP Skill 自适配实现记录

> 日期：2026-05-08
> 关联设计文档：`20260508_ChatAssistant_UE_Skill自适配方案.md`
> 状态：已完成

---

## 背景

`backend/ue_plugins/UnrealClientProtocol/Skills/` 下有 24 个 SKILL.md，原本是为 Claude Code CLI 设计的（Claude 读文件 + 调 Bash 执行 UCP.py）。本次改造让聊天助手在 UE 项目里无需用户指定路径，即可自动发现并使用这些 Skill 操控 UE Editor。

---

## 改动文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `actions/chat/read_local_file.py` | 新建 | 读本地文件工具，含安全白名单 |
| `actions/chat/ue_call.py` | 新建 | 通用 UCP TCP 执行工具 |
| `agents/chat_assistant.py` | 修改 | 注册两个新 Action + traits 过滤 |
| `skills/loader.py` | 修改 | 新增 `scan_dir` 类型支持 |
| `skills/skills.json` | 修改 | 新增 `unreal-ucp-skills` 条目 |

---

## 核心设计：知识与执行解耦

```
旧思路：每个 Skill 写 prompt.md + 注册 + 写 Action（每次都要开发）
新思路：知识动态加载 + 通用执行工具（一次实现，永久复用）
```

### 自动注入流程（UE 项目启动对话时）

```
项目 traits 包含 engine:ue5
    ↓
SkillLoader.build_prompt_for_agent("ChatAssistant", traits=[...])
    ↓
命中 unreal-ucp-skills（type: scan_dir）
    ↓
扫描 ue_plugins/UnrealClientProtocol/Skills/*/SKILL.md
读取每个文件的 frontmatter（name + description）
    ↓
生成索引表注入 system prompt（~8KB，包含 24 个 Skill 的名称/描述/绝对路径）
```

### 对话时执行流程

```
用户："列出当前场景所有 Actor"
    ↓
AI 在 system prompt 里看到 unreal-actor-editing 的路径
    ↓
AI 调 read_local_file(path) → 读取 SKILL.md 全文
    ↓
AI 理解 API：GetAllLevelActors 在 /Script/UnrealEd.Default__EditorActorSubsystem
    ↓
AI 调 ue_call(object=..., function="GetAllLevelActors")
    ↓
TCP → UCP 9876 → UE Editor → 返回 Actor 列表
```

---

## 新增工具说明

### `read_local_file`

- 读取白名单目录内的任意本地文件（`ue_plugins/`、`skills/`、`docs/`、`sop/`）
- 禁止读取凭证类文件（`.env`、`.pem`、含 `secret/token/password` 的文件名）
- 最大返回 12000 字符，超出截断
- 对所有项目类型可用（无 traits 限制）

### `ue_call`

- 直接接受 UCP JSON 格式：`object / function / params`
- 内部 TCP 连接 `127.0.0.1:9876`，4 字节小端长度帧协议
- `available_for_traits = {any_of: ["engine:ue5", "engine:ue4"]}`，仅 UE 项目暴露
- Editor 未开或插件未启用时返回明确的操作指引

### traits 过滤增强

`_exposed_tool_schemas()` 新增了对 `action.available_for_traits` 的检查：

```python
action_traits_cfg = getattr(action, "available_for_traits", None)
if action_traits_cfg and traits is not None:
    from actions.base import _match_traits
    if not _match_traits(action_traits_cfg, set(traits)):
        continue
```

---

## SkillLoader 扩展：scan_dir 类型

`skills.json` 新增条目格式：

```json
{
  "unreal-ucp-skills": {
    "type": "scan_dir",
    "scan_dir": "../ue_plugins/UnrealClientProtocol/Skills",
    "header": "...",
    "inject_to": ["ChatAssistant"],
    "traits_match": { "any_of": ["engine:ue5", "engine:ue4"] }
  }
}
```

`SkillLoader._build_scan_dir_prompt()` 的生成逻辑：

1. 扫描目录下所有 `*/SKILL.md`
2. 解析 frontmatter 取 `name` + `description`（超 120 字截断）
3. 拼装 Markdown 索引表（含绝对路径）
4. 附加使用说明（先 read_local_file，再 ue_call）

服务重启时自动重扫，新增 Skill 无需任何配置改动。

---

## 扩展性

同一协议的新 Skill 只需放入 `ue_plugins/Skills/<新目录>/SKILL.md`，重启生效，零维护成本。

其他协议类 Skill 若需接入，只需：
1. 加对应通用执行 Action 一次（如 `maya_call`、`blender_call`）
2. 在 `skills.json` 加 `scan_dir` 条目

不需要为每个 Skill 单独开发适配代码。

---

## 验证结果

```
UE 项目（engine:ue5）：
  ✅ system prompt 自动包含 24 个 Skill 索引（~8321 字符）
  ✅ ue_call 工具暴露给 LLM
  ✅ read_local_file 工具暴露给 LLM

非 UE 项目（platform:web）：
  ✅ system prompt 不含 UCP 索引
  ✅ ue_call 工具不暴露
```
