# NextPhase Commands 斜杠命令系统完整验收

> 系列：NextPhase  
> 日期：2026-05-19  
> 提交范围：`e973507`（A-1）→ `6d9bbb2`（键盘操作）

---

## 效果截图

![斜杠命令补全面板](screenshots/20260519_slash_commands.png)

截图说明：
- 输入 `/` 立即弹出所有可用命令补全
- 高亮显示当前选中项（`/compact`）
- 每条命令显示：**命令名**（紫色）+ **参数提示**（蓝色）+ **描述**
- 使用 ↑↓ 键导航，Tab/Enter 补全，Esc 关闭

---

## 完整功能清单

### 可用命令（7 个）

| 命令 | 参数 | 功能 |
|---|---|---|
| `/compact` | — | 手动触发对话历史压缩 |
| `/memory` | `[query]` | 查看或搜索 Agent 记忆 |
| `/skills` | — | 查看当前项目已加载 Skills |
| `/think` | `<on\|off\|adaptive>` | 切换 Extended Thinking 模式 |
| `/ue-bp-gen` | `<描述>` | 生成 Blueprint 并写入 UE Editor |
| `/ue-level` | `<描述>` | 生成并布置 UE 关卡 |
| `/ue-run` | `<python>` | 在 UE Editor 执行 Python 代码 |

### 键盘操作

| 按键 | 行为 |
|---|---|
| `/` | 立即显示所有命令补全 |
| `/m`（任意字母）| 过滤匹配命令 |
| `↑` `↓` | 在建议列表间导航 |
| `Tab` / `Enter` | 补全当前高亮命令 |
| `Esc` | 关闭建议列表 |

### 扩展方式

新增命令只需在 `backend/skills/commands/` 加 `.md` 文件 + 在 `api/commands.py` 加处理函数，服务器重启后自动出现在补全列表。

---

## 调试记录

| 问题 | 原因 | 修复 |
|---|---|---|
| 页面白屏 JS 报错 | `@file` 正则 `/[^\s]*` 中 `/` 未转义 | 改为 `\/[^\s]*` |
| 补全框不显示 | `insertAdjacentElement('beforebegin')` 插在 wrap 外，`position:absolute` 计算错误 | 改为 `afterbegin` 插入 wrap 内，加 `position:relative` |
| 输入 `/` 不触发 | `val.length < 2` 过滤了单字符 `/` | 移除长度限制 |
