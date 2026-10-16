"""compose_sop 与 skill 链的集成测试。

这是「拓扑排序」真正接进生产路径的那一步。关注三件事：
  1. **无 x-workflow skill 时组装结果一字不差**（48 个基线测试的延伸）
  2. skill 子链插在正确位置（branch_only 区块之前 / skill_block_anchor）
  3. 状态链连通 —— relink 后 skill stage 真的能被 orchestrator 调度到

用真实文件（tmp_path 下的 SKILL.md）而非 mock：x-workflow 的解析、kind lint、
拓扑排序、插入位置是一条完整链路，mock 掉任何一环都测不到真实行为。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.4 / §3.5
"""
from pathlib import Path

import pytest

from sop.loader import (
    _skill_block_insert_idx,
    compose_sop,
    invalidate_sop_cache,
    sop_to_transition_rules,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """每个用例前后清缓存 —— compose_sop 带缓存，repo_path 不同 key 不同，
    但 traits 相同的用例会互相命中。"""
    invalidate_sop_cache()
    yield
    invalidate_sop_cache()


def write_skill(repo: Path, skill_id: str, *, stage_id: str,
                consumes=(), produces=(), priority=50,
                traits_line: str = "", extra_lines=()) -> Path:
    """在 repo 的 pack 目录里造一个带 x-workflow 的 SKILL.md。"""
    d = repo / ".codebuddy" / "packs" / "demo" / "skills" / skill_id
    d.mkdir(parents=True, exist_ok=True)

    lines = [
        "---",
        f"name: {skill_id}",
        f"description: {stage_id} 测试用",
        "x-workflow:",
        f"  stage_id: {stage_id}",
        f"  priority: {priority}",
    ]
    if consumes:
        lines.append("  consumes: [" + ", ".join(consumes) + "]")
    if produces:
        lines.append("  produces:")
        for kind, glob in produces:
            lines.append(f"    - {{kind: {kind}, glob: {glob}}}")
    if traits_line:
        lines.append(f"  {traits_line}")
    lines.extend(f"  {x}" for x in extra_lines)
    lines += [
        "x-runner:",
        "  builtin_tools: [write_file]",
        "  outputs:",
        f"    root: \"artifacts/{stage_id}\"",
        "    globs: [" + ", ".join(g for _, g in produces) + "]",
        "---",
        "",
        "执行步骤略。",
    ]
    md = d / "SKILL.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md


def blog_chain(repo: Path, **kw) -> None:
    """三段式内容链，**声明顺序故意反着写**（cover → draft → outline）。"""
    write_skill(repo, "demo-cover", stage_id="demo_cover",
                consumes=["draft_article"],
                produces=[("cover_image", "cover.png")], **kw)
    write_skill(repo, "demo-draft", stage_id="demo_draft",
                consumes=["content_outline"],
                produces=[("draft_article", "draft.md")], **kw)
    write_skill(repo, "demo-outline", stage_id="demo_outline",
                consumes=["ticket_brief"],
                produces=[("content_outline", "outline.md")], **kw)


def ids(cfg) -> list:
    return [s["id"] for s in cfg["stages"]]


# ════════════════ 向后兼容：无 skill 时一字不差 ════════════════

@pytest.mark.parametrize("traits,ticket_type", [
    ([], None),
    (["platform:web"], "feature"),
    (["platform:web", "category:app"], "feature"),
    (["category:game", "engine:ue5"], "feature"),
    (["pipeline:content"], "feature"),
])
def test_no_skills_means_no_change(traits, ticket_type, tmp_path):
    """空 repo（无任何 SKILL.md）→ 组装结果与不传 repo_path 完全一致。

    这是 skill 链接入的**向后兼容契约**：现存 31 个项目一个 workflow skill
    都没有，它们的 SOP 必须一个字节都不变。
    """
    without = compose_sop(traits=traits, ticket_type=ticket_type)
    invalidate_sop_cache()
    with_repo = compose_sop(traits=traits, ticket_type=ticket_type,
                            repo_path=str(tmp_path))
    assert ids(without) == ids(with_repo)
    assert with_repo["composed_from_skills"] == []
    assert with_repo["sop_diagnostics"] == without["sop_diagnostics"]


def test_skill_without_x_workflow_is_ignored(tmp_path):
    """只有 x-runner 的 skill（如 openspec-*）不参与流程组装。"""
    d = tmp_path / ".codebuddy" / "packs" / "p" / "skills" / "plain"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: plain\nx-runner:\n  builtin_tools: [write_file]\n---\n正文\n",
        encoding="utf-8",
    )
    cfg = compose_sop(traits=[], repo_path=str(tmp_path))
    assert cfg["composed_from_skills"] == []


