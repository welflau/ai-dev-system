"""OpenSpec 收尾：测试阶段通过后的 verify，历史工单的 verify 和 archive 补跑。

`maybe_openspec_verify` 在测试阶段通过后触发 verify：`openspec_stage` 已经是 verified 或 archived 时直接返回 True，其余情况调 TestAgent 的 `_run_openspec_verify`（按源码注释，工单没有 OpenSpec 时由它自己跳过）并返回它的结果，任何异常都记一条 debug 日志并返回 False。`finalize_openspec_after_done` 给历史工单补跑收尾，函数自己只看 `openspec_stage`，不检查工单状态：空、archived 或其他值直接返回；proposed 或 applied 时先以 `block_on_fail=False` 跑 verify，未通过就记日志并返回，通过后重读 stage；stage 是 verified（包括一进来就是 verified）时调 DeployAgent 的 `_run_openspec_archive`，再读一次库，确实是 archived 才写一条 layer 为 spec 的日志。TestAgent 和 DeployAgent 都经 `runtime_facade` 取，用到时才解析。

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
import logging

logger = logging.getLogger("orchestrator")


async def maybe_openspec_verify(
    orch, db, project_id: str, ticket_id: str, *, stage_label: str = "",
) -> bool:
    """测试阶段通过后触发 OpenSpec Verify（规范层，可选增强）。

    为什么放 orchestrator 而不是 Agent 里：Verify 失败要把工单打成 blocked，
    而 orchestrator 在 Agent 返回之后才写状态 —— Agent 内部写的 blocked 会被
    随后的 play_test_passed 覆盖掉。run_tests 那条路径侥幸没踩到是因为它写
    状态的时机恰好在后面，但同一件事分两处实现迟早走样，所以统一收口到这里。

    幂等：openspec_stage 已经是 verified / archived 就不重跑。
    """
    try:
        row = await db.fetch_one(
            "SELECT openspec_stage FROM tickets WHERE id = ?", (ticket_id,),
        )
        stage = ((row or {}).get("openspec_stage") or "").strip()
        # 没有 OpenSpec（空）→ _run_openspec_verify 自己会静默跳过；
        # 已 verified/archived → 重复 validate 没意义，还会多发一条里程碑评论
        if stage in ("verified", "archived"):
            return True

        import runtime_facade
        ctx = {"project_id": project_id, "ticket_id": ticket_id}
        ok = await runtime_facade.agents_test().TestAgent()._run_openspec_verify(ctx)
        if ok and stage_label:
            logger.info(
                "📐 OpenSpec Verify 由 %s 阶段触发并通过（ticket=%s）",
                stage_label, ticket_id[:12],
            )
        return ok
    except Exception as e:
        logger.debug("_maybe_openspec_verify 失败（忽略）: %s", e)
        return False


async def finalize_openspec_after_done(
    orch, db, project_id: str, ticket_id: str,
) -> None:
    """工单已到 testing_done/deployed 但 OpenSpec 停在 applied 时，软收尾 Verify→Archive。

    用于历史单（含旧 force_pass）打开详情时补跑；新路径 reject 上限改为 blocked，不再走此收尾。
    Verify 失败不回 blocked（block_on_fail=False）。
    """
    row = await db.fetch_one(
        "SELECT openspec_stage, status FROM tickets WHERE id = ?", (ticket_id,),
    )
    if not row:
        return
    stage = (row.get("openspec_stage") or "").strip()
    if stage in ("", "archived"):
        return
    if stage not in ("proposed", "applied", "verified"):
        return

    ctx = {"project_id": project_id, "ticket_id": ticket_id}
    if stage in ("proposed", "applied"):
        import runtime_facade
        ok = await runtime_facade.agents_test().TestAgent()._run_openspec_verify(ctx, block_on_fail=False)
        if not ok:
            logger.info(
                "📐 OpenSpec 终态收尾：Verify 未通过，跳过 Archive（ticket=%s）",
                ticket_id[:12],
            )
            return
        row = await db.fetch_one(
            "SELECT openspec_stage FROM tickets WHERE id = ?", (ticket_id,),
        )
        stage = ((row or {}).get("openspec_stage") or "").strip()

    if stage == "verified":
        import runtime_facade
        await runtime_facade.agents_deploy().DeployAgent()._run_openspec_archive(ctx)
        # archive 成功时 DeployAgent 会写 openspec_stage=archived；补一条 layer 日志便于时间轴跳转
        row2 = await db.fetch_one(
            "SELECT openspec_stage FROM tickets WHERE id = ?", (ticket_id,),
        )
        if (row2 or {}).get("openspec_stage") == "archived":
            await orch._add_layer_log(
                ticket_id, project_id, action="openspec_archive",
                layer="spec", detail={"message": "终态收尾 Archive 完成"},
            )
