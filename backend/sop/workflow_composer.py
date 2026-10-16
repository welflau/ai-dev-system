"""workflow_composer —— 把 WorkflowSkill 按数据依赖排成有序 stage 列表。

## 为什么是拓扑排序而不是位置锚点

`sop/fragments/*.yaml` 用 `insert_after: development` 表达位置。那有三个问题：
  1. 顺序硬编码进每个能力 —— 想在 A、B 之间插 C，要改 B 的锚点
  2. LLM 无法动态组装 —— 让它吐 `insert_after` 一定会编出不存在的锚点
  3. 锚点失效是静默的 —— loader.py:154 只 warning 后追加末尾

skill 改为声明**数据契约**（consumes/produces），顺序由依赖图推出。LLM 只需回答
「这集需要哪些能力」（集合选择），顺序和合法性由图保证。

## 为什么下游零改动

`sop/loader.py:_relink_stage_transitions` 会**覆盖** stage 自己声明的 trigger_on，
按线性位置重链状态。所以 `insert_after` 本质只是排序 hint —— 把排序依据从位置
换成依赖，`sop_to_transition_rules` / orchestrator / 前端全部无感。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.4
"""
from __future__ import annotations

import heapq
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from skills.executable_loader import WorkflowSkill

logger = logging.getLogger("sop.workflow_composer")

# skill stage 统一由 SkillAgent 执行（决策 2：新能力不新增 Agent）
SKILL_AGENT = "SkillAgent"


def _stage_action(stage_id: str) -> str:
    """stage 的 action 名。

    加 `skill_` 前缀是为了避开 `loader.py:505` 的 `by_action` 索引 ——
    那是「同一 action 多个 fragment 复用时先到先得」，若 skill 的 action 与
    某个 fragment 撞名，`_sop_stage_for` 会反查到错误的 stage。
    """
    return f"skill_{stage_id}"


def skill_to_stage(skill: WorkflowSkill) -> Dict[str, Any]:
    """WorkflowSkill → SOP stage dict。

    状态名全部由 stage_id 派生，SKILL.md 不声明：
      success_status = {stage_id}_done
      reject_status  = {stage_id}_failed
      trigger_on     = 占位，会被 _relink_stage_transitions 覆盖

    **刻意不设 reject_goto**：`loader.py:464` 会据此派生「失败回跳规则」
    （reject_status → goto stage 的 agent.fix_issues）。指回 SkillAgent 就是
    无限重试一个 LLM 自由发挥的 skill —— 烧 token 的风险远大于收益。
    失败走 blocked 等人工，见 orchestrator 的 SkillAgent 分支。
    """
    sid = skill.stage_id
    return {
        "id": sid,
        "name": skill.stage_name,
        "agent": SKILL_AGENT,
        "action": _stage_action(sid),
        "trigger_on": f"{sid}_pending",          # 占位，relink 会改写
        "success_status": f"{sid}_done",
        "reject_status": f"{sid}_failed",
        "description": skill.description,
        "config": {
            "skill_id": skill.skill_id,
            # 下划线前缀 = 框架内部字段，不是给 LLM 看的业务配置。
            # 经 orchestrator.py:1833 进 context["sop_config"]，
            # 供 SkillAgent 读 skill_id、SkillRunner 做 kind 反查。
            "_stage_id": sid,
            "_success_status": f"{sid}_done",
            "_reject_status": f"{sid}_failed",
            "_consumes": [c.to_dict() for c in skill.consumes],
            "_produces": [p.to_dict() for p in skill.produces],
            "_fanout": skill.fanout,
            # UI 分组声明透传给 compose_sop 的 _skill_view_contribs，
            # 让 skill 能像 fragment 一样贡献 pipeline_view 组
            "_pipeline_view_contrib": skill.pipeline_view_contrib,
        },
    }


def _matches(
    skill: WorkflowSkill, traits_set: Set[str], ticket_type: Optional[str],
) -> bool:
    """复用 fragment 的 trait/ticket_type 匹配器。

    把 WorkflowSkill 包成 frag 形状喂给 `_fragment_matches` —— 同一套
    all_of/any_of/none_of 语义，不建第二份解析。
    """
    from sop.loader import _fragment_matches
    return _fragment_matches(
        {
            "required_traits": skill.required_traits,
            "required_ticket_type": skill.required_ticket_type,
        },
        traits_set, ticket_type,
    )