# ════════════════════ 插入位置 ════════════════════

def test_skill_block_inserted_before_branch_only(tmp_path):
    """**硬约束：skill 子链必须在 branch_only 区块之前。**

    `_relink_stage_transitions` 跳过 branch_only 且不让它们参与 prev_success
    传递。插在它们后面的话，skill 的 trigger_on 会被接到最后一个线性 stage
    的 success 上 —— 但列表顺序显示它在 rework 后面，状态链的实际走向与
    列表顺序不符，排查时极易误判。
    """
    blog_chain(tmp_path)
    cfg = compose_sop(traits=[], ticket_type="feature", repo_path=str(tmp_path))
    order = ids(cfg)

    assert order.index("demo_cover") < order.index("rework")
    assert order.index("demo_cover") < order.index("development_retry")
    # 缺省锚点 = 最后一个非 branch_only（deploy）之后
    assert order.index("deploy") < order.index("demo_outline")


def test_skill_chain_topologically_ordered(tmp_path):
    """声明序（cover→draft→outline）≠ 执行序。"""
    blog_chain(tmp_path)
    cfg = compose_sop(traits=[], ticket_type="feature", repo_path=str(tmp_path))
    order = ids(cfg)
    assert (order.index("demo_outline")
            < order.index("demo_draft")
            < order.index("demo_cover"))


def test_insert_idx_respects_anchor_before():
    """skill_block_anchor.insert_before 指定插在某个 base_stage 之前。"""
    composed = [
        {"id": "planning"}, {"id": "acceptance"}, {"id": "deploy"},
        {"id": "rework", "branch_only": True},
    ]
    core = {"skill_block_anchor": {"insert_before": "acceptance"}}
    assert _skill_block_insert_idx(core, composed) == 1


def test_insert_idx_respects_anchor_after():
    composed = [{"id": "planning"}, {"id": "deploy"},
                {"id": "rework", "branch_only": True}]
    core = {"skill_block_anchor": {"insert_after": "planning"}}
    assert _skill_block_insert_idx(core, composed) == 1


def test_insert_idx_falls_back_when_anchor_missing():
    """锚点 stage 被裁剪掉时退回缺省位置，不是追加到最末尾。

    追加到末尾会落在 branch_only 之后 —— 正是上面那条硬约束禁止的。
    """
    composed = [{"id": "planning"}, {"id": "deploy"},
                {"id": "rework", "branch_only": True}]
    core = {"skill_block_anchor": {"insert_before": "development"}}  # 已被裁
    assert _skill_block_insert_idx(core, composed) == 2       # rework 之前


def test_insert_idx_default_is_before_first_branch_only():
    composed = [{"id": "a"}, {"id": "b"},
                {"id": "rework", "branch_only": True},
                {"id": "retry", "branch_only": True}]
    assert _skill_block_insert_idx({}, composed) == 2


def test_insert_idx_no_branch_only_appends():
    composed = [{"id": "a"}, {"id": "b"}]
    assert _skill_block_insert_idx({}, composed) == 2


# ════════════════════ 状态链连通（最关键） ════════════════════

