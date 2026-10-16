"""workflow_composer 的单测 —— 拓扑排序与四种边界的裁决。

关注点不是「排序算法对不对」（Kahn 是教科书算法），而是**边界情况的裁决是否
如设计所愿**：缺源级联、歧义剔除、成环降级、同层稳定。这四条每一条选错都会
产出一个「看着能跑但实际断链」的 SOP。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.4
"""
import pytest

from skills.executable_loader import ConsumeSpec, ProduceSpec, WorkflowSkill
from sop.workflow_composer import (
    SKILL_AGENT,
    _stage_action,
    compose_workflow_stages,
    skill_to_stage,
)

# ticket_brief 是 kinds.yaml 里唯一的 builtin kind（天然源）
BUILTIN = {"ticket_brief"}


def mk(
    stage_id: str, consumes=(), produces=(), *,
    priority: int = 50, traits=None, ticket_type=None, skill_id=None,
) -> WorkflowSkill:
    """造一个 WorkflowSkill。consumes/produces 传 kind 字符串即可。"""
    return WorkflowSkill(
        skill_id=skill_id or stage_id.replace("_", "-"),
        stage_id=stage_id,
        stage_name=stage_id,
        consumes=[
            c if isinstance(c, ConsumeSpec) else ConsumeSpec(c) for c in consumes
        ],
        produces=[
            p if isinstance(p, ProduceSpec) else ProduceSpec(p) for p in produces
        ],
        required_traits=traits,
        required_ticket_type=ticket_type,
        priority=priority,
    )


def ids(stages) -> list:
    return [s["id"] for s in stages]


def compose(skills, **kw):
    kw.setdefault("available_kinds", BUILTIN)
    return compose_workflow_stages(skills, **kw)


# ════════════════════ stage 生成 ════════════════════

def test_skill_to_stage_derives_all_status_names():
    """状态名全部由 stage_id 派生，SKILL.md 不声明。"""
    stage = skill_to_stage(mk("demo_draft", ["content_outline"], ["draft_article"]))
    assert stage["id"] == "demo_draft"
    assert stage["agent"] == SKILL_AGENT
    assert stage["action"] == "skill_demo_draft"
    assert stage["success_status"] == "demo_draft_done"
    assert stage["reject_status"] == "demo_draft_failed"


def test_stage_has_no_reject_goto():
    """**刻意不设 reject_goto**。

    loader.py:464 会据此派生「reject_status → goto stage 的 agent.action」
    回跳规则。指回 SkillAgent = 无限重试一个 LLM 自由发挥的 skill，
    烧 token 的风险远大于收益。失败走 blocked 等人工。
    """
    stage = skill_to_stage(mk("demo_draft"))
    assert "reject_goto" not in stage


def test_no_retry_rule_is_derived_for_skill_stages():
    """把上一条的**后果**也钉死 —— 只断言 dict 里没某个 key 太弱了。

    这里直接走 sop_to_transition_rules，确认 `{stage_id}_failed` 根本不在
    规则表里。有 reject_goto 时它会派生成
    `demo_draft_failed → SkillAgent.skill_demo_draft`，即工单一失败就重跑
    同一个 skill，再失败再重跑 —— 唯一的止损是全局 max_retries。
    """
    from sop.loader import sop_to_transition_rules

    stage = skill_to_stage(mk("demo_draft", ["ticket_brief"], ["draft_article"]))
    stage["trigger_on"] = "pending"          # 模拟 relink 后的样子
    rules = sop_to_transition_rules({"stages": [stage]})

    assert "pending" in rules
    assert rules["pending"]["agent"] == SKILL_AGENT
    assert "demo_draft_failed" not in rules, (
        "派生出了失败回跳规则 → skill 会被无限重试"
    )


def test_stage_action_prefixed_to_avoid_collision():
    """action 加 `skill_` 前缀避开 by_action 索引碰撞。

    loader.py:505 的 by_action 是「同 action 多 fragment 复用时先到先得」。
    skill 的 action 若与某 fragment 撞名，_sop_stage_for 会反查到错误的 stage。
    """
    assert _stage_action("development") == "skill_development"
    assert skill_to_stage(mk("development"))["action"] != "develop"


