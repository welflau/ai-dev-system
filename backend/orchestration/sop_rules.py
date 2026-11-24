"""SOP 规则：加载默认转换规则，按项目特征派生规则，查阶段定义，片段收尾。

`TicketOrchestrator` 用「状态 → 该派给哪个 Agent 做什么」这张表驱动工单流转。默认的一份在
启动时从 `default_sop` 读出来放在 `orch.transition_rules`；带 traits 的项目由
`get_rules_for_project` 调 `compose_sop` 现算，结果缓存在 `orch._project_rules_cache`。
`get_all_actionable_statuses` 把默认规则和所有活跃项目的规则并起来，给轮询当扫描条件。

`apply_fragment_closeout` 处理声明了 `closeout: status` 的片段阶段：按片段写状态、记日志、
跑 `on_success` / `on_failure` 钩子，失败时按钩子的返回值回跳。文件开头的几个纯函数是它
拼日志和找回跳目标用的。

`is_noncode_ticket` 和 `needs_design_stage` 是两个按关键词判断工单性质的启发式，SOP 片段的
跳过条件会用到。

约定（`orchestration` 包里按职责拆出的模块都一样）：

- 函数体从 `TicketOrchestrator` 的同名方法原样搬来，函数名去掉了前导下划线。改动只有
  `self` 写成 `orch`，以及下面单独列出的几处。
- `TicketOrchestrator` 上保留同名方法，只做转发。这里的函数互相调用、调用别的模块里的
  逻辑都走 `orch.xxx`，测试给实例打的桩才会生效。
- `db` 由转发方法在调用时传入，这里不导入它。测试用
  `monkeypatch.setattr(orchestrator, "db", test_db)` 换库，函数必须拿到同一个对象。
- 状态都放在 `orch` 上，这个模块自己不存状态。
- 函数内的延迟导入保持原样，测试的打桩打在这些源模块上。

关键词表和终态集合这几个常量也搬到了这里，类上的同名属性指向同一个对象。函数里仍然经
`orch._UI_KEYWORDS_CN` 这样的类属性读它们，和搬之前一样。
"""
import json
import logging
from typing import Any, Dict, List, Optional

from models import TicketStatus
from utils import now_iso

logger = logging.getLogger("orchestrator")


def stage_hook_names(stage: Dict, key: str) -> List[str]:
    """片段 stage 上的 on_success / on_failure。只认字符串名字。"""
    raw = (stage or {}).get(key) or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [item.strip() for item in raw if isinstance(item, str) and item.strip()]


def rewind_trigger(stages: List[Dict], stage_id: str) -> Optional[str]:
    """回跳目标是组合后该阶段的 trigger_on，不是 YAML 里手写的那个，也不是阶段 id。"""
    for stage in stages or []:
        if stage.get("id") == stage_id:
            trigger = stage.get("trigger_on")
            return str(trigger) if trigger else None
    return None


def closeout_log_level(result: Dict, ok: bool) -> str:
    if not ok:
        return "warning"
    warnings = result.get("warnings") or []
    nested = result.get("ue_test_gen")
    if isinstance(nested, dict) and nested.get("warnings"):
        warnings = nested.get("warnings") or []
    return "warning" if warnings else "info"


def closeout_message(
    stage: Dict, result: Dict, ok: bool, notes: Optional[List[str]] = None,
) -> str:
    extra = "".join(str(item) for item in (notes or []) if item)
    name = str(stage.get("name") or stage.get("id") or "阶段")
    nested = result.get("ue_test_gen")
    if isinstance(nested, dict) and nested.get("summary"):
        return f"{nested['summary']}{extra}"
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    try:
        secs = int(result.get("duration_ms") or 0) // 1000
    except (TypeError, ValueError):
        secs = 0
    goto = stage.get("reject_goto")
    tail = f"，打回 {goto}" if (not ok and goto) else ""
    if ok:
        if "total" in summary:
            return (
                f"{name} 通过（{summary.get('passed', 0)}/{summary.get('total', 0)}，{secs}s）{extra}"
            )
        target = result.get("target_name")
        bits: List[str] = []
        if result.get("duration_ms") is not None:
            bits.append(f"{secs}s")
        if target:
            bits.append(f"target={target}")
        if bits:
            return f"{name} 通过（{'，'.join(bits)}）{extra}"
        return f"{name} 通过{extra}"
    errors = result.get("errors") or []
    if errors:
        return f"{name} 失败 · {len(errors)} 个错误{tail}{extra}"
    if "total" in summary:
        return (
            f"{name} 失败 · {summary.get('failed', 0)}/{summary.get('total', 0)} failed{tail}{extra}"
        )
    return f"{name} 失败{tail}{extra}"


