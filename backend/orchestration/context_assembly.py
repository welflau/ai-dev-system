"""为 Agent 组装执行上下文：工单、需求、产物、项目配置及可用知识。

按创建时间读取历史产物，同类型取最后一份；保留原有的 JSON 解析与缺省值。
从项目读取 traits 与 UE 配置，从仓库、记忆和知识库补充文件、同需求工单和经验。
UCP 探测仍检查 project_traits；本次只迁移实现，不改变该键与 traits 的既有差异。

约定（`orchestration` 包里按职责拆出的模块都一样）：

- 函数体从 `TicketOrchestrator` 的同名方法原样搬来，函数名去掉了前导下划线。改动只有
  `self` 写成 `orch`，以及下面单独列出的几处。
- `TicketOrchestrator` 上保留同名方法，只做转发。这里的函数互相调用、调用别的模块里的
  逻辑都走 `orch.xxx`，测试给实例打的桩才会生效。
- `db` 由转发方法在调用时传入，这里不导入它。测试用
  `monkeypatch.setattr(orchestrator, "db", test_db)` 换库，函数必须拿到同一个对象。
- 状态都放在 `orch` 上，这个模块自己不存状态。
- 函数内的延迟导入保持原样，测试的打桩打在这些源模块上。
"""
import json
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger("orchestrator")


