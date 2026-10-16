"""端到端：一张真工单从 pending 跑完整条 skill 链。

## 与前面所有测试的区别

前 290 个单测验的是**零件**：拓扑排序对不对、产物存得进去吗、
orchestrator 分支会不会推进状态。它们加起来**不等于**「链路真的能跑通」——
零件之间的接缝（stage.config 怎么传到 SkillAgent、ArtifactOut 怎么变成
下一个 skill 的 consumes）只有端到端才看得见。

这里打桩的只有 `SkillRunner.execute`（它要调 LLM）。打桩版本做的事和真
skill 一样：读 `_artifacts` 里的上游内容 → 往 outputs.root 写文件。
**其余全是真的** —— 真 SQLite、真文件、真 compose_sop、真 orchestrator 分支。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §九
"""
import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

import database as database_module
import orchestrator as orch_module
from database import Database
from models import TicketStatus
from orchestrator import TicketOrchestrator
from skills.runner import ArtifactOut, SkillRunResult

PROJECT_ID = "P-demo"
REQ_ID = "REQ-20261015-c0ffee"
TICKET_ID = "TK-20261015-beef01"
REQ_SHORT, TICKET_SHORT = "c0ffee", "beef01"

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(128))

pytestmark = pytest.mark.real_builtin_skills      # 要用真实的 demo-* skill


# ════════════════════ 打桩的 skill 执行 ════════════════════

def _fake_execute_factory(repo: Path, trace: list):
    """模拟 LLM 跑 skill：读上游 → 写产出。

    关键在于它**真的去读 `context["_artifacts"]`** —— 如果 consumes 注入
    没生效，这里就拿不到上游内容，产出会退化成占位文本，断言会抓到。
    """
    async def fake_execute(self, context, on_tool=None):
        skill_id = self.skill.skill_id
        out_root = self._output_root(context)
        out_root.mkdir(parents=True, exist_ok=True)
        arts = context.get("_artifacts") or {}
        trace.append({
            "skill_id": skill_id,
            "out_root": str(out_root),
            "upstream_kinds": sorted(arts),
            "upstream_text": {k: (v.get("text") or "")[:80] for k, v in arts.items()},
            "missing": list(context.get("_artifacts_missing") or []),
        })

        if skill_id == "demo-outline":
            brief = arts.get("ticket_brief", {}).get("text") or "{}"
            title = json.loads(brief).get("title", "?") if brief.strip() else "?"
            (out_root / "outline.md").write_text(
                f"# {title}\n\n## 章节\n1. 背景 — 要点A / 要点B\n2. 实现 — 要点C\n",
                encoding="utf-8",
            )
        elif skill_id == "demo-draft":
            outline = arts.get("content_outline", {}).get("text") or "(缺大纲)"
            (out_root / "draft.md").write_text(
                f"# 正文\n\n<!-- 基于大纲 -->\n{outline}\n\n实际内容若干。\n",
                encoding="utf-8",
            )
        elif skill_id == "demo-cover":
            draft = arts.get("draft_article", {}).get("text") or ""
            imgs = out_root / "images"
            imgs.mkdir(parents=True, exist_ok=True)
            # 把上游正文长度编进文件名，证明 cover 真读到了 draft
            (imgs / "cover.png").write_bytes(PNG)
            (imgs / "_seen_draft_len.txt").write_text(str(len(draft)), encoding="utf-8")

        outs = self._collect_outputs(context, out_root)
        return SkillRunResult(status="success", outputs=outs, rounds=2,
                              message=f"{skill_id} ok")
    return fake_execute


# ════════════════════ 环境 ════════════════════

