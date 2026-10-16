"""compose_sop 基线测试 —— 锁住 trait-first 动态组装的现有行为。

## 为什么需要这批测试

`sop/loader.py:compose_sop` 是 4 层变换叠加：
  ① base_stages 骨架
  ② fragments fixed-point 多轮插桩（insert_after / insert_before）
  ③ priority 升序（反直觉：数值大的最终更靠近锚点、更先执行）
  ④ _relink_stage_transitions 重链状态（**覆盖** fragment 自己声明的 trigger_on）
  ⑤ stage_overrides patch + pipeline_view 合并

全仓库此前对它零测试。即将做的改动（base_stages 支持 required_traits 裁剪、
skill 链按数据依赖拓扑排序后整块插入）全部落在这条链路上，没有基线等于盲改。

## 这批测试的定位

**回归锁，不是正确性断言。** 其中 T6 如实锁住了一个已知 bug（见该用例注释）——
目的是让「改动没有意外改变行为」可被机械验证，而不是证明现有行为都对。

所有期望序列都是从当前实现实测捕获的，不是手写推演。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §4.1
"""
import json

import pytest

from sop.loader import compose_sop, sop_to_transition_rules


def ids_of(cfg) -> list:
    return [s["id"] for s in cfg["stages"]]


# ───────────────────────── T1：无 trait 行为不变 ─────────────────────────

def test_t1_no_traits_equals_base_stages():
    """无 traits → 纯 base_stages 原序，一个 fragment 都不插。

    这是后续所有 loader 改动的**安全网**：base_stages 裁剪与 skill 链接入
    都必须保证「没声明新 trait 的老项目行为完全不变」。
    """
    cfg = compose_sop(traits=[], ticket_type=None)
    assert ids_of(cfg) == [
        "planning", "architecture", "development", "code_review",
        "acceptance", "deploy", "rework", "development_retry",
    ]
    assert cfg["composed_from_fragments"] == []


def test_t1b_no_traits_first_stage_triggers_on_pending():
    """首个 stage 必须被 pending 触发，否则工单永远起不来。

    _relink_stage_transitions 对 i == 0 是 pass（保留原声明），所以这条
    不变式目前靠 _core.yaml 里 planning 手写 `trigger_on: pending` 维持。
    base_stages 裁剪后 planning 可能被裁掉，届时必须显式兜住 —— 这条测试
    就是那个改动的警报器。
    """
    cfg = compose_sop(traits=[], ticket_type=None)
    assert cfg["stages"][0]["trigger_on"] == "pending"


# ───────────────────────── T2：web 项目组装 ─────────────────────────

def test_t2_web_feature_full_sequence():
    cfg = compose_sop(traits=["platform:web"], ticket_type="feature")
    assert ids_of(cfg) == [
        "planning",
        "ux_design",      # insert_after: planning, priority 90
        "art_design",     # insert_after: ux_design, priority 88
        "architecture",
        "development",
        "code_review",
        "acceptance",
        "deploy_web",     # insert_after: acceptance, priority 70
        "deploy",
        "rework",
        "development_retry",
    ]


def test_t2b_web_app_gets_smoke_test():
    """category:app 额外带出 smoke_test（required_traits.any_of 命中）。"""
    cfg = compose_sop(traits=["platform:web", "category:app"], ticket_type="feature")
    ids = ids_of(cfg)
    assert "smoke_test" in ids
    # smoke_test insert_after: development
    assert ids.index("smoke_test") == ids.index("development") + 1


# ───────────────────── T3：priority 升序的反直觉语义 ─────────────────────

def test_t3_ue_game_priority_ordering():
    """锁住 loader.py:94 的插入顺序语义。

    engine_compile(95) / play_test(85) / ue_test_gen(97) 都 insert_after: development。
    loader 按 priority **升序**遍历插入，而 insert(idx+1) 会把后插入的挤到锚点+1，
    所以**数值大的最终更靠近锚点、更先执行**。

    期望顺序 ue_test_gen(97) → engine_compile(95) → play_test(85) 正是这个
    反直觉规则的产物。任何「看起来更自然」的改动都会打破它。
    """
    cfg = compose_sop(traits=["category:game", "engine:ue5"], ticket_type="feature")
    assert ids_of(cfg) == [
        "planning",
        "ux_design",
        "art_design",
        "architecture",
        "asset_gen",        # insert_before: development
        "development",
        "ue_test_gen",      # 97
        "engine_compile",   # 95
        "play_test",        # 85
        "deploy_ue",        # insert_after: play_test
        "code_review",
        "acceptance",
        "deploy",
        "rework",
        "development_retry",
    ]


