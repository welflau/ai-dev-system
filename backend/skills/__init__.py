"""
Skills 注入系统 — 给 Agent 动态挂载专业领域知识

对标 MagicAI 的 Skills 机制（src/agents/game_agent/utils/skill_loader.py）。
核心思路：一个 .md 文件 = 一个 Skill；通过 skills.json 配置挂给哪些 Agent。
Agent 启动时把适用的 Skills 拼成一段 prompt，运行 Action 时通过 ContextVar
透明注入到 ActionNode 的 system prompt 开头。

详见 docs/20260420_01_Skills注入系统实现方案.md
"""
from contextvars import ContextVar

# 当前 Action 执行上下文中的 Skills prompt 文本。
# BaseAgent.run_action() 在调 action.run() 前 set，finally 里 reset。
# ActionNode._compile() 读取并 prepend 到 LLM prompt 开头。
# asyncio 原生支持 ContextVar，并发安全。
_current_skills: ContextVar[str] = ContextVar("current_skills", default="")

from skills.loader import SkillLoader

# 单例：进程启动时加载一次 skills.json，之后全局共享
skill_loader = SkillLoader()

__all__ = ["skill_loader", "_current_skills", "SkillLoader"]