@asynccontextmanager
async def _env(tmp_path, monkeypatch):
    db_file = tmp_path / "e2e.db"
    repo = tmp_path / "repo"
    repo.mkdir()

    original_db = database_module.db
    test_db = Database(db_path=str(db_file))
    await test_db.connect()
    await test_db.init_tables()
    database_module.db = test_db
    monkeypatch.setattr(orch_module, "db", test_db, raising=False)

    await test_db.insert("projects", {
        "id": PROJECT_ID, "name": "demo-content",
        "traits": json.dumps(["pipeline:content"]),
        "git_repo_path": str(repo),
        "created_at": "2026-10-15T00:00:00Z", "updated_at": "2026-10-15T00:00:00Z",
    })
    await test_db.insert("requirements", {
        "id": REQ_ID, "project_id": PROJECT_ID,
        "title": "写一篇产物总线的技术博客", "description": "面向工程师",
        "created_at": "2026-10-15T00:00:00Z", "updated_at": "2026-10-15T00:00:00Z",
    })
    await test_db.insert("tickets", {
        "id": TICKET_ID, "project_id": PROJECT_ID, "requirement_id": REQ_ID,
        "title": "产物总线设计与实现", "description": "讲清 file 与 inline 两种存储形态",
        "type": "feature", "module": "content", "status": "pending",
        "created_at": "2026-10-15T00:00:00Z", "updated_at": "2026-10-15T00:00:00Z",
    })

    sse = []

    async def fake_publish(pid, event, payload):
        sse.append((event, payload))
    monkeypatch.setattr(orch_module.event_manager, "publish_to_project", fake_publish)

    from sop.loader import invalidate_sop_cache
    invalidate_sop_cache()

    try:
        yield test_db, repo, sse
    finally:
        database_module.db = original_db
        await test_db.disconnect()
        invalidate_sop_cache()


async def _drive_chain(db, repo, monkeypatch, trace, max_steps=10) -> list:
    """按 SOP 规则手工驱动 skill 链，返回状态轨迹。

    不用 `orchestrator.process_ticket`（它要跑真 Agent 调度、并发池、
    事件总线）。这里只做 orchestrator 做的三件事：查规则 → 跑 SkillAgent
    → 调 `_handle_skill_agent_result`。**规则表来自真实的 compose_sop。**
    """
    from agents.skill_agent import SkillAgent
    from skills import runner as runner_mod
    from sop.loader import compose_sop, sop_to_transition_rules

    monkeypatch.setattr(runner_mod.SkillRunner, "execute",
                        _fake_execute_factory(repo, trace))

    cfg = compose_sop(traits=["pipeline:content"], ticket_type="feature",
                      repo_path=str(repo))
    rules = sop_to_transition_rules(cfg)

    orch = TicketOrchestrator.__new__(TicketOrchestrator)
    orch._HARD_TERMINAL = {
        TicketStatus.BLOCKED.value, TicketStatus.CANCELLED.value,
        TicketStatus.TESTING_DONE.value, TicketStatus.DEPLOYED.value,
        TicketStatus.DONE.value, "completed",
    }

    async def noop_dispatch(pid, tid):
        pass
    orch.process_ticket = noop_dispatch

    async def fake_rules(pid, traits_json=None, ticket_type=None):
        return rules
    orch._get_rules_for_project = fake_rules

    async def fake_stage(pid, act, tt=None):
        for s in cfg["stages"]:
            if s.get("action") == act:
                return s
        return None
    orch._sop_stage_for = fake_stage

    agent = SkillAgent()
    history = []
    for _ in range(max_steps):
        row = await db.fetch_one("SELECT * FROM tickets WHERE id = ?", (TICKET_ID,))
        status = row["status"]
        history.append(status)
        rule = rules.get(status)
        if not rule:
            break
        if rule.get("agent") != "SkillAgent":
            # 非 skill 阶段（content profile 下是 planning / acceptance / deploy）
            # 由真实 Agent 跑，这里不是本次验证对象 —— 直接推到它的成功态。
            #
            # 不能从 pending 直接跳到第一个 skill：那样就跳过了「skill 链接在
            # base_stages 之后」这个事实，等于绕开 relink 的状态链验证。
            stage = next((s for s in cfg["stages"]
                          if s.get("action") == rule["action"]), None)
            nxt = (stage or {}).get("success_status")
            if not nxt:
                break
            await db.update("tickets", {"status": nxt}, "id = ?", (TICKET_ID,))
            continue

        ctx = {
            "project_id": PROJECT_ID, "ticket_id": TICKET_ID,
            "requirement_id": REQ_ID, "repo_path": str(repo),
            "ticket_title": row["title"], "ticket_description": row["description"],
            "req_short": REQ_SHORT, "ticket_short": TICKET_SHORT,
            "sop_config": rule.get("config") or {},
        }
        result = await agent.execute(rule["action"], ctx)
        await orch._handle_skill_agent_result(
            project_id=PROJECT_ID, ticket_id=TICKET_ID, ticket=dict(row),
            requirement_id=REQ_ID, action=rule["action"], result=result,
            result_json=json.dumps(result, ensure_ascii=False),
            current_status=status,
        )
    return history


