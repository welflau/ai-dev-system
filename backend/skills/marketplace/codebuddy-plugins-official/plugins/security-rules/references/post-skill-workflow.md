# 技能使用上报工作流（参考文档）

> 引用方：skills/csig-code-security/SKILL.md（第 1 层、第 2 层）

## 上报架构：双保障机制

本插件采用**双保障**上报架构，确保使用数据的完整收集：

| 层级 | 机制 | 可靠性 | 说明 |
|------|------|--------|------|
| **第 1 层：AI 主动上报** | SKILL.md 中内联 execute_command | 中高 | AI 在技能加载和代码生成时主动调用 report.py |
| **第 2 层：Stop Hook 兜底** | hooks/hooks.json > Stop Hook | 极高 | 框架级保障，会话结束时自动执行 report_hook.py |

### 为什么需要双保障？

- AI 主动上报可能因上下文过长、模型跳过、用户中断等原因不触发
- Stop Hook 由框架自动调度，不依赖 AI 的推理决策，始终会执行
- 后端通过 `action` 字段区分上报来源（`load`/`code_generation` 为 AI 主动上报，`hook_fallback` 为兜底上报）

---

## 插件根目录

**`${CODEBUDDY_PLUGIN_ROOT}`**：由框架对 skill/hook 内容自动替换为插件安装的绝对路径。

**目录结构**：
```
${CODEBUDDY_PLUGIN_ROOT}/
├── rules/                          ← 安全规则目录
├── scripts/
│   ├── report.py                   ← 主上报脚本
│   └── report_hook.py              ← Stop Hook 兜底上报脚本
├── hooks/
│   └── hooks.json                  ← Stop Hook 声明
├── skills/
│   └── csig-code-security/
│       └── SKILL.md
├── safe-functions/
└── references/
    └── post-skill-workflow.md      ← 当前文件
```

---

## AI 主动上报（SKILL.md 内联）

SKILL.md 中直接内联 execute_command 命令，AI 在执行技能时主动调用：

### 技能加载上报

**触发时机**：第 1 层通用规则加载完成后

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/report.py" load \
  --language <语言> \
  --rules <规则列表> \
  --path <工作目录>
```

### 代码生成上报

**触发时机**：第 2 层代码生成完成后，与代码写入**并行**执行

```bash
python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/report.py" code_generation \
  --language <语言> \
  --rules <规则列表> \
  --safe-functions <安全函数指南> \
  --code-lines <代码行数> \
  --path <工作目录>
```

---

## Stop Hook 兜底上报（框架自动触发）

声明在 `hooks/hooks.json` 中，AI 会话停止时由框架自动执行 `report_hook.py`。

- 始终 exit 0，不阻止 Agent 停止
- 发送 `action: "hook_fallback"` 事件
- 后端可据此统计 AI 主动上报的遗漏率

---

## 上报服务配置

上报服务地址和认证 Token 硬编码在 `scripts/report.py` 中：

| 配置项 | 值 | 位置 |
|---------|------|------|
| 上报 URL | `http://21.214.71.122/api/v1/security-skill/report` | `get_report_url()` |
| 认证 Token | 硬编码在 `get_report_token()` 中 | `get_report_token()` |

> 如需修改上报地址或 Token，直接编辑 `scripts/report.py` 中对应函数即可。
