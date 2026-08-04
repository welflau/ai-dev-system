"""
ExecutableSkillLoader — 加载"可执行 skill"（带 x-runner 扩展的 SKILL.md）。

与普通 skill（skills/loader.py，注入 prompt 的静态知识）不同，可执行 skill 声明了
一组工具（CLI/内置/MCP）+ 任务目标，交给 SkillRunner 驱动 LLM 自主调用工具完成。

SKILL.md frontmatter 复用普通格式（name/description 等），额外挂一个 `x-runner`
命名空间：
    x-runner:
      version: 1
      availability: [has_openspec]          # capability_check.* 函数名，全 True 才可用
      cli_tools:
        - name: openspec_new_change
          command_template: "{cli} new change {change_id} --description {desc} --goal {goal}"
          description: 创建 change 目录
          timeout: 60
          free_slots: []                     # 可选：显式声明 LLM 可填的槽（默认自动推断）
      builtin_tools: [write_file]            # write_file / shell / mcp__server__tool
      outputs:
        root: "openspec/changes/{change_id}"
        globs: ["proposal.md", "specs.md", "design.md", "tasks.md"]
      budget: {max_rounds: 12, max_seconds: 300, max_tokens: 120000}

来源优先级：项目级 `.claude/packs/*/skills/<id>/SKILL.md` > backend 内置
`backend/skills/executable_skills/<id>/SKILL.md`。MVP 只用 backend 内置。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("skills.executable_loader")

# backend 内置可执行 skill 根目录
_BUILTIN_ROOT = Path(__file__).resolve().parent / "executable_skills"

# 从 command_template 抠 {占位符}
_SLOT_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


@dataclass
class CliToolSpec:
    """一条声明过的 CLI 命令 → 一个 LLM 工具。"""
    name: str
    command_template: str
    description: str = ""
    timeout: int = 60
    # LLM 可填的自由槽（未声明时 = 模板槽 - context 预填槽，运行时推断）
    free_slots: Optional[List[str]] = None

    def template_slots(self) -> List[str]:
        """模板里所有 {占位符}（去重保序）。"""
        seen: List[str] = []
        for m in _SLOT_RE.finditer(self.command_template):
            if m.group(1) not in seen:
                seen.append(m.group(1))
        return seen


@dataclass
class ExecutableSkill:
    skill_id: str
    name: str
    description: str
    body: str                                  # SKILL.md 正文 → 给 LLM 的 system
    source_path: Path
    availability: List[str] = field(default_factory=list)
    cli_tools: List[CliToolSpec] = field(default_factory=list)
    builtin_tools: List[str] = field(default_factory=list)
    outputs: Dict[str, Any] = field(default_factory=dict)   # {root, globs}
    budget: Dict[str, Any] = field(default_factory=dict)     # {max_rounds, max_seconds, max_tokens}

    @property
    def output_globs(self) -> List[str]:
        return list(self.outputs.get("globs") or [])

    @property
    def output_root_template(self) -> str:
        return self.outputs.get("root") or ""

    @property
    def expected_output_count(self) -> int:
        return len(self.output_globs)


def _find_skill_dir(skill_id: str, repo_path: str = "") -> Optional[Path]:
    """按来源优先级定位 <id>/SKILL.md 所在目录。"""
    candidates: List[Path] = []
    # 项目级 .claude/packs/*/skills/<id>/
    if repo_path:
        packs = Path(repo_path) / ".claude" / "packs"
        if packs.is_dir():
            for pack in packs.iterdir():
                d = pack / "skills" / skill_id
                if (d / "SKILL.md").is_file():
                    candidates.append(d)
    # backend 内置
    builtin = _BUILTIN_ROOT / skill_id
    if (builtin / "SKILL.md").is_file():
        candidates.append(builtin)
    return candidates[0] if candidates else None


def _parse_cli_tools(raw: Any) -> List[CliToolSpec]:
    tools: List[CliToolSpec] = []
    for item in (raw or []):
        if not isinstance(item, dict) or not item.get("name") or not item.get("command_template"):
            logger.warning("跳过无效 cli_tool 声明: %r", item)
            continue
        tools.append(CliToolSpec(
            name=str(item["name"]),
            command_template=str(item["command_template"]),
            description=str(item.get("description") or ""),
            timeout=int(item.get("timeout") or 60),
            free_slots=list(item["free_slots"]) if isinstance(item.get("free_slots"), list) else None,
        ))
    return tools


def load_executable_skill(skill_id: str, repo_path: str = "") -> Optional[ExecutableSkill]:
    """加载可执行 skill；找不到或无 x-runner 返回 None。"""
    skill_dir = _find_skill_dir(skill_id, repo_path)
    if not skill_dir:
        logger.info("可执行 skill 未找到: %s（repo=%s）", skill_id, repo_path or "-")
        return None

    md_path = skill_dir / "SKILL.md"
    try:
        text = md_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning("读 %s 失败: %s", md_path, e)
        return None

    # 复用普通 loader 的 frontmatter 解析（yaml.safe_load + body 分离）
    from skills.loader import _parse_frontmatter
    fm, body = _parse_frontmatter(text)
    runner = fm.get("x-runner") or fm.get("x_runner")   # 容忍下划线写法
    if not isinstance(runner, dict):
        logger.info("skill %s 无 x-runner 声明，非可执行 skill", skill_id)
        return None

    return ExecutableSkill(
        skill_id=skill_id,
        name=str(fm.get("name") or skill_id),
        description=str(fm.get("description") or ""),
        body=body.strip(),
        source_path=md_path,
        availability=[str(x) for x in (runner.get("availability") or [])],
        cli_tools=_parse_cli_tools(runner.get("cli_tools")),
        builtin_tools=[str(x) for x in (runner.get("builtin_tools") or [])],
        outputs=dict(runner.get("outputs") or {}),
        budget=dict(runner.get("budget") or {}),
    )
