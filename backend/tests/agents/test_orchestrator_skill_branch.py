"""orchestrator 的 SkillAgent 分支。

**为什么这个分支必须存在**：缺了它，SkillAgent 的结果会落到
`_handle_agent_result` 末尾的 `else: new_status = current_status` ——
状态不推进 → 同一条 rule 反复命中 → skill 被无限重跑烧 token。
ArtistAgent（orchestrator.py:2247）和 UEEditorAgent（:2383）的注释都记着
同一个坑，它们都是踩了才补的分支。所以第一条测试就是防这个。

测试用真实 SQLite，只打桩 `process_ticket`（会递归派单）和
`event_manager.publish_to_project`（需要 SSE 连接）。状态推进和日志落库
是本分支的核心职责，必须真跑。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.8
"""
import asyncio
import json
from contextlib import asynccontextmanager

import pytest

import database as database_module
import orchestrator as orch_module
from database import Database
from models import TicketStatus
from orchestrator import TicketOrchestrator

PROJECT_ID = "P1"
REQ_ID = "REQ-20261015-aaa111"
TICKET_ID = "TK-20261015-bbb222"
STAGE_ID = "demo_draft"
SKILL_ID = "demo-draft"
ACTION = f"skill_{STAGE_ID}"
SUCCESS_STATUS = f"{STAGE_ID}_done"


def sop_config(*, produces=(), consumes=()) -> dict:
    """模拟 workflow_composer.skill_to_stage 产出的 config。"""
    return {
        "skill_id": SKILL_ID,
        "_stage_id": STAGE_ID,
        "_success_status": SUCCESS_STATUS,
        "_reject_status": f"{STAGE_ID}_failed",
        "_consumes": list(consumes),
        "_produces": list(produces),
    }


def skill_result(skill_status="success", *, artifacts=(), outputs=(),
                 sop_cfg=None, success_status=SUCCESS_STATUS,
                 message="", rounds=3) -> dict:
    """模拟 SkillAgent._run_skill 的回传。"""
    return {
        "status": "success" if skill_status in ("success", "partial") else skill_status,
        "skill_id": SKILL_ID,
        "skill_status": skill_status,
        "success_status": success_status,
        "sop_config": sop_cfg if sop_cfg is not None else sop_config(),
        "outputs": list(outputs),
        "artifacts": list(artifacts),
        "rounds": rounds,
        "message": message,
    }


@asynccontextmanager
async def _env(tmp_path, monkeypatch, *, initial_status="pending"):
    """真实库 + 打桩递归派单与 SSE。

    ⚠️ **必须跑 `init_tables()`，不能只 executescript(SCHEMA_SQL)。**
    `ticket_comments.reply_to_comment_id` 只存在于 `_auto_migrate` 的
    migrations 列表（database.py:133），SCHEMA_SQL 里没有。只建表不迁移的话
    `_write_phase_comment` 的 insert 会失败 —— 而它把异常吞在
    `logger.debug`（orchestrator.py:4652），测试里表现为「评论数为 0」
    而非报错。第一版就是这么踩的。

    try/finally 保证 disconnect —— aiosqlite 的 worker 是非守护线程，漏掉会让
    pytest 在退出阶段挂死（见 dev-notes/2026-10-15_04）。
    """
    db_file = tmp_path / "t.db"

    original_db = database_module.db
    test_db = Database(db_path=str(db_file))
    await test_db.connect()
    await test_db.init_tables()          # 建表 + 迁移，缺一不可
    database_module.db = test_db
    monkeypatch.setattr(orch_module, "db", test_db, raising=False)

    await test_db.insert("projects", {
        "id": PROJECT_ID, "name": "demo", "traits": '["pipeline:content"]',
        "created_at": "2026-10-15T00:00:00Z", "updated_at": "2026-10-15T00:00:00Z",
    })
    await test_db.insert("requirements", {
        "id": REQ_ID, "project_id": PROJECT_ID, "title": "需求",
        "description": "描述",
        "created_at": "2026-10-15T00:00:00Z", "updated_at": "2026-10-15T00:00:00Z",
    })
    await test_db.insert("tickets", {
        "id": TICKET_ID, "project_id": PROJECT_ID, "requirement_id": REQ_ID,
        "title": "写技术博客", "description": "讲产物总线",
        "type": "feature", "module": "content", "status": initial_status,
        "created_at": "2026-10-15T00:00:00Z", "updated_at": "2026-10-15T00:00:00Z",
    })

    sse_events = []

    async def fake_publish(pid, event, payload):
        sse_events.append((event, payload))
    monkeypatch.setattr(
        orch_module.event_manager, "publish_to_project", fake_publish
    )

    orch = TicketOrchestrator.__new__(TicketOrchestrator)
    dispatched = []

    async def fake_process(pid, tid):
        dispatched.append(tid)
    orch.process_ticket = fake_process

    async def fake_rules(pid, traits_json=None, ticket_type=None):
        return {SUCCESS_STATUS: {"agent": "SkillAgent", "action": "next"}}
    orch._get_rules_for_project = fake_rules

    async def fake_stage(pid, act, tt=None):
        return None
    orch._sop_stage_for = fake_stage

    # `__new__` 绕过了 __init__，`_HARD_TERMINAL` 是实例属性（orchestrator.py:64）
    # 而非类属性，走 `_handle_agent_result` 真实入口时会 AttributeError。
    # 不调真 __init__ 是因为它会实例化 13 个 Agent + 连 event_bus。
    orch._HARD_TERMINAL = {
        TicketStatus.BLOCKED.value,
        TicketStatus.CANCELLED.value,
        TicketStatus.TESTING_DONE.value,
        TicketStatus.DEPLOYED.value,
        TicketStatus.DONE.value,
        "completed",
    }

    try:
        yield orch, test_db, sse_events, dispatched
    finally:
        database_module.db = original_db
        await test_db.disconnect()