def test_stage_config_carries_framework_fields():
    """config 经 orchestrator.py:1833 进 context["sop_config"]，
    供 SkillAgent 读 skill_id、SkillRunner 做 kind 反查。"""
    stage = skill_to_stage(mk(
        "demo_draft",
        [ConsumeSpec("content_outline", required=False, mode="text")],
        [ProduceSpec("draft_article", "draft.md")],
    ))
    cfg = stage["config"]
    assert cfg["skill_id"] == "demo-draft"
    assert cfg["_stage_id"] == "demo_draft"
    assert cfg["_success_status"] == "demo_draft_done"
    assert cfg["_consumes"] == [
        {"kind": "content_outline", "required": False, "mode": "text"}
    ]
    assert cfg["_produces"] == [{"kind": "draft_article", "glob": "draft.md"}]


# ════════════════════ 基本排序 ════════════════════

def test_topo_order_ignores_declaration_order():
    """声明序 ≠ 执行序 —— 这是整个方案的核心主张。"""
    skills = [
        mk("demo_cover", ["draft_article"], ["cover_image"]),
        mk("demo_draft", ["content_outline"], ["draft_article"]),
        mk("demo_outline", ["ticket_brief"], ["content_outline"]),
    ]
    stages, diag = compose(skills)
    assert ids(stages) == ["demo_outline", "demo_draft", "demo_cover"]
    assert diag == []


def test_empty_input():
    assert compose([]) == ([], [])


def test_single_skill_from_builtin_source():
    stages, _ = compose([mk("a_stage", ["ticket_brief"], ["content_outline"])])
    assert ids(stages) == ["a_stage"]


def test_optional_consume_participates_in_ordering():
    """可选依赖也要排序 —— 有的话顺序必须对，没有不阻止组装。"""
    skills = [
        mk("consumer", [ConsumeSpec("style_guide", required=False)], ["draft_article"]),
        mk("producer", ["ticket_brief"], ["style_guide"]),
    ]
    stages, _ = compose(skills)
    assert ids(stages) == ["producer", "consumer"]


def test_optional_consume_missing_does_not_prune():
    """可选依赖缺 producer 时 skill 仍参与组装（运行期靠 _artifacts_missing 提示）。"""
    stages, diag = compose([
        mk("solo", [
            ConsumeSpec("ticket_brief"),
            ConsumeSpec("style_guide", required=False),
        ], ["draft_article"])
    ])
    assert ids(stages) == ["solo"]
    assert diag == []


# ════════════════════ 边界 1：缺源 + 级联 ════════════════════

def test_missing_required_source_prunes_skill():
    stages, diag = compose([mk("orphan", ["content_outline"], ["draft_article"])])
    assert stages == []
    assert any("无 producer" in d for d in diag)


def test_missing_source_cascades_fixed_point():
    """**级联**：A 出局 → 它产出的 kind 消失 → 依赖它的 B 也出局。

    单轮过滤会留下一串拿不到输入的 skill —— 它们会在运行期卡住，
    而不是在组装期就被排除。所以必须迭代到稳定。
    """
    skills = [
        mk("a", ["nonexistent"], ["k1"]),      # 缺源，出局
        mk("b", ["k1"], ["k2"]),               # 依赖 a → 级联出局
        mk("c", ["k2"], ["k3"]),               # 依赖 b → 级联出局
    ]
    stages, diag = compose(skills)
    assert stages == []
    pruned = [d for d in diag if "出局" in d]
    assert len(pruned) == 3


def test_partial_cascade_keeps_independent_chain():
    """级联只影响依赖链上的 skill，独立链不受牵连。"""
    skills = [
        mk("bad", ["nonexistent"], ["k1"]),
        mk("bad_child", ["k1"], ["k2"]),
        mk("good", ["ticket_brief"], ["content_outline"]),
        mk("good_child", ["content_outline"], ["draft_article"]),
    ]
    stages, _ = compose(skills)
    assert ids(stages) == ["good", "good_child"]


def test_builtin_kind_counts_as_available():
    """ticket_brief 由 ArtifactStore 产出，无 skill produces 它。

    不把它算作 available 的话，所有以它为源的链都会被判缺源而全部出局。
    """
    skills = [mk("x", ["ticket_brief"], ["content_outline"])]
    assert ids(compose(skills, available_kinds=BUILTIN)[0]) == ["x"]
    assert compose(skills, available_kinds=set())[0] == []


# ════════════════════ 边界 2：歧义（一 kind 多 producer） ════════════════════