async def build_context(orch, db, ticket: Dict, agent_name: str = "") -> Dict:
    """构建 Agent 执行上下文"""
    requirement = await db.fetch_one(
        "SELECT * FROM requirements WHERE id = ?", (ticket["requirement_id"],)
    )

    # 获取之前的执行结果
    prev_results = await db.fetch_all(
        "SELECT * FROM artifacts WHERE ticket_id = ? ORDER BY created_at",
        (ticket["id"],),
    )

    project_id = ticket.get("project_id", "")
    req_short = (ticket["requirement_id"] or "standalone")[-6:]

    # 获取项目 repo_path，注入 context 供 Agent 直接使用（无需再查 DB）
    _repo_path = ""
    try:
        from git_manager import git_manager as _gm
        _rp = _gm._repo_path(project_id)
        if _rp:
            _repo_path = str(_rp)
    except Exception:
        pass

    context = {
        "ticket_id": ticket["id"],
        "ticket_title": ticket["title"],
        "ticket_description": ticket.get("description", ""),
        "ticket_type": ticket.get("type", "feature"),
        "module": ticket.get("module", "other"),
        "project_id": project_id,
        "requirement_id": ticket.get("requirement_id") or "",
        "agent_type": agent_name or "",
        "repo_path": _repo_path,          # ← 注入 repo_path
        "requirement_description": requirement["description"] if requirement else "",
        "requirement_title": requirement["title"] if requirement else "",
        "docs_prefix": f"docs/Reqs/{req_short}/{ticket['id'][-6:]}/",
        "src_prefix": f"src/{ticket.get('module', 'other')}/",
        "tests_prefix": f"tests/{req_short}/",
        "_ticket_progress_cb": orch._make_ticket_progress_callback(project_id, ticket["id"]),
    }

    # 返工失败信号（rejection_reason / test_issues）注入，供反思 Action 读取
    await orch._inject_rejection_context(context, ticket)

    # 若为 BUG ticket，附加 BUG 原始信息
    if ticket.get("type") == "bug":
        bug = await db.fetch_one(
            "SELECT * FROM bugs WHERE ticket_id = ?", (ticket["id"],)
        )
        if bug:
            context["bug_id"] = bug["id"]
            context["bug_priority"] = bug.get("priority", "medium")
            context["bug_description"] = bug.get("description", "")
            context["bug_fix_notes"] = bug.get("fix_notes") or ""

    # 添加之前阶段的产物
    for art in prev_results:
        if art["type"] == "architecture":
            try:
                context["architecture"] = json.loads(art["content"]) if art["content"] else {}
            except json.JSONDecodeError:
                context["architecture"] = {}
        elif art["type"] == "code":
            try:
                context["dev_result"] = json.loads(art["content"]) if art["content"] else {}
            except json.JSONDecodeError:
                context["dev_result"] = {}
        elif art["type"] == "test":
            try:
                context["test_result"] = json.loads(art["content"]) if art["content"] else {}
            except json.JSONDecodeError:
                context["test_result"] = {}

    # v0.18 Phase B：注入项目级 UE 配置（引擎/uproject/target 等），供
    # UECompileCheckAction / InstantiateUETemplateAction 等 UE 相关 action 透传使用。
    # 这样 DevAgent.run_engine_compile 不再需要每次从前端卡片 context 里取。
    #
    # v0.19.x A 方案：同时注入 traits，让 SelfTestAction 按 trait 分 UE / web 分支
    try:
        traits_row = await db.fetch_one(
            "SELECT traits FROM projects WHERE id = ?", (project_id,),
        )
        raw = (traits_row or {}).get("traits") or "[]"
        try:
            traits_list = json.loads(raw) if isinstance(raw, str) else list(raw)
        except Exception:
            traits_list = []
        if isinstance(traits_list, list):
            context["traits"] = [str(t) for t in traits_list if t]
    except Exception as e:
        logger.debug("读 traits 失败（忽略）: %s", e)

    try:
        proj_row = await db.fetch_one(
            """SELECT ue_engine_path, ue_engine_version, ue_engine_type,
                          uproject_path, ue_target_name, ue_target_platform, ue_target_config
                   FROM projects WHERE id = ?""",
            (project_id,),
        )
        if proj_row:
            for k, v in proj_row.items():
                if v is not None and v != "":
                    context[k] = v
            # uproject_path 若是相对路径，拼成绝对
            up = context.get("uproject_path")
            if up and not Path(up).is_absolute():
                from git_manager import git_manager
                rp = git_manager._repo_path(project_id)
                if rp:
                    context["uproject_path"] = str(Path(rp) / up)
    except Exception as e:
        logger.warning("读取项目 UE 配置失败（非致命）: %s", e)

    # === 增量开发上下文：读取仓库中已有文件 ===
    try:
        from memory import AgentMemory
        mem = AgentMemory(project_id)
        code_ctx = await mem.get_code_context()
        context["existing_files"] = code_ctx.get("file_list", [])
        context["existing_code"] = code_ctx.get("code", {})
        logger.info("📂 已有代码上下文: %d 文件, %d 个代码片段",
                    len(context["existing_files"]), len(context["existing_code"]))
    except Exception as e:
        logger.warning("读取已有代码失败: %s", e)
        context["existing_files"] = []
        context["existing_code"] = {}

    # 获取同需求下已完成工单的摘要
    try:
        context["sibling_tickets"] = await mem.get_sibling_tickets(
            ticket["requirement_id"], exclude_ticket_id=ticket["id"]
        )
    except Exception:
        context["sibling_tickets"] = []

    # === 知识库上下文（按 Agent 类型差异化加载）===
    try:
        from knowledge_loader import KnowledgeLoader
        loader = KnowledgeLoader(agent_name, project_id, context.get("traits", []))
        knowledge = await loader.load()
        context["project_knowledge"]  = knowledge.get("project_knowledge", "")
        context["domain_knowledge"]   = knowledge.get("domain_knowledge", "")
        context["agent_spec"]         = knowledge.get("agent_spec", "")
        # 向后兼容：合并到旧字段，防止使用旧字段的 Agent 读不到
        context["knowledge_docs"] = "\n\n".join(
            filter(None, [context["project_knowledge"], context["domain_knowledge"]])
        ) or orch._load_knowledge_docs(project_id)
    except Exception as e:
        logger.warning("KnowledgeLoader 失败，降级到旧逻辑: %s", e)
        context["knowledge_docs"] = orch._load_knowledge_docs(project_id)
        context["project_knowledge"] = context["domain_knowledge"] = context["agent_spec"] = ""

    # === Insight 主动注入：编码前自动检索相关历史经验 ===
    try:
        context["prior_insights"] = await orch._fetch_prior_insights(
            ticket["title"], project_id
        )
    except Exception as e:
        logger.warning("Insight 注入失败（非致命）: %s", e)
        context["prior_insights"] = ""

    # === v0.20 UCP：探测 Editor 是否可用，注入到 context ===
    traits = context.get("project_traits") or []
    is_ue_project = any(t in traits for t in ("engine:ue5", "engine:ue4"))
    if is_ue_project:
        try:
            import runtime_facade
            context["ucp_available"] = await runtime_facade.actions_ue_editor_control().probe_ucp(timeout=1.0)
        except Exception:
            context["ucp_available"] = False
    else:
        context["ucp_available"] = False

    return context