def _run(body, tmp_path, monkeypatch, **kw):
    async def main():
        async with _env(tmp_path, monkeypatch, **kw) as env:
            return await body(*env)
    return asyncio.run(main())


async def _call(orch, result, *, current_status="pending"):
    ticket = {"id": TICKET_ID, "requirement_id": REQ_ID, "title": "写技术博客",
              "type": "feature", "status": current_status}
    await orch._handle_skill_agent_result(
        project_id=PROJECT_ID, ticket_id=TICKET_ID, ticket=ticket,
        requirement_id=REQ_ID, action=ACTION, result=result,
        result_json=json.dumps(result, ensure_ascii=False),
        current_status=current_status,
    )


async def _call_via_dispatcher(orch, result, *, current_status="pending"):
    """走 `_handle_agent_result` 这个**真实入口**，而不是直接调分支函数。

    为什么必须有这条路径：直接调 `_handle_skill_agent_result` 测不出
    「`_handle_agent_result` 里到底有没有那条分发语句」。实测删掉整个
    `if agent_name == "SkillAgent":` 分支后，上面所有直调的测试**依然全绿**
    —— 而生产环境会落进 `else: new_status = current_status` 死循环。

    `_handle_git_files` 需要真实 git 仓库，打桩掉（skill 的产物走产物总线，
    不走 result["files"]）。
    """
    async def no_git(*a, **kw):
        return None
    orch._handle_git_files = no_git

    ticket = {"id": TICKET_ID, "requirement_id": REQ_ID, "title": "写技术博客",
              "type": "feature", "status": current_status}
    await orch._handle_agent_result(
        PROJECT_ID, TICKET_ID, ticket, "SkillAgent", ACTION, result,
    )


async def _status(db) -> str:
    row = await db.fetch_one("SELECT status FROM tickets WHERE id = ?", (TICKET_ID,))
    return row["status"]


async def _logs(db) -> list:
    return await db.fetch_all(
        "SELECT action, level, from_status, to_status, detail FROM ticket_logs "
        "WHERE ticket_id = ? ORDER BY created_at", (TICKET_ID,)
    )


# ════════════════ 核心：状态必须推进（防死循环） ════════════════

def test_dispatcher_routes_skill_agent_to_branch(tmp_path, monkeypatch):
    """**最关键的一条**：`_handle_agent_result` 必须把 SkillAgent 路由到分支。

    缺那条 `if agent_name == "SkillAgent":` 时，结果会落到函数末尾的
    `else: new_status = current_status` —— 状态原地不动 → 同一条 rule 反复
    命中 → skill 被无限重跑烧 token。ArtistAgent（orchestrator.py:2247）和
    UEEditorAgent（:2383）的注释都记着同一个坑，它们都是踩了才补的。

    **必须走真实入口**：本文件其余用例直调 `_handle_skill_agent_result`，
    测不出分发语句是否存在（实测删掉分支后那些用例全绿）。
    """
    async def body(orch, db, sse, dispatched):
        await _call_via_dispatcher(orch, skill_result("success"))
        assert await _status(db) == SUCCESS_STATUS, (
            "状态没推进 —— _handle_agent_result 里可能缺 SkillAgent 分发"
        )
        logs = await _logs(db)
        assert any(l["agent_type"] == "SkillAgent" if "agent_type" in l.keys()
                   else True for l in logs)
    _run(body, tmp_path, monkeypatch)