def test_duplicate_producer_keeps_highest_priority():
    """不要「都装」—— 两个 skill 产出同一 kind 会互相覆盖，
    latest_per_kind 取到谁取决于执行顺序，产物总线语义被破坏。"""
    skills = [
        mk("low", ["ticket_brief"], ["content_outline"], priority=10),
        mk("high", ["ticket_brief"], ["content_outline"], priority=90),
    ]
    stages, diag = compose(skills)
    assert ids(stages) == ["high"]
    assert any("多个 producer" in d for d in diag)


def test_duplicate_producer_tie_broken_by_stage_id():
    """同 priority 按 stage_id 字典序 —— 结果必须可预测，否则测试写不了。"""
    skills = [
        mk("zebra", ["ticket_brief"], ["content_outline"]),
        mk("alpha", ["ticket_brief"], ["content_outline"]),
    ]
    assert ids(compose(skills)[0]) == ["alpha"]


def test_dropped_producer_takes_its_consumers_down():
    """落选的 producer 被剔除后，只依赖它的 skill 会因缺源级联出局。"""
    skills = [
        mk("winner", ["ticket_brief"], ["content_outline"], priority=90),
        mk("loser", ["ticket_brief"], ["content_outline", "style_guide"], priority=10),
        mk("needs_style", ["style_guide"], ["draft_article"]),
    ]
    stages, diag = compose(skills)
    assert ids(stages) == ["winner"]
    assert any("多个 producer" in d for d in diag)
    assert any("needs_style" in d and "出局" in d for d in diag)


# ════════════════════ 边界 3：成环 ════════════════════

def test_cycle_drops_entire_chain():
    """成环 → **整条链不组装**，不是只剔除环上的节点。

    部分组装会产出「看着能跑但中间断链」的 SOP，比没有更危险 ——
    orchestrator 会把工单推到某个状态后再也找不到下一条规则。
    """
    skills = [
        mk("a", ["ticket_brief", "k2"], ["k1"]),
        mk("b", ["k1"], ["k2"]),
    ]
    stages, diag = compose(skills)
    assert stages == []
    assert any("成环" in d for d in diag)


def test_cycle_also_drops_healthy_skills():
    """健康的 skill 也一起不组装 —— 这是「整条链」的字面含义。

    理由：拓扑序断了就无法保证剩下那部分的执行顺序正确。
    宁可退化成纯 fragment SOP（compose_sop 会照常工作）。
    """
    skills = [
        mk("a", ["ticket_brief", "k2"], ["k1"]),
        mk("b", ["k1"], ["k2"]),
        mk("healthy", ["ticket_brief"], ["content_outline"]),
    ]
    stages, _ = compose(skills)
    assert stages == []


def test_three_node_cycle_detected():
    skills = [
        mk("a", ["k3"], ["k1"]),
        mk("b", ["k1"], ["k2"]),
        mk("c", ["k2"], ["k3"]),
    ]
    stages, diag = compose(skills)
    assert stages == []
    stuck = [d for d in diag if "成环" in d][0]
    for sid in ("a", "b", "c"):
        assert sid in stuck


def test_self_loop_tolerated_as_fallback():
    """自环已在 discover 的 lint 拦下；这里兜底不让它变成死循环。

    真跑到这里说明有人绕过了 discover 直接调 composer（如测试）。
    此时 skill 自己产出自己的输入 —— 视为「源已就绪」继续排序，
    而不是整条链崩掉。
    """
    skills = [mk("weird", ["k1"], ["k1"])]
    stages, _ = compose(skills)
    assert ids(stages) == ["weird"]


# ════════════════════ 边界 4：同层稳定序 ════════════════════

def test_same_layer_ordered_by_priority_then_id():
    """同层（都无依赖）按 (-priority, stage_id)。

    不用 heap 的话同层顺序取决于 dict 迭代序 —— 测试写不了，线上不可复现。
    """
    skills = [
        mk("mid", ["ticket_brief"], ["k_mid"], priority=50),
        mk("top", ["ticket_brief"], ["k_top"], priority=99),
        mk("bottom", ["ticket_brief"], ["k_bot"], priority=1),
    ]
    assert ids(compose(skills)[0]) == ["top", "mid", "bottom"]


