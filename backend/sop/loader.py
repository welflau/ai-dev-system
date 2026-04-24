"""
SOP 配置加载器
从 YAML 文件加载工作流定义，转换为 orchestrator 可用的 transition_rules

v0.17 Trait-First 扩展：
- compose_sop(traits, ticket_type) —— 从 _core.yaml + fragments/*.yaml
  按 traits/ticket_type 过滤动态组装 SOP
- load_sop() 保持向后兼容，作为无 traits 场景的兜底
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Set

logger = logging.getLogger("sop")

# SOP 目录
SOP_DIR = Path(__file__).parent
FRAGMENTS_DIR = SOP_DIR / "fragments"
CORE_FILE = SOP_DIR / "_core.yaml"


def load_sop(name: str = "default_sop") -> Dict[str, Any]:
    """加载 SOP 配置文件，返回完整配置"""
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML 未安装，使用内置解析")
        return _load_sop_fallback(name)

    sop_file = SOP_DIR / f"{name}.yaml"
    if not sop_file.exists():
        logger.warning("SOP 文件不存在: %s, 使用默认配置", sop_file)
        return _default_sop()

    with open(sop_file, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    logger.info("✅ SOP 已加载: %s (v%s, %d 阶段)",
                config.get("name", name), config.get("version", "?"), len(config.get("stages", [])))
    return config


# ==================== v0.17 Trait-First 组合器 ====================

def compose_sop(
    traits: Optional[List[str]] = None,
    ticket_type: Optional[str] = None,
) -> Dict[str, Any]:
    """根据 traits + ticket_type 动态组装 SOP。

    流程：
      1. 读 _core.yaml 的 base_stages
      2. 扫 fragments/*.yaml
      3. 按 required_traits / required_ticket_type 过滤 fragments
      4. 按 insert_after / insert_before 插入 base_stages
      5. 同插入点按 priority 降序（priority 大的靠近锚点）
      6. 返回跟 load_sop() 兼容的 dict（stages 列表）

    无 traits 时退化为 base_stages（等价于通用 web SOP）。
    """
    import yaml

    # 1. 读 core
    if not CORE_FILE.exists():
        logger.warning("_core.yaml 不存在，回退到 default_sop")
        return load_sop("default_sop")

    with open(CORE_FILE, "r", encoding="utf-8") as f:
        core = yaml.safe_load(f) or {}
    base_stages = list(core.get("base_stages", []))

    traits_set = set(traits or [])

    # 2-4. 扫 fragments，过滤 + 分类（按 insert_after/before 分桶）
    frag_entries: List[Dict] = []
    if FRAGMENTS_DIR.exists():
        for ff in sorted(FRAGMENTS_DIR.glob("*.yaml")):
            try:
                with open(ff, "r", encoding="utf-8") as f:
                    frag = yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning("fragment %s 解析失败: %s", ff.name, e)
                continue

            if not _fragment_matches(frag, traits_set, ticket_type):
                continue
            frag_entries.append(frag)

    # 5. 按 priority 升序排：低优先级先插入，高优先级后插入。
    # 因为 insert(idx+1) 会把后插入的挤到锚点+1 位置，导致高优先级最终更靠近锚点（先执行）。
    # 例：engine_compile (95) + play_test (85) 都 insert_after: development
    #   ASC 序：play_test 先插 → [dev, play, ...]
    #         engine 后插到 dev+1 → [dev, eng, play, ...]  ✓ 高优先级（eng）先跑
    frag_entries.sort(key=lambda f: f.get("priority", 50))

    # 6. 实际插入 —— fixed-point 多轮，解决 fragment-to-fragment 锚点依赖
    #    每轮只插入锚点已存在的 fragment；重复到无变化为止
    composed = list(base_stages)
    pending = list(frag_entries)
    while True:
        applied_any = False
        still_pending: List[Dict] = []
        for frag in pending:
            anchor_after = frag.get("insert_after")
            anchor_before = frag.get("insert_before")
            stage = frag.get("stage", {})
            if not stage:
                logger.warning("fragment %s 缺 stage 块，跳过", frag.get("id"))
                continue
            # 把 fragment 自己的 id/name/description 复制到 stage 里
            for k in ("id", "name", "description"):
                if k not in stage and frag.get(k):
                    stage[k] = frag[k]

            if anchor_after:
                idx = _find_stage_idx(composed, anchor_after)
                if idx is None:
                    still_pending.append(frag)  # 等下一轮
                    continue
                composed.insert(idx + 1, stage)
                applied_any = True
            elif anchor_before:
                idx = _find_stage_idx(composed, anchor_before)
                if idx is None:
                    still_pending.append(frag)
                    continue
                composed.insert(idx, stage)
                applied_any = True
            else:
                composed.append(stage)
                applied_any = True

        pending = still_pending
        if not applied_any:
            # 剩下的 fragment 都找不到锚点 —— 放到末尾并 warning
            for frag in pending:
                stage = frag.get("stage", {})
                logger.warning(
                    "fragment %s: 锚点 %s / %s 未找到，追加到末尾",
                    stage.get("id"),
                    frag.get("insert_after"),
                    frag.get("insert_before"),
                )
                composed.append(stage)
            break
        if not pending:
            break

    # 重新链 trigger_on → success_status：fragment 插入后要让前后阶段的状态链连通
    composed = _relink_stage_transitions(composed)

    # 合并 fragments 的 pipeline_view_contrib 到 core 的 pipeline_view
    merged_view = _merge_pipeline_view(
        core.get("pipeline_view") or {},
        frag_entries,
    )

    result = dict(core)
    result["stages"] = composed
    result["base_stages"] = None   # 运行时不需要
    result["pipeline_view"] = merged_view
    result["composed_from_fragments"] = [f.get("id") for f in frag_entries]
    result["traits_used"] = sorted(traits_set)
    result["ticket_type_used"] = ticket_type

    logger.info(
        "📋 SOP composed: %d 阶段（base %d + fragments %s）traits=%s ticket=%s",
        len(composed), len(base_stages),
        [f.get("id") for f in frag_entries],
        sorted(traits_set) or "(无)", ticket_type or "(无)",
    )
    return result


def _fragment_matches(
    frag: Dict,
    traits_set: Set[str],
    ticket_type: Optional[str],
) -> bool:
    """单个 fragment 是否适用当前 (traits, ticket_type)"""
    rt = frag.get("required_traits")
    if rt:
        all_of = rt.get("all_of") or []
        any_of = rt.get("any_of") or []
        none_of = rt.get("none_of") or []
        if all_of and not all(t in traits_set for t in all_of):
            return False
        if any_of and not any(t in traits_set for t in any_of):
            return False
        if none_of and any(t in traits_set for t in none_of):
            return False

    rtt = frag.get("required_ticket_type")
    if rtt:
        if ticket_type is None:
            # fragment 声明了对 ticket_type 的要求但当前未指定 → 默认不应用
            # （保守策略；若想默认跑，可改成 return True）
            return False
        any_of = rtt.get("any_of") or []
        none_of = rtt.get("none_of") or []
        if any_of and ticket_type not in any_of:
            return False
        if none_of and ticket_type in none_of:
            return False
    return True


def _find_stage_idx(stages: List[Dict], stage_id: str) -> Optional[int]:
    for i, s in enumerate(stages):
        if s.get("id") == stage_id:
            return i
    return None


def _relink_stage_transitions(stages: List[Dict]) -> List[Dict]:
    """fragment 插入后，重新把 trigger_on 链起来。

    规则：
      - 第一个 stage 的 trigger_on 保持 'pending'（项目起点）
      - 后续每个 stage 的 trigger_on ← 前一个 stage 的 success_status
      - fragment 自己声明的 trigger_on（如 smoke_test_pending）被**覆盖** ——
        因为孤立的 trigger_on 没人产出，orchestrator 永远不会触发
      - reject_goto 保留 fragment 自己声明的（没 goto 就不改）
      - **branch_only: true 的 stage 跳过**：它们是 reject_goto 分支目标
        （典型如 rework），只通过拒绝跳转进入，不在线性主链上。
        同时它们也不参与 prev_success 的链接（不然后面 stage 会被接到
        分支 stage 的 success 上，比如 acceptance 接到 rework.success=development_done）

    每个阶段的 success_status 不动。reject_status / reject_goto 不动。
    """
    if not stages:
        return stages
    result = [dict(s) for s in stages]

    prev_success = None
    for i, s in enumerate(result):
        if s.get("branch_only"):
            # 分支目标：保留原声明的 trigger_on / success_status，不参与线性链
            continue
        if i == 0:
            # 第一个阶段的 trigger_on 保留（通常是 'pending'）
            pass
        else:
            if prev_success:
                s["trigger_on"] = prev_success
        prev_success = s.get("success_status")
    return result


def _merge_pipeline_view(
    core_view: Dict[str, Any],
    frag_entries: List[Dict],
) -> Dict[str, Any]:
    """把 fragments 的 pipeline_view_contrib 合并进 core 的 pipeline_view。

    - 已存在的 UI 组 → 把 fragment 的 stage.id 追加到该组的 sop_stages，
      running_statuses 也合并（如果 fragment 自己声明了 reject_status 就一并加）
    - 不存在的 UI 组 → 按 create_if_missing 建新组，insert_after/before 指定相对位置

    fragments 没声明 pipeline_view_contrib 的 —— 默认归到 "testing" 组（兜底）。
    """
    stages = [dict(s) for s in (core_view.get("stages") or [])]
    # 深拷贝可变字段，避免同一个 list 对象被多次 append 污染原 yaml cache
    for s in stages:
        if "sop_stages" in s:
            s["sop_stages"] = list(s["sop_stages"])
        if "running_statuses" in s:
            s["running_statuses"] = list(s["running_statuses"])

    def _find(key: str) -> Optional[int]:
        for i, s in enumerate(stages):
            if s.get("key") == key:
                return i
        return None

    for frag in frag_entries:
        stage_def = frag.get("stage", {}) or {}
        sid = stage_def.get("id") or frag.get("id")
        if not sid:
            continue

        contrib = frag.get("pipeline_view_contrib") or {}
        group = contrib.get("group") or "testing"  # 默认挂到测试组
        create_if_missing = contrib.get("create_if_missing") or {}

        idx = _find(group)
        if idx is None:
            # 新建 UI 组
            new_stage = {
                "key": group,
                "name": create_if_missing.get("name", group),
                "icon": create_if_missing.get("icon", ""),
                "description": create_if_missing.get("description", ""),
                "sop_stages": [],
                "running_statuses": [],
            }
            insert_after = create_if_missing.get("insert_after")
            insert_before = create_if_missing.get("insert_before")
            anchor_idx = None
            if insert_after:
                anchor_idx = _find(insert_after)
                if anchor_idx is not None:
                    stages.insert(anchor_idx + 1, new_stage)
            if anchor_idx is None and insert_before:
                anchor_idx = _find(insert_before)
                if anchor_idx is not None:
                    stages.insert(anchor_idx, new_stage)
            if anchor_idx is None:
                # 没锚点 —— 放到 merge_develop 之前（若有），否则末尾
                merge_idx = _find("merge_develop")
                if merge_idx is not None:
                    stages.insert(merge_idx, new_stage)
                else:
                    stages.append(new_stage)
            idx = _find(group)

        # 往 group 里塞 sop_stage id + running_statuses
        target = stages[idx]
        target.setdefault("sop_stages", [])
        target.setdefault("running_statuses", [])
        if sid not in target["sop_stages"]:
            target["sop_stages"].append(sid)

        # 收集该 fragment 可能的 running 状态：trigger_on / reject_status
        # （success_status 不算 running——它是"过了"这组才有的状态）
        for status_key in ("trigger_on", "reject_status"):
            st = stage_def.get(status_key)
            if st and st not in target["running_statuses"]:
                target["running_statuses"].append(st)

    result = dict(core_view)
    result["stages"] = stages
    return result


# ==================== end v0.17 ====================



def sop_to_transition_rules(config: Dict[str, Any]) -> Dict[str, Dict]:
    """将 SOP 配置转换为 orchestrator 的 transition_rules 格式

    v0.18 Phase D: 除了 trigger_on → agent.action 的主规则，还会从 reject_status +
    reject_goto 派生 **失败回跳规则**：reject_status → {goto stage 的 agent}.fix_issues。
    这让 SOP yaml 里声明的"编译失败走 fix_issues 反思重写"能自动落地，
    不再需要手写对应规则。
    """
    stages = config.get("stages", [])
    stages_by_id = {s.get("id"): s for s in stages if s.get("id")}
    rules = {}

    for stage in stages:
        trigger = stage.get("trigger_on")
        if not trigger:
            continue

        rule = {
            "agent": stage["agent"],
            "action": stage["action"],
            "next_status": _get_next_status(stage),
        }

        # 可选字段
        if stage.get("pass_threshold"):
            rule["pass_threshold"] = stage["pass_threshold"]
        if stage.get("optional"):
            rule["optional"] = True
        if stage.get("config"):
            rule["config"] = stage["config"]

        rules[trigger] = rule

        # v0.18 D：派生 reject 回跳规则
        reject_status = stage.get("reject_status")
        reject_goto = stage.get("reject_goto")
        if reject_status and reject_goto and reject_status not in rules:
            goto_stage = stages_by_id.get(reject_goto)
            if goto_stage:
                rules[reject_status] = {
                    "agent": goto_stage.get("agent", "DevAgent"),
                    # fix_issues 是 DevAgent 的反思修复 action；若 goto 的 agent 不是
                    # DevAgent（未来扩展场景），保留 goto 阶段自己的 action 作兜底
                    "action": "fix_issues" if goto_stage.get("agent") == "DevAgent"
                              else goto_stage.get("action", "fix_issues"),
                    "next_status": _get_next_status(goto_stage),
                    "config": goto_stage.get("config", {}),
                    "_rework_source_stage": stage.get("id"),
                    "_rework_goto_stage": reject_goto,
                }

    logger.info("📋 转换规则: %d 条状态转换", len(rules))
    return rules


def get_sop_stages(config: Dict[str, Any]) -> List[Dict]:
    """获取所有阶段定义（供前端展示）"""
    stages = config.get("stages", [])
    result = []
    for s in stages:
        result.append({
            "id": s.get("id", ""),
            "name": s.get("name", s.get("id", "")),
            "agent": s.get("agent", ""),
            "action": s.get("action", ""),
            "trigger_on": s.get("trigger_on", ""),
            "success_status": s.get("success_status", ""),
            "reject_status": s.get("reject_status"),
            "reject_goto": s.get("reject_goto"),
            "description": s.get("description", ""),
            "optional": s.get("optional", False),
            "pass_threshold": s.get("pass_threshold"),
            "config": s.get("config", {}),
        })
    return result


def get_sop_metadata(config: Dict[str, Any]) -> Dict:
    """获取 SOP 元信息"""
    return {
        "name": config.get("name", "未命名流程"),
        "version": config.get("version", "1.0"),
        "description": config.get("description", ""),
        "stage_count": len(config.get("stages", [])),
    }


def _get_next_status(stage: Dict) -> Optional[str]:
    """推断阶段执行后的中间状态（in_progress）"""
    agent = stage.get("agent", "")
    action = stage.get("action", "")

    # 常见的 in_progress 状态映射
    status_map = {
        ("ArchitectAgent", "design_architecture"): "architecture_in_progress",
        ("DevAgent", "develop"): "development_in_progress",
        ("DevAgent", "rework"): "development_in_progress",
        ("DevAgent", "fix_issues"): "development_in_progress",
        ("TestAgent", "run_tests"): "testing_in_progress",
    }

    return status_map.get((agent, action))


# =============================================================================
# Pipeline 可视化配置派生（从 SOP 生成 UI 5 阶段的 STAGE_DEFS / PAST / PRE）
# =============================================================================

# 终态状态（SOP 之外，硬性附加到线性序尾部）
_TERMINAL_STATUSES = ["deploying", "deployed"]


def _statuses_for_sop_stage(stage: Dict) -> List[str]:
    """某 SOP 阶段"处于该阶段中"的工单 status 集（按进入顺序）：
    [_in_progress（如有）, success_status, reject_status（如有）]"""
    result: List[str] = []
    in_progress = _get_next_status(stage)
    if in_progress:
        result.append(in_progress)
    success = stage.get("success_status")
    if success:
        result.append(success)
    reject = stage.get("reject_status")
    if reject:
        result.append(reject)
    return result


def _build_status_linear_order(sop_stages: List[Dict]) -> List[str]:
    """按 SOP 声明顺序走一遍，收集所有可能的工单 status 并排线性序"""
    order = ["pending"]
    seen = set(order)
    for stage in sop_stages:
        for s in _statuses_for_sop_stage(stage):
            if s not in seen:
                order.append(s)
                seen.add(s)
    for s in _TERMINAL_STATUSES:
        if s not in seen:
            order.append(s)
            seen.add(s)
    return order


def build_pipeline_stages(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 SOP 配置派生 Pipeline UI 的阶段定义。

    入参：SOP config（由 load_sop 加载）
    返回：
      {
        "order": ["stage_key", ...],                 # UI stage key 顺序
        "defs": [                                    # 每个 UI stage 的定义
          {"key", "name", "icon", "synthetic" / "sop_stages", "in_statuses": [...]},
          ...
        ],
        "past": {"stage_key": {status, ...}, ...},   # 判定 stage 已完成的 status 集
        "pre":  {"stage_key": {status, ...}, ...},   # 判定 stage 未开始的 status 集
      }

    注意：
    - synthetic 合成阶段（需求分析 / 合入Develop）不进 past/pre（上层用需求级 status 判定）
    - past_i = 从"第一个 SOP 子阶段的 success_status"往后的所有线性序 status
    - pre_i  = 第一个"处理中"status（_in_progress 或无则 success）之前的所有 status
    """
    sop_stages = config.get("stages", [])
    view_cfg = config.get("pipeline_view", {}) or {}
    ui_stages = view_cfg.get("stages", []) or []

    if not ui_stages:
        # 没配 pipeline_view：回退到硬编码兼容模式（避免破坏）
        return _legacy_pipeline_stages()

    # SOP id → stage 对象索引
    sop_by_id = {s.get("id"): s for s in sop_stages if s.get("id")}

    linear = _build_status_linear_order(sop_stages)
    linear_idx = {s: i for i, s in enumerate(linear)}

    # sop_stage id → 它所属的 UI group key（反向索引，用于 reject_goto 判定）
    sop_to_ui: Dict[str, str] = {}
    for ui in ui_stages:
        for sid in ui.get("sop_stages") or []:
            sop_to_ui[sid] = ui["key"]

    # UI group key → 声明序索引（用于判定"前置/后置 UI 组"）
    ui_order_idx = {ui["key"]: i for i, ui in enumerate(ui_stages)}

    defs: List[Dict[str, Any]] = []
    past: Dict[str, set] = {}
    pre: Dict[str, set] = {}
    order_keys: List[str] = []

    for ui in ui_stages:
        key = ui.get("key")
        if not key:
            continue
        order_keys.append(key)

        entry = {
            "key": key,
            "name": ui.get("name", key),
            "icon": ui.get("icon", ""),
            "description": ui.get("description", ""),
        }

        if ui.get("synthetic"):
            entry["synthetic"] = ui["synthetic"]
            entry["in_statuses"] = []
            defs.append(entry)
            continue

        sop_ids = ui.get("sop_stages") or []
        entry["sop_stages"] = sop_ids

        # 找该 UI 组的"主 SOP stage"（第一个非返工 stage）——
        # 返工 stage 特征：success_status 映射回 earlier UI group（reject_goto 机制带回前置 UI 组）
        primary_sid = None
        rework_sids: List[str] = []
        for sid in sop_ids:
            sstage = sop_by_id.get(sid)
            if not sstage:
                continue
            success = sstage.get("success_status")
            # 若 success_status 属于"更早 UI 组"内工单会进入的 status（即本 stage 是返工型）
            # 粗判：success_status 在 linear_order 中早于该 UI 组其他 stage 的 _in_progress
            if primary_sid is None:
                primary_sid = sid
            elif success and success in linear_idx:
                first_in_main = _get_next_status(sop_by_id[primary_sid]) \
                    or sop_by_id[primary_sid].get("success_status")
                if first_in_main and first_in_main in linear_idx \
                        and linear_idx[success] < linear_idx[first_in_main]:
                    rework_sids.append(sid)
                # 否则视作续写主流程的 stage（如 acceptance 接 development）

        # 收集 in_statuses —— 仅聚合主 SOP stage + 续写 stage 的 status，
        # 排除返工 stage（其 success 指向更早 UI 组）
        in_set: List[str] = []
        for sid in sop_ids:
            if sid in rework_sids:
                continue
            sstage = sop_by_id.get(sid)
            if not sstage:
                logger.warning("pipeline_view 引用了不存在的 SOP stage: %s", sid)
                continue
            for s in _statuses_for_sop_stage(sstage):
                if s not in in_set:
                    in_set.append(s)
        entry["in_statuses"] = in_set
        # running_statuses：yaml 里显式给的"正在运行该 UI 组"的状态集；
        # 不给的话回退为 in_statuses 第一个（通常是 _in_progress）
        running = ui.get("running_statuses")
        if running is not None:
            entry["running_statuses"] = list(running)
        elif in_set:
            entry["running_statuses"] = [in_set[0]]
        else:
            entry["running_statuses"] = []

        # past / pre 基于主 SOP stage
        if primary_sid:
            primary_stage = sop_by_id[primary_sid]
            first_success = primary_stage.get("success_status")
            if first_success and first_success in linear_idx:
                start = linear_idx[first_success]
                past_set = set(linear[start:])
                # 排除"reject 后会回退到更早状态"的 reject_status
                # （例：testing 组的 testing_failed → fix_issues → success 指向 development_done
                # 比 testing 组的 first_success 早，说明是真正的回退，不算"过了测试"）
                for sid in sop_ids:
                    sstage = sop_by_id.get(sid)
                    if not sstage:
                        continue
                    reject = sstage.get("reject_status")
                    reject_goto = sstage.get("reject_goto")
                    if not reject or not reject_goto:
                        continue
                    goto_stage = sop_by_id.get(reject_goto)
                    if not goto_stage:
                        continue
                    goto_success = goto_stage.get("success_status")
                    if not goto_success or goto_success not in linear_idx:
                        continue
                    # 若 reject_goto 的最终落点早于本 UI 组的 first_success 起点，说明回退
                    if linear_idx[goto_success] < start:
                        past_set.discard(reject)
                past[key] = past_set
            else:
                past[key] = set()

            first_processing = _get_next_status(primary_stage) or first_success
            if first_processing and first_processing in linear_idx:
                end = linear_idx[first_processing]
                pre[key] = set(linear[:end])
            else:
                pre[key] = set()

        defs.append(entry)

    return {
        "order": order_keys,
        "defs": defs,
        "past": past,
        "pre": pre,
        "linear_order": linear,
    }


def _legacy_pipeline_stages() -> Dict[str, Any]:
    """Pipeline view 未配置时的硬编码回退（与 api/requirements.py 原值等价）"""
    return {
        "order": ["requirement_analysis", "architecture", "development", "testing", "merge_develop"],
        "defs": [
            {"key": "requirement_analysis", "name": "需求分析", "icon": "📋",
             "synthetic": "requirement_status", "in_statuses": []},
            {"key": "architecture", "name": "架构设计", "icon": "🏗️",
             "sop_stages": ["architecture"],
             "in_statuses": ["architecture_in_progress", "architecture_done"]},
            {"key": "development", "name": "开发实现", "icon": "💻",
             "sop_stages": ["development", "acceptance", "rework"],
             "in_statuses": ["development_in_progress", "development_done",
                             "acceptance_passed", "acceptance_rejected"]},
            {"key": "testing", "name": "测试验证", "icon": "🧪",
             "sop_stages": ["testing", "fix_issues"],
             "in_statuses": ["testing_in_progress", "testing_done", "testing_failed"]},
            {"key": "merge_develop", "name": "合入Develop", "icon": "🔀",
             "synthetic": "merge", "in_statuses": []},
        ],
        "past": {
            "architecture": {"architecture_done", "development_in_progress", "development_done",
                             "acceptance_passed", "acceptance_rejected", "testing_in_progress",
                             "testing_done", "testing_failed", "deploying", "deployed"},
            "development": {"development_done", "acceptance_passed", "acceptance_rejected",
                            "testing_in_progress", "testing_done", "testing_failed",
                            "deploying", "deployed"},
            "testing": {"testing_done", "deploying", "deployed"},
        },
        "pre": {
            "architecture": {"pending"},
            "development": {"pending", "architecture_in_progress", "architecture_done"},
            "testing": {"pending", "architecture_in_progress", "architecture_done",
                        "development_in_progress", "development_done",
                        "acceptance_passed", "acceptance_rejected"},
        },
        "linear_order": [],
    }


def _default_sop() -> Dict[str, Any]:
    """内置默认 SOP（不依赖 YAML 文件）"""
    return {
        "name": "默认开发流程",
        "version": "1.0",
        "description": "内置默认流程",
        "stages": [
            {"id": "architecture", "agent": "ArchitectAgent", "action": "design_architecture",
             "trigger_on": "pending", "success_status": "architecture_done"},
            {"id": "development", "agent": "DevAgent", "action": "develop",
             "trigger_on": "architecture_done", "success_status": "development_done"},
            {"id": "acceptance", "agent": "ProductAgent", "action": "acceptance_review",
             "trigger_on": "development_done", "success_status": "acceptance_passed",
             "reject_status": "acceptance_rejected", "reject_goto": "rework"},
            {"id": "testing", "agent": "TestAgent", "action": "run_tests",
             "trigger_on": "acceptance_passed", "success_status": "testing_done",
             "reject_status": "testing_failed", "reject_goto": "fix_issues", "pass_threshold": 60},
            {"id": "rework", "agent": "DevAgent", "action": "rework",
             "trigger_on": "acceptance_rejected", "success_status": "development_done"},
            {"id": "fix_issues", "agent": "DevAgent", "action": "fix_issues",
             "trigger_on": "testing_failed", "success_status": "development_done"},
        ],
    }


def _load_sop_fallback(name: str) -> Dict[str, Any]:
    """不依赖 PyYAML 的简单解析（兜底）"""
    sop_file = SOP_DIR / f"{name}.yaml"
    if not sop_file.exists():
        return _default_sop()

    # 简易 YAML 解析（只处理本项目用到的简单格式）
    import re
    content = sop_file.read_text(encoding="utf-8")

    config = {"stages": []}
    current_stage = None

    for line in content.split("\n"):
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue

        # 顶层字段
        if re.match(r'^(name|version|description):', line):
            key, val = line.split(":", 1)
            val = val.strip().strip('"').strip("'")
            config[key.strip()] = val
            continue

        # 新阶段
        if line_stripped.startswith("- id:"):
            current_stage = {"id": line_stripped.split(":", 1)[1].strip()}
            config["stages"].append(current_stage)
            continue

        # 阶段属性
        if current_stage and ":" in line_stripped:
            key, val = line_stripped.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val.lower() == "true":
                val = True
            elif val.lower() == "false":
                val = False
            elif val.isdigit():
                val = int(val)
            if key in ("id", "name", "agent", "action", "trigger_on", "success_status",
                       "reject_status", "reject_goto", "description", "optional", "pass_threshold"):
                current_stage[key] = val

    logger.info("✅ SOP 已加载(fallback): %s (%d 阶段)", config.get("name", name), len(config["stages"]))
    return config
