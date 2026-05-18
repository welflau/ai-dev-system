# NextPhase A-1：Commands 斜杠命令系统

> 系列：NextPhase（ADS 下一阶段综合升级）  
> 日期：2026-05-18  
> 提交：`e973507`  
> 对应计划：`docs/20260518_04_ADS下一阶段综合开发计划.md` 方向 A-1

---

## 背景

ADS 之前只有 `/test` 一个调试命令。Claude Code 有 ~50 个斜杠命令，用户可以直接触发任意操作无需经过 LLM 识别意图。

本次实现了完整的 Commands 机制，作为后续所有斜杠命令（UE 创作、管理操作等）的基础框架。

---

## 实现内容

### 后端：`backend/api/commands.py`

**架构**：
```
GET  /api/commands                       ← 列出所有命令（前端补全用）
POST /api/commands/{name}                ← 执行全局命令
POST /api/projects/{pid}/commands/{name} ← 执行项目命令
```

**命令分发器**：`_dispatch_command()` 路由到对应处理函数，支持：
- 内置命令（硬编码）
- 磁盘命令（`skills/commands/*.md` 定义，自动加载）

**7 个初始命令**：

| 命令 | 功能 | 状态 |
|---|---|---|
| `/compact` | 手动触发历史压缩 | ✅ 通知前端 |
| `/memory [query]` | 查询 Agent 记忆 | ✅ 直接查 DB |
| `/think <on/off/adaptive>` | 切换 thinking 模式 | ✅ 写 Feature Flags |
| `/skills` | 查看已加载 Skills | ✅ 调 skill_loader |
| `/ue-run <code>` | UE Editor 执行 Python | ⚠️ 待 B-0 桥接 |
| `/ue-bp-gen <desc>` | 生成 Blueprint | ⚠️ 待 B-1 实现 |
| `/ue-level <desc>` | 生成关卡 | ⚠️ 待 B-2 实现 |

### 磁盘命令：`backend/skills/commands/*.md`

YAML frontmatter 定义元信息，任何人可新增 `.md` 文件来扩展命令：
```yaml
---
description: 命令描述
args_hint: "<参数提示>"
requires_project: true/false
---
```

### 前端：`frontend/app.js`

**斜杠拦截**（`handleChatKeydown`）：
- 输入 `/xxx args` 按 Enter → 拦截，不走 LLM → 调后端 `/api/commands/xxx`

**实时补全**（`_onChatInputChange`）：
- 输入 `/` 开头时，请求 `/api/commands` 加载命令列表
- 显示下拉补全框，点击填充到输入框

**结果渲染**（`_handleSlashCommand`）：
- 显示「正在执行」提示
- 完成后展示结果气泡（成功绿色边框，失败红色边框）

---

## 使用方式

**Ctrl+Shift+F5 刷新后**，在聊天框输入：

```
/memory          → 查看当前项目记忆
/memory 波次     → 搜索含"波次"的记忆
/think on        → 强制开启推理链
/think adaptive  → 自适应模式（默认）
/compact         → 触发历史压缩
/skills          → 查看已加载 Skills
```

输入 `/` 会弹出补全建议框。

---

## 扩展方式

新增命令只需：
1. 在 `backend/skills/commands/` 新建 `xxx.md`（定义元信息）
2. 在 `backend/api/commands.py` 的 `handlers` 字典加 `"xxx": _cmd_xxx`
3. 实现 `async def _cmd_xxx(args, project_id, context) -> CommandResult`

---

## 下一步

- **A-2**：Thinking 三态模式 + ultrathink 关键字（`/think` 命令依赖）
- **B-0**：UE Python 桥接（`/ue-run` 命令依赖）
- **B-1**：BlueprintGenAction（`/ue-bp-gen` 命令依赖）
