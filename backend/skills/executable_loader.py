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

来源优先级：项目级 pack > ``backend/plugins/*/skills/<id>/`` > backend 内置
``backend/skills/executable_skills/<id>/SKILL.md``。
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


def _project_pack_skill_roots(repo_path: str) -> List[Path]:
    """项目级 skill 的 `skills/` 父目录们，按 IDE 目录约定展开。

    ADS 支持四种 IDE 的 pack 目录（见 api/projects.py:3066 的同款遍历）。
    `_find_skill_dir` 历史上只查了 `.claude`，装在 `.codebuddy/packs/` 下的
    skill 根本发现不了 —— 而 ADS 自己的 ConfigPack 装的正是 `.codebuddy`
    （plugin_scanner.py:13）。这里统一成四种都扫。
    """
    roots: List[Path] = []
    if not repo_path:
        return roots
    for cli in ("cursor", "claude", "codebuddy", "workbuddy"):
        packs = Path(repo_path) / f".{cli}" / "packs"
        if not packs.is_dir():
            continue
        try:
            for pack in sorted(packs.iterdir()):
                skills_dir = pack / "skills"
                if skills_dir.is_dir():
                    roots.append(skills_dir)
        except OSError as e:
            logger.warning("扫描 pack 目录失败 %s: %s", packs, e)
    return roots


def _plugin_skill_dirs() -> List[Path]:
    """插件 skill 目录。失败时降级为空列表，不让发现机制整体挂掉。"""
    try:
        from plugins.registry import iter_plugin_skill_dirs
        return list(iter_plugin_skill_dirs())
    except Exception as e:
        logger.warning("扫描插件 skill 失败: %s", e)
        return []


def _find_skill_dir(skill_id: str, repo_path: str = "") -> Optional[Path]:
    """按来源优先级定位 <id>/SKILL.md 所在目录。项目级 > 插件 > backend 内置。"""
    for skills_dir in _project_pack_skill_roots(repo_path):
        d = skills_dir / skill_id
        if (d / "SKILL.md").is_file():
            return d
    for d in _plugin_skill_dirs():
        if d.name == skill_id and (d / "SKILL.md").is_file():
            return d
    builtin = _BUILTIN_ROOT / skill_id
    if (builtin / "SKILL.md").is_file():
        return builtin
    return None


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


# =============================================================================
# v0.20 x-workflow：能力自描述 + 发现机制
#
# `load_executable_skill` 只能按**已知 id** 加载。组装器要「扫出所有带
# x-workflow 的 skill，按数据依赖排序」，必须先有发现函数。
#
# x-workflow 与 x-runner 的分工：
#   x-runner   —— 「怎么执行」：工具集、产出 glob、预算、可用性
#   x-workflow —— 「在流程里是谁」：stage 身份、consumes/produces 数据契约、
#                  适用什么项目
# 前者已存在（20260802 方案），后者是本次新增。
#
# 方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.3
# =============================================================================

# stage_id 命名规范：小写蛇形。它会直接变成 SOP stage.id 和状态名
# （{stage_id}_done / {stage_id}_failed），含连字符或大写会让状态名不一致。
_STAGE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass
class ConsumeSpec:
    """一条 consumes 声明。

    mode 决定 injector 怎么把产物递给 LLM：
      path（默认）— 只给路径，让 LLM 用 read_file 自取。二进制和大文件唯一可行方式
      text        — 额外读全文塞 prompt（上限 8000 字符），小文件且必读时用
      both        — 同 text（保留字面量，语义等同）
    """
    kind: str
    required: bool = True
    mode: str = "path"

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "required": self.required, "mode": self.mode}


@dataclass
class ProduceSpec:
    """一条 produces 声明。glob 必须是 x-runner.outputs.globs 里的某一条 ——
    SkillRunner._collect_outputs 靠 {glob: kind} 反查给产出文件归类。"""
    kind: str
    glob: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "glob": self.glob}


@dataclass
class WorkflowSkill:
    """一个「自带工作流身份」的 skill。

    skill_id 与 stage_id 分开：前者是文件系统标识（目录名，可带连字符如
    `demo-outline`），后者是流程标识（SOP stage.id，必须蛇形如 `demo_outline`）。
    不强制相等是因为状态名由 stage_id 派生，而目录名习惯用连字符。
    """
    skill_id: str
    stage_id: str
    stage_name: str
    description: str = ""
    consumes: List[ConsumeSpec] = field(default_factory=list)
    produces: List[ProduceSpec] = field(default_factory=list)
    required_traits: Optional[Dict[str, Any]] = None
    required_ticket_type: Any = None
    priority: int = 50
    fanout: bool = False                        # 预留：阶段内扁出子工单
    pipeline_view_contrib: Optional[Dict[str, Any]] = None
    source_path: Optional[Path] = None

    @property
    def consume_kinds(self) -> List[str]:
        return [c.kind for c in self.consumes]

    @property
    def produce_kinds(self) -> List[str]:
        return [p.kind for p in self.produces]

    @property
    def required_consume_kinds(self) -> List[str]:
        return [c.kind for c in self.consumes if c.required]


def _parse_consumes(raw: Any) -> List[ConsumeSpec]:
    """支持简写 `- content_outline` 和全写 `- {kind: ..., required: false}`。"""
    out: List[ConsumeSpec] = []
    for item in (raw or []):
        if isinstance(item, str):
            out.append(ConsumeSpec(kind=item))
            continue
        if isinstance(item, dict) and item.get("kind"):
            mode = str(item.get("mode") or "path")
            if mode not in ("path", "text", "both"):
                logger.warning("consumes mode 非法 %r，退回 path", mode)
                mode = "path"
            out.append(ConsumeSpec(
                kind=str(item["kind"]),
                required=bool(item.get("required", True)),
                mode=mode,
            ))
            continue
        logger.warning("跳过无效 consumes 声明: %r", item)
    return out


def _parse_produces(raw: Any) -> List[ProduceSpec]:
    out: List[ProduceSpec] = []
    for item in (raw or []):
        if isinstance(item, str):
            out.append(ProduceSpec(kind=item))
            continue
        if isinstance(item, dict) and item.get("kind"):
            out.append(ProduceSpec(
                kind=str(item["kind"]), glob=str(item.get("glob") or ""),
            ))
            continue
        logger.warning("跳过无效 produces 声明: %r", item)
    return out


def parse_workflow_skill(
    skill_id: str, fm: Dict[str, Any], source_path: Optional[Path] = None,
) -> Optional[WorkflowSkill]:
    """从 frontmatter 解析 x-workflow 块。无声明或结构错 → None。

    结构错一律 ERROR 级 + 返回 None（该 skill 出局）。原因同 kinds.py 的三道闸：
    warning 没人看，静默降级等于没有校验 —— trait_taxonomy.yaml 就是这么漂的。
    """
    wf = fm.get("x-workflow") or fm.get("x_workflow")   # 容忍下划线写法
    if not isinstance(wf, dict):
        return None

    stage_id = str(wf.get("stage_id") or "").strip()
    if not stage_id:
        logger.error("❌ skill %s 的 x-workflow 缺 stage_id，出局", skill_id)
        return None
    if not _STAGE_ID_RE.match(stage_id):
        logger.error(
            "❌ skill %s 的 stage_id='%s' 不符合命名规范（小写蛇形 %s）—— "
            "它会直接变成 SOP stage.id 和状态名 %s_done，出局",
            skill_id, stage_id, _STAGE_ID_RE.pattern, stage_id,
        )
        return None

    try:
        priority = int(wf.get("priority", 50))
    except (TypeError, ValueError):
        logger.warning("skill %s 的 priority=%r 非整数，用默认 50",
                       skill_id, wf.get("priority"))
        priority = 50

    rt = wf.get("required_traits")
    if rt is not None and not isinstance(rt, dict):
        logger.error("❌ skill %s 的 required_traits 必须是映射，实际 %s，出局",
                     skill_id, type(rt).__name__)
        return None

    pvc = wf.get("pipeline_view_contrib")
    if pvc is not None and not isinstance(pvc, dict):
        logger.warning("skill %s 的 pipeline_view_contrib 非映射，忽略", skill_id)
        pvc = None

    return WorkflowSkill(
        skill_id=skill_id,
        stage_id=stage_id,
        stage_name=str(wf.get("stage_name") or fm.get("name") or stage_id),
        description=str(wf.get("description") or fm.get("description") or ""),
        consumes=_parse_consumes(wf.get("consumes")),
        produces=_parse_produces(wf.get("produces")),
        required_traits=rt,
        required_ticket_type=wf.get("required_ticket_type"),
        priority=priority,
        fanout=bool(wf.get("fanout")),
        pipeline_view_contrib=pvc,
        source_path=source_path,
    )


def _iter_skill_dirs(repo_path: str = "") -> List[Path]:
    """所有候选 skill 目录，**项目级在前**（同 stage_id 时覆盖插件 / 内置）。"""
    dirs: List[Path] = []
    for skills_dir in _project_pack_skill_roots(repo_path):
        try:
            dirs.extend(d for d in sorted(skills_dir.iterdir()) if d.is_dir())
        except OSError as e:
            logger.warning("扫描 skill 目录失败 %s: %s", skills_dir, e)
    dirs.extend(_plugin_skill_dirs())
    if _BUILTIN_ROOT.is_dir():
        try:
            dirs.extend(d for d in sorted(_BUILTIN_ROOT.iterdir()) if d.is_dir())
        except OSError as e:
            logger.warning("扫描内置 skill 目录失败: %s", e)
    return dirs


def discover_workflow_skills(repo_path: str = "") -> List[WorkflowSkill]:
    """扫出所有带 x-workflow 的 skill，供 compose_workflow_stages 建图。

    扫描范围（与 _find_skill_dir 同一套优先级）：
      <repo>/.{cursor,claude,codebuddy,workbuddy}/packs/*/skills/*/SKILL.md
      backend/plugins/*/skills/*/SKILL.md
      backend/skills/executable_skills/*/SKILL.md

    **kind lint 在这里执行**（三道闸的第 1 道）：consumes/produces 引用未注册
    的 kind、produces 了 inline/builtin kind、自环 —— 任一命中则该 skill 出局
    并打 ERROR。不拦的后果是下游 consumes 永远匹配不上，流水线静默少跑一步。

    stage_id 去重：**先到先得**，项目级先扫所以能覆盖内置同名 skill。
    """
    from artifacts.kinds import lint_kind_refs

    found: Dict[str, WorkflowSkill] = {}       # stage_id → skill
    for skill_dir in _iter_skill_dirs(repo_path):
        md_path = skill_dir / "SKILL.md"
        if not md_path.is_file():
            continue
        try:
            text = md_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning("读 %s 失败: %s", md_path, e)
            continue

        from skills.loader import _parse_frontmatter
        fm, _body = _parse_frontmatter(text)
        if not isinstance(fm, dict):
            continue

        wf = parse_workflow_skill(skill_dir.name, fm, source_path=md_path)
        if wf is None:
            continue

        if wf.stage_id in found:
            logger.info(
                "skill %s 的 stage_id='%s' 已被 %s 占用，跳过（项目级优先）",
                wf.skill_id, wf.stage_id, found[wf.stage_id].skill_id,
            )
            continue

        lint = lint_kind_refs(wf.skill_id, wf.consume_kinds, wf.produce_kinds)
        if not lint.ok:
            for err in lint.errors:
                logger.error("❌ %s（%s）", err, md_path)
            logger.error("❌ skill %s 因 kind 校验失败出局", wf.skill_id)
            continue
        for warn in lint.warnings:
            logger.warning("⚠️ %s", warn)

        found[wf.stage_id] = wf

    if found:
        logger.info("🔍 发现 %d 个 workflow skill: %s",
                    len(found), sorted(found))
    return list(found.values())
