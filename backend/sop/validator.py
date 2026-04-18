"""
SOP 配置校验器 —— SOP 编辑器保存前用
只在明显结构错误时拒收，不强制所有语义（留空间给灵活配置）。
"""
from typing import Dict, List, Any


_ALLOWED_SYNTHETIC = {"requirement_status", "merge"}
_REQUIRED_STAGE_FIELDS = ["id", "agent", "action", "trigger_on", "success_status"]


def validate_sop_config(cfg: Dict[str, Any]) -> List[str]:
    """
    返回错误信息列表；列表为空即校验通过。
    只做结构性校验，不阻止"未使用的阶段"等软警告。
    """
    errors: List[str] = []

    if not isinstance(cfg, dict):
        return ["配置必须是 dict"]

    # ---- stages ----
    stages = cfg.get("stages")
    if not isinstance(stages, list) or len(stages) == 0:
        errors.append("stages 必须是非空数组")
        return errors  # 后续校验基于 stages，没有就提前返回

    seen_ids = set()
    for idx, s in enumerate(stages):
        if not isinstance(s, dict):
            errors.append(f"stages[{idx}] 必须是对象")
            continue

        for field in _REQUIRED_STAGE_FIELDS:
            val = s.get(field)
            if not val or (isinstance(val, str) and not val.strip()):
                errors.append(f"stages[{idx}] 缺少必填字段: {field}")

        sid = s.get("id", "")
        if sid:
            if sid in seen_ids:
                errors.append(f"stages[{idx}] id '{sid}' 重复")
            seen_ids.add(sid)

        # pass_threshold 如果有必须是数字
        pt = s.get("pass_threshold")
        if pt is not None and not isinstance(pt, (int, float)):
            errors.append(f"stages[{idx}] ('{sid}') pass_threshold 必须是数字")

    # reject_goto 必须指向已存在的 id
    for idx, s in enumerate(stages):
        rg = s.get("reject_goto")
        if rg and rg not in seen_ids:
            errors.append(f"stages[{idx}] ('{s.get('id')}') reject_goto='{rg}' 指向不存在的阶段")

    # ---- pipeline_view（可选）----
    pv = cfg.get("pipeline_view")
    if pv is not None:
        if not isinstance(pv, dict):
            errors.append("pipeline_view 必须是对象")
        else:
            pv_stages = pv.get("stages")
            if not isinstance(pv_stages, list) or len(pv_stages) == 0:
                errors.append("pipeline_view.stages 必须是非空数组")
            else:
                seen_ui_keys = set()
                for idx, ui in enumerate(pv_stages):
                    if not isinstance(ui, dict):
                        errors.append(f"pipeline_view.stages[{idx}] 必须是对象")
                        continue
                    key = ui.get("key")
                    if not key or not isinstance(key, str):
                        errors.append(f"pipeline_view.stages[{idx}] 缺少 key")
                    elif key in seen_ui_keys:
                        errors.append(f"pipeline_view.stages[{idx}] key '{key}' 重复")
                    else:
                        seen_ui_keys.add(key)

                    syn = ui.get("synthetic")
                    sop_stages_ref = ui.get("sop_stages")
                    if syn is None and not sop_stages_ref:
                        errors.append(
                            f"pipeline_view.stages[{idx}] ('{key}') 必须二选一：synthetic 或 sop_stages"
                        )
                    if syn is not None and syn not in _ALLOWED_SYNTHETIC:
                        errors.append(
                            f"pipeline_view.stages[{idx}] ('{key}') synthetic 只能是 "
                            f"{sorted(_ALLOWED_SYNTHETIC)}，当前: {syn}"
                        )
                    if sop_stages_ref:
                        if not isinstance(sop_stages_ref, list):
                            errors.append(
                                f"pipeline_view.stages[{idx}] ('{key}') sop_stages 必须是数组"
                            )
                        else:
                            for ref in sop_stages_ref:
                                if ref not in seen_ids:
                                    errors.append(
                                        f"pipeline_view.stages[{idx}] ('{key}') "
                                        f"sop_stages 引用不存在的 SOP 阶段: {ref}"
                                    )

    return errors