def test_t3b_asset_gen_before_development():
    """美术资产必须在开发前就位（insert_before: development）。"""
    cfg = compose_sop(traits=["category:game", "engine:ue5"], ticket_type="feature")
    ids = ids_of(cfg)
    assert ids.index("asset_gen") < ids.index("development")


def test_t3c_fragment_to_fragment_anchor_resolves():
    """deploy_ue 锚在 play_test（另一个 fragment）上 —— 锁住 fixed-point 多轮循环。

    单轮插桩会因为「锚点此刻还不存在」而让 deploy_ue 失锚追加末尾。
    """
    cfg = compose_sop(traits=["category:game", "engine:ue5"], ticket_type="feature")
    ids = ids_of(cfg)
    assert ids.index("deploy_ue") == ids.index("play_test") + 1


def test_t3d_godot_game_gets_html_prototype():
    """html_prototype(92) 高于 ux_design(90)，且 engine:ue5 被 none_of 排除。

    Godot 项目命中 category:game 且不在 none_of 里 → 应出现在 ux_design 之前。
    """
    cfg = compose_sop(traits=["category:game", "engine:godot4"], ticket_type="feature")
    ids = ids_of(cfg)
    assert ids.index("html_prototype") < ids.index("ux_design")
    # UE 项目则被排除
    ue = compose_sop(traits=["category:game", "engine:ue5"], ticket_type="feature")
    assert "html_prototype" not in ids_of(ue)


# ───────────────────── T4：branch_only 不参与线性链 ─────────────────────

def test_t4_branch_only_trigger_on_preserved():
    """rework / development_retry 的 trigger_on 不能被前一个 stage 的 success 覆盖。

    _relink_stage_transitions 跳过 branch_only 正是为此。若被覆盖会死循环：
    deploy.success=deployed 覆盖 rework.trigger=acceptance_rejected 后，
    rework 被 deployed 触发 → 产出 development_done → 又走到 deploy → 又触发 rework。
    """
    cfg = compose_sop(traits=["category:game", "engine:ue5"], ticket_type="feature")
    by_id = {s["id"]: s for s in cfg["stages"]}
    assert by_id["rework"]["trigger_on"] == "acceptance_rejected"
    assert by_id["development_retry"]["trigger_on"] == "development_failed"
    assert by_id["rework"]["branch_only"] is True
    assert by_id["development_retry"]["branch_only"] is True


def test_t4b_branch_only_not_in_linear_chain():
    """branch_only stage 也不能参与 prev_success 的传递。

    否则它后面的 stage 会被接到分支 stage 的 success 上。
    """
    cfg = compose_sop(traits=["platform:web"], ticket_type="feature")
    stages = cfg["stages"]
    rework_idx = next(i for i, s in enumerate(stages) if s["id"] == "rework")
    # rework 之前的最后一个非 branch_only 是 deploy
    assert stages[rework_idx - 1]["id"] == "deploy"
    # development_retry 紧跟 rework，其 trigger 不是 rework 的 success
    assert stages[rework_idx + 1]["trigger_on"] != stages[rework_idx]["success_status"]


# ──────────────────── T5：relink 不变式（最关键） ────────────────────

@pytest.mark.parametrize("traits,ticket_type", [
    ([], None),
    (["platform:web"], "feature"),
    (["platform:web", "category:app"], "feature"),
    (["category:game", "engine:ue5"], "feature"),
    (["category:game", "engine:godot4"], "feature"),
    (["engine:ue5"], "ue_content"),
])
def test_t5_relink_invariant(traits, ticket_type):
    """**不变式**：每个非 branch_only stage 的 trigger_on == 前一个非 branch_only
    stage 的 success_status。

    这是整条状态链连通的充分条件，也是 skill 链按拓扑排序插入后**仍必须成立**
    的那个性质。拓扑排序只改变 stage 的先后，不改变这条链式关系。
    """
    cfg = compose_sop(traits=traits, ticket_type=ticket_type)
    prev_success = None
    violations = []
    for s in cfg["stages"]:
        if s.get("branch_only"):
            continue
        if prev_success is not None and s.get("trigger_on") != prev_success:
            violations.append((s["id"], s.get("trigger_on"), prev_success))
        prev_success = s.get("success_status")
    assert violations == [], f"状态链断裂: {violations}"