def test_same_priority_same_layer_alphabetical():
    skills = [
        mk("charlie", ["ticket_brief"], ["k_c"]),
        mk("alpha", ["ticket_brief"], ["k_a"]),
        mk("bravo", ["ticket_brief"], ["k_b"]),
    ]
    assert ids(compose(skills)[0]) == ["alpha", "bravo", "charlie"]


def test_compose_is_deterministic():
    """同输入多次组装结果完全一致（输入顺序打乱也一样）。"""
    base = [
        mk("c", ["k_b"], ["k_c"]),
        mk("a", ["ticket_brief"], ["k_a"]),
        mk("b", ["k_a"], ["k_b"]),
    ]
    first = ids(compose(list(base))[0])
    for _ in range(3):
        assert ids(compose(list(reversed(base)))[0]) == first


def test_priority_does_not_override_dependency():
    """依赖是硬约束，priority 只在同层生效。

    低 priority 的 producer 仍必须排在高 priority 的 consumer 之前 ——
    否则下游拿不到输入，排序就失去意义了。
    """
    skills = [
        mk("consumer", ["k_src"], ["k_out"], priority=99),
        mk("producer", ["ticket_brief"], ["k_src"], priority=1),
    ]
    assert ids(compose(skills)[0]) == ["producer", "consumer"]


# ════════════════════ trait / ticket_type 过滤 ════════════════════

def test_trait_filter_excludes_non_matching():
    skills = [
        mk("content_only", ["ticket_brief"], ["content_outline"],
           traits={"any_of": ["pipeline:content"]}),
        mk("always", ["ticket_brief"], ["style_guide"]),
    ]
    assert ids(compose(skills, traits=[])[0]) == ["always"]
    assert set(ids(compose(skills, traits=["pipeline:content"])[0])) == {
        "content_only", "always"
    }


def test_ticket_type_filter():
    skills = [mk("no_bugfix", ["ticket_brief"], ["content_outline"],
                 ticket_type={"none_of": ["bug-fix"]})]
    assert ids(compose(skills, ticket_type="feature")[0]) == ["no_bugfix"]
    assert compose(skills, ticket_type="bug-fix")[0] == []


def test_trait_filtered_out_producer_cascades():
    """被 trait 过滤掉的 producer 同样会让下游缺源。

    这比「skill 自己不匹配」更隐蔽：下游 skill 的 trait 条件是满足的，
    它只是碰巧依赖了一个不适用于本项目的上游。
    """
    skills = [
        mk("ue_only", ["ticket_brief"], ["k_ue"], traits={"any_of": ["engine:ue5"]}),
        mk("downstream", ["k_ue"], ["draft_article"]),
    ]
    stages, diag = compose(skills, traits=["pipeline:content"])
    assert stages == []
    assert any("downstream" in d and "出局" in d for d in diag)


def test_no_skill_matches_returns_empty():
    skills = [mk("x", ["ticket_brief"], ["content_outline"],
                 traits={"all_of": ["engine:ue5", "category:game"]})]
    assert compose(skills, traits=["pipeline:content"])[0] == []


# ════════════════════ 并行度诊断 ════════════════════

def test_parallelizable_pairs_reported():
    """拓扑能表达并行，但 relink 会压平成串行 —— 把损失量化出来。

    三个互不依赖的 skill 被排成串行链 → 2 处可并行点。
    """
    skills = [
        mk("a", ["ticket_brief"], ["k_a"]),
        mk("b", ["ticket_brief"], ["k_b"]),
        mk("c", ["ticket_brief"], ["k_c"]),
    ]
    stages, diag = compose(skills)
    assert len(stages) == 3
    note = [d for d in diag if "可并行" in d]
    assert len(note) == 1
    assert "2 处" in note[0]


def test_strict_chain_has_no_parallel_note():
    """严格线性链没有并行损失，不该刷无意义的 diagnostic。"""
    skills = [
        mk("a", ["ticket_brief"], ["k_a"]),
        mk("b", ["k_a"], ["k_b"]),
        mk("c", ["k_b"], ["k_c"]),
    ]
    _, diag = compose(skills)
    assert not any("可并行" in d for d in diag)


# ════════════════════ 默认 available_kinds ════════════════════

def test_default_available_kinds_from_registry():
    """不传 available_kinds 时取 kinds.yaml 里标了 builtin 的那些。"""
    skills = [mk("x", ["ticket_brief"], ["content_outline"])]
    stages, _ = compose_workflow_stages(skills)      # 不传 available_kinds
    assert ids(stages) == ["x"]