def test_dispatcher_routes_skipped(tmp_path, monkeypatch):
    """skipped 也要经分发进分支（它和 success 走不同代码路径）。"""
    async def body(orch, db, sse, dispatched):
        await _call_via_dispatcher(orch, skill_result("skipped"))
        assert await _status(db) == SUCCESS_STATUS
    _run(body, tmp_path, monkeypatch)


def test_dispatcher_blocked_path(tmp_path, monkeypatch):
    """失败路径同样要经分发 —— 不能落到通用 else 里静默推进。"""
    async def body(orch, db, sse, dispatched):
        await _call_via_dispatcher(orch, skill_result(
            "budget_exceeded", artifacts=[], message="超时",
        ))
        assert await _status(db) == TicketStatus.BLOCKED.value
    _run(body, tmp_path, monkeypatch)


def test_status_advances_not_stuck(tmp_path, monkeypatch):
    """分支内部：状态从 current 推进到 success_status。"""
    async def body(orch, db, sse, dispatched):
        await _call(orch, skill_result("success"))
        assert await _status(db) == SUCCESS_STATUS
    _run(body, tmp_path, monkeypatch)


def test_success_logs_and_comments(tmp_path, monkeypatch):
    async def body(orch, db, sse, dispatched):
        await _call(orch, skill_result(
            "success",
            outputs=["draft.md"],
            artifacts=[{"kind": "draft_article", "path": "a/b/draft.md"}],
        ))
        logs = await _logs(db)
        assert [l["action"] for l in logs] == ["complete"]
        assert logs[0]["level"] == "info"
        assert logs[0]["to_status"] == SUCCESS_STATUS
        detail = json.loads(logs[0]["detail"])
        assert detail["skill_id"] == SKILL_ID
        assert detail["artifact_kinds"] == ["draft_article"]

        comments = await db.fetch_all(
            "SELECT content FROM ticket_comments WHERE ticket_id = ?", (TICKET_ID,)
        )
        assert len(comments) == 1
        assert "draft_article" in comments[0]["content"]
    _run(body, tmp_path, monkeypatch)


def test_partial_advances_with_warning(tmp_path, monkeypatch):
    """partial 仍推进状态（产出不全但有东西），日志降级成 warning。"""
    async def body(orch, db, sse, dispatched):
        await _call(orch, skill_result(
            "partial", outputs=["draft.md"], message="只写了一半",
        ))
        assert await _status(db) == SUCCESS_STATUS
        logs = await _logs(db)
        assert logs[0]["level"] == "warning"
    _run(body, tmp_path, monkeypatch)


def test_sse_event_published(tmp_path, monkeypatch):
    async def body(orch, db, sse, dispatched):
        await _call(orch, skill_result("success"))
        events = [e for e, _ in sse if e == "ticket_status_changed"]
        assert events, "没有发 ticket_status_changed，前端不会刷新"
        payload = next(p for e, p in sse if e == "ticket_status_changed")
        assert payload["to"] == SUCCESS_STATUS
        assert payload["agent"] == "SkillAgent"
    _run(body, tmp_path, monkeypatch)


def test_next_stage_dispatched(tmp_path, monkeypatch):
    """必须自己触发下一阶段。

    这个分支 early-return 了，拿不到函数末尾的通用收尾逻辑。不自己派单的话
    skill 链会在第一个 stage 之后停住，只能等 30s 的 poll_loop 兜底。
    """
    async def body(orch, db, sse, dispatched):
        await _call(orch, skill_result("success"))
        assert dispatched == [TICKET_ID]
    _run(body, tmp_path, monkeypatch)


# ════════════════════ skipped：跳过而非卡住 ════════════════════

def test_skipped_advances_to_success(tmp_path, monkeypatch):
    """availability 不满足 → 跳到成功态，**不能停在原状态**。

    停住的话那条 rule 会反复命中同一个不可用的 skill（比如依赖的 CLI 没装），
    每次都走一遍 load → is_available → 返回 skipped 的循环。
    """
    async def body(orch, db, sse, dispatched):
        await _call(orch, skill_result("skipped", message="openspec 未安装"))
        assert await _status(db) == SUCCESS_STATUS
        logs = await _logs(db)
        assert logs[0]["action"] == "skip"
        assert logs[0]["level"] == "warning"
    _run(body, tmp_path, monkeypatch)


