"""需求收尾：判断需求是否完成，生成汇总报告，触发依赖工单。

`check_requirement_completion` 在工单到达完成状态后调用，需求下的工单都已测试通过或部署完成时
把需求标成完成，写 Agent Memory，再调 `generate_requirement_report` 生成汇总报告的 Markdown，
存进 Git 仓库和 artifacts 表。`trigger_dependents` 在一张工单完成后放行依赖它的后续工单。

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
import asyncio
import json
import logging

from events import event_manager
from git_manager import git_manager
from models import RequirementStatus, TicketStatus
from utils import generate_id, now_iso

logger = logging.getLogger("orchestrator")


async def check_requirement_completion(orch, db, project_id: str, requirement_id: str):
    """检查需求下所有工单是否都已测试通过或部署完成"""
    tickets = await db.fetch_all(
        "SELECT status FROM tickets WHERE requirement_id = ? AND status != 'cancelled'",
        (requirement_id,),
    )

    DONE_STATUSES = {TicketStatus.TESTING_DONE.value, TicketStatus.DEPLOYED.value}
    all_done = all(t["status"] in DONE_STATUSES for t in tickets)

    if all_done and tickets:
        await db.update("requirements", {
            "status": RequirementStatus.COMPLETED.value,
            "completed_at": now_iso(),
            "updated_at": now_iso(),
        }, "id = ?", (requirement_id,))

        await orch._log(
            project_id, requirement_id, None, "Orchestrator",
            "complete", "in_progress", "completed",
            f"需求已完成！所有 {len(tickets)} 个工单均已测试通过，可进行统一部署"
        )

        await event_manager.publish_to_project(
            project_id,
            "requirement_completed",
            {"requirement_id": requirement_id},
        )
        # 同時推 log_added，讓操作日誌面板也能看到
        try:
            from utils import now_iso as _now_iso
            import json as _json
            req_title = ""
            try:
                _req = await db.fetch_one("SELECT title FROM requirements WHERE id=?", (requirement_id,))
                req_title = f"「{_req['title'][:30]}」" if _req else ""
            except Exception:
                pass
            await event_manager.publish_to_project(project_id, "log_added", {
                "id":         f"req-done-{requirement_id[-8:]}",
                "agent_type": "Orchestrator",
                "action":     "requirement_completed",
                "detail":     _json.dumps({"message": f"🎉 需求{req_title}已全部完成！所有工单测试通过"}, ensure_ascii=False),
                "level":      "info",
                "created_at": _now_iso(),
            })
        except Exception:
            pass

        # 生成需求完成报告
        try:
            await orch._generate_requirement_report(project_id, requirement_id)
        except Exception as rpt_err:
            logger.warning("生成需求报告失败(非致命): %s", rpt_err)

        # 写入 Agent Memory（需求完成记录）
        try:
            await orch._write_memory(
                project_id=project_id,
                mem_type="project_status",
                title=f"需求完成: {requirement.get('title','') if (requirement := await db.fetch_one('SELECT title FROM requirements WHERE id=?',(requirement_id,))) else requirement_id}",
                content=f'{{"requirement_id":"{requirement_id}","ticket_count":{len(tickets)},"status":"completed"}}',
                agent_type="Orchestrator",
                requirement_id=requirement_id,
            )
        except Exception:
            pass

        # === 规范合并：先拉 develop 最新到 feat → 确认无冲突 → 再合入 develop ===
        try:
            req_data = await db.fetch_one("SELECT branch_name FROM requirements WHERE id = ?", (requirement_id,))
            branch_name = req_data.get("branch_name") if req_data else None
            if branch_name:
                # 确保 develop 分支存在
                primary_branch = await git_manager.get_primary_branch(project_id)
                await git_manager.ensure_branch(project_id, "develop", from_branch=primary_branch)

                # Step 1: 先把 develop 最新代码合入 feat（解决冲突在 feat 上）
                logger.info("🔀 Step 1: merge develop → %s（拉最新）", branch_name)
                pre_merge = await git_manager.merge_branch(
                    project_id, "develop", branch_name,
                    message=f"merge: develop → {branch_name} (合入最新代码)"
                )
                if not pre_merge["success"]:
                    logger.error("❌ develop → %s 合并冲突: %s", branch_name, pre_merge.get("error"))
                    await orch._log(
                        project_id, requirement_id, None, "Orchestrator",
                        "error", "completed", "completed",
                        f"合并冲突: develop → {branch_name} 失败，需手动解决: {pre_merge.get('error', '')}"
                    )
                    # 不继续合入 develop，等手动解决
                    return

                # Step 2: feat 合入 develop
                logger.info("🔀 Step 2: merge %s → develop（合入功能）", branch_name)
                merge_result = await git_manager.merge_branch(
                    project_id, branch_name, "develop",
                    message=f"merge: {branch_name} → develop (需求完成)"
                )
                if merge_result["success"]:
                    await orch._log(
                        project_id, requirement_id, None, "Orchestrator",
                        "complete", "completed", "completed",
                        f"分支 {branch_name} 已合并到 develop (commit: {merge_result.get('commit', '?')})"
                    )
                    await event_manager.publish_to_project(
                        project_id,
                        "branch_merged",
                        {"source": branch_name, "target": "develop",
                         "commit": merge_result.get("commit"),
                         "requirement_id": requirement_id},
                    )
                    logger.info("🔀 分支合并完成: %s → develop", branch_name)

                    # === develop → 主分支：检查该项目所有需求是否都已完成，若是则合入主分支 ===
                    try:
                        all_reqs = await db.fetch_all(
                            "SELECT status FROM requirements WHERE project_id = ? AND status != 'cancelled'",
                            (project_id,),
                        )
                        all_reqs_done = all_reqs and all(
                            r["status"] == RequirementStatus.COMPLETED.value for r in all_reqs
                        )
                        if all_reqs_done:
                            primary_branch = await git_manager.get_primary_branch(project_id)
                            main_merge = await git_manager.merge_branch(
                                project_id, "develop", primary_branch,
                                message=f"merge: develop → {primary_branch} (所有需求已完成，发布版本)"
                            )
                            if main_merge["success"]:
                                await orch._log(
                                    project_id, requirement_id, None, "Orchestrator",
                                    "complete", "completed", "completed",
                                    f"develop 已合并到 {primary_branch} (commit: {main_merge.get('commit', '?')})"
                                )
                                await event_manager.publish_to_project(
                                    project_id,
                                    "branch_merged",
                                    {"source": "develop", "target": primary_branch,
                                     "commit": main_merge.get("commit"),
                                     "requirement_id": requirement_id},
                                )
                                logger.info("🚀 develop → %s 合并完成，项目版本已更新", primary_branch)
                            else:
                                logger.warning("develop → %s 合并失败: %s", primary_branch, main_merge.get("error"))
                    except Exception as main_merge_err:
                        logger.warning("develop → 主分支合并失败(非致命): %s", main_merge_err)

                else:
                    await orch._log(
                        project_id, requirement_id, None, "Orchestrator",
                        "error", "completed", "completed",
                        f"分支合并失败: {merge_result.get('error', '未知错误')}", "warn"
                    )
                    logger.warning("分支合并失败: %s", merge_result.get("error"))
        except Exception as merge_err:
            logger.warning("分支合并失败(非致命): %s", merge_err)


async def generate_requirement_report(orch, db, project_id: str, requirement_id: str):
    """需求完成后生成汇总报告 Markdown，保存到 Git 仓库 + artifacts 表"""
    req = await db.fetch_one("SELECT * FROM requirements WHERE id = ?", (requirement_id,))
    if not req:
        return

    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    req_short = requirement_id[-6:]

    # 获取所有工单
    tickets = await db.fetch_all(
        "SELECT * FROM tickets WHERE requirement_id = ? ORDER BY sort_order, created_at",
        (requirement_id,),
    )

    # 获取所有产物
    artifacts = await db.fetch_all(
        "SELECT * FROM artifacts WHERE requirement_id = ? ORDER BY created_at",
        (requirement_id,),
    )

    # 获取 LLM 会话统计
    llm_stats = await db.fetch_one(
        "SELECT COUNT(*) as count, SUM(input_tokens) as input_tokens, SUM(output_tokens) as output_tokens, SUM(duration_ms) as total_ms FROM llm_conversations WHERE requirement_id = ?",
        (requirement_id,),
    )

    # 获取日志
    logs = await db.fetch_all(
        "SELECT * FROM ticket_logs WHERE requirement_id = ? ORDER BY created_at",
        (requirement_id,),
    )

    # 获取 Git 提交记录
    git_commits = []
    try:
        git_commits = await git_manager.get_log(project_id, limit=50)
    except Exception:
        pass

    # === 构建报告 Markdown ===
    from datetime import datetime

    duration_str = ""
    if req.get("created_at") and req.get("completed_at"):
        try:
            t1 = datetime.fromisoformat(req["created_at"])
            t2 = datetime.fromisoformat(req["completed_at"])
            delta = t2 - t1
            hours = delta.total_seconds() / 3600
            duration_str = f"{hours:.1f} 小时"
        except Exception:
            pass

    md = f"# 📋 需求完成报告\n\n"
    md += f"## 基本信息\n\n"
    md += f"| 项目 | 内容 |\n|------|------|\n"
    md += f"| **需求ID** | {requirement_id} |\n"
    md += f"| **标题** | {req['title']} |\n"
    md += f"| **项目** | {project['name'] if project else '-'} |\n"
    md += f"| **优先级** | {req.get('priority', '-')} |\n"
    md += f"| **开发分支** | `{req.get('branch_name', '-')}` |\n"
    md += f"| **创建时间** | {req.get('created_at', '-')} |\n"
    md += f"| **完成时间** | {req.get('completed_at', '-')} |\n"
    md += f"| **总耗时** | {duration_str or '-'} |\n"
    md += f"| **工单数** | {len(tickets)} |\n\n"

    # 需求描述
    md += f"## 需求描述\n\n{req.get('description', '-')}\n\n"

    # PRD
    if req.get("prd_content"):
        md += f"## PRD 摘要\n\n{req['prd_content']}\n\n"

    # 工单清单
    md += f"## 工单清单 ({len(tickets)})\n\n"
    md += f"| # | 标题 | 状态 | 类型 | 模块 | Agent | 预估工时 |\n"
    md += f"|---|------|------|------|------|-------|----------|\n"
    for i, t in enumerate(tickets, 1):
        status_label = t.get("status", "")
        md += f"| {i} | {t['title']} | {status_label} | {t.get('type', '-')} | {t.get('module', '-')} | {t.get('assigned_agent', '-')} | {t.get('estimated_hours', '-')}h |\n"
    md += "\n"

    # 产出文件
    if artifacts:
        md += f"## 产出文件 ({len(artifacts)})\n\n"
        for a in artifacts:
            ticket_short = (a.get("ticket_id") or "")[-6:]
            md += f"- **{a.get('name', a['type'])}** ({a['type']}) — 工单 #{ticket_short} — {a.get('created_at', '')[:16]}\n"
        md += "\n"

    # 截图预览（收集各工单 Medias 目录下的图片）
    try:
        from git_manager import git_manager as _gm
        repo_dir = _gm._repo_path(project_id)
        req_short_path = req_short  # 需求短码
        screenshot_entries = []
        # 扫描 docs/<req_short>/<ticket_short>/Medias/ 目录
        docs_root = repo_dir / "docs" / req_short_path
        if docs_root.exists():
            for medias_dir in docs_root.glob("*/Medias"):
                for img in sorted(medias_dir.glob("*.png")):
                    rel = img.relative_to(repo_dir / "docs" / req_short_path)
                    screenshot_entries.append(str(rel).replace("\\", "/"))
        if screenshot_entries:
            md += f"## 测试截图\n\n"
            for s in screenshot_entries:
                md += f"![{s}](./{s})\n\n"
    except Exception:
        pass

    # AI 会话统计
    if llm_stats and llm_stats.get("count"):
        input_t = llm_stats.get("input_tokens") or 0
        output_t = llm_stats.get("output_tokens") or 0
        total_ms = llm_stats.get("total_ms") or 0
        md += f"## AI 会话统计\n\n"
        md += f"| 指标 | 数值 |\n|------|------|\n"
        md += f"| 会话次数 | {llm_stats['count']} |\n"
        md += f"| 输入 tokens | {input_t:,} |\n"
        md += f"| 输出 tokens | {output_t:,} |\n"
        md += f"| 总计 tokens | {input_t + output_t:,} |\n"
        md += f"| 总耗时 | {total_ms / 1000:.1f}s |\n\n"

    # 时间线（关键日志）
    key_actions = ["create", "decompose", "assign", "complete", "accept", "reject", "error"]
    key_logs = [l for l in logs if l.get("action") in key_actions][:30]
    if key_logs:
        md += f"## 关键时间线\n\n"
        md += f"| 时间 | Agent | 动作 | 说明 |\n|------|-------|------|------|\n"
        for l in key_logs:
            detail = ""
            try:
                d = json.loads(l.get("detail", "{}"))
                detail = d.get("message", "")[:60]
            except Exception:
                detail = str(l.get("detail", ""))[:60]
            md += f"| {l.get('created_at', '')[:16]} | {l.get('agent_type', '-')} | {l.get('action', '-')} | {detail} |\n"
        md += "\n"

    # Git 提交记录
    if git_commits:
        md += f"## Git 提交记录 (最近 {len(git_commits)} 条)\n\n"
        for c in git_commits[:20]:
            md += f"- `{c.get('short_hash', '?')}` {c.get('message', '')} — {c.get('author', '')} {c.get('date', '')[:16]}\n"
        md += "\n"

    md += f"\n---\n*报告由 AI Dev System 自动生成 — {now_iso()[:16]}*\n"

    # === 保存报告 ===
    report_path = f"docs/{req_short}/REPORT.md"

    # 写入 Git 仓库
    try:
        await git_manager.write_file(project_id, report_path, md)
        commit_hash = await git_manager.commit(
            project_id,
            f"[Report] 需求完成报告: {req['title'][:30]}",
            author="AI Dev System",
        )
        await git_manager.push(project_id)
        logger.info("📊 需求报告已生成: %s (commit: %s)", report_path, commit_hash)
    except Exception as git_err:
        logger.warning("报告写入 Git 失败: %s", git_err)

    # 保存到 artifacts 表
    await db.insert("artifacts", {
        "id": generate_id("ART"),
        "project_id": project_id,
        "requirement_id": requirement_id,
        "ticket_id": None,
        "type": "report",
        "name": f"需求完成报告 - {req['title']}",
        "path": report_path,
        "content": md,
        "metadata": json.dumps({"ticket_count": len(tickets), "artifact_count": len(artifacts)}),
        "created_at": now_iso(),
    })

    await orch._log(
        project_id, requirement_id, None, "Orchestrator",
        "complete", "completed", "completed",
        f"需求完成报告已生成: {report_path}"
    )

    # P5-3 三级内省：需求完成后写入知识库（供后续 Insight 检索）
    try:
        rework_count = sum(1 for l in logs if l.get("action") in ("rework", "fix_issues"))
        block_count  = sum(1 for l in logs if l.get("to_status") == "blocked")
        total_ms     = (llm_stats["total_ms"] or 0) if llm_stats else 0
        insight_content = (
            f"需求「{req['title']}」完成复盘：\n"
            f"- 工单数: {len(tickets)}，产物数: {len(artifacts)}\n"
            f"- 返工次数: {rework_count}，Blocked 次数: {block_count}\n"
            f"- LLM 总耗时: {total_ms//1000}s\n"
            f"{'- 注意: 有较多返工，说明需求描述或架构设计需要改进' if rework_count > 2 else ''}"
        )
        from api.knowledge import _upsert_knowledge_index
        fname = f"insight__req_{req_short}_retrospective.md"
        await _upsert_knowledge_index(
            project_id, fname, insight_content,
            agent_scope="dev",
        )
        logger.info("📝 需求级内省已写入知识库: %s", fname)
    except Exception as intro_err:
        logger.debug("内省写入失败（非致命）: %s", intro_err)


async def trigger_dependents(orch, db, project_id: str, completed_ticket_id: str):
    """工单完成后，触发依赖它的后续工单流转"""
    # 查找同项目下所有 pending 且 dependencies 包含此工单 ID 的工单
    pending_tickets = await db.fetch_all(
        "SELECT * FROM tickets WHERE project_id = ? AND status = ? AND dependencies IS NOT NULL AND dependencies != '[]'",
        (project_id, TicketStatus.PENDING.value),
    )

    for pt in pending_tickets:
        try:
            deps = json.loads(pt["dependencies"]) if pt["dependencies"] else []
        except (json.JSONDecodeError, TypeError):
            continue

        if completed_ticket_id not in deps:
            continue

        # 检查该工单的所有依赖是否都已完成（testing_done 或 deployed）
        DONE_STATUSES = {TicketStatus.TESTING_DONE.value, TicketStatus.DEPLOYED.value}
        all_deps_done = True
        for dep_id in deps:
            dep_ticket = await db.fetch_one(
                "SELECT status FROM tickets WHERE id = ?", (dep_id,)
            )
            if not dep_ticket or dep_ticket["status"] not in DONE_STATUSES:
                all_deps_done = False
                break

        if all_deps_done:
            logger.info(
                "🔓 工单 %s 的所有前置依赖已完成，开始流转",
                pt["id"][:12],
            )
            await orch._log(
                project_id, pt["requirement_id"], pt["id"], "Orchestrator",
                "info", "pending", "pending",
                f"前置依赖已全部完成（包括 #{completed_ticket_id[-6:]}），开始自动流转", "info"
            )
            # 直接续跑依赖工单：此时当前工单仍占项目槽，enqueue 会被槽满挡住；
            # 互斥由 process_ticket claim 保证，不会与轮询双开同一张单。
            asyncio.create_task(orch.process_ticket(project_id, pt["id"]))