@pytest.mark.parametrize("traits,ticket_type", [
    ([], None),
    (["platform:web"], "feature"),
    (["category:game", "engine:ue5"], "feature"),
])
def test_t5b_every_stage_has_agent_action_and_success(traits, ticket_type):
    """每个 stage 必须有 agent / action / success_status，否则 orchestrator 派不出去。"""
    cfg = compose_sop(traits=traits, ticket_type=ticket_type)
    for s in cfg["stages"]:
        assert s.get("agent"), f"{s.get('id')} 缺 agent"
        assert s.get("action"), f"{s.get('id')} 缺 action"
        assert s.get("success_status"), f"{s.get('id')} 缺 success_status"


@pytest.mark.parametrize("traits,ticket_type", [
    (["platform:web"], "feature"),
    (["category:game", "engine:ue5"], "feature"),
])
def test_t5c_stage_ids_unique(traits, ticket_type):
    cfg = compose_sop(traits=traits, ticket_type=ticket_type)
    ids = ids_of(cfg)
    assert len(ids) == len(set(ids)), f"stage id 重复: {ids}"


# ─────────────────────── T6：已知 bug，如实锁住 ───────────────────────

def test_t6_ticket_type_bug_vs_bugfix_mismatch():
    """# KNOWN ISSUE —— trait 词表与 fragment 声明不一致。

    trait_taxonomy.yaml 的 ticket_type 枚举是 `bug-fix`，但 ux_design.yaml 和
    art_design.yaml 的 required_ticket_type.none_of 写的是 `bug`。结果：
      ticket_type='bug'     → 正确跳过设计阶段
      ticket_type='bug-fix' → **设计阶段仍被组装进来**（本意是要跳过的）

    本测试如实锁住当前行为。修这个 bug 时本测试会失败 —— 那是预期的，
    届时把断言改成两者一致即可。不要在没有意识到的情况下让它变绿。
    """
    bug = ids_of(compose_sop(traits=["platform:web"], ticket_type="bug"))
    assert "ux_design" not in bug
    assert "art_design" not in bug

    bugfix = ids_of(compose_sop(traits=["platform:web"], ticket_type="bug-fix"))
    assert "ux_design" in bugfix      # ← bug：本应 not in
    assert "art_design" in bugfix     # ← bug：本应 not in


def test_t6b_missing_anchor_falls_through_to_tail():
    """# KNOWN ISSUE —— 锚点找不到时静默追加到末尾，而非报错。

    multiplayer_stress 锚在 play_test（UE/游戏专属 fragment）上。web 项目命中
    multiplayer:true 但没有 play_test → loader.py:134-145 只打 warning 然后
    **追加到 development_retry 之后**，位置完全错了（在 branch_only 区之后）。

    base_stages 裁剪会放大这个风险（裁掉 development 会让 7 个 fragment 失锚），
    所以后续要加失锚校验。本测试锁住当前的静默降级行为。
    """
    cfg = compose_sop(
        traits=["platform:web", "multiplayer:true"], ticket_type="feature"
    )
    ids = ids_of(cfg)
    assert "play_test" not in ids
    assert ids[-1] == "multiplayer_stress"       # 被追加到最末尾
    assert ids.index("multiplayer_stress") > ids.index("development_retry")


# ──────────────────── T7：required_ticket_type 过滤 ────────────────────

def test_t7_ue_content_gen_needs_matching_ticket_type():
    """ue_content_gen 声明 required_ticket_type: ue_content（字符串形式）。

    不传 ticket_type 时该 fragment 不应被组装 —— orchestrator 扫状态/续跑时
    务必带上工单自己的 type，否则派生出的规则集和派单用的不一致。
    """
    with_type = ids_of(compose_sop(traits=["engine:ue5"], ticket_type="ue_content"))
    assert "ue_content_gen" in with_type
    assert with_type.index("ue_content_gen") == with_type.index("architecture") + 1

    without = ids_of(compose_sop(traits=["engine:ue5"], ticket_type=None))
    assert "ue_content_gen" not in without


