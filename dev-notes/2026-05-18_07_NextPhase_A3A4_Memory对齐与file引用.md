# NextPhase A-3/A-4：Memory 对齐 + @file 引用展开

> 系列：NextPhase  
> 日期：2026-05-18  
> 提交：`4403a4f`（A-3）、`577ab22`（A-4）

---

## A-3：Memory 4 类型对齐（对标 Claude Code）

### 类型映射

| 新类型（Claude Code 对齐）| 旧类型（自动映射）| 表情 | 说明 |
|---|---|---|---|
| `user_profile` | `user` | 👤 | 用户角色、偏好、知识背景 |
| `behavior_feedback` | `insight` | 💬 | 行为反馈（正向确认或纠正）|
| `project_context` | `project`、`technical`、`decision` | 📁 | 项目决策、里程碑、技术方案 |
| `external_ref` | — | 🔗 | 外部资源指针（Linear/文档链接）|

### MEMORY.md 索引样式注入

**之前**：
```
## 项目历史记忆（最近 3 条）
  [decision] 选择 Phaser 3 框架（2026-05-14）
```

**现在**（MEMORY.md 样式）：
```
## 项目记忆（MEMORY）

- [📁 项目] **选择 Phaser 3 框架**（2026-05-14）
  考虑了 Godot/Unity 后选择 Phaser 3，因为轻量且前端友好
- [👤 用户] **用户偏好：代码注释用中文**（2026-05-15）
- [💬 反馈] **不要 mock 数据库**（2026-05-16）
  之前测试通过但 prod 失败，必须真实 DB

如需完整记忆请调用 get_memory 工具。
```

### 改动

- `actions/chat/memory_write.py`：枚举扩充到 4 类，旧值自动映射
- `agents/base.py`：`_MEMORY_TYPE_LABELS` + `get_memory_prompt()` 更新为 MEMORY.md 格式，limit 3→5
- `agents/chat_assistant.py`：Memory 注入改为调用 `BaseAgent.get_memory_prompt`

---

## A-4：@file 引用展开（对标 Claude Code `@include`）

**用法**：在消息中输入文件路径，前面加 `@`：
```
帮我分析这个崩溃日志 @G:/A_Works/OG2/BUG/2026-05-14_Crash/修复方案.md
对比这两个文件：@./src/main.py 和 @./src/utils.py
```

**工作原理**：
```
用户消息（含 @file）
  ↓ api/chat.py _expand_file_refs()
  ├─ 识别所有 @/path 语法
  ├─ 读取文件（限 100KB）
  ├─ 注入为 markdown 附件块
  └─ 失败的引用显示警告
  ↓ 展开后的消息 → LLM
```

**安全限制**：
- 文件大小上限：100KB
- 禁止：`.pem`、`.key`、`.pfx`、`.p12` 密钥文件

**前端**：输入 `@` 后显示 3 秒提示气泡告知用法。