def test_state_chain_is_connected_through_skills(tmp_path):
    """relink 之后整条链（含 skill stage）的 trigger_on 必须都有人产出。

    这是基线测试 T5 不变式在 skill 接入后的延续。断了就是静默卡死：
    orchestrator 把工单推到某状态后找不到下一条规则，不报错、不超时。
    """
    blog_chain(tmp_path)
    cfg = compose_sop(traits=[], ticket_type="feature", repo_path=str(tmp_path))
    stages = cfg["stages"]

    prev_success = None
    for s in stages:
        if s.get("branch_only"):
            continue
        if prev_success is not None:
            assert s["trigger_on"] == prev_success, (
                f"stage {s['id']} 的 trigger_on={s['trigger_on']} "
                f"≠ 上一阶段 success={prev_success}"
            )
        prev_success = s["success_status"]


def test_skill_stages_are_dispatchable(tmp_path):
    """skill stage 必须真的出现在 transition_rules 里，否则调度不到。"""
    blog_chain(tmp_path)
    cfg = compose_sop(traits=[], ticket_type="feature", repo_path=str(tmp_path))
    rules = sop_to_transition_rules(cfg)

    by_id = {s["id"]: s for s in cfg["stages"]}
    for sid in ("demo_outline", "demo_draft", "demo_cover"):
        trigger = by_id[sid]["trigger_on"]
        assert trigger in rules, f"{sid} 的 trigger {trigger} 无规则 → 调度不到"
        assert rules[trigger]["agent"] == "SkillAgent"
        assert rules[trigger]["config"]["skill_id"] == sid.replace("_", "-")


def test_no_retry_rules_derived_for_skill_stages(tmp_path):
    """skill stage 不配 reject_goto → 不该派生失败重试规则。

    有的话 `{stage}_failed → SkillAgent.skill_{stage}` 会让一个 LLM
    自由发挥的 skill 被无限重试，只有全局 max_retries 兜底。
    """
    blog_chain(tmp_path)
    cfg = compose_sop(traits=[], ticket_type="feature", repo_path=str(tmp_path))
    rules = sop_to_transition_rules(cfg)
    for sid in ("demo_outline", "demo_draft", "demo_cover"):
        assert f"{sid}_failed" not in rules


def test_skill_stage_ids_do_not_collide_with_base(tmp_path):
    """stage_id 与 base_stage 重名时跳过并报 ERROR。

    不拦的话 `_find_stage_idx` / `by_action` 的「先到先得」会反查到错误的
    stage —— 比如 `_sop_stage_for('development')` 返回 skill 的那个。
    """
    write_skill(tmp_path, "sneaky", stage_id="development",
                consumes=["ticket_brief"], produces=[("content_outline", "o.md")])
    cfg = compose_sop(traits=[], ticket_type="feature", repo_path=str(tmp_path))

    assert cfg["composed_from_skills"] == []
    assert any("重名" in d for d in cfg["sop_diagnostics"])
    # base 的 development 还在，且仍是 DevAgent
    dev = next(s for s in cfg["stages"] if s["id"] == "development")
    assert dev["agent"] == "DevAgent"


# ════════════════════ 降级行为 ════════════════════

def test_missing_source_prunes_chain(tmp_path):
    """缺源的 skill 出局（这里 demo_draft 的上游 outline 不存在）。"""
    write_skill(tmp_path, "demo-draft", stage_id="demo_draft",
                consumes=["content_outline"],
                produces=[("draft_article", "draft.md")])
    cfg = compose_sop(traits=[], ticket_type="feature", repo_path=str(tmp_path))
    assert cfg["composed_from_skills"] == []
    assert any("无 producer" in d for d in cfg["sop_diagnostics"])