def _run(body, tmp_path, monkeypatch):
    """跑完整条链，再把 (db, repo, sse, trace, history) 交给 body 断言。

    body 可以是同步函数（纯断言）或 async（需要再查库）。
    """
    async def main():
        async with _env(tmp_path, monkeypatch) as (db, repo, sse):
            trace = []
            history = await _drive_chain(db, repo, monkeypatch, trace)
            out = body(db, repo, sse, trace, history)
            if asyncio.iscoroutine(out):
                out = await out
            return out
    return asyncio.run(main())


# ════════════════════ 验证点 ════════════════════

def test_v1_topological_order(tmp_path, monkeypatch):
    """① 执行顺序 = 拓扑序，不是声明序也不是 priority 序。

    三个 SKILL.md 的 priority 是 cover=90 / draft=50 / outline=20 ——
    **刻意与依赖顺序相反**。只按 priority 排会得出 cover→draft→outline。
    """
    def body(db, repo, sse, trace, history):
        assert [t["skill_id"] for t in trace] == [
            "demo-outline", "demo-draft", "demo-cover",
        ]
    _run(body, tmp_path, monkeypatch)


def test_v2_produces_to_consumes_really_flows(tmp_path, monkeypatch):
    """② **produces → consumes 通路真的传了数据**（整个框架的核心主张）。

    不是「上游产物的路径出现在 context 里」，而是打桩 skill 真的读到了
    上游**内容**：draft 里出现了 outline 写的章节标题。
    """
    def body(db, repo, sse, trace, history):
        by_skill = {t["skill_id"]: t for t in trace}

        assert by_skill["demo-outline"]["upstream_kinds"] == ["ticket_brief"]
        assert "产物总线设计与实现" in by_skill["demo-outline"]["upstream_text"]["ticket_brief"]

        assert "content_outline" in by_skill["demo-draft"]["upstream_kinds"]
        outline_text = by_skill["demo-draft"]["upstream_text"]["content_outline"]
        assert "产物总线设计与实现" in outline_text, "draft 没读到 outline 的内容"

        assert "draft_article" in by_skill["demo-cover"]["upstream_kinds"]

        # 落盘内容的链式传递
        draft = (repo / "artifacts" / REQ_SHORT / TICKET_SHORT
                 / "draft_article" / "draft.md").read_text(encoding="utf-8")
        assert "章节" in draft, "draft.md 里没有 outline 的结构"
    _run(body, tmp_path, monkeypatch)