def _resolve_producers(
    skills: List[WorkflowSkill], diagnostics: List[str],
) -> Tuple[Dict[str, WorkflowSkill], List[WorkflowSkill]]:
    """kind → 唯一 producer。一个 kind 多个 producer 时裁决并剔除落选者。

    为什么不「都装」：两个 skill 产出同一 kind 会在同一路径上互相覆盖，
    `latest_per_kind` 取到谁取决于执行顺序，产物总线的语义被破坏。
    真要分叉应该用不同 kind。

    裁决规则：`(-priority, stage_id)` —— priority 高者胜，同 priority 按
    stage_id 字典序，保证结果**可预测**（便于写测试和排查）。
    """
    by_kind: Dict[str, List[WorkflowSkill]] = defaultdict(list)
    for s in skills:
        for kind in s.produce_kinds:
            by_kind[kind].append(s)

    producers: Dict[str, WorkflowSkill] = {}
    dropped: List[WorkflowSkill] = []
    for kind, candidates in by_kind.items():
        if len(candidates) == 1:
            producers[kind] = candidates[0]
            continue
        ordered = sorted(candidates, key=lambda s: (-s.priority, s.stage_id))
        winner, losers = ordered[0], ordered[1:]
        producers[kind] = winner
        dropped.extend(losers)
        msg = (
            f"kind '{kind}' 有多个 producer: "
            f"{[s.stage_id for s in ordered]} → 保留 {winner.stage_id}"
            f"（priority {winner.priority}），其余剔除。"
            f"多个 skill 产出同一 kind 会互相覆盖，应改用不同 kind"
        )
        logger.warning("⚠️ %s", msg)
        diagnostics.append(msg)
    return producers, dropped


def _prune_missing_sources(
    skills: List[WorkflowSkill],
    producers: Dict[str, WorkflowSkill],
    available_kinds: Set[str],
    diagnostics: List[str],
) -> List[WorkflowSkill]:
    """剔除「required consume 既无 producer 也不在 available_kinds」的 skill。

    **fixed-point 级联**：A 出局后它 produce 的 kind 也消失，依赖那个 kind 的 B
    跟着出局，如此迭代到稳定。单轮过滤会留下一串拿不到输入的 skill。

    这不是错误，是「这个项目用不上这个能力」—— 所以用 info 级日志。
    真正的错误（kind 拼错）已在 discover_workflow_skills 的 lint 拦下。
    """
    alive = {s.stage_id: s for s in skills}
    while True:
        produced = {
            kind for kind, s in producers.items() if s.stage_id in alive
        } | available_kinds

        doomed = [
            s for s in alive.values()
            if any(k not in produced for k in s.required_consume_kinds)
        ]
        if not doomed:
            return list(alive.values())

        for s in doomed:
            missing = [k for k in s.required_consume_kinds if k not in produced]
            msg = (
                f"skill {s.stage_id} 出局：required consumes {missing} "
                f"无 producer 且非内置 kind"
            )
            logger.info("⏭ %s", msg)
            diagnostics.append(msg)
            alive.pop(s.stage_id, None)


