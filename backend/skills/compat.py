"""SKILL.md 跨 Client 兼容性分析。

外部 CLI 目录（.cursor / .claude / .codebuddy / .workbuddy）里的 Skill 能被我们
扫到，不等于能照原样跑：格式（frontmatter + markdown）是通用的，但正文里经常点名
宿主自己的工具名和运行时设施。LLM 读到一个不存在的工具名，要么去找、找不到后瞎编，
要么静默走 fallback —— 两种都比"提前标出来"糟。

这里按四档分类，只做静态文本判断，不猜语义：

  native    带 x-runner，是我们自己的可执行 Skill 格式，SkillRunner 能直接驱动
  portable  纯知识型，没有外部工具/运行时依赖，正文塞进 prompt 即可
  degraded  点名了别家的工具名（AskQuestion / TodoWrite …），能读但那几步会失效
  host_only 依赖宿主运行时（cursor-agent CLI / Background Agent / Bugbot …），
            或声明了 IDE surface —— 脱离原 Client 基本没有意义

判断保守优先：宁可标 portable 漏掉一个边缘依赖，也不要把大量纯文档 Skill 误标成
不可用（那样标识就没人看了）。所以只匹配高信号的专有名词，不匹配 Read/Write/Bash
这类各家都有的通用工具名。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

# ── 别家的工具名 → (归属 Client, 人类可读说明) ───────────────────────
# 只收"我们没有对应实现"的专有工具。Read/Write/Edit/Glob/Grep/Bash 这类通用名
# 故意不收：几乎每个 Skill 都会提，收了等于全员 degraded，标识失去区分度。
_FOREIGN_TOOLS: Dict[str, Tuple[str, str]] = {
    "AskQuestion":      ("cursor", "Cursor 交互提问工具"),
    "todo_write":       ("cursor", "Cursor 待办工具"),
    "AskUserQuestion":  ("claude", "Claude Code 交互提问工具"),
    "TodoWrite":        ("claude", "Claude Code 待办工具"),
    "NotebookEdit":     ("claude", "Claude Code Notebook 编辑"),
    "ExitPlanMode":     ("claude", "Claude Code 计划模式"),
    "EnterPlanMode":    ("claude", "Claude Code 计划模式"),
    "SlashCommand":     ("claude", "Claude Code 斜杠命令工具"),
    "ReportFindings":   ("claude", "Claude Code 审查上报工具"),
    "BashOutput":       ("claude", "Claude Code 后台 shell 读取"),
    "KillShell":        ("claude", "Claude Code 后台 shell 终止"),
}

# ── 宿主运行时设施：命中即 host_only ────────────────────────────────
_HOST_RUNTIME: List[Tuple[str, str, str]] = [
    (r"cursor-agent",                  "cursor", "cursor-agent CLI"),
    (r"Background Agents?",            "cursor", "Cursor 后台 Agent"),
    (r"Bugbot",                        "cursor", "Cursor Bugbot 审查服务"),
    (r"\bcursor\s+api\b",              "cursor", "Cursor 云端 API"),
    (r"claude\s+mcp\b",                "claude", "claude CLI mcp 子命令"),
    (r"claude\s+-p\b",                 "claude", "claude CLI headless 调用"),
    (r"\bclaude\s+plugin\b",           "claude", "claude CLI plugin 子命令"),
]

# ── 子 Agent / 并行编排：我们没有对等能力，算 degraded ───────────────
_SUBAGENT_HINTS: List[Tuple[str, str]] = [
    (r"\bTask tool\b",        "子 Agent 派发（Task）"),
    (r"\bsubagents?\b",       "子 Agent 编排"),
    (r"\bAgent tool\b",       "子 Agent 派发（Agent）"),
]

_COMPAT_LABELS = {
    "native":    "原生可执行",
    "portable":  "可直接用",
    "degraded":  "部分依赖",
    "host_only": "宿主专有",
}

# 正文里带 ``` 代码块时，工具名常出现在示例里；不做区分（示例里的依赖同样是依赖）。
_FM_RE = re.compile(r"^---\r?\n(.*?)\r?\n---", re.S)


def _frontmatter_block(content: str) -> str:
    m = _FM_RE.match(content or "")
    return m.group(1) if m else ""


def _fm_flag(fm_text: str, key: str) -> bool:
    """frontmatter 里 `key: true` —— 只认顶层的裸 key，不进嵌套。"""
    for line in fm_text.splitlines():
        if line[:1] in (" ", "\t", "-"):
            continue
        m = re.match(rf"^{re.escape(key)}\s*:\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip().strip("\"'").lower() in ("true", "yes", "1")
    return False


def analyze_skill_compat(content: str, cli: str = "") -> Dict[str, Any]:
    """静态分析一份 SKILL.md，判断能否脱离原 Client 直接使用。

    content 可以是截断过的正文（调用方通常只留前 4000 字符）—— 依赖声明基本都在
    开头的 frontmatter 和前几节里，截断对判断影响很小。

    返回 dict，可直接合并进 skill 条目：
        compat / compat_label / compat_reasons / foreign_tools / foreign_clients
    """
    text = content or ""
    fm = _frontmatter_block(text)

    reasons: List[str] = []
    foreign_tools: List[str] = []
    clients: List[str] = []

    def _note_client(c: str) -> None:
        if c and c != cli and c not in clients:
            clients.append(c)

    # x-runner 是我们自己的可执行格式，优先级最高：认它就不用再猜可移植性
    if re.search(r"^x-runner\s*:", fm, re.M):
        return {
            "compat": "native",
            "compat_label": _COMPAT_LABELS["native"],
            "compat_reasons": ["声明了 x-runner，SkillRunner 可直接驱动"],
            "foreign_tools": [],
            "foreign_clients": [],
            "manual_only": _fm_flag(fm, "disable-model-invocation"),
        }

    host_only = False

    # 1. 宿主运行时设施
    for pat, owner, desc in _HOST_RUNTIME:
        if re.search(pat, text, re.I):
            host_only = True
            _note_client(owner)
            if desc not in reasons:
                reasons.append(f"依赖{desc}")

    # 2. IDE surface：这类 Skill 改的是编辑器自身设置，脱离 IDE 没有意义
    if re.search(r"surfaces\s*:", fm) and re.search(r"-\s*ide\b", fm):
        host_only = True
        _note_client(cli)
        reasons.append("声明 surfaces: ide，作用对象是编辑器本身")

    # 3. 别家的专有工具名
    for token, (owner, desc) in _FOREIGN_TOOLS.items():
        if re.search(rf"\b{re.escape(token)}\b", text):
            foreign_tools.append(token)
            _note_client(owner)
            if desc not in reasons:
                reasons.append(f"引用 {token}（{desc}）")

    # 4. 子 Agent 编排
    for pat, desc in _SUBAGENT_HINTS:
        if re.search(pat, text, re.I):
            if desc not in reasons:
                reasons.append(f"依赖{desc}")
            break

    # 5. disable-model-invocation：语义是"禁止模型自动触发，只能显式调用"。
    #    注入链路已认这个字段（单独归到「仅用户显式点名」分组），所以不算兼容性缺陷，
    #    只作为一个独立标记暴露出去，不进 reasons、不拉低档位。
    manual_only = _fm_flag(fm, "disable-model-invocation")

    if host_only:
        compat = "host_only"
    elif reasons:
        compat = "degraded"
    else:
        compat = "portable"

    return {
        "compat": compat,
        "compat_label": _COMPAT_LABELS[compat],
        "compat_reasons": reasons,
        "foreign_tools": foreign_tools,
        "foreign_clients": clients,
        "manual_only": manual_only,
    }