def closeout_detail(result: Dict) -> Dict[str, Any]:
    """收尾日志要带上反思和验收还在读的字段。"""
    detail: Dict[str, Any] = {}
    if not isinstance(result, dict):
        return detail
    errors = [item for item in (result.get("errors") or []) if isinstance(item, dict)]
    if errors:
        detail["errors"] = errors[:10]
        parts = []
        for item in errors[:3]:
            fname = str(item.get("file") or "?").replace("\\", "/").split("/")[-1]
            parts.append(
                f"{fname}:{item.get('line', '?')} {item.get('code', '')} "
                f"{str(item.get('msg') or '')[:80]}"
            )
        detail["err_brief"] = "; ".join(parts)
    warnings = result.get("warnings") or []
    if warnings:
        detail["warnings"] = list(warnings)[:5]
    for key, limit in (("hints", 5), ("screenshots", 5)):
        value = result.get(key)
        if isinstance(value, list) and value:
            detail[key] = value[:limit]
    products = result.get("products")
    if products:
        detail["products"] = products
    for key in ("exit_code", "duration_ms", "command", "task_id", "summary", "target_name"):
        value = result.get(key)
        if value not in (None, "", [], {}):
            detail[key] = value
    raw_tail = result.get("raw_tail")
    if raw_tail:
        detail["raw_tail"] = str(raw_tail)[-4000:]
    tests = result.get("tests") or []
    failed = [item for item in tests if isinstance(item, dict) and item.get("result") == "failed"]
    if failed:
        detail["tests"] = failed[:10]
        briefs = []
        for item in failed[:3]:
            first = (item.get("errors") or ["?"])[:1]
            briefs.append(f"{item.get('name', '?')}: {str(first[0])[:60]}")
        detail["fail_brief"] = "; ".join(briefs)
    module_errors = result.get("module_load_errors") or []
    if module_errors:
        detail["module_load_errors"] = module_errors
    nested = result.get("ue_test_gen")
    if isinstance(nested, dict):
        detail["generated"] = nested.get("generated") or []
        if nested.get("warnings"):
            detail["warnings"] = list(nested.get("warnings") or [])[:10]
    return detail


def load_transition_rules(orch) -> Dict:
    """从 SOP YAML 加载状态转换规则（默认 web 项目）"""
    try:
        from sop.loader import load_sop, sop_to_transition_rules
        orch._sop_config = load_sop("default_sop")
        rules = sop_to_transition_rules(orch._sop_config)
        if rules:
            logger.info("📋 SOP 配置已加载: %s (%d 条规则)",
                        orch._sop_config.get("name", "?"), len(rules))
            return rules
    except Exception as e:
        logger.warning("SOP 配置加载失败，使用内置规则: %s", e)

    # 兜底：内置硬编码规则
    logger.info("📋 使用内置状态转换规则")
    return {
        TicketStatus.PENDING.value: {
            "agent": "PlannerAgent",
            "action": "write_prd",
            "next_status": TicketStatus.PLANNING_IN_PROGRESS.value,
        },
        TicketStatus.PLANNING_DONE.value: {
            "agent": "ArchitectAgent",
            "action": "design_architecture",
            "next_status": TicketStatus.ARCHITECTURE_IN_PROGRESS.value,
        },
        TicketStatus.ARCHITECTURE_DONE.value: {
            "agent": "DevAgent",
            "action": "develop",
            "next_status": TicketStatus.DEVELOPMENT_IN_PROGRESS.value,
        },
        TicketStatus.DEVELOPMENT_DONE.value: {
            "agent": "ProductAgent",
            "action": "acceptance_review",
            "next_status": None,
        },
        TicketStatus.ACCEPTANCE_PASSED.value: {
            "agent": "TestAgent",
            "action": "run_tests",
            "next_status": TicketStatus.TESTING_IN_PROGRESS.value,
        },
        TicketStatus.ACCEPTANCE_REJECTED.value: {
            "agent": "DevAgent",
            "action": "rework",
            "next_status": TicketStatus.DEVELOPMENT_IN_PROGRESS.value,
        },
        TicketStatus.TESTING_FAILED.value: {
            "agent": "DevAgent",
            "action": "fix_issues",
            "next_status": TicketStatus.DEVELOPMENT_IN_PROGRESS.value,
        },
    }


