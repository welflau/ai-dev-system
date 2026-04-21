"""
SkillLoader — 加载 skills.json 配置并为每个 Agent 构建专业技能 prompt

移植自 MagicAI src/agents/game_agent/utils/skill_loader.py，精简掉 game-agent
特有的部分（codebuddy SDK / MCP 关联），保留核心的：
- 按 inject_to 过滤 Agent
- 按 priority 排序（high > medium > low）
- 读取 prompt.md 内容并拼接成一段 system prompt

配置格式与 MagicAI 完全兼容，MagicAI 的 Skill 包可直接 drop-in 到 packs/ 下。
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("skills")

_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


class SkillLoader:
    """Skills 加载器 — 单例，进程启动时加载一次"""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path(__file__).parent
        self.config_path = self.base_dir / "skills.json"
        self.skills: Dict[str, dict] = {}
        # 缓存每个 Agent 的拼接结果，避免重复读文件
        self._agent_prompt_cache: Dict[str, str] = {}
        self._load_config()

    def _load_config(self) -> None:
        """从 skills.json 读取配置；文件不存在时静默跳过（skills 是可选能力）"""
        if not self.config_path.exists():
            logger.info("skills.json 不存在，Skills 系统未启用")
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.skills = json.load(f)
        except Exception as e:
            logger.warning("加载 skills.json 失败: %s", e)
            self.skills = {}
            return

        enabled = [k for k, v in self.skills.items() if v.get("enabled", False)]
        logger.info("✅ Skills 已加载: %d 条（启用 %d）", len(self.skills), len(enabled))

    def get_skill_prompt(self, skill_id: str) -> Optional[str]:
        """读取单个 skill 的 prompt.md 内容；禁用 / 文件缺失时返回 None"""
        config = self.skills.get(skill_id)
        if not config or not config.get("enabled", False):
            return None

        prompt_rel = config.get("prompt_file")
        if not prompt_rel:
            logger.warning("Skill '%s' 未配置 prompt_file", skill_id)
            return None

        prompt_file = self.base_dir / prompt_rel
        if not prompt_file.exists():
            logger.warning("Skill '%s' 的 prompt 文件不存在: %s", skill_id, prompt_file)
            return None

        try:
            return prompt_file.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.warning("读取 Skill '%s' 失败: %s", skill_id, e)
            return None

    def get_skills_for_agent(self, agent_type: str) -> List[str]:
        """返回指定 Agent 适用的 skill_id 列表，按 priority 排序"""
        applicable = [
            skill_id
            for skill_id, cfg in self.skills.items()
            if cfg.get("enabled", False) and agent_type in cfg.get("inject_to", [])
        ]
        return sorted(
            applicable,
            key=lambda sid: _PRIORITY_ORDER.get(self.skills[sid].get("priority", "medium"), 1),
        )

    def build_prompt_for_agent(self, agent_type: str) -> str:
        """聚合一个 Agent 的所有 Skills → 一段可注入到 system prompt 的文本。
        空字符串表示这个 Agent 没有挂任何 Skill。"""
        if agent_type in self._agent_prompt_cache:
            return self._agent_prompt_cache[agent_type]

        skill_ids = self.get_skills_for_agent(agent_type)
        if not skill_ids:
            self._agent_prompt_cache[agent_type] = ""
            return ""

        sections: List[str] = []
        loaded_ids: List[str] = []
        for sid in skill_ids:
            content = self.get_skill_prompt(sid)
            if content:
                name = self.skills[sid].get("name", sid)
                sections.append(f"<!-- Skill: {sid} ({name}) -->\n{content}")
                loaded_ids.append(sid)

        if not sections:
            self._agent_prompt_cache[agent_type] = ""
            return ""

        prompt = "\n\n---\n\n".join(sections)
        self._agent_prompt_cache[agent_type] = prompt
        logger.info("🎓 %s 加载 %d 个 Skill: %s", agent_type, len(loaded_ids), ", ".join(loaded_ids))
        return prompt

    def get_enabled_skills(self) -> Dict[str, dict]:
        """返回所有启用的 Skills 配置（供调试 / 后续只读 API）"""
        return {k: v for k, v in self.skills.items() if v.get("enabled", False)}

    def get_all_skills_status(self) -> Dict[str, dict]:
        """每个 Skill 的状态（enabled / prompt 文件存在 / inject_to 列表）"""
        status = {}
        for sid, cfg in self.skills.items():
            prompt_rel = cfg.get("prompt_file", "")
            prompt_file = self.base_dir / prompt_rel if prompt_rel else None
            status[sid] = {
                "name": cfg.get("name", sid),
                "description": cfg.get("description", ""),
                "enabled": cfg.get("enabled", False),
                "inject_to": cfg.get("inject_to", []),
                "priority": cfg.get("priority", "medium"),
                "prompt_exists": bool(prompt_file and prompt_file.exists()),
            }
        return status

    def print_status(self) -> str:
        """格式化状态输出（供调试 / 命令行）"""
        status = self.get_all_skills_status()
        if not status:
            return "Skills: (未配置 skills.json)"
        lines = ["Skills 状态:", "-" * 50]
        for sid, info in status.items():
            mark = "✅" if info["enabled"] and info["prompt_exists"] else "❌"
            lines.append(f"{mark} {sid} — {info['name']}")
            lines.append(f"   注入到: {', '.join(info['inject_to']) or '(无)'}")
            lines.append(f"   优先级: {info['priority']}  |  Prompt: {'OK' if info['prompt_exists'] else 'MISSING'}")
        return "\n".join(lines)

    def reload(self) -> None:
        """重新读取 skills.json（供未来动态刷新使用）"""
        self.skills = {}
        self._agent_prompt_cache.clear()
        self._load_config()