def test_skipped_still_dispatches_next(tmp_path, monkeypatch):
    async def body(orch, db, sse, dispatched):
        await _call(orch, skill_result("skipped"))
        assert dispatched == [TICKET_ID]
    _run(body, tmp_path, monkeypatch)


# ════════════════════ 失败：blocked 且不重试 ════════════════════

def test_budget_exceeded_without_outputs_blocks(tmp_path, monkeypatch):
    async def body(orch, db, sse, dispatched):
        await _call(orch, skill_result(
            "budget_exceeded",
            sop_cfg=sop_config(produces=[{"kind": "draft_article", "glob": "d.md"}]),
            artifacts=[],                      # 什么都没产出
            message="时间上限已达到",
        ))
        assert await _status(db) == TicketStatus.BLOCKED.value
        logs = await _logs(db)
        assert logs[0]["action"] == "blocked"
        assert logs[0]["level"] == "error"
    _run(body, tmp_path, monkeypatch)


def test_blocked_does_not_dispatch(tmp_path, monkeypatch):
    """**刻意不自动重试**。

    skill 是 LLM 自由发挥的，重跑一次就再烧一轮 token，而失败原因
    （prompt 不清 / 工具不可用 / 预算太紧）重跑都解决不了。
    workflow_composer 也因此不给 skill stage 配 reject_goto。

    ⚠️ **规则表里必须放一条 blocked 的规则**，否则测不出代码里的 BLOCKED 判断。
    默认 `fake_rules` 只含 SUCCESS_STATUS，blocked 天然不在表里 ——
    去掉 `and new_status != BLOCKED` 这个条件后测试照样绿（实测过），
    因为派单前的 `if updated["status"] in rules` 把它过滤掉了。
    真实的 default_sop 里有没有 blocked 规则不该是这条不变式的依赖。
    """
    async def body(orch, db, sse, dispatched):
        async def rules_with_blocked(pid, traits_json=None, ticket_type=None):
            return {
                SUCCESS_STATUS: {"agent": "SkillAgent", "action": "next"},
                TicketStatus.BLOCKED.value: {"agent": "DevAgent",
                                             "action": "fix_issues"},
            }
        orch._get_rules_for_project = rules_with_blocked

        await _call(orch, skill_result("budget_exceeded", artifacts=[]))
        assert await _status(db) == TicketStatus.BLOCKED.value
        assert dispatched == [], "blocked 后仍派单 → 无限重试烧 token"
    _run(body, tmp_path, monkeypatch)


def test_unknown_status_blocks(tmp_path, monkeypatch):
    """未知 skill_status 走 blocked 而非静默推进。

    静默推进等于「替没跑完的阶段宣布成功」，下游拿着空产物继续跑
    （TK-20260920-ce79a9 就是这么一路 deployed 的）。
    """
    async def body(orch, db, sse, dispatched):
        await _call(orch, skill_result("weird_new_status"))
        assert await _status(db) == TicketStatus.BLOCKED.value
    _run(body, tmp_path, monkeypatch)


def test_blocked_writes_comment(tmp_path, monkeypatch):
    async def body(orch, db, sse, dispatched):
        await _call(orch, skill_result("budget_exceeded", message="超时了"))
        comments = await db.fetch_all(
            "SELECT content FROM ticket_comments WHERE ticket_id = ?", (TICKET_ID,)
        )
        assert len(comments) == 1
        assert "需人工介入" in comments[0]["content"]
    _run(body, tmp_path, monkeypatch)


# ═══════════ budget_exceeded 豁免：产出齐全就算成功 ═══════════

def test_budget_exceeded_with_all_produces_treated_as_partial(tmp_path, monkeypatch):
    """超预算但 produces 声明的 kind 全拿到了 → 按成功处理。

    理由：`query_engine/engine.py:391` 的 `Budget.check()` 只在**轮与轮之间**
    生效。像 gen_image 这种阻塞几十秒的工具，跑完回来下一轮开头就可能触发
    超时 —— 此时图已经落盘了，判 blocked 等于白烧一次钱。
    """
    async def body(orch, db, sse, dispatched):
        await _call(orch, skill_result(
            "budget_exceeded",
            sop_cfg=sop_config(produces=[
                {"kind": "draft_article", "glob": "d.md"},
                {"kind": "cover_image", "glob": "c.png"},
            ]),
            artifacts=[{"kind": "draft_article"}, {"kind": "cover_image"}],
        ))
        assert await _status(db) == SUCCESS_STATUS
        logs = await _logs(db)
        assert logs[0]["action"] == "complete"
        assert logs[0]["level"] == "warning"       # 按 partial 记
    _run(body, tmp_path, monkeypatch)