def reload_sop(orch):
    """热重载 SOP 配置（供 API 调用）"""
    orch.transition_rules = orch._load_transition_rules()
    # v0.17 清掉项目级缓存，下次 dispatch 时按最新 default + traits 重算
    orch._project_rules_cache.clear()
    # v0.20 compose_sop 自己也带缓存（单次组装 53ms）。只清 rules 不清它
    # 等于热重载无效 —— 派生 rules 的输入还是旧 config。
    try:
        from sop.loader import invalidate_sop_cache
        invalidate_sop_cache()
    except Exception as e:
        logger.warning("清 SOP 组装缓存失败（忽略）: %s", e)
    return orch._sop_config


# 非代码工单关键词：命中则跳过 UE 引擎编译（无可编译 C++）
NONCODE_TICKET_KEYWORDS = (
    "验证 openspec", "openspec 流程", "验证流程", "跑通流程", "流程验证",
    "测试流程", "件套", "冒烟", "验证钩子", "钩子验证", "端到端",
    "验证 propose", "propose 流程", "流程测试", "验收流程",
)


def is_noncode_ticket(orch, ticket: Dict) -> bool:
    """启发式判断工单是否为"非代码验证/流程类"（无可编译产物）。

    用于让 engine_compile fragment 对这类工单跳过——它们描述的是"验证某流程
    跑通"而非"实现某功能"，硬跑 UBT 编译只会空转报错。
    仅按标题+描述关键词匹配，宁可漏跳（真实代码工单照常编译）也不误跳。
    """
    text = f"{ticket.get('title', '')} {ticket.get('description', '')}".lower()
    return any(kw in text for kw in orch._NONCODE_TICKET_KEYWORDS)


# ── 界面/视觉相关信号 ──────────────────────────────────────────
# ux_design / art_design fragment 的 trait 条件是 platform:* / category:game，
# 任何桌面或游戏项目都必然命中，跟工单本身是否涉及界面无关。
# 实测：给 UE 项目加一个纯 C++ 的 SprintComponent，也会跑完整 UX 设计 +
# 视觉规范 + design_tokens.json，空转 153s。
#
# 判定策略与 _is_noncode_ticket 相反：这里要的是"确定不需要 UI"才跳过，
# 所以采用白名单（命中任一 UI 信号 → 正常走设计阶段），宁可多跑不可漏跑。
#
# 中文按子串匹配（无词边界概念）；英文必须按**单词**匹配 ——
# 子串匹配会让 "ui" 命中 build/guide/require/suite，"form" 命中
# format/performance/platform，"icon" 命中 silicon，几乎全部工单都会误判为需要设计。
UI_KEYWORDS_CN = (
    "界面", "页面", "视图", "布局", "样式", "主题", "配色", "图标", "字体",
    "按钮", "弹窗", "对话框", "菜单", "表单", "列表页", "面板", "控件",
    "交互", "动效", "动画", "过渡", "美术", "视觉",
    "素材", "贴图", "材质", "特效", "蓝图界面", "响应式", "适配",
    "前端", "原型", "线框", "设计稿", "可视化", "图表", "渲染",
)
UI_KEYWORDS_EN = frozenset({
    "ui", "ux", "hud", "gui", "interface", "layout", "style", "styles",
    "styling", "theme", "themes", "palette", "icon", "icons", "button",
    "buttons", "dialog", "modal", "menu", "menus", "form", "forms",
    "panel", "widget", "widgets", "screen", "screens", "animation",
    "animations", "transition", "frontend", "front-end", "responsive",
    "chart", "charts", "visual", "visuals", "texture", "textures",
    "material", "materials", "shader", "shaders", "sprite", "sprites",
    "css", "scss", "wireframe", "mockup", "render", "rendering",
})
WORD_RE = __import__("re").compile(r"[a-z][a-z\-]*")