def test_t7b_asset_gen_requires_feature_ticket():
    """asset_gen 的 required_ticket_type.any_of = [feature]。"""
    feat = ids_of(compose_sop(traits=["category:game", "engine:ue5"], ticket_type="feature"))
    assert "asset_gen" in feat
    none = ids_of(compose_sop(traits=["category:game", "engine:ue5"], ticket_type=None))
    assert "asset_gen" not in none


# ──────────────────── T8：transition_rules 转换 ────────────────────

def test_t8_transition_rules_keys_unique_and_complete():
    cfg = compose_sop(traits=["platform:web", "category:app"], ticket_type="feature")
    rules = sop_to_transition_rules(cfg)

    # 每个非 branch_only stage 的 trigger_on 都要有对应规则
    for s in cfg["stages"]:
        trigger = s.get("trigger_on")
        if trigger:
            assert trigger in rules, f"stage {s['id']} 的 trigger {trigger} 无规则"

    assert "pending" in rules
    assert rules["pending"]["agent"] == "PlannerAgent"


def test_t8b_reject_goto_derives_fix_issues_rules():
    """reject_status + reject_goto → 自动派生 DevAgent.fix_issues 回跳规则。

    锁住 loader.py:392-415。这也是 skill stage **不配 reject_goto** 的原因：
    派生出的规则会指回 SkillAgent，变成无限重试。
    """
    cfg = compose_sop(traits=["platform:web", "category:app"], ticket_type="feature")
    rules = sop_to_transition_rules(cfg)

    for status in ("acceptance_rejected", "development_failed", "self_test_failed"):
        assert status in rules, f"缺回跳规则 {status}"
        assert rules[status]["agent"] == "DevAgent"
        assert rules[status]["action"] == "fix_issues"


def test_t8c_rework_source_stage_recorded():
    """回跳规则要记下失败来源阶段，供 orchestrator 止损判断。"""
    cfg = compose_sop(traits=["category:game", "engine:ue5"], ticket_type="feature")
    rules = sop_to_transition_rules(cfg)
    derived = [k for k, v in rules.items() if "_rework_source_stage" in v]
    assert derived, "没有任何派生的回跳规则"


# ──────────────────────── T9：pipeline_view 合并 ────────────────────────

def test_t9_pipeline_view_group_sequence():
    """fragments 的 pipeline_view_contrib 按 insert_after/before 建组。

    asset_gen 建「资产准备」组（insert_before: development），
    art_design/ux_design 建「设计」组（insert_after: requirement_analysis）。
    """
    cfg = compose_sop(traits=["category:game", "engine:ue5"], ticket_type="feature")
    keys = [g["key"] for g in cfg["pipeline_view"]["stages"]]
    assert keys == [
        "requirement_analysis",
        "design",
        "architecture",
        "asset_preparation",
        "development",
        "testing",
        "delivery",
        "merge_develop",
    ]


def test_t9b_merge_pipeline_view_does_not_mutate_input():
    """_merge_pipeline_view 必须深拷贝，不得 mutate 传入的 core_view。

    为什么直接测这个私有函数而不是测 compose_sop 的多次调用：
    compose_sop 目前每次都从磁盘重读 yaml（没有模块级缓存），所以「连调两次」
    这个场景**不可能**暴露污染问题 —— 写成那样是假绿（已实测：去掉深拷贝，
    35 个用例全过）。

    真正的风险在下一步：方案 §3.6 要给 compose_sop 加 lru_cache。一旦 yaml
    加载被缓存，deepcopy 就成了唯一屏障。所以这里显式模拟「同一个 dict 对象
    被反复使用」（= 缓存生效后的情形），把契约钉死：

        传给 _merge_pipeline_view 的对象，调用后必须与调用前完全相等。

    这条测试是 lru_cache 改动的前置保险。
    """
    from sop.loader import _merge_pipeline_view

    core_view = {
        "stages": [
            {"key": "development", "name": "开发", "sop_stages": ["development"]},
            {"key": "testing", "name": "测试", "sop_stages": []},
        ]
    }
    before = json.loads(json.dumps(core_view))

    frag_a = {
        "id": "smoke_test",
        "stage": {"id": "smoke_test", "trigger_on": "development_done"},
        "pipeline_view_contrib": {"group": "testing"},
    }
    frag_b = {
        "id": "art_design",
        "stage": {"id": "art_design", "trigger_on": "planning_done"},
        "pipeline_view_contrib": {"group": "development"},
    }

    out_1 = _merge_pipeline_view(core_view, [frag_a])
    # 污染一旦发生，core_view 会被 append；第二次调用就拿到脏数据
    assert core_view == before, "core_view 被 mutate 了 —— 缺深拷贝"

    out_2 = _merge_pipeline_view(core_view, [frag_b])
    assert core_view == before, "第二次调用同样不得 mutate 输入"

    dev_1 = next(g for g in out_1["stages"] if g["key"] == "development")
    assert dev_1["sop_stages"] == ["development"]        # frag_b 未参与第一次
    dev_2 = next(g for g in out_2["stages"] if g["key"] == "development")
    assert dev_2["sop_stages"] == ["development", "art_design"]
    # 两次输出互不影响
    assert dev_1["sop_stages"] != dev_2["sop_stages"]