def test_v3_artifacts_registered_with_kind(tmp_path, monkeypatch):
    """③ artifacts 表：kind 正确、content 为 NULL、path 指向真实文件。"""
    async def body(db, repo, sse, trace, history):
        rows = await db.fetch_all(
            "SELECT * FROM artifacts WHERE ticket_id = ? ORDER BY created_at",
            (TICKET_ID,),
        )
        kinds = [r["kind"] for r in rows]
        assert kinds == ["ticket_brief", "content_outline",
                         "draft_article", "cover_image"], kinds
        for r in rows:
            assert r["content"] is None, f"{r['kind']} 的内容不该入库（file 存储）"
            assert r["type"] == r["kind"], "type/kind 双写失效，老查询会落空"
            assert (repo / r["path"]).is_file(), f"{r['path']} 不存在"
            assert r["size_bytes"] > 0
            assert r["produced_by"], f"{r['kind']} 缺 produced_by"
    _run(body, tmp_path, monkeypatch)


def test_v4_binary_bytes_intact(tmp_path, monkeypatch):
    """④ **PNG 字节完好 + 被正确标记为 binary** —— 产物总线改造的核心目标。

    改造前 `_collect_outputs` 会 `read_text(errors="replace")`，
    PNG 变成一堆 U+FFFD 塞进内存。

    ⚠️ 只断言「字节完好」是不够的：ArtifactStore 用 `shutil.copy2` 复制文件，
    根本不读内容，所以 `is_binary` 标记错了字节照样完好（实测注入
    `is_binary=False` 后全绿，是假绿）。

    真实危害在 `text_outputs` —— 它靠 `is_binary` 决定跳过谁。标记错了就会
    把 PNG 读成字符串。所以这里必须同时验**标记**和**它的下游行为**。
    """
    def body(db, repo, sse, trace, history):
        png = (repo / "artifacts" / REQ_SHORT / TICKET_SHORT
               / "cover_image" / "images" / "cover.png")
        assert png.is_file()
        raw = png.read_bytes()
        assert raw[:8] == b"\x89PNG\r\n\x1a\n", "PNG 字节头被破坏"
        assert raw == PNG

        # 重新回收一次，检查标记本身
        from skills.executable_loader import load_executable_skill
        from skills.runner import SkillRunner, SkillRunResult

        skill = load_executable_skill("demo-cover")
        runner = SkillRunner(skill)
        out_root = (repo / "artifacts" / REQ_SHORT / TICKET_SHORT / "cover_image")
        outs = runner._collect_outputs(
            {"sop_config": {"_produces": [
                {"kind": "cover_image", "glob": "images/*.png"}
            ]}},
            out_root,
        )
        png_out = next(o for o in outs if o.name == "cover.png")
        assert png_out.is_binary is True, "PNG 未被标记为 binary"
        assert png_out.mime == "image/png"

        # 下游行为：text_outputs 必须跳过它，而不是读成乱码
        result = SkillRunResult(status="success", outputs=outs)
        assert "images/cover.png" not in result.text_outputs, (
            "PNG 被 text_outputs 读进内存了"
        )
    _run(body, tmp_path, monkeypatch)


def test_v5_content_pipeline_starts_from_pending(tmp_path, monkeypatch):
    """⑤ pipeline:content 下 base 被裁，工单仍从 pending 正常启动。

    裁剪后首个阶段不再是 planning，若 relink 不强制 trigger_on=pending，
    工单会永久卡死（不报错、不超时）。
    """
    def body(db, repo, sse, trace, history):
        from sop.loader import compose_sop, sop_to_transition_rules
        cfg = compose_sop(traits=["pipeline:content"], ticket_type="feature",
                          repo_path=str(repo))
        ids = [s["id"] for s in cfg["stages"]]
        assert "development" not in ids and "architecture" not in ids
        assert cfg["composed_from_skills"] == [
            "demo_outline", "demo_draft", "demo_cover",
        ]
        assert cfg["stages"][0]["trigger_on"] == "pending"
        assert "pending" in sop_to_transition_rules(cfg)
    _run(body, tmp_path, monkeypatch)


