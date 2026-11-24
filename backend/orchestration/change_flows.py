"""用户评论触发的流程：Agent 回复评论，变更影响分析，三种返工流程。

用户在工单下发评论后，`reply_to_comment` 先把评论交给 `handle_change_impact` 判断是否带需求变更。
没有变更就让当前负责的 Agent（或 ChatAssistant）回一条评论；有变更按级别走三条路：

- `tweak_flow`：细节调整，specs 不变，重置开发阶段重新执行；
- `partial_flow`：局部需求变化，先更新 OpenSpec specs，再重跑受影响的阶段；
- `breaking_flow`：需求根本变更，关闭当前工单，创建衍生的新工单。

阶段重置走 `orch.reset_phases`，实现在 `orchestration/rewind.py`。

重构方案第四节给这个文件起的名字是 `change_impact.py`。`backend/change_impact.py` 已经是做
变更分级的模块，这里的函数还要导入它，所以换了一个名字。

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
from typing import Optional

from utils import now_iso

logger = logging.getLogger("orchestrator")


async def reply_to_comment(
    orch, db,
    ticket_id: str,
    project_id: str,
    comment_content: str,
    comment_id: str = None,
):
    """用户发评论后，由当前负责 Agent（或 ChatAssistant）立刻异步回复。

    三层融合扩展：先过变更分析中间件，检测评论是否含需求变更；
    有变更 → 路由到对应 Flow（tweak/partial/breaking）；
    无变更 → 原有 LLM 回复路径。
    """
    try:
        ticket = await db.fetch_one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if not ticket:
            return

        # ── 变更分析中间件（三层融合：变更触发机制）──────────────────
        handled = await orch._handle_change_impact(
            ticket_id, project_id, comment_content, comment_id, ticket,
        )
        if handled:
            return  # 已由变更 Flow 处理，不走普通回复

        # 读取完整评论历史（正序）
        history = await db.fetch_all(
            "SELECT author, author_type, content FROM ticket_comments "
            "WHERE ticket_id = ? ORDER BY created_at ASC",
            (ticket_id,),
        )

        # 选择回复的 Agent：优先用当前负责的 Agent，否则用 ChatAssistant
        agent_name = ticket.get("assigned_agent") or "ChatAssistant"
        # 对于终态工单（无 assigned_agent），也能回复
        if agent_name not in orch.agents:
            agent_name = "ChatAssistant"

        # 构建历史对话文本（不含最新一条，因为那就是 comment_content）
        history_lines = []
        for c in history:
            if c["content"] == comment_content and c["author_type"] == "human":
                continue  # 跳过刚写入的这条，避免重复
            role = "用户" if c["author_type"] == "human" else c["author"]
            history_lines.append(f"[{role}] {c['content']}")
        history_text = "\n".join(history_lines) if history_lines else "（无）"

        # 工单基本信息
        title = ticket.get("title", "")
        status = ticket.get("status", "")
        description = (ticket.get("description") or "")[:300]
        result_brief = ""
        try:
            result_obj = json.loads(ticket.get("result") or "{}")
            # 取各阶段 summary 字段
            for key in ("notes", "prd_content", "architecture", "summary"):
                val = result_obj.get(key)
                if val:
                    result_brief = str(val)[:200]
                    break
        except Exception:
            pass

        # 若用户是在某条具体日志（或挂在该日志下的评论串）上追问，向上追溯绑定的 log 详情注入 prompt
        bound_log_brief = ""
        try:
            cur_cid = comment_id
            bound_log_id = None
            for _ in range(6):
                if not cur_cid:
                    break
                crow = await db.fetch_one(
                    "SELECT reply_to_log_id, reply_to_comment_id FROM ticket_comments WHERE id = ?",
                    (cur_cid,),
                )
                if not crow:
                    break
                if crow.get("reply_to_log_id"):
                    bound_log_id = crow["reply_to_log_id"]
                    break
                cur_cid = crow.get("reply_to_comment_id")
            log_row = None
            if bound_log_id:
                log_row = await db.fetch_one(
                    "SELECT action, detail FROM ticket_logs WHERE id = ?", (bound_log_id,)
                )
            if not log_row:
                log_row = await db.fetch_one(
                    "SELECT action, detail FROM ticket_logs WHERE ticket_id = ? AND action = 'reject' ORDER BY created_at DESC LIMIT 1",
                    (ticket_id,),
                )
            if log_row and log_row.get("detail"):
                ld = json.loads(log_row["detail"])
                l_parts = [f"[{log_row.get('action')}] {ld.get('message') or ''}"]
                if ld.get("errors"):
                    l_parts.append("报错明细: " + json.dumps(ld["errors"][:5], ensure_ascii=False))
                if ld.get("raw_tail"):
                    l_parts.append("控制台输出尾部: " + str(ld["raw_tail"])[-400:])
                bound_log_brief = "\n".join(l_parts)
        except Exception:
            pass

        prompt = (
            f"你是 {agent_name}，正在处理工单「{title}」。\n"
            f"当前状态：{status}\n"
            f"工单描述：{description}\n"
            + (f"最新产出摘要：{result_brief}\n" if result_brief else "")
            + (f"关联日志/报错详情：\n{bound_log_brief}\n" if bound_log_brief else "")
            + f"\n== 历史对话 ==\n{history_text}\n"
            f"\n== 用户最新评论 ==\n{comment_content}\n"
            "\n请针对用户评论简洁回复（2-4句）。"
            "如涉及修改要求，说明你将如何处理；"
            "如是询问进展，直接说明当前状态和产出；"
            "不要用 markdown 标题，直接用自然语言。"
        )

        from llm_client import llm_client, set_llm_context, clear_llm_context
        # 必须带上 ticket/project，chat() 才会走流式并推 ticket_llm_token
        set_llm_context(
            ticket_id=ticket_id,
            requirement_id=ticket.get("requirement_id"),
            project_id=project_id,
            agent_type=agent_name,
            action="reply_to_comment",
        )
        try:
            reply_text = await llm_client.generate(
                prompt,
                max_tokens=400,
                temperature=0.5,
            )
        finally:
            clear_llm_context()

        if reply_text and reply_text.strip():
            await orch._write_phase_comment(
                project_id, ticket_id, agent_name, reply_text.strip(),
                reply_to_comment_id=comment_id,
            )
            logger.info(
                "💬 %s 回复工单 %s 的评论（%d 字）",
                agent_name, ticket_id[:12], len(reply_text.strip()),
            )

    except Exception as e:
        logger.warning("reply_to_comment 失败（忽略）: %s", e)


async def handle_change_impact(
    orch, db,
    ticket_id: str,
    project_id: str,
    comment: str,
    comment_id: Optional[str],
    ticket: dict,
) -> bool:
    """
    变更分析中间件：检测评论是否含需求变更，路由到对应 Flow。
    返回 True 表示已处理（不再走普通回复），False 表示无变更正常回复。
    """
    try:
        from change_impact import change_analyzer, is_active_phase

        ticket_status = ticket.get("status", "")
        if not is_active_phase(ticket_status):
            return False

        # 读取 OpenSpec specs（有则辅助分析）
        specs_content = None
        try:
            from capability_check import get_ticket_specs_path
            repo_row = await db.fetch_one(
                "SELECT git_repo_path FROM projects WHERE id = ?", (project_id,)
            )
            repo_path = (repo_row or {}).get("git_repo_path", "")
            if repo_path:
                sp = get_ticket_specs_path(repo_path, ticket_id)
                if sp.exists():
                    specs_content = sp.read_text(encoding="utf-8", errors="replace")[:2000]
        except Exception:
            pass

        impact = await change_analyzer.analyze(
            comment=comment,
            ticket_title=ticket.get("title", ""),
            ticket_status=ticket_status,
            specs_content=specs_content,
        )

        if not impact.is_change:
            return False  # 无变更，走正常回复

        # 记录变更日志
        await orch._add_layer_log(
            ticket_id, project_id,
            action="change_detected", layer="harness",
            detail={
                "type": impact.type,
                "reason": impact.reason,
                "comment_id": comment_id or "",
                "comment_preview": comment[:100],
            },
        )

        # 路由到对应 Flow
        if impact.type == "tweak":
            await orch._tweak_flow(ticket_id, project_id, comment, impact, comment_id)
            return True
        elif impact.type == "partial":
            await orch._partial_flow(ticket_id, project_id, comment, impact, comment_id, ticket)
            return True
        elif impact.type == "breaking":
            await orch._breaking_flow(ticket_id, project_id, comment, impact, comment_id, ticket)
            return True

    except Exception as e:
        logger.debug("_handle_change_impact 失败（忽略）: %s", e)

    return False


async def tweak_flow(
    orch, db,
    ticket_id: str,
    project_id: str,
    comment: str,
    impact,
    comment_id: Optional[str] = None,
) -> None:
    """
    Tweak Flow：细节调整，specs 不变，重置开发阶段重新执行。
    适用于 tweak 和 P2 前的 partial（specs 更新逻辑 P2 再补）。
    """
    # 1. 记录变更日志（change_count + 1）
    await db.execute(
        "UPDATE tickets SET change_count = COALESCE(change_count, 0) + 1, updated_at = ? "
        "WHERE id = ?",
        (now_iso(), ticket_id),
    )

    # 2. 判断从哪个阶段重置
    #    tweak → 从 development 重置
    #    partial（简化）→ 从 development 重置（P2 再支持从 architecture 重置）
    from_phase = "development"
    reason = f"{impact.type}: {impact.reason} （来自评论 {comment[:60]}）"

    before = await db.fetch_one("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
    before_status = (before or {}).get("status") or ""

    reset_ok = await orch.reset_phases(ticket_id, project_id, from_phase, reason)

    if reset_ok:
        # 3. 回复用户确认。区分「真回退了」和「尚未跑到该阶段，只记指令」，
        #    否则用户看到「已重置」但工单没动会以为系统骗人。
        after = await db.fetch_one("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
        after_status = (after or {}).get("status") or ""
        queued = ticket_id in orch._pending_restart
        if queued:
            msg = (
                f"✅ 已收到需求调整：{impact.reason}\n"
                f"当前阶段正在执行，收尾后将回到**开发阶段**按最新要求重做。\n"
                f"（变更类型：{impact.type}）"
            )
        elif after_status != before_status:
            msg = (
                f"✅ 已收到需求调整：{impact.reason}\n"
                f"已重置**开发阶段**（状态回退到 `{after_status}`），将根据最新要求重新实现。\n"
                f"（变更类型：{impact.type}）"
            )
        else:
            msg = (
                f"📝 已记录需求调整：{impact.reason}\n"
                f"工单尚未进入开发阶段，该要求已作为最高优先级指令，"
                f"开发时会直接按新要求执行（不重跑已完成阶段）。\n"
                f"（变更类型：{impact.type}）"
            )
    else:
        msg = (
            f"⚠️ 检测到需求调整（{impact.reason}），但阶段重置次数已超限，"
            f"请人工确认是否继续。"
        )

    await orch._write_phase_comment(
        project_id, ticket_id, "System", msg,
        reply_to_comment_id=comment_id,
    )
    logger.info("tweak_flow: ticket=%s reason=%s reset_ok=%s", ticket_id[:12], impact.reason[:40], reset_ok)


async def partial_flow(
    orch, db,
    ticket_id: str,
    project_id: str,
    comment: str,
    impact,
    comment_id: Optional[str],
    ticket: dict,
) -> None:
    """
    Partial Flow：局部需求变化，更新 OpenSpec specs 后重新执行受影响阶段。

    步骤：
    1. SpecVersionManager 备份当前 specs.md
    2. LLM 生成 spec delta（只改变化部分）
    3. 写入新 specs.md + DB 版本记录
    4. 判断是否影响架构，决定从哪个阶段重置
    5. 回复用户确认
    """
    try:
        from capability_check import ticket_has_specs, _get_repo_path
        from spec_version_manager import SpecVersionManager, generate_spec_delta

        repo_path = ticket.get("repo_path") or await _get_repo_path(project_id)
        if not repo_path:
            # 无 repo_path → 降级到 tweak
            await orch._tweak_flow(ticket_id, project_id, comment, impact, comment_id)
            return

        # 1. 读取当前 specs
        spec_mgr = SpecVersionManager(ticket_id, repo_path)
        current_specs = spec_mgr.read_current_specs()

        if not current_specs:
            # 无 specs → 降级到 tweak（没有规范文件无法做 partial）
            await orch._tweak_flow(ticket_id, project_id, comment, impact, comment_id)
            return

        # 2. 备份当前 specs
        ver = spec_mgr.snapshot()

        # 3. LLM 生成新 specs（追加/修改场景）
        new_specs = await generate_spec_delta(
            current_specs=current_specs,
            change_request=comment,
            affected_specs=impact.affected_specs,
        )

        # 4. 写入 specs.md + DB
        spec_mgr.apply_delta(new_specs)
        await spec_mgr.save_version_to_db(
            content=new_specs,
            change_summary=impact.reason,
            comment_id=comment_id,
        )

        # 5. 更新 change_count
        await db.execute(
            "UPDATE tickets SET change_count=COALESCE(change_count,0)+1, "
            "openspec_stage='proposed', updated_at=? WHERE id=?",
            (now_iso(), ticket_id),
        )

        # 6. 判断是否影响架构（含"架构"关键词时从 architecture 重置）
        arch_keywords = ("架构", "数据库", "接口", "API", "数据结构", "architecture", "database", "schema")
        needs_arch = any(kw in comment.lower() for kw in arch_keywords)
        from_phase = "architecture" if needs_arch else "development"

        reason = f"partial({ver}→{spec_mgr.current_version}): {impact.reason}"
        before = await db.fetch_one(
            "SELECT status FROM tickets WHERE id = ?", (ticket_id,)
        )
        before_status = (before or {}).get("status") or ""
        reset_ok = await orch.reset_phases(ticket_id, project_id, from_phase, reason)

        # 7. 写时间轴日志
        await orch._add_layer_log(
            ticket_id, project_id, action="spec_updated", layer="spec",
            detail={
                "old_version": ver,
                "new_version": spec_mgr.current_version,
                "summary": impact.reason,
                "from_phase": from_phase,
            },
        )

        # 8. 回复用户。同 _tweak_flow：区分「真回退」「排队中」「尚未跑到该阶段」，
        #    不能一律说「已重置」——工单没动的话用户会以为系统在骗人。
        phase_desc = "架构 → 开发 → 测试 → 验证" if needs_arch else "开发 → 测试 → 验证"
        spec_line = (
            f"规范已更新至 **v{spec_mgr.current_version}**（原 v{ver}）"
        )
        if not reset_ok:
            msg = (
                f"📐 检测到局部变更（{impact.reason}），{spec_line}，"
                f"但阶段重置次数超限，请人工确认。"
            )
        else:
            after = await db.fetch_one(
                "SELECT status FROM tickets WHERE id = ?", (ticket_id,)
            )
            after_status = (after or {}).get("status") or ""
            if ticket_id in orch._pending_restart:
                msg = (
                    f"📐 已收到局部需求变更：{impact.reason}\n"
                    f"{spec_line}。当前阶段正在执行，收尾后将重跑：{phase_desc}。"
                )
            elif after_status != before_status:
                msg = (
                    f"📐 已收到局部需求变更：{impact.reason}\n"
                    f"{spec_line}，状态回退到 `{after_status}`，"
                    f"重置阶段：{phase_desc}。"
                )
            else:
                msg = (
                    f"📐 已收到局部需求变更：{impact.reason}\n"
                    f"{spec_line}。工单尚未跑到该阶段，新规范会在执行时直接生效"
                    f"（不重跑已完成阶段）。"
                )

        await orch._write_phase_comment(
            project_id, ticket_id, "System", msg,
            reply_to_comment_id=comment_id,
        )
        logger.info("partial_flow: ticket=%s ver=%s->%s from=%s", ticket_id[:12], ver, spec_mgr.current_version, from_phase)

    except Exception as e:
        logger.warning("_partial_flow 失败，降级到 tweak: %s", e)
        await orch._tweak_flow(ticket_id, project_id, comment, impact, comment_id)


async def breaking_flow(
    orch, db,
    ticket_id: str,
    project_id: str,
    comment: str,
    impact,
    comment_id: Optional[str],
    ticket: dict,
) -> None:
    """
    Breaking Flow：需求根本变更，关闭当前工单，创建衍生新工单。

    步骤：
    1. 当前工单 → cancelled
    2. 从评论提取新需求标题和描述
    3. 创建新工单（source_ticket_id 关联原工单）
    4. 两边都留记录
    """
    try:
        from utils import generate_id

        # 1. 关闭当前工单
        await db.execute(
            "UPDATE tickets SET status='cancelled', updated_at=? WHERE id=?",
            (now_iso(), ticket_id),
        )

        # 2. 提取新需求标题（LLM 从评论中抽取，失败用评论前30字）
        new_title = await orch._extract_title_from_comment(comment, ticket.get("title", ""))
        new_desc = comment[:500]

        # 3. 创建新工单
        new_ticket_id = generate_id("TK")
        requirement_id = ticket.get("requirement_id", "")
        project_id_t = ticket.get("project_id", project_id)

        await db.insert("tickets", {
            "id": new_ticket_id,
            "requirement_id": requirement_id,
            "project_id": project_id_t,
            "title": new_title,
            "description": new_desc,
            "type": ticket.get("type", "feature"),
            "module": ticket.get("module", "other"),
            "priority": ticket.get("priority", 3),
            "sort_order": 0,
            "status": "pending",
            "assigned_agent": ticket.get("assigned_agent", ""),
            "source_ticket_id": ticket_id,
            "estimated_hours": ticket.get("estimated_hours"),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })

        # 4. 更新 change_count
        await db.execute(
            "UPDATE tickets SET change_count=COALESCE(change_count,0)+1, updated_at=? WHERE id=?",
            (now_iso(), ticket_id),
        )

        # 5. 原工单留记录
        await orch._write_phase_comment(
            project_id, ticket_id, "System",
            f"⚠️ 需求根本性变更，当前工单已关闭。\n"
            f"原因：{impact.reason}\n"
            f"新工单：#{new_ticket_id[-6:]}「{new_title}」已创建，将走完整流程。",
            reply_to_comment_id=comment_id,
        )

        # 6. 新工单留来源记录
        await orch._write_phase_comment(
            project_id, new_ticket_id, "System",
            f"📋 此工单由 #{ticket_id[-6:]}「{ticket.get('title', '')}」变更派生。\n"
            f"变更原因：{impact.reason}",
        )

        await orch._add_layer_log(
            ticket_id, project_id, action="breaking_change", layer="harness",
            detail={"new_ticket_id": new_ticket_id, "reason": impact.reason},
        )

        logger.info("breaking_flow: old=%s new=%s reason=%s", ticket_id[:12], new_ticket_id[:12], impact.reason[:40])

    except Exception as e:
        logger.warning("_breaking_flow 失败: %s", e)
        # 降级：通知人工
        await orch.post_milestone_comment(
            ticket_id, project_id,
            f"⚠️ 检测到根本性变更（{impact.reason}），自动处理失败，请人工介入。",
            level="error",
        )


async def extract_title_from_comment(orch, comment: str, original_title: str) -> str:
    """从评论中提取新需求标题，失败返回截断评论。"""
    try:
        from llm_client import llm_client
        prompt = (
            f"从以下需求变更评论中提取一个简洁的需求标题（10-20字，中文）：\n{comment[:300]}\n"
            f"原工单标题参考：{original_title}\n只返回标题，不要解释："
        )
        title = await llm_client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.2, max_tokens=60,
        )
        return title.strip()[:50] or comment[:30]
    except Exception:
        return comment[:30]