# 明确不涉及界面的模块类型（module 字段）
NON_UI_MODULES = frozenset({"backend", "api", "database", "test"})


def needs_design_stage(orch, ticket: Dict) -> bool:
    """工单是否真的需要 UX / 美术设计阶段。

    任一成立即认为需要：
      1. module 是界面相关类型（frontend / design / character 等）
      2. 标题或描述命中 UI 信号（中文子串 / 英文整词）

    module ∈ {backend, api, database, test} 或 other，且无任何 UI 信号
    → 跳过设计阶段。判不准时一律走（宁可多跑 153s，不可漏做设计）。
    """
    module = (ticket.get("module") or "").lower()
    # 非 "other" 的界面相关 module 直接放行
    if module and module not in orch._NON_UI_MODULES and module != "other":
        return True

    text = f"{ticket.get('title', '')} {ticket.get('description', '')}".lower()
    if any(kw in text for kw in orch._UI_KEYWORDS_CN):
        return True
    # 英文按整词匹配，避免 build→ui / platform→form 之类的子串误命中
    return bool(orch._UI_KEYWORDS_EN & set(orch._WORD_RE.findall(text)))


async def get_rules_for_project(
    orch, db,
    project_id: str,
    traits_json: Optional[str] = None,
    ticket_type: Optional[str] = None,
) -> Dict:
    """按项目 traits + 工单 type 派生 transition_rules。

    无 traits（老 web 项目 / 未迁移）→ 用 default `orch.transition_rules`。
    有 traits → 调 compose_sop + sop_to_transition_rules，cache 一份。

    ticket_type 参与 compose：fragment 可声明 required_ticket_type
    （如 ue_content_gen 只对 type=ue_content 工单生效）。不传则该类
    fragment 不会被组装进来 —— 所以扫状态/续跑时务必带上工单自己的 type，
    否则派生出的规则集和实际派单用的规则集会不一致。

    cache key 是 (project_id, traits_tuple, ticket_type)；任一变动自然 miss。
    """
    if traits_json is None:
        row = await db.fetch_one(
            "SELECT traits FROM projects WHERE id = ?", (project_id,)
        )
        traits_json = row["traits"] if row else "[]"

    try:
        import json as _json
        traits = _json.loads(traits_json) if traits_json else []
        if not isinstance(traits, list):
            traits = []
    except Exception:
        traits = []

    # 空 traits → 回退到 default（向后兼容所有老项目）
    if not traits:
        return orch.transition_rules

    traits_tuple = tuple(sorted(traits))
    cache_key = (project_id, traits_tuple, ticket_type)

    if cache_key in orch._project_rules_cache:
        return orch._project_rules_cache[cache_key]

    try:
        from sop.loader import compose_sop, sop_to_transition_rules
        sop_config = compose_sop(traits=traits, ticket_type=ticket_type)
        rules = sop_to_transition_rules(sop_config)
        orch._project_rules_cache[cache_key] = rules
        logger.info(
            "📋 项目 %s traits=%s type=%s → SOP %d 条规则",
            project_id[:12], traits, ticket_type or "(无)", len(rules),
        )
        return rules
    except Exception as e:
        logger.warning(
            "为项目 %s compose SOP 失败，回退到 default: %s",
            project_id[:12], e,
        )
        return orch.transition_rules


async def sop_stage_for(
    orch, project_id: str, action: str, ticket_type: Optional[str] = None,
) -> Optional[Dict]:
    """查该项目 SOP 里执行 `action` 的 stage 定义。

    同一个 action 会被多个 fragment 复用但状态语义不同 —— 例如
    run_ci_deploy 在 deploy_ue 产出 packaged（中间态）、在 deploy_web 产出
    deployed（终态）；run_tests 在 smoke_test 产出 smoke_test_passed、
    在基础 testing 阶段产出 testing_done。硬编码任一个都会弄坏另一类项目，
    所以按项目 traits + 工单 type 读 SOP 声明。

    找不到（无 traits / compose 失败 / action 不在 SOP 里）→ None，调用方兜底。

    同一个 action 出现多次时返回组合结果里的第一个。`run_ci_deploy` 因此不能
    打 `closeout: status`，否则先出现的那个阶段会把另一个的状态语义吃掉。
    """
    for stage in await orch._sop_stages_for(project_id, ticket_type):
        if stage.get("action") == action:
            return stage
    return None