def test_cycle_degrades_to_fragment_only_sop(tmp_path):
    """成环 → 整条 skill 链不组装，但 SOP 的 fragment 部分照常工作。

    这是「整条链不组装」这个激进选择的安全网：退化后仍是一个**可用**的 SOP。
    """
    write_skill(tmp_path, "a", stage_id="stage_a",
                consumes=["ticket_brief", "draft_article"],
                produces=[("content_outline", "o.md")])
    write_skill(tmp_path, "b", stage_id="stage_b",
                consumes=["content_outline"],
                produces=[("draft_article", "d.md")])

    cfg = compose_sop(traits=["platform:web"], ticket_type="feature",
                      repo_path=str(tmp_path))
    assert cfg["composed_from_skills"] == []
    assert any("成环" in d for d in cfg["sop_diagnostics"])
    # fragment 部分完好
    assert "ux_design" in ids(cfg)
    assert "deploy_web" in ids(cfg)


def test_unregistered_kind_keeps_sop_working(tmp_path):
    """kind 拼错的 skill 在 discover 期出局，SOP 其余部分不受影响。"""
    write_skill(tmp_path, "typo", stage_id="typo_stage",
                consumes=["content_outlne"],       # 少个 i
                produces=[("draft_article", "d.md")])
    cfg = compose_sop(traits=["platform:web"], ticket_type="feature",
                      repo_path=str(tmp_path))
    assert cfg["composed_from_skills"] == []
    assert "ux_design" in ids(cfg)


# ════════════════════ trait 过滤透传 ════════════════════

def test_skill_trait_filter_applies(tmp_path):
    blog_chain(tmp_path, traits_line="required_traits: {any_of: [pipeline:content]}")

    off = compose_sop(traits=[], ticket_type="feature", repo_path=str(tmp_path))
    assert off["composed_from_skills"] == []

    invalidate_sop_cache()
    on = compose_sop(traits=["pipeline:content"], ticket_type="feature",
                     repo_path=str(tmp_path))
    assert on["composed_from_skills"] == ["demo_outline", "demo_draft", "demo_cover"]


def test_content_pipeline_full_integration(tmp_path):
    """端到端：pipeline:content 下 base 被裁 + skill 链接上 + 状态链连通。

    这是框架的目标形态 —— 内容类项目不跑架构/开发/审查，
    流程主体由 skill 链承载。
    """
    blog_chain(tmp_path)
    cfg = compose_sop(traits=["pipeline:content"], ticket_type="feature",
                      repo_path=str(tmp_path))
    order = ids(cfg)

    # base 被裁到只剩 3 个
    assert "development" not in order
    assert "architecture" not in order
    # skill 链在 deploy 之后、无 branch_only 残留
    assert order == ["planning", "acceptance", "deploy",
                     "demo_outline", "demo_draft", "demo_cover"]

    # 首个阶段仍被 pending 触发（裁剪后的硬约束）
    assert cfg["stages"][0]["trigger_on"] == "pending"
    rules = sop_to_transition_rules(cfg)
    assert "pending" in rules

    # 状态链闭合
    produced = {"pending"} | {s["success_status"] for s in cfg["stages"]}
    for s in cfg["stages"]:
        assert s["trigger_on"] in produced


# ════════════════════ pipeline_view 贡献 ════════════════════

def test_skill_contributes_pipeline_view_group(tmp_path):
    """skill 能像 fragment 一样建 UI 组。

    不传 `_skill_view_contribs` 的话 skill stage 在前端完全不可见 ——
    流水线跑着但界面上没有任何格子亮起。注入验证时测试全绿过，
    说明「功能对但没覆盖」，所以补了这条。
    """
    write_skill(
        tmp_path, "demo-outline", stage_id="demo_outline",
        consumes=["ticket_brief"], produces=[("content_outline", "outline.md")],
        extra_lines=[
            "pipeline_view_contrib:",
            "    group: content_pipeline",
            "    create_if_missing: {name: 内容流水线, icon: 📝,"
            " insert_after: requirement_analysis}",
        ],
    )
    cfg = compose_sop(traits=[], ticket_type="feature", repo_path=str(tmp_path))

    keys = [g["key"] for g in cfg["pipeline_view"]["stages"]]
    assert "content_pipeline" in keys
    # 按 insert_after 落在需求分析之后
    assert keys.index("content_pipeline") == keys.index("requirement_analysis") + 1

    grp = next(g for g in cfg["pipeline_view"]["stages"]
               if g["key"] == "content_pipeline")
    assert grp["name"] == "内容流水线"
    assert grp["sop_stages"] == ["demo_outline"]
    # reject_status 要进 running_statuses，否则失败时界面不显示在该组
    assert "demo_outline_failed" in grp["running_statuses"]


