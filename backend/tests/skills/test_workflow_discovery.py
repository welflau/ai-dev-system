"""x-workflow 解析与 skill 发现机制的单测。

两件事：
  1. `parse_workflow_skill` —— frontmatter 的 x-workflow 块 → WorkflowSkill
  2. `discover_workflow_skills` —— 扫目录 + kind lint + stage_id 去重

发现机制是组装器的前置：没有它只能按已知 id 加载，无法「扫出所有带 x-workflow
的 skill 再排序」。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.3
"""
from pathlib import Path

import pytest

from skills.executable_loader import (
    _BUILTIN_ROOT,
    ConsumeSpec,
    ProduceSpec,
    WorkflowSkill,
    _find_skill_dir,
    _project_pack_skill_roots,
    discover_workflow_skills,
    load_executable_skill,
    parse_workflow_skill,
)


def _write_skill(skills_dir: Path, skill_id: str, frontmatter: str, body: str = "正文") -> Path:
    d = skills_dir / skill_id
    d.mkdir(parents=True, exist_ok=True)
    md = d / "SKILL.md"
    md.write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")
    return md


def _wf_fm(stage_id="demo_draft", **extra) -> str:
    """最小可用的 x-workflow frontmatter。"""
    lines = [
        "name: demo",
        "description: 测试用",
        "x-workflow:",
        f"  stage_id: {stage_id}",
        "  consumes: [content_outline]",
        "  produces:",
        "    - {kind: draft_article, glob: draft.md}",
    ]
    for k, v in extra.items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)


# ════════════════════ parse_workflow_skill ════════════════════

def test_parse_minimal_declaration():
    wf = parse_workflow_skill("demo-draft", {
        "name": "草稿",
        "x-workflow": {
            "stage_id": "demo_draft",
            "consumes": ["content_outline"],
            "produces": [{"kind": "draft_article", "glob": "draft.md"}],
        },
    })
    assert wf is not None
    assert wf.skill_id == "demo-draft"          # 目录名可带连字符
    assert wf.stage_id == "demo_draft"          # stage 标识必须蛇形
    assert wf.stage_name == "草稿"              # 回退到 frontmatter.name
    assert wf.consume_kinds == ["content_outline"]
    assert wf.produce_kinds == ["draft_article"]
    assert wf.priority == 50
    assert wf.fanout is False


def test_parse_returns_none_without_x_workflow():
    """没有 x-workflow 的 skill（如 openspec-*）不是 workflow skill，不报错。"""
    assert parse_workflow_skill("x", {"name": "a", "x-runner": {}}) is None
    assert parse_workflow_skill("x", {}) is None


def test_parse_accepts_underscore_alias():
    """YAML 里写 x_workflow 也认（与 x-runner 的 x_runner 别名一致）。"""
    wf = parse_workflow_skill("x", {"x_workflow": {"stage_id": "a_b"}})
    assert wf is not None and wf.stage_id == "a_b"


def test_parse_rejects_missing_stage_id():
    """stage_id 是流程身份，缺了无法生成 SOP stage。"""
    assert parse_workflow_skill("x", {"x-workflow": {"consumes": ["a"]}}) is None


@pytest.mark.parametrize("bad", ["Demo-Draft", "demoDraft", "demo.draft",
                                 "2demo", "_demo", "demo draft"])
def test_parse_rejects_bad_stage_id(bad):
    """stage_id 会直接变成 SOP stage.id 和状态名 `{stage_id}_done`。

    连字符/大写/点号都会让派生出的状态名与 SOP 其它地方的蛇形约定不一致 ——
    orchestrator 按状态名查规则，对不上就是静默卡死。
    """
    assert parse_workflow_skill("x", {"x-workflow": {"stage_id": bad}}) is None


def test_parse_consumes_shorthand_and_full():
    wf = parse_workflow_skill("x", {"x-workflow": {
        "stage_id": "s",
        "consumes": [
            "content_outline",                                    # 简写
            {"kind": "style_guide", "required": False, "mode": "text"},
        ],
    }})
    assert wf.consumes[0] == ConsumeSpec("content_outline", True, "path")
    assert wf.consumes[1] == ConsumeSpec("style_guide", False, "text")
    assert wf.required_consume_kinds == ["content_outline"]


def test_parse_consumes_bad_mode_falls_back_to_path():
    wf = parse_workflow_skill("x", {"x-workflow": {
        "stage_id": "s",
        "consumes": [{"kind": "a", "mode": "telepathy"}],
    }})
    assert wf.consumes[0].mode == "path"