def test_budget_exceeded_with_partial_produces_still_blocks(tmp_path, monkeypatch):
    """只拿到一部分 → 不豁免。豁免条件是「声明的全部拿到」。"""
    async def body(orch, db, sse, dispatched):
        await _call(orch, skill_result(
            "budget_exceeded",
            sop_cfg=sop_config(produces=[
                {"kind": "draft_article", "glob": "d.md"},
                {"kind": "cover_image", "glob": "c.png"},
            ]),
            artifacts=[{"kind": "draft_article"}],
        ))
        assert await _status(db) == TicketStatus.BLOCKED.value
    _run(body, tmp_path, monkeypatch)


def test_produces_satisfied_requires_declaration():
    """没有 produces 声明（老 skill）→ 不豁免。

    无从判断是否齐全，宁可按失败处理交人工。
    """
    f = TicketOrchestrator._skill_produces_satisfied
    assert f({"_produces": [{"kind": "a"}]}, [{"kind": "a"}]) is True
    assert f({"_produces": [{"kind": "a"}, {"kind": "b"}]}, [{"kind": "a"}]) is False
    assert f({}, [{"kind": "a"}]) is False
    assert f({"_produces": []}, []) is False
    # 坏条目不该让判断崩
    assert f({"_produces": [None, "x", {"kind": "a"}]}, [{"kind": "a"}]) is True


# ════════════════════ success_status 三级回退 ════════════════════

def test_success_status_from_result_preferred(tmp_path, monkeypatch):
    """优先用回传的 success_status —— 零 DB 查询（compose_sop 单次 53ms）。"""
    async def body(orch, db, sse, dispatched):
        called = []

        async def spy_stage(pid, act, tt=None):
            called.append(act)
            return {"success_status": "SHOULD_NOT_BE_USED"}
        orch._sop_stage_for = spy_stage

        await _call(orch, skill_result("success"))
        assert await _status(db) == SUCCESS_STATUS
        assert called == [], "有回传值却还去查 SOP"
    _run(body, tmp_path, monkeypatch)


def test_success_status_falls_back_to_sop_lookup(tmp_path, monkeypatch):
    """回传缺失时反查 SOP（兼容手工构造的 context）。"""
    async def body(orch, db, sse, dispatched):
        async def stage(pid, act, tt=None):
            return {"success_status": "from_sop_done"}
        orch._sop_stage_for = stage

        async def rules(pid, traits_json=None, ticket_type=None):
            return {}
        orch._get_rules_for_project = rules

        res = skill_result("success", success_status="")
        res["sop_config"] = {"skill_id": SKILL_ID}      # 没有 _success_status
        await _call(orch, res)
        assert await _status(db) == "from_sop_done"
    _run(body, tmp_path, monkeypatch)


def test_success_status_last_resort_convention(tmp_path, monkeypatch):
    """两处都拿不到 → 按 `{stage_id}_done` 约定推导。

    action 形如 `skill_demo_draft`（见 workflow_composer._stage_action），
    去掉前缀即 stage_id。
    """
    async def body(orch, db, sse, dispatched):
        async def rules(pid, traits_json=None, ticket_type=None):
            return {}
        orch._get_rules_for_project = rules

        res = skill_result("success", success_status="")
        res["sop_config"] = {}
        await _call(orch, res)
        assert await _status(db) == SUCCESS_STATUS       # demo_draft_done
    _run(body, tmp_path, monkeypatch)


# ════════════════════ 容错 ════════════════════

def test_handles_result_without_optional_fields(tmp_path, monkeypatch):
    """手工构造的最小 result 不该让分支崩。

    真实场景：有人直接调 SkillAgent 而不经过 workflow_composer 的 stage。
    """
    async def body(orch, db, sse, dispatched):
        await _call(orch, {"status": "success", "skill_status": "success"})
        assert await _status(db) == SUCCESS_STATUS
    _run(body, tmp_path, monkeypatch)


def test_same_status_does_not_redispatch(tmp_path, monkeypatch):
    """success_status 恰好等于当前状态时不再派单 —— 防自己触发死循环。"""
    async def body(orch, db, sse, dispatched):
        await _call(orch, skill_result("success"), current_status=SUCCESS_STATUS)
        assert dispatched == []
    _run(body, tmp_path, monkeypatch, initial_status=SUCCESS_STATUS)