# ──────────────────────────── T10：幂等性 ────────────────────────────

@pytest.mark.parametrize("traits,ticket_type", [
    ([], None),
    (["platform:web", "category:app"], "feature"),
    (["category:game", "engine:ue5"], "feature"),
])
def test_t10_compose_is_idempotent(traits, ticket_type):
    """连续调用三次结果必须完全相同。

    loader 直接 mutate 从 yaml 读出的 dict（把 fragment 的 id/name 复制进
    stage、stage_overrides 的 config.update）。若 yaml 有模块级 cache，
    第二次调用就会拿到被污染的对象。这条测试是那类 bug 的探针。
    """
    def snapshot():
        cfg = compose_sop(traits=traits, ticket_type=ticket_type)
        return json.dumps(
            {"stages": cfg["stages"], "pipeline_view": cfg["pipeline_view"]},
            sort_keys=True, ensure_ascii=False, default=str,
        )

    a, b, c = snapshot(), snapshot(), snapshot()
    assert a == b == c


def test_t10b_interleaved_compose_no_cross_contamination():
    """交错组装不同 trait 组合，彼此不污染。"""
    web_1 = ids_of(compose_sop(traits=["platform:web"], ticket_type="feature"))
    compose_sop(traits=["category:game", "engine:ue5"], ticket_type="feature")
    compose_sop(traits=[], ticket_type=None)
    web_2 = ids_of(compose_sop(traits=["platform:web"], ticket_type="feature"))
    assert web_1 == web_2


# ────────────────── T11：base_stages 裁剪（v0.20 新增） ──────────────────

@pytest.mark.parametrize("traits,ticket_type", [
    ([], None),
    (["pipeline:code"], "feature"),              # 显式 code 与缺省等价
    (["platform:web"], "feature"),
    (["platform:web", "category:app"], "feature"),
    (["category:game", "engine:ue5"], "feature"),
])
def test_t11_no_pruning_for_code_pipelines(traits, ticket_type):
    """代码类项目（含缺省）必须零裁剪、零 diagnostic。

    这是 base_stages 裁剪改动的**向后兼容契约**：没声明 pipeline:content 的项目
    一个阶段都不该少。T1/T2/T3 锁的是序列，这条锁的是「裁剪机制本身没被误触发」。
    """
    cfg = compose_sop(traits=traits, ticket_type=ticket_type)
    assert cfg["dropped_base_stages"] == []
    assert cfg["sop_diagnostics"] == []


def test_t11b_content_pipeline_prunes_code_stages():
    """pipeline:content → 架构/开发/审查 + 两个 branch_only 全部裁掉。"""
    cfg = compose_sop(traits=["pipeline:content"], ticket_type="feature")
    assert ids_of(cfg) == ["planning", "acceptance", "deploy"]
    assert cfg["dropped_base_stages"] == [
        "architecture", "code_review", "development",
        "development_retry", "rework",
    ]