def test_parse_skips_malformed_specs():
    """坏条目跳过但不让整个 skill 出局 —— kind lint 会在下一关兜住真问题。"""
    wf = parse_workflow_skill("x", {"x-workflow": {
        "stage_id": "s",
        "consumes": [None, 42, {"no_kind": 1}, "content_outline"],
        "produces": ["draft_article", {"bad": 1}],
    }})
    assert wf.consume_kinds == ["content_outline"]
    assert wf.produce_kinds == ["draft_article"]


def test_parse_produces_glob_defaults_empty():
    """不写 glob 时为空串 —— _collect_outputs 的 kind 反查会落空但不报错。"""
    wf = parse_workflow_skill("x", {"x-workflow": {
        "stage_id": "s", "produces": ["draft_article"],
    }})
    assert wf.produces[0] == ProduceSpec("draft_article", "")


def test_parse_rejects_non_mapping_required_traits():
    """required_traits 要喂给 _fragment_matches，必须是 all_of/any_of/none_of 映射。"""
    assert parse_workflow_skill("x", {"x-workflow": {
        "stage_id": "s", "required_traits": ["pipeline:content"],
    }}) is None


def test_parse_keeps_trait_and_ticket_filters():
    wf = parse_workflow_skill("x", {"x-workflow": {
        "stage_id": "s",
        "required_traits": {"any_of": ["pipeline:content"]},
        "required_ticket_type": {"none_of": ["bug-fix"]},
    }})
    assert wf.required_traits == {"any_of": ["pipeline:content"]}
    assert wf.required_ticket_type == {"none_of": ["bug-fix"]}


def test_parse_bad_priority_falls_back():
    wf = parse_workflow_skill("x", {"x-workflow": {
        "stage_id": "s", "priority": "high",
    }})
    assert wf.priority == 50


def test_parse_ignores_non_mapping_pipeline_view_contrib():
    wf = parse_workflow_skill("x", {"x-workflow": {
        "stage_id": "s", "pipeline_view_contrib": "testing",
    }})
    assert wf is not None and wf.pipeline_view_contrib is None


# ════════════════════ 目录扫描 ════════════════════

def test_project_pack_roots_cover_four_ide_dirs(tmp_path):
    """ADS 支持四种 IDE 的 pack 目录。

    `_find_skill_dir` 历史上只查 `.claude`，而 ADS 自己的 ConfigPack 装在
    `.codebuddy/packs/`（plugin_scanner.py:13）—— 装进去的 skill 发现不了。
    """
    for cli in ("cursor", "claude", "codebuddy", "workbuddy"):
        (tmp_path / f".{cli}" / "packs" / "p1" / "skills").mkdir(parents=True)
    roots = _project_pack_skill_roots(str(tmp_path))
    assert len(roots) == 4
    assert {r.parent.parent.parent.name for r in roots} == {
        ".cursor", ".claude", ".codebuddy", ".workbuddy"
    }


def test_project_pack_roots_empty_without_repo():
    assert _project_pack_skill_roots("") == []


@pytest.mark.real_builtin_skills
def test_find_skill_dir_prefers_project_over_builtin(tmp_path):
    """同 id 时项目级覆盖内置 —— 允许项目定制内置 skill。"""
    skills = tmp_path / ".codebuddy" / "packs" / "p1" / "skills"
    _write_skill(skills, "openspec-propose", "name: 定制版")

    found = _find_skill_dir("openspec-propose", str(tmp_path))
    assert found is not None
    assert found.parent == skills            # 不是 _BUILTIN_ROOT

    # 无 repo_path 时回退内置
    builtin = _find_skill_dir("openspec-propose")
    assert builtin == _BUILTIN_ROOT / "openspec-propose"


@pytest.mark.real_builtin_skills
def test_load_executable_skill_still_works_after_refactor():
    """_find_skill_dir 被重构过，确认现存 skill 仍能加载（回归保护）。"""
    skill = load_executable_skill("openspec-propose")
    assert skill is not None
    assert skill.output_globs == ["proposal.md", "specs.md", "design.md", "tasks.md"]


# ════════════════════ discover_workflow_skills ════════════════════

def test_discover_builtin_only_finds_nothing_yet():
    """现有 3 个内置 skill（openspec-*）都没有 x-workflow。

    这条同时是「不误报」的保护：发现机制不该把老 skill 当成 workflow skill。
    """
    assert discover_workflow_skills() == []


def test_discover_finds_project_skill(tmp_path):
    skills = tmp_path / ".codebuddy" / "packs" / "demo" / "skills"
    _write_skill(skills, "demo-draft", _wf_fm())

    found = discover_workflow_skills(str(tmp_path))
    assert len(found) == 1
    assert found[0].stage_id == "demo_draft"
    assert found[0].skill_id == "demo-draft"
    assert found[0].source_path is not None