async def sop_stages_for(
    orch, db, project_id: str, ticket_type: Optional[str] = None,
) -> List[Dict]:
    try:
        row = await db.fetch_one(
            "SELECT traits FROM projects WHERE id = ?", (project_id,)
        )
        traits = json.loads((row or {}).get("traits") or "[]")
        if not isinstance(traits, list) or not traits:
            return []
        from sop.loader import compose_sop
        stages = compose_sop(traits=traits, ticket_type=ticket_type).get("stages") or []
        return [stage for stage in stages if isinstance(stage, dict)]
    except Exception as e:
        logger.warning("读取 SOP stages 失败: %s", e)
        return []


async def sop_success_status_for(
    orch, project_id: str, action: str, *, default: str,
    ticket_type: Optional[str] = None,
) -> str:
    """该项目 SOP 里 `action` 阶段声明的 success_status，找不到返回 default。"""
    stage = await orch._sop_stage_for(project_id, action, ticket_type)
    return (stage or {}).get("success_status") or default


async def invoke_stage_hook(orch, name: str, ctx: Dict) -> Optional[Dict]:
    from plugins.registry import stage_hook
    fn = stage_hook(name)
    if fn is None:
        logger.warning("阶段钩子未注册: %s", name)
        return None
    try:
        outcome = await fn(orch, ctx)
    except Exception as e:
        logger.warning("阶段钩子 %s 失败（忽略）: %s", name, e)
        return None
    return outcome if isinstance(outcome, dict) else None


async def apply_fragment_closeout(
    orch, db,
    project_id: str,
    ticket_id: str,
    ticket: Dict,
    agent_name: str,
    action: str,
    result: Dict,
    result_json: str,
    current_status: str,
    requirement_id: Optional[str],
) -> bool:
    """阶段声明了 closeout: status 时，按片段写状态并跑钩子。

    返回 True 表示这次结果已经收尾，调用方必须 return，不能再落到
    develop 的产物落库。没有这个标记时返回 False，原路径继续。
    """
    stages = await orch._sop_stages_for(project_id, ticket.get("type"))
    stage = next((item for item in stages if item.get("action") == action), None)
    if not stage or stage.get("closeout") != "status":
        return False

    ctx = {
        "project_id": project_id,
        "ticket_id": ticket_id,
        "requirement_id": requirement_id,
        "agent_name": agent_name,
        "action": action,
        "result": result,
        "stage": stage,
        "stages": stages,
        "current_status": current_status,
    }
    ok = result.get("status") == "success"
    if ok:
        new_status = stage.get("success_status") or ""
        if not new_status:
            logger.error("阶段 %s 声明了 closeout 但没有 success_status", stage.get("id"))
            return True
        await db.update("tickets", {
            "status": new_status,
            "result": result_json,
            "updated_at": now_iso(),
        }, "id = ?", (ticket_id,))
        await orch._log(
            project_id, requirement_id, ticket_id, agent_name,
            "complete", current_status, new_status,
            closeout_message(stage, result, True),
            level=closeout_log_level(result, True),
            detail_data=closeout_detail(result),
        )
        for name in stage_hook_names(stage, "on_success"):
            await orch._invoke_stage_hook(name, ctx)
        return True

    notes: List[str] = []
    for name in stage_hook_names(stage, "on_failure"):
        outcome = await orch._invoke_stage_hook(name, ctx)
        if not outcome:
            continue
        rewind_id = outcome.get("rewind_to_stage")
        if rewind_id:
            trigger = rewind_trigger(stages, str(rewind_id))
            if not trigger:
                logger.warning(
                    "钩子 %s 要求回到阶段 %s，组合后的 SOP 里没有它的 trigger_on",
                    name, rewind_id,
                )
                if outcome.get("log_note"):
                    notes.append(str(outcome["log_note"]))
                continue
            await orch._log(
                project_id, requirement_id, ticket_id, agent_name,
                "action", current_status, trigger,
                str(outcome.get("log_message") or f"回到阶段 {rewind_id}"),
                detail_data=outcome.get("detail") if isinstance(outcome.get("detail"), dict) else {},
            )
            await db.update("tickets", {
                "status": trigger,
                "updated_at": now_iso(),
            }, "id = ?", (ticket_id,))
            return True
        if outcome.get("log_note"):
            notes.append(str(outcome["log_note"]))

    new_status = stage.get("reject_status") or ""
    if not new_status:
        logger.error("阶段 %s 声明了 closeout 但没有 reject_status", stage.get("id"))
        return True
    await db.update("tickets", {
        "status": new_status,
        "result": result_json,
        "updated_at": now_iso(),
    }, "id = ?", (ticket_id,))
    await orch._log(
        project_id, requirement_id, ticket_id, agent_name,
        "reject", current_status, new_status,
        closeout_message(stage, result, False, notes),
        "warning",
        detail_data=closeout_detail(result),
    )
    return True


