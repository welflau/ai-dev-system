"""
SOP 配置加载器
从 YAML 文件加载工作流定义，转换为 orchestrator 可用的 transition_rules
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger("sop")

# SOP 目录
SOP_DIR = Path(__file__).parent


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


def sop_to_transition_rules(config: Dict[str, Any]) -> Dict[str, Dict]:
    """将 SOP 配置转换为 orchestrator 的 transition_rules 格式"""
    stages = config.get("stages", [])
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