def test_t11c_content_pipeline_first_stage_still_triggers_on_pending():
    """**裁剪后首个阶段仍被 pending 触发** —— 否则工单永久卡死。

    工单创建时 status='pending'，orchestrator 只认 transition_rules['pending']。
    裁剪改变了首个阶段是谁，所以 _relink_stage_transitions 必须强制赋值而不是
    「保留原声明」。回归形态极其隐蔽：不报错、不超时、无日志，工单只是永远不动。

    ⚠️ 本用例**单独不足以**守住这个性质 —— content profile 保留下来的 planning
    恰好在 yaml 里手写了 `trigger_on: pending`，所以即便强制赋值被去掉它也是绿的
    （已实测）。真正守住契约的是下面 test_t11c2 对 _relink_stage_transitions
    的直接断言。这条保留是因为它同时锁了规则表里有 pending 键这个端到端事实。
    """
    cfg = compose_sop(traits=["pipeline:content"], ticket_type="feature")
    assert cfg["stages"][0]["trigger_on"] == "pending"
    rules = sop_to_transition_rules(cfg)
    assert "pending" in rules, "规则表缺 pending 键 → 工单永远起不来"


def test_t11c2_relink_forces_entry_status_on_first_stage():
    """直接钉死 _relink_stage_transitions 的契约：首个非 branch_only 阶段
    的 trigger_on **必须被强制改写成 entry_status**，无论它原本声明了什么。

    为什么必须直接测而不是通过 compose_sop 间接测：
    compose_sop 的现有输入空间里，首个阶段永远是 planning（yaml 里已手写
    pending），所以「保留原声明」和「强制赋值」两种实现产生的结果完全相同 ——
    间接测试对此**不可区分**（已实测：去掉强制赋值，47 个用例全绿）。

    而真实风险恰恰在间接测试覆盖不到的地方：
      - 将来 planning 被某个 profile 裁掉，首个阶段变成别的
      - 将来有 fragment 插到 planning 之前
      - 将来 _core.yaml 里 planning 的 trigger_on 被改成别的值
    三种情况下「保留原声明」都会让工单卡死在 pending。所以这里构造一个
    首个阶段声明了**孤立 trigger_on** 的 stage 列表，把契约钉死。
    """
    from sop.loader import _relink_stage_transitions

    stages = [
        {"id": "a", "trigger_on": "nobody_produces_this",
         "success_status": "a_done"},
        {"id": "b", "trigger_on": "a_done", "success_status": "b_done"},
        {"id": "branch", "trigger_on": "x_failed", "success_status": "a_done",
         "branch_only": True},
    ]
    out = _relink_stage_transitions(stages)

    assert out[0]["trigger_on"] == "pending", (
        "首个阶段的孤立 trigger_on 未被改写成 pending → 工单永远起不来"
    )
    assert out[1]["trigger_on"] == "a_done"
    # branch_only 不受影响
    assert out[2]["trigger_on"] == "x_failed"

    # 从中间开始（branch_only 排在最前）也要正确识别「首个」
    stages2 = [
        {"id": "branch", "trigger_on": "x_failed", "success_status": "z_done",
         "branch_only": True},
        {"id": "a", "trigger_on": "孤立状态", "success_status": "a_done"},
    ]
    out2 = _relink_stage_transitions(stages2)
    assert out2[1]["trigger_on"] == "pending"

    # entry_status 可定制
    out3 = _relink_stage_transitions(stages, entry_status="todo")
    assert out3[0]["trigger_on"] == "todo"

    # 不得 mutate 输入
    assert stages[0]["trigger_on"] == "nobody_produces_this"


def test_t11d_content_pipeline_state_chain_is_closed():
    """每个阶段的 trigger_on 都要有人产出，每个 success 都要有人消费（除终态）。

    裁剪最容易制造的是「孤岛阶段」：trigger_on 指向一个没人产出的状态。
    这条测试把闭合性做成机械检查，而不是靠肉眼读 yaml。
    """
    cfg = compose_sop(traits=["pipeline:content"], ticket_type="feature")
    stages = cfg["stages"]
    produced = {"pending"} | {s.get("success_status") for s in stages}

    for s in stages:
        assert s.get("trigger_on") in produced, (
            f"stage {s['id']} 的 trigger_on={s.get('trigger_on')} 无人产出 → 不可达"
        )

    # deployed 是 _HARD_TERMINAL 的流程终点，允许无人消费；其余都要有下游
    consumed = {s.get("trigger_on") for s in stages}
    for s in stages:
        succ = s.get("success_status")
        if succ in ("deployed",):
            continue
        assert succ in consumed, f"stage {s['id']} 的 success={succ} 无人消费 → 走到即停"