def invalidate_project_rules(orch, project_id: str):
    """清除指定项目的 rules 缓存（当 traits 变动时调用）"""
    to_remove = [k for k in orch._project_rules_cache if k[0] == project_id]
    for k in to_remove:
        del orch._project_rules_cache[k]
    if to_remove:
        logger.info("清除项目 %s 的 SOP 规则缓存（%d 条）", project_id[:12], len(to_remove))
    # compose_sop 的缓存 key 不含 project_id（只有 traits/ticket_type/repo_path），
    # 没法按项目精确清 —— 但 traits 变动恰恰意味着旧 key 不会再被命中，
    # 全清一次代价只是下次组装 53ms，比留着脏数据安全。
    try:
        from sop.loader import invalidate_sop_cache
        invalidate_sop_cache()
    except Exception as e:
        logger.warning("清 SOP 组装缓存失败（忽略）: %s", e)


# 真正的终态，无论 SOP 如何配置都不应再触发新动作
TERMINAL_STATUSES = frozenset({
    TicketStatus.DEPLOYED.value,       # 已部署 = 流程终点
    TicketStatus.CANCELLED.value,      # 已取消
    "acceptance_complete",             # 未来扩展用
})


async def get_all_actionable_statuses(orch, db) -> List[str]:
    """轮询扫 ticket 用的 WHERE IN (...) 集合。

    = default rules keys ∪ 所有活跃项目 × 其在用的工单 type compose 出来的
    rules keys（union，不重复），再排除硬编码的终态。

    必须按 type 展开：type 相关的 fragment（如 ue_content_gen 的
    ue_content_pending）只在传对 ticket_type 时才会出现在规则里。
    漏掉就会导致这些状态的工单永远扫不到、卡死不动。
    """
    all_statuses = set(orch.transition_rules.keys())

    try:
        projects = await db.fetch_all(
            "SELECT id, traits FROM projects WHERE status = 'active'"
        )
        for p in projects:
            # 该项目现存工单用到的 type（None 代表"无 type 限定"的基础流程）
            type_rows = await db.fetch_all(
                "SELECT DISTINCT type FROM tickets WHERE project_id = ?", (p["id"],)
            )
            ticket_types = {r["type"] for r in type_rows if r.get("type")}
            ticket_types.add(None)
            for tt in ticket_types:
                rules = await orch._get_rules_for_project(
                    p["id"], p.get("traits"), ticket_type=tt,
                )
                all_statuses.update(rules.keys())
    except Exception as e:
        logger.warning("汇总 actionable_statuses 异常（只用 default）: %s", e)

    # 强制排除终态，防止 SOP 配置错误（如 deployed → deploy）导致无限循环
    all_statuses -= orch._TERMINAL_STATUSES
    return list(all_statuses)


def status_is_executing(status: str) -> bool:
    """执行中、进程一死就会变成僵尸的状态。

    不能只认软件 SOP 那几个枚举：视频链的 director_visual_in_progress
    不在 transition_rules 的 trigger 里，硬编码名单一漏，重启后永远扫不到。
    """
    s = (status or "").strip()
    if not s:
        return False
    if s.endswith("_in_progress") or s == TicketStatus.DEPLOYING.value:
        return True
    return False