def _topo_sort(
    skills: List[WorkflowSkill],
    producers: Dict[str, WorkflowSkill],
    diagnostics: List[str],
) -> Optional[List[WorkflowSkill]]:
    """Kahn 拓扑排序。成环返回 None（调用方据此整条链不组装）。

    就绪队列用 heap，key `(-priority, stage_id)` —— 同层顺序稳定且可预测。
    不这么做的话同层顺序取决于 dict 迭代序，测试写不了、线上也不可复现。
    """
    alive = {s.stage_id: s for s in skills}

    # producer_stage → [consumer_stage]
    edges: Dict[str, Set[str]] = defaultdict(set)
    indegree: Dict[str, int] = {sid: 0 for sid in alive}

    for consumer in alive.values():
        for kind in consumer.consume_kinds:          # 含可选依赖：有则排序，无则忽略
            producer = producers.get(kind)
            if producer is None or producer.stage_id not in alive:
                continue
            if producer.stage_id == consumer.stage_id:
                continue                             # 自环已在 lint 拦，这里兜底
            if consumer.stage_id not in edges[producer.stage_id]:
                edges[producer.stage_id].add(consumer.stage_id)
                indegree[consumer.stage_id] += 1

    heap = [
        (-alive[sid].priority, sid)
        for sid, deg in indegree.items() if deg == 0
    ]
    heapq.heapify(heap)

    ordered: List[WorkflowSkill] = []
    while heap:
        _, sid = heapq.heappop(heap)
        ordered.append(alive[sid])
        for nxt in sorted(edges[sid]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(heap, (-alive[nxt].priority, nxt))

    if len(ordered) != len(alive):
        stuck = sorted(sid for sid in alive if indegree[sid] > 0)
        msg = (
            f"skill 依赖成环，涉及 {stuck} —— **整条 skill 链不组装**。"
            f"部分组装会产出「看着能跑但中间断链」的 SOP，比没有更危险"
        )
        logger.error("❌ %s", msg)
        diagnostics.append(msg)
        return None
    return ordered


def _count_parallelizable(ordered: List[WorkflowSkill]) -> int:
    """统计「本可并行但被串行化」的相邻对数。

    拓扑序能表达「A、B 并行后汇入 C」，但 `_relink_stage_transitions` 会把它
    压成 A→B→C 串行链（orchestrator 的 transition_rules 是 Dict[status→rule]
    单链模型，一个状态只能映射一条规则）。

    本次不解决，只把损失量化出来 —— 漫剧场景若要「N 个分镜并行出图」，
    出路是阶段内扁出子工单（dispatch_subtask），而非改 relink。
    """
    count = 0
    for i in range(1, len(ordered)):
        prev, cur = ordered[i - 1], ordered[i]
        # cur 不消费 prev 的任何产出 → 两者本可并行
        if not (set(cur.consume_kinds) & set(prev.produce_kinds)):
            count += 1
    return count


def compose_workflow_stages(
    skills: List[WorkflowSkill],
    traits: Optional[List[str]] = None,
    ticket_type: Optional[str] = None,
    available_kinds: Optional[Set[str]] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """把 WorkflowSkill 列表编译成有序 SOP stage 列表。

    流程：
      1. traits / ticket_type 过滤（复用 _fragment_matches）
      2. produces 建索引，一 kind 多 producer 时裁决
      3. 缺源剔除 + fixed-point 级联
      4. Kahn 拓扑排序（heap 保证同层稳定）
      5. 成环 → 返回空列表（整条链不组装）

    available_kinds 缺省取 `artifacts.kinds` 里标了 builtin 的那些
    （当前只有 ticket_brief）—— 它们由框架产出，视为天然就绪。

    返回 (stages, diagnostics)。diagnostics 会被 compose_sop 并进
    `sop_diagnostics`，供前端 SOP 预览和排障读取。
    """
    diagnostics: List[str] = []
    if not skills:
        return [], diagnostics

    if available_kinds is None:
        from artifacts.kinds import builtin_kinds
        available_kinds = builtin_kinds()

    traits_set = set(traits or [])

    # 1. trait / ticket_type 过滤
    candidates = [s for s in skills if _matches(s, traits_set, ticket_type)]
    if not candidates:
        logger.info("🔍 无 workflow skill 匹配 traits=%s ticket=%s",
                    sorted(traits_set) or "(无)", ticket_type or "(无)")
        return [], diagnostics

    # 2. producer 裁决
    producers, dropped = _resolve_producers(candidates, diagnostics)
    if dropped:
        dropped_ids = {s.stage_id for s in dropped}
        candidates = [s for s in candidates if s.stage_id not in dropped_ids]

    # 3. 缺源剔除（fixed-point）
    candidates = _prune_missing_sources(
        candidates, producers, available_kinds, diagnostics
    )
    if not candidates:
        return [], diagnostics

    # 4-5. 拓扑排序
    ordered = _topo_sort(candidates, producers, diagnostics)
    if ordered is None:
        return [], diagnostics          # 成环 → 整条链不组装

    parallel = _count_parallelizable(ordered)
    if parallel:
        msg = (
            f"检测到 {parallel} 处可并行但已串行化 —— orchestrator 的状态链是"
            f"单链模型，阶段间并行需走「阶段内扁出子工单」(dispatch_subtask)"
        )
        logger.info("ℹ️ %s", msg)
        diagnostics.append(msg)

    stages = [skill_to_stage(s) for s in ordered]
    logger.info("🧩 skill 链组装完成: %s", [s["id"] for s in stages])
    return stages, diagnostics
