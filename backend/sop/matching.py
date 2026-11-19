"""fragment trait/ticket_type 匹配纯函数 —— P2 拆环叶子模块。

原先 ``_fragment_matches`` 定义在 ``sop.loader``，``sop.workflow_composer``
为了复用它反过来 import ``sop.loader``，与 ``sop.loader → sop.workflow_composer``
（取 compose_workflow_stages）构成双向环。抽到本叶子模块后两边都单向依赖它。

本模块刻意不 import 任何项目内模块，只依赖 typing，因此在静态依赖图里是叶子。
"""
from __future__ import annotations

from typing import Dict, Optional, Set


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
            return False
        # 兼容两种格式：字符串 "feature" 或对象 {any_of: [...]}
        if isinstance(rtt, str):
            if ticket_type != rtt:
                return False
        else:
            any_of = rtt.get("any_of") or []
            none_of = rtt.get("none_of") or []
            if any_of and ticket_type not in any_of:
                return False
            if none_of and ticket_type in none_of:
                return False
    return True