def test_t11e_dangling_reject_goto_is_stripped_not_silent():
    """acceptance 的 reject_goto: rework 在 content profile 下悬空 → 必须剥离 + 报告。

    为什么不能放着不管：sop_to_transition_rules:459 的 `if goto_stage:` 对
    「reject_goto 指向不存在的 stage」是**静默跳过**，不派生任何规则。结果是
    acceptance_rejected 这个状态在规则表里根本不存在，验收一旦拒绝就静默卡死。

    剥离后语义退化成「拒绝后停在原地等人工」—— 明确且可见，比死锁好得多。
    """
    cfg = compose_sop(traits=["pipeline:content"], ticket_type="feature")
    acceptance = next(s for s in cfg["stages"] if s["id"] == "acceptance")
    assert "reject_goto" not in acceptance
    assert "reject_status" not in acceptance

    # 必须留下可排查的痕迹
    assert any("reject_goto" in d and "rework" in d for d in cfg["sop_diagnostics"])

    # 规则表里不该出现指向已裁阶段的残留
    rules = sop_to_transition_rules(cfg)
    assert "acceptance_rejected" not in rules


def test_t11f_lost_anchor_is_reported_as_error():
    """锚点被裁剪导致 fragment 失锚 → 必须进 sop_diagnostics（ERROR 级）。

    pipeline:content + engine:ue5 是个无意义组合，但正好能触发这条路径：
    UE 的 engine_compile / play_test / ue_test_gen 锚在 development 上，
    而 development 被 content 裁掉了。

    此前的行为是 warning 后追加到末尾 —— 位置完全错（落在 branch_only 区之后），
    但没有任何结构化痕迹。现在要能被程序读到。
    """
    cfg = compose_sop(traits=["pipeline:content", "engine:ue5"], ticket_type="feature")
    lost = [d for d in cfg["sop_diagnostics"] if "已被 base_stages 裁剪" in d]
    assert len(lost) >= 3
    assert any("engine_compile" in d for d in lost)


def test_t11g_pipeline_view_drops_empty_groups():
    """裁剪后 pipeline_view 不留空壳组（sop_stages 全失效的组整体移除）。

    「开发实现」组的 sop_stages = [development, code_review, acceptance, rework]，
    content profile 下只剩 acceptance 一个有效 —— 组保留但引用被清理。
    「架构设计」组只引用 architecture，全失效 → 整组移除。
    """
    cfg = compose_sop(traits=["pipeline:content"], ticket_type="feature")
    groups = {g["key"]: g for g in cfg["pipeline_view"]["stages"]}

    assert "architecture" not in groups, "架构组 sop_stages 全失效，应整组移除"
    assert groups["development"]["sop_stages"] == ["acceptance"]

    # synthetic 组不依赖 sop_stages，必须保留
    assert "requirement_analysis" in groups
    assert "merge_develop" in groups

    # 任何保留下来的组都不该引用已裁阶段
    dropped = set(cfg["dropped_base_stages"])
    for g in cfg["pipeline_view"]["stages"]:
        assert not (set(g.get("sop_stages") or []) & dropped)


def test_t11h_pruning_is_idempotent():
    """裁剪路径同样要幂等（_prune_dangling_reject_gotos 会 pop 字段，有 mutate 风险）。

    该函数直接 `s.pop("reject_goto")`。若 s 是从 yaml 读出的共享对象，
    第二次调用就会拿到已被剥离的 stage —— 加 lru_cache 后尤其危险。
    """
    def snap():
        cfg = compose_sop(traits=["pipeline:content"], ticket_type="feature")
        return json.dumps(
            {"s": cfg["stages"], "d": cfg["sop_diagnostics"]},
            sort_keys=True, ensure_ascii=False, default=str,
        )

    a, b, c = snap(), snap(), snap()
    assert a == b == c


# ────────────────── 元数据字段（组装结果自描述） ──────────────────

def test_metadata_fields_reflect_inputs():
    cfg = compose_sop(traits=["platform:web", "category:app"], ticket_type="feature")
    assert cfg["traits_used"] == ["category:app", "platform:web"]   # 已排序
    assert cfg["ticket_type_used"] == "feature"
    assert "smoke_test" in cfg["composed_from_fragments"]
    assert cfg["base_stages"] is None        # 运行时不需要，显式置空
