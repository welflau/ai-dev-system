"""脚手架工单识别 —— 判定「初始化项目脚手架与技术栈」类工单。

背景：DevAgent 用 existing_code 是否为空区分「全新生成 / 增量修改」
（agents/dev.py::_do_develop），但仓库 clone 自带 README/.gitignore、
第一轮降级产出的 index.html 都会让 existing_code 恒非空，导致脚手架
工单被判成增量 → PlanCodeChange 回退 WriteCode → write_code._fallback
的「已有代码不许用降级模板」硬失败 → development_failed 无限循环。
TK-20261110-48b6af 实测 344 次 LLM 调用 / 25 reject。

治本不是继续调 existing_code 的语义，而是给脚手架工单一条独立的
确定性路由（actions/scaffold_web.py）。本模块只回答「是不是脚手架工单」，
任何一步不确定都返回 False 走原路径（保守，只降级不升级）。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger("actions.scaffold_utils")

# 脚手架模板目前只覆盖纯前端 Web + TS/JS 新项目
_WEB_TRAIT = "platform:web"
_LANG_TRAITS = {"lang:typescript", "lang:javascript"}

# 命中 >= 2 个才算，避免单个「搭建」误伤业务功能工单
_SCAFFOLD_KEYWORDS = (
    "初始化", "脚手架", "技术栈", "项目骨架", "目录结构", "统一入口",
    "类型定义", "共享工具", "工程配置", "基础框架", "构建配置", "搭建",
)
_EXCLUDED_TYPES = {"bug", "bugfix", "hotfix"}


def _as_list(v: Any) -> list:
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip():
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    return []


async def is_scaffold_ticket(context: Dict[str, Any]) -> bool:
    """是否为「初始化脚手架」类工单。判不准一律返回 False 走原路径。"""
    ticket_id = str(context.get("ticket_id") or "")
    requirement_id = str(context.get("requirement_id") or "")
    if not ticket_id or not requirement_id:
        return False

    # A. 项目 traits：纯前端 Web + TS/JS
    traits = set(context.get("traits") or context.get("project_traits") or [])
    if _WEB_TRAIT not in traits or not (traits & _LANG_TRAITS):
        return False

    # B. 标题/描述关键词 >= 2
    text = (str(context.get("ticket_title") or "") + " " +
            str(context.get("ticket_description") or "")).lower()
    hits = [k for k in _SCAFFOLD_KEYWORDS if k in text]
    if len(hits) < 2:
        return False

    # C. 拆单 DAG 根节点：sort_order==0、无前置依赖、且被同需求其它工单依赖。
    #    这三条组合才能区分「脚手架首单」与「独立 bug 单 / 老项目无依赖单」。
    try:
        from database import db
        row = await db.fetch_one(
            "SELECT type, sort_order, dependencies FROM tickets WHERE id = ?",
            (ticket_id,),
        )
        if not row:
            return False
        if str(row.get("type") or "").lower() in _EXCLUDED_TYPES:
            return False
        if int(row.get("sort_order") or 0) != 0:
            return False
        if _as_list(row.get("dependencies")):
            return False
        siblings = await db.fetch_all(
            "SELECT dependencies FROM tickets WHERE requirement_id = ? AND id != ?",
            (requirement_id, ticket_id),
        )
        depended = any(
            ticket_id in {str(x) for x in _as_list(s.get("dependencies"))}
            for s in (siblings or [])
        )
        if not depended:
            return False
    except Exception as e:
        logger.warning("脚手架识别查询失败，回退原路径: %s", e)
        return False

    logger.info("🧩 识别为脚手架工单 %s（关键词=%s）", ticket_id[:12], hits[:4])
    return True