def test_discover_skips_skill_without_x_workflow(tmp_path):
    skills = tmp_path / ".claude" / "packs" / "demo" / "skills"
    _write_skill(skills, "plain", "name: 普通 skill\nx-runner:\n  builtin_tools: [write_file]")
    assert discover_workflow_skills(str(tmp_path)) == []


def test_discover_dedups_by_stage_id_first_wins(tmp_path):
    """同 stage_id 先到先得。

    项目级目录先扫，所以项目定制能覆盖内置同名 stage。
    """
    skills_a = tmp_path / ".cursor" / "packs" / "a" / "skills"
    skills_b = tmp_path / ".workbuddy" / "packs" / "b" / "skills"
    _write_skill(skills_a, "first", _wf_fm("demo_draft"))
    _write_skill(skills_b, "second", _wf_fm("demo_draft"))

    found = discover_workflow_skills(str(tmp_path))
    assert len(found) == 1
    # .cursor 在遍历顺序里先于 .workbuddy
    assert found[0].skill_id == "first"


def test_discover_rejects_unregistered_kind(tmp_path):
    """kind lint 第 1 道闸：拼错的 kind 让 skill 出局。

    不拦的后果：下游 consumes 永远匹配不上 → 静默少跑一步，无任何报错。
    """
    skills = tmp_path / ".codebuddy" / "packs" / "demo" / "skills"
    _write_skill(skills, "typo", "\n".join([
        "name: typo",
        "x-workflow:",
        "  stage_id: typo_stage",
        "  consumes: [content_outlne]",          # 少个 i
        "  produces: [draft_article]",
    ]))
    assert discover_workflow_skills(str(tmp_path)) == []


def test_discover_rejects_producing_inline_kind(tmp_path):
    """produces inline kind（老 Agent 路径的产物）是静默断链。"""
    skills = tmp_path / ".codebuddy" / "packs" / "demo" / "skills"
    _write_skill(skills, "bad", "\n".join([
        "name: bad",
        "x-workflow:",
        "  stage_id: bad_stage",
        "  produces: [prd]",
    ]))
    assert discover_workflow_skills(str(tmp_path)) == []


def test_discover_rejects_self_loop(tmp_path):
    """自环会让**整条** skill 链因检出环而全部不组装。"""
    skills = tmp_path / ".codebuddy" / "packs" / "demo" / "skills"
    _write_skill(skills, "loop", "\n".join([
        "name: loop",
        "x-workflow:",
        "  stage_id: loop_stage",
        "  consumes: [content_outline]",
        "  produces: [content_outline]",
    ]))
    assert discover_workflow_skills(str(tmp_path)) == []


def test_discover_allows_consuming_legacy_kind(tmp_path):
    """反向允许：新 skill 读老产物（内容 skill 参考 PRD）是合理需求。"""
    skills = tmp_path / ".codebuddy" / "packs" / "demo" / "skills"
    _write_skill(skills, "reads-prd", "\n".join([
        "name: reads-prd",
        "x-workflow:",
        "  stage_id: reads_prd",
        "  consumes:",
        "    - {kind: prd, mode: text}",
        "  produces: [content_outline]",
    ]))
    found = discover_workflow_skills(str(tmp_path))
    assert len(found) == 1
    assert found[0].consume_kinds == ["prd"]


def test_discover_tolerates_broken_skill_md(tmp_path):
    """一个坏文件不该让整次扫描失败 —— 其它 skill 仍要被发现。"""
    skills = tmp_path / ".codebuddy" / "packs" / "demo" / "skills"
    (skills / "broken").mkdir(parents=True)
    (skills / "broken" / "SKILL.md").write_text(
        "---\nname: [unclosed\n---\n", encoding="utf-8"
    )
    _write_skill(skills, "good", _wf_fm())

    found = discover_workflow_skills(str(tmp_path))
    assert [w.stage_id for w in found] == ["demo_draft"]


def test_discover_ignores_dir_without_skill_md(tmp_path):
    skills = tmp_path / ".codebuddy" / "packs" / "demo" / "skills"
    (skills / "empty-dir").mkdir(parents=True)
    _write_skill(skills, "good", _wf_fm())
    assert len(discover_workflow_skills(str(tmp_path))) == 1


def test_discover_multiple_skills_across_packs(tmp_path):
    """多个 pack 的 skill 一起发现（组装器需要全集才能建图）。"""
    for pack, sid in (("p1", "demo_outline"), ("p2", "demo_draft")):
        skills = tmp_path / ".codebuddy" / "packs" / pack / "skills"
        _write_skill(skills, f"s-{sid}", _wf_fm(sid))

    found = discover_workflow_skills(str(tmp_path))
    assert {w.stage_id for w in found} == {"demo_outline", "demo_draft"}