def test_skill_without_contrib_falls_into_default_group(tmp_path):
    """没声明 contrib 的 skill 走 _merge_pipeline_view 的默认分组（testing）。

    关键是**不能消失** —— 前端按组渲染，不在任何组里 = 不可见。
    """
    blog_chain(tmp_path)
    cfg = compose_sop(traits=[], ticket_type="feature", repo_path=str(tmp_path))

    all_refs = set()
    for g in cfg["pipeline_view"]["stages"]:
        all_refs.update(g.get("sop_stages") or [])
    for sid in ("demo_outline", "demo_draft", "demo_cover"):
        assert sid in all_refs, f"{sid} 不在任何 pipeline 组里 → 前端不可见"


# ════════════════════ 缓存 ════════════════════

def test_cache_returns_isolated_copies(tmp_path):
    """返回深拷贝 —— 调用方 mutate 不该污染后续调用。

    compose_sop 的调用方确实会改结果（orchestrator 读 stage 后改 config、
    `_merge_pipeline_view` 里的 append）。

    ⚠️ **必须调三次**：第一次是「未命中 → 组装 → 写缓存 → 返回拷贝」，
    它本来就返回独立对象。少了深拷贝只会让**第 2 次之后**的调用共用同一个
    缓存对象 —— 用「改第 1 个、查第 2 个」的写法测不出来（实测注入后全绿，
    是个假绿）。污染发生在第 2、3 次之间，所以要改第 2 个、验第 3 个。
    """
    blog_chain(tmp_path)
    kw = dict(traits=[], ticket_type="feature", repo_path=str(tmp_path))

    first = compose_sop(**kw)                      # 冷启动：组装并写缓存
    second = compose_sop(**kw)                     # 命中缓存
    assert first is not second

    second["stages"][0].setdefault("config", {})["POLLUTED"] = True
    second["stages"].append({"id": "injected"})
    second["pipeline_view"]["stages"][0]["sop_stages"] = ["WRECKED"]

    third = compose_sop(**kw)                      # 同样命中缓存
    assert third is not second
    assert "POLLUTED" not in third["stages"][0].get("config", {})
    assert "injected" not in ids(third)
    assert third["pipeline_view"]["stages"][0].get("sop_stages") != ["WRECKED"]


def test_cache_key_includes_repo_path(tmp_path):
    """不同 repo 的 skill 不同 → 不能共用缓存条目。"""
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    repo_a.mkdir()
    repo_b.mkdir()
    blog_chain(repo_a)

    with_skills = compose_sop(traits=[], ticket_type="feature",
                              repo_path=str(repo_a))
    without = compose_sop(traits=[], ticket_type="feature",
                          repo_path=str(repo_b))
    assert with_skills["composed_from_skills"]
    assert without["composed_from_skills"] == []


def test_invalidate_cache_picks_up_new_skill(tmp_path):
    """新增 SKILL.md 后清缓存能被发现（热更新路径）。"""
    first = compose_sop(traits=[], ticket_type="feature", repo_path=str(tmp_path))
    assert first["composed_from_skills"] == []

    blog_chain(tmp_path)
    cached = compose_sop(traits=[], ticket_type="feature", repo_path=str(tmp_path))
    assert cached["composed_from_skills"] == [], "缓存未命中，说明 key 不稳定"

    invalidate_sop_cache()
    fresh = compose_sop(traits=[], ticket_type="feature", repo_path=str(tmp_path))
    assert fresh["composed_from_skills"] == [
        "demo_outline", "demo_draft", "demo_cover"
    ]
