"""
DevAgent — 开发 Agent (Role)
职责：接单开发代码 → 自测 → 开发笔记
Actions: PlanCodeChangeAction (增量) / WriteCodeAction (全新) + SelfTestAction + ReflectionAction
Mode: BY_ORDER
Watch: design_architecture

rework / fix_issues 会先调用 ReflectionAction 做结构化反思，反思结果注入
后续代码生成 Action 的 prompt（见 plan_code_change.py / write_code.py）。
详见 docs/20260419_01_Reflexion反思框架实现方案.md
"""
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict
from agents.base import BaseAgent, ReactMode
from actions.write_code import WriteCodeAction
from actions.plan_code_change import PlanCodeChangeAction
from actions.self_test import SelfTestAction
from actions.reflection import ReflectionAction
from actions.write_html_prototype import WriteHtmlPrototypeAction

logger = logging.getLogger("dev_agent")


class DevAgent(BaseAgent):

    action_classes = [WriteCodeAction, PlanCodeChangeAction, SelfTestAction, ReflectionAction,
                      WriteHtmlPrototypeAction]
    react_mode = ReactMode.SINGLE  # 自己控制流程，不用 BY_ORDER
    watch_actions = {"design_architecture"}

    @property
    def agent_type(self) -> str:
        return "DevAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "develop":
            return await self._do_develop(context)
        elif task_name == "rework":
            return await self._do_rework(context)
        elif task_name == "fix_issues":
            return await self._do_fix_issues(context)
        elif task_name == "run_engine_compile":
            return await self._do_run_engine_compile(context)
        elif task_name == "write_html_prototype":
            return await self._do_write_html_prototype(context)
        return {"status": "error", "message": f"未知任务: {task_name}"}

    async def _do_write_html_prototype(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """HTML 原型验证阶段：生成单文件 HTML 原型验证核心玩法循环。"""
        from actions.write_html_prototype import WriteHtmlPrototypeAction
        action = WriteHtmlPrototypeAction()
        result = await action.run(context)
        if result.success:
            return result.data or {"status": "success"}
        return {"status": "error", "message": result.message or "HTML 原型生成失败"}

    async def _do_run_engine_compile(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """UE 引擎编译验证（v0.18 Phase A）—— 调 UnrealBuildTool 编译项目。

        入参通过 context 透传：engine_path / uproject_path / target_name / platform / config。
        若 context 缺项，Action 会自动解析（resolve_project_engine + _infer_target_name）。
        """
        from actions.ue_compile_check import UECompileCheckAction
        action = UECompileCheckAction()
        result = await action.run(context)
        # ActionResult.to_dict() 已经把 status / errors / warnings / products 都平铺好
        return result.to_dict()

    async def _do_develop(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """开发：有 OpenSpec change/tasks 时强制走 Apply；否则 WriteCode / PlanCodeChange。"""
        existing_code = context.get("existing_code", {})
        step_total = 2

        # Superpowers 纪律注入（可选增强，项目装了 Pack 才激活）
        project_id = context.get("project_id", "")
        repo_path = context.get("repo_path", "")
        await self._inject_superpowers(context, project_id, repo_path)

        # 步骤 1：代码生成（OpenSpec Apply 优先）
        t0 = time.monotonic()
        await self.emit_step("代码生成", context, phase="start", step_index=1, step_total=step_total)
        apply_result = await self._run_openspec_apply(context)
        if apply_result is not None:
            code_result = apply_result
            logger.info("📐 开发走 OpenSpec Apply（files=%d）", len(code_result.get("files") or {}))
        elif existing_code:
            logger.info("📋 检测到已有代码，使用 PlanCodeChange 精准增量")
            code_result = await self.run_action("plan_code_change", context)
        else:
            logger.info("📝 空项目，使用 WriteCode 全新生成")
            code_result = await self.run_action("write_code", context)
        await self.emit_step("代码生成", context, phase="done", step_index=1, step_total=step_total,
                             duration_ms=int((time.monotonic() - t0) * 1000))

        # Apply 硬失败：不继续自测，直接返回错误（避免绕过规范层瞎写）
        if code_result.get("_openspec_apply_failed"):
            return {
                "status": "error",
                "message": code_result.get("message") or "OpenSpec Apply 失败",
                "files": code_result.get("files") or {},
                "dev_result": code_result.get("dev_result") or {"files": {}, "notes": ""},
                "openspec_apply": code_result.get("openspec_apply"),
            }

        # 注入 files 到 context，供 SelfTest 使用
        files = code_result.get("files", {})
        context["_files"] = files
        context["dev_result"] = code_result.get("dev_result", {"files": files})

        # 步骤 2：自测
        t1 = time.monotonic()
        await self.emit_step("自测验证", context, phase="start", step_index=2, step_total=step_total)
        test_result = await self.run_action("self_test", context)
        await self.emit_step("自测验证", context, phase="done", step_index=2, step_total=step_total,
                             duration_ms=int((time.monotonic() - t1) * 1000))

        # 合并结果
        result = {**code_result}
        result.setdefault("files", {}).update(test_result.get("files", {}))
        result["self_test"] = test_result.get("self_test", {})
        if "dev_result" not in result:
            result["dev_result"] = {"files": files, "notes": ""}
        result["estimated_hours"] = result.get("estimated_hours", 4)

        return result

    async def _run_openspec_apply(self, context: Dict[str, Any]):
        """有 OpenSpec change+tasks 时用 SkillRunner 跑 Apply；否则返回 None（走旧开发路径）。

        返回 dict（含 files / status）表示已接管开发；返回 None 表示未启用 Apply。
        """
        try:
            project_id = context.get("project_id", "")
            ticket_id = context.get("ticket_id", "")
            if not project_id or not ticket_id:
                return None

            from capability_check import (
                has_openspec, get_openspec_cli, _get_repo_path,
                ticket_has_tasks, ticket_has_change, _short_ticket_id,
            )
            repo_path = context.get("repo_path") or await _get_repo_path(project_id)
            if not repo_path or not await has_openspec(project_id, repo_path):
                return None
            # 本工单已有 OpenSpec change → 强制 Apply，禁止降级 WriteCode
            if not ticket_has_change(repo_path, ticket_id):
                logger.info("📐 OpenSpec Apply 跳过：本工单尚无 change（ticket=%s）", ticket_id[:12])
                return None
            if not ticket_has_tasks(repo_path, ticket_id):
                logger.warning("📐 OpenSpec change 存在但缺 tasks.md，拒绝降级 WriteCode（ticket=%s）",
                               ticket_id[:12])
                return {
                    "status": "error",
                    "_openspec_apply_failed": True,
                    "message": "OpenSpec Propose 尚未产出 tasks.md，无法 Apply。请先完成 Propose 四件套。",
                    "files": {},
                }

            from skills.executable_loader import load_executable_skill
            from skills.runner import SkillRunner
            skill = load_executable_skill("openspec-apply", repo_path=repo_path)
            if not skill:
                logger.warning("📐 openspec-apply skill 未找到，拒绝降级到 WriteCode")
                return {
                    "status": "error",
                    "_openspec_apply_failed": True,
                    "message": "项目已有 OpenSpec change，但 openspec-apply skill 未找到",
                    "files": {},
                }
            runner = SkillRunner(skill)
            if not await runner.is_available({"project_id": project_id, "repo_path": repo_path}):
                return None

            cli = get_openspec_cli()
            change_id = _short_ticket_id(ticket_id)
            if not cli or not change_id:
                return None

            from database import db
            from utils import now_iso
            from orchestrator import orchestrator as orch

            project_traits = []
            try:
                row = await db.fetch_one("SELECT traits FROM projects WHERE id=?", (project_id,))
                if row and row.get("traits"):
                    project_traits = json.loads(row["traits"])
            except Exception:
                pass

            # 把反思/编译错误等注入 goal，便于 Apply 修回归
            extra_bits = []
            if context.get("reflection"):
                extra_bits.append(f"反思: {json.dumps(context['reflection'], ensure_ascii=False)[:400]}")
            if context.get("compile_errors"):
                extra_bits.append(f"编译错误: {json.dumps(context['compile_errors'], ensure_ascii=False)[:400]}")
            if context.get("test_issues"):
                extra_bits.append(f"测试问题: {json.dumps(context['test_issues'], ensure_ascii=False)[:300]}")

            run_ctx = {
                **context,
                "cli": cli, "change_id": change_id,
                "repo_path": repo_path, "project_id": project_id, "ticket_id": ticket_id,
                "project_traits": project_traits,
                "_skill_written_files": {},
            }
            if extra_bits:
                run_ctx["ticket_description"] = (
                    f"{context.get('ticket_description') or ''}\n" + "\n".join(extra_bits)
                )

            logger.info("📐 [规范层] OpenSpec Apply 启动: change=%s", change_id)
            await orch._add_layer_log(
                ticket_id, project_id, action="openspec_apply_started", layer="spec",
                detail={"change_id": change_id,
                        "message": f"OpenSpec Apply 已启动，按 tasks.md 落地实现（change `{change_id}`）…"},
            )
            await orch.post_milestone_comment(
                ticket_id, project_id,
                f"📐 [规范层] **OpenSpec Apply 已启动** — 按 `openspec/changes/{change_id}/tasks.md` "
                f"逐项实现（不再走通用 WriteCode）…",
            )

            async def on_tool(ev):
                try:
                    await self._emit_react_tool(
                        project_id, context.get("requirement_id"), ticket_id,
                        ev.tool, ev.args_hint, ev.duration_ms,
                        output_summary=(ev.result or "")[:500], summary=ev.summary or "",
                    )
                except Exception:
                    pass

            result = await runner.execute(run_ctx, on_tool=on_tool)
            files = dict(run_ctx.get("_skill_written_files") or {})
            # 确保 tasks.md 最新内容进 commit（若磁盘有而 tracker 漏了）
            try:
                from capability_check import get_ticket_tasks_path
                tp = get_ticket_tasks_path(repo_path, ticket_id)
                if tp.is_file():
                    rel = tp.relative_to(Path(repo_path)).as_posix()
                    files.setdefault(rel, tp.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                pass

            # 无任何落盘且 runner 报错/超预算 → 硬失败；all_done 未改文件仍算成功
            is_fail = (result.status in ("error", "budget_exceeded") and not files)
            is_partial = (result.status not in ("success",)) and bool(files)

            if is_fail:
                await orch._add_layer_log(
                    ticket_id, project_id, action="openspec_apply_failed", layer="spec",
                    level="warning",
                    detail={"change_id": change_id, "status": result.status,
                            "message": (result.message or "")[:400], "rounds": result.rounds},
                )
                await orch.post_milestone_comment(
                    ticket_id, project_id,
                    f"📐 [规范层] **OpenSpec Apply 失败** — {result.status}: {(result.message or '')[:300]}",
                    level="error",
                )
                return {
                    "status": "error",
                    "_openspec_apply_failed": True,
                    "message": f"OpenSpec Apply 失败（{result.status}）: {result.message or ''}",
                    "files": files,
                    "openspec_apply": {"change_id": change_id, "status": result.status},
                    "dev_result": {"files": files, "notes": result.message or ""},
                }

            await db.execute(
                "UPDATE tickets SET openspec_stage='applied', updated_at=? WHERE id=?",
                (now_iso(), ticket_id),
            )
            action = "openspec_apply_partial" if is_partial and result.status != "success" else "openspec_apply"
            await orch._add_layer_log(
                ticket_id, project_id, action=action, layer="spec",
                level="warning" if action.endswith("partial") else "info",
                detail={"change_id": change_id, "status": result.status, "rounds": result.rounds,
                        "files": list(files.keys())[:40], "message": (result.message or "")[:400]},
            )
            await orch.post_milestone_comment(
                ticket_id, project_id,
                f"📐 [规范层] **OpenSpec Apply "
                f"{'部分完成' if action.endswith('partial') else '完成'}** — "
                f"change `{change_id}`，写入 {len(files)} 个文件（{result.rounds} 轮）。",
            )
            logger.info("📐 OpenSpec Apply %s（ticket=%s, files=%d, status=%s）",
                        "部分完成" if action.endswith("partial") else "成功",
                        ticket_id[:12], len(files), result.status)

            notes = result.message or f"OpenSpec Apply {change_id}"
            return {
                "status": "success",
                "files": files,
                "dev_result": {"files": files, "notes": notes},
                "openspec_apply": {
                    "change_id": change_id,
                    "status": result.status,
                    "rounds": result.rounds,
                    "files_count": len(files),
                },
                "estimated_hours": 4,
            }
        except Exception as e:
            logger.warning("_run_openspec_apply 异常: %s", e, exc_info=True)
            return {
                "status": "error",
                "_openspec_apply_failed": True,
                "message": f"OpenSpec Apply 异常: {e}",
                "files": {},
            }

    async def _do_rework(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """返工（Reflexion）：先反思失败根因 → 再按反思策略重开发"""
        context["failure_type"] = "acceptance_rejected"
        return await self._do_retry_with_reflection(context)

    async def _do_fix_issues(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """失败修复（Reflexion）：先识别是什么类型的失败，再反思根因 → 按策略重开发。

        v0.18 Phase D：支持 engine_compile_failed 场景 —— 从最近一条 reject 日志读
        结构化编译 errors，注入 context 供 reflect + write_code 用。
        """
        from database import db

        ticket_id = context.get("ticket_id")
        failure_type = "testing_failed"   # 默认兜底

        if ticket_id:
            cur = await db.fetch_one("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
            cur_status = (cur or {}).get("status") or ""
            if cur_status == "engine_compile_failed":
                failure_type = "engine_compile_failed"
            elif cur_status == "play_test_failed":
                # v0.19 Phase ②：UE Automation playtest 失败
                failure_type = "play_test_failed"
            elif cur_status == "self_test_failed":
                # v0.19.x A 方案：UE 静态预检（Layer 1）失败
                failure_type = "self_test_failed"
            elif cur_status == "testing_failed":
                failure_type = "testing_failed"
            elif cur_status == "acceptance_rejected":
                failure_type = "acceptance_rejected"

            # 对于编译失败，从最近的 reject 日志 detail 里拿 errors 列表
            if failure_type == "engine_compile_failed":
                log = await db.fetch_one(
                    """SELECT detail FROM ticket_logs
                       WHERE ticket_id = ? AND action = 'reject'
                       ORDER BY created_at DESC LIMIT 1""",
                    (ticket_id,),
                )
                if log and log.get("detail"):
                    try:
                        det = json.loads(log["detail"])
                        context["compile_errors"] = det.get("errors") or []
                        context["compile_warnings"] = det.get("warnings") or []
                        context["compile_command"] = det.get("command") or ""
                        logger.info(
                            "🔧 fix_issues 接到编译失败 context: %d errors",
                            len(context["compile_errors"]),
                        )
                    except Exception as e:
                        logger.warning("解析编译失败 detail 异常: %s", e)

            # v0.19.x A 方案：UE 静态预检失败 → 从 artifacts 拉 blocking issues
            # （self_test 失败时 orchestrator 把 issues 存进 ticket.result）
            if failure_type == "self_test_failed":
                t_row = await db.fetch_one(
                    "SELECT result FROM tickets WHERE id = ?", (ticket_id,)
                )
                if t_row and t_row.get("result"):
                    try:
                        r = json.loads(t_row["result"])
                        st = r.get("self_test") or {}
                        blocking_issues = st.get("ue_blocking_issues") or []
                        context["ue_blocking_issues"] = blocking_issues
                        logger.info(
                            "🔍 fix_issues 接到 UE 自测 blocking context: %d issues",
                            len(blocking_issues),
                        )
                    except Exception as e:
                        logger.warning("解析 self_test result 异常: %s", e)

            # v0.19：playtest 失败，从 reject 日志拿失败测试列表
            if failure_type == "play_test_failed":
                log = await db.fetch_one(
                    """SELECT detail FROM ticket_logs
                       WHERE ticket_id = ? AND action = 'reject'
                       ORDER BY created_at DESC LIMIT 1""",
                    (ticket_id,),
                )
                if log and log.get("detail"):
                    try:
                        det = json.loads(log["detail"])
                        context["failed_tests"] = det.get("tests") or []
                        context["playtest_summary"] = det.get("summary") or {}
                        context["playtest_command"] = det.get("command") or ""
                        logger.info(
                            "🎮 fix_issues 接到 playtest 失败 context: %d failed tests",
                            len(context["failed_tests"]),
                        )
                    except Exception as e:
                        logger.warning("解析 playtest 失败 detail 异常: %s", e)

                # v0.20 UCP：若 Editor 可用，查当前关卡 Actor 列表辅助 Reflexion
                if context.get("ucp_available"):
                    try:
                        from actions.ue_editor_control import UEEditorControlAction
                        ucp_result = await UEEditorControlAction().run({
                            "op": "get_actors",
                            "project_id": context.get("project_id"),
                        })
                        if ucp_result.success:
                            actors = ucp_result.data.get("result", [])
                            context["editor_state"] = {
                                "actors": actors[:50],  # 最多50个
                                "actor_count": len(actors),
                            }
                            logger.info("🎮 UCP editor_state 注入: %d actors", len(actors))
                    except Exception as e:
                        logger.debug("UCP editor_state 查询失败（非致命）: %s", e)

        context["failure_type"] = failure_type
        return await self._do_retry_with_reflection(context)

    async def _do_retry_with_reflection(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """通用重试流程：拉历次反思 → 反思当次失败 → 注入 context → 重开发"""
        step_total = 3

        # 步骤 1：拉取重试上下文
        t0 = time.monotonic()
        await self.emit_step("拉取重试上下文", context, phase="start", step_index=1, step_total=step_total)
        await self._enrich_retry_context(context)
        await self.emit_step("拉取重试上下文", context, phase="done", step_index=1, step_total=step_total,
                             duration_ms=int((time.monotonic() - t0) * 1000))

        # 2. SOP config 允许关掉反思做 A/B
        sop_cfg = context.get("sop_config") or {}
        enable_reflection = sop_cfg.get("enable_reflection", True)

        reflection = None
        if enable_reflection and self.has_action("reflect"):
            # 步骤 2：反思根因
            t1 = time.monotonic()
            await self.emit_step("反思失败根因", context, phase="start", step_index=2, step_total=step_total)
            refl_result = await self.run_action("reflect", context)
            reflection = refl_result.get("reflection") or {}
            reflection["retry_count"] = context.get("retry_count", 1)
            context["reflection"] = reflection
            await self.emit_step("反思失败根因", context, phase="done", step_index=2, step_total=step_total,
                                 duration_ms=int((time.monotonic() - t1) * 1000))
            logger.info(
                "🔍 Reflection 已注入（retry=%d, confidence=%.2f）",
                reflection["retry_count"],
                float(reflection.get("confidence", 0.0) or 0.0),
            )
        else:
            # 降级到旧逻辑：把失败信号拼到 ticket_description
            ft = context.get("failure_type")
            if ft == "acceptance_rejected":
                rr = context.get("rejection_reason", "")
                if rr:
                    context["ticket_description"] = (
                        f"{context.get('ticket_description', '')} [返工原因] {rr}"
                    )
            elif ft == "engine_compile_failed":
                errs = context.get("compile_errors") or []
                if errs:
                    brief = "; ".join(
                        f"{e.get('file', '?')}:{e.get('line', '?')} {e.get('code', '')} {(e.get('msg') or '')[:80]}"
                        for e in errs[:5]
                    )
                    context["ticket_description"] = (
                        f"{context.get('ticket_description', '')} [编译错误] {brief}"
                    )
            else:
                ti = context.get("test_issues", [])
                if ti:
                    context["ticket_description"] = (
                        f"{context.get('ticket_description', '')} "
                        f"[测试问题] {json.dumps(ti, ensure_ascii=False)}"
                    )

        # 步骤 3：重新开发
        await self.emit_step("重新开发", context, phase="start", step_index=3, step_total=step_total)
        t2 = time.monotonic()
        result = await self._do_develop(context)
        await self.emit_step("重新开发", context, phase="done", step_index=3, step_total=step_total,
                             duration_ms=int((time.monotonic() - t2) * 1000))

        # 4. 带出反思，供 orchestrator 写入 ticket_logs
        if reflection:
            result["last_reflection"] = reflection
        return result

    async def _enrich_retry_context(self, context: Dict[str, Any]):
        """从 DB 拉取重试所需上下文：retry_count + previous_reflections + previous_code"""
        from database import db

        ticket_id = context.get("ticket_id")
        if not ticket_id:
            context.setdefault("retry_count", 1)
            context.setdefault("previous_reflections", [])
            context.setdefault("previous_code", context.get("existing_code") or {})
            return

        # 重试次数：历史上这个工单被 reject 过几次，本次就是第 N+1 次
        try:
            row = await db.fetch_one(
                "SELECT COUNT(*) AS c FROM ticket_logs WHERE ticket_id = ? AND action = 'reject'",
                (ticket_id,),
            )
            context["retry_count"] = (row["c"] if row else 0) + 1
        except Exception as e:
            logger.warning("查询 retry_count 失败: %s", e)
            context["retry_count"] = 1

        # 历次反思（按时间正序，最多 3 条）
        try:
            refl_logs = await db.fetch_all(
                """SELECT detail FROM ticket_logs
                   WHERE ticket_id = ? AND action = 'reflection'
                   ORDER BY created_at DESC LIMIT 3""",
                (ticket_id,),
            )
            prevs = []
            for log in reversed(refl_logs):  # DB 降序 → 反转成时间正序
                try:
                    parsed = json.loads(log["detail"])
                    # detail 里可能直接是 reflection dict，也可能包了一层
                    refl = parsed.get("reflection", parsed) if isinstance(parsed, dict) else {}
                    if refl:
                        prevs.append(refl)
                except Exception:
                    pass
            context["previous_reflections"] = prevs
        except Exception as e:
            logger.warning("查询 previous_reflections 失败: %s", e)
            context["previous_reflections"] = []

        # 上次代码（简化：用 existing_code；完整实现应该从 feat 分支 git read）
        context["previous_code"] = context.get("existing_code") or {}

        # Failure Library：跨工单相似失败（供 ReflectionAction 参考，避免重复踩坑）
        try:
            from failure_library import failure_library
            context["similar_failures"] = await failure_library.search_similar(
                agent_type=self.agent_type,
                failure_type=context.get("failure_type", "acceptance_rejected"),
                ticket_description=context.get("ticket_description", "") or "",
                module=context.get("module"),
                project_id=context.get("project_id"),
                current_ticket_id=ticket_id,
                limit=3,
            )
            if context["similar_failures"]:
                logger.info("🔎 查到 %d 条跨工单相似失败", len(context["similar_failures"]))
        except Exception as e:
            logger.warning("查询 similar_failures 失败: %s", e)
            context["similar_failures"] = []

    # ──────────────────────────────────────────────────────────────
    # Superpowers 纪律注入
    # ──────────────────────────────────────────────────────────────

    # 开发阶段注入的核心 Skill 列表（按重要性排序，控制 token 量）
    _SUPERPOWERS_DEV_SKILLS = [
        "using-superpowers",           # 铁律总纲（最重要）
        "test-driven-development",     # TDD 铁律
        "systematic-debugging",        # 根因分析
        "verification-before-completion",  # 完成前必须验证
    ]

    async def _inject_superpowers(
        self,
        context: Dict[str, Any],
        project_id: str,
        repo_path: str,
    ) -> None:
        """
        检测项目是否安装了 Superpowers Pack，有则把核心 Skill 注入 context['superpowers_context']。
        Actions（如 WriteCodeAction）读取该字段追加到 instruction 中。
        无 Pack 时静默跳过，不影响原有执行路径。
        """
        if not repo_path:
            return
        try:
            from capability_check import has_superpowers, load_superpowers_skills
            if not await has_superpowers(project_id, repo_path):
                return

            sp_content = load_superpowers_skills(repo_path, self._SUPERPOWERS_DEV_SKILLS)
            if not sp_content:
                return

            context["superpowers_context"] = sp_content
            logger.info("⚡ Superpowers 纪律已注入 DevAgent（%d chars）", len(sp_content))

            # 写时间轴日志（layer=discipline）
            ticket_id = context.get("ticket_id", "")
            if ticket_id:
                try:
                    import json as _json
                    from database import db
                    from utils import generate_id, now_iso
                    await db.insert("ticket_logs", {
                        "id": generate_id("LOG"),
                        "ticket_id": ticket_id,
                        "project_id": project_id,
                        "agent_type": "discipline",
                        "action": "superpowers_skill",
                        "detail": _json.dumps({
                            "skills": self._SUPERPOWERS_DEV_SKILLS,
                            "pack": "superpowers",
                            "chars": len(sp_content),
                        }, ensure_ascii=False),
                        "level": "info",
                        "layer": "discipline",
                        "created_at": now_iso(),
                    })
                except Exception:
                    pass
        except Exception as e:
            logger.debug("_inject_superpowers 失败（忽略）: %s", e)