def test_v6_state_chain_no_loop(tmp_path, monkeypatch):
    """⑥ 状态单调推进，没有重复 —— 死循环的直接证据就是状态重复出现。"""
    def body(db, repo, sse, trace, history):
        assert len(history) == len(set(history)), f"状态重复（死循环）: {history}"
        assert history[0] == "pending"
        for sid in ("demo_outline_done", "demo_draft_done", "demo_cover_done"):
            assert sid in history, f"缺状态 {sid}: {history}"
        # 每个 skill 只跑一次
        ran = [t["skill_id"] for t in trace]
        assert len(ran) == len(set(ran)), f"skill 重复执行: {ran}"
    _run(body, tmp_path, monkeypatch)


def test_v7_missing_source_degrades(tmp_path, monkeypatch):
    """⑦ 缺源 → 该 skill 及其下游出局，SOP 其余部分照常。"""
    def body(db, repo, sse, trace, history):
        from skills.executable_loader import discover_workflow_skills
        from sop.workflow_composer import compose_workflow_stages
        import dataclasses
        from skills.executable_loader import ConsumeSpec

        ws = discover_workflow_skills()
        broken = [
            dataclasses.replace(w, consumes=[ConsumeSpec("nonexistent_kind")])
            if w.stage_id == "demo_outline" else w
            for w in ws
        ]
        stages, diag = compose_workflow_stages(
            broken, traits=["pipeline:content"], ticket_type="feature",
        )
        assert stages == [], "缺源的 skill 及其下游应全部出局"
        assert any("无 producer" in d for d in diag)
    _run(body, tmp_path, monkeypatch)


def test_v8_cycle_degrades_to_fragment_sop(tmp_path, monkeypatch):
    """⑧ 成环 → 整条 skill 链不组装，退化成可用的 fragment SOP。"""
    def body(db, repo, sse, trace, history):
        import dataclasses
        from skills.executable_loader import (
            ConsumeSpec, ProduceSpec, discover_workflow_skills,
        )
        from sop.workflow_composer import compose_workflow_stages

        ws = discover_workflow_skills()
        # cover 产出 content_outline → outline→draft→cover→outline 成环
        looped = [
            dataclasses.replace(
                w, produces=[ProduceSpec("content_outline", "images/*.png")]
            ) if w.stage_id == "demo_cover" else w
            for w in ws
        ]
        stages, diag = compose_workflow_stages(
            looped, traits=["pipeline:content"], ticket_type="feature",
        )
        assert stages == []
        assert any("成环" in d or "多个 producer" in d for d in diag)
    _run(body, tmp_path, monkeypatch)


# ════════════════ 额外：产物目录布局 ════════════════

def test_artifact_layout_matches_convention(tmp_path, monkeypatch):
    """落盘路径符合 `<repo>/artifacts/{req}/{ticket}/{kind}/` 约定。

    skill 的 outputs.root 模板和 ArtifactStore 的目录约定必须一致，
    否则 put 会多做一次 copy（功能上没错，但产物会有两份）。
    """
    def body(db, repo, sse, trace, history):
        base = repo / "artifacts" / REQ_SHORT / TICKET_SHORT
        assert (base / "ticket_brief" / "brief.json").is_file()
        assert (base / "content_outline" / "outline.md").is_file()
        assert (base / "draft_article" / "draft.md").is_file()
        assert (base / "cover_image" / "images" / "cover.png").is_file()

        # skill 写的位置就是 store 登记的位置 —— 没有产生副本
        for t in trace:
            assert str(base) in t["out_root"], t
    _run(body, tmp_path, monkeypatch)


def test_optional_consume_missing_is_reported(tmp_path, monkeypatch):
    """demo-draft 声明了可选的 style_guide，没人产出 → 记入 missing 但不阻塞。"""
    def body(db, repo, sse, trace, history):
        draft = next(t for t in trace if t["skill_id"] == "demo-draft")
        assert "style_guide" in draft["missing"]
        assert "content_outline" in draft["upstream_kinds"]
    _run(body, tmp_path, monkeypatch)
