"""SkillAgent 的输入注入与输出登记。

这是 `produces → consumes` 数据通路在 Agent 层的闭环：
  跑之前 — 确保天然源就位 + 把上游产物查出来注入 run_ctx
  跑之后 — 把 ArtifactOut 登记进 artifacts 表 + 回传给 orchestrator

用真实 SQLite + 真实文件，SkillRunner.execute 打桩（它需要 LLM）。
注入/登记这两段本身不碰 LLM，是纯数据搬运，必须真跑。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.6
"""
import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

import database as database_module
from agents.skill_agent import SkillAgent
from database import SCHEMA_SQL, Database
from skills.runner import ArtifactOut, SkillRunResult

PROJECT_ID = "P1"
REQ_ID = "REQ-20261015-aaa111"
TICKET_ID = "TK-20261015-bbb222"
REQ_SHORT, TICKET_SHORT = "aaa111", "bbb222"


@asynccontextmanager
async def _env(tmp_path):
    """真实库 + 真实仓库目录，把全局 db 指到临时库。

    ArtifactStore 内部 `from database import db` 取模块级单例，只能替换它。
    try/finally 保证 disconnect —— aiosqlite 的 worker 是非守护线程，漏掉会让
    pytest 在退出阶段挂死（见 dev-notes/2026-10-15_04）。
    """
    db_file = tmp_path / "t.db"
    repo = tmp_path / "repo"
    repo.mkdir()

    conn = sqlite3.connect(db_file)
    conn.executescript(SCHEMA_SQL)
    conn.executescript(f"""
        INSERT INTO projects (id, name, traits, git_repo_path, created_at, updated_at)
        VALUES ('{PROJECT_ID}', 'demo', '["pipeline:content"]', '{repo.as_posix()}',
                '2026-10-15T00:00:00Z', '2026-10-15T00:00:00Z');
        INSERT INTO requirements (id, project_id, title, description, created_at, updated_at)
        VALUES ('{REQ_ID}', '{PROJECT_ID}', '需求', '描述',
                '2026-10-15T00:00:00Z', '2026-10-15T00:00:00Z');
        INSERT INTO tickets (id, project_id, requirement_id, title, description,
                             type, module, status, created_at, updated_at)
        VALUES ('{TICKET_ID}', '{PROJECT_ID}', '{REQ_ID}', '写技术博客',
                '讲产物总线', 'feature', 'content', 'pending',
                '2026-10-15T00:00:00Z', '2026-10-15T00:00:00Z');
    """)
    conn.commit()
    conn.close()

    original = database_module.db
    test_db = Database(db_path=str(db_file))
    await test_db.connect()
    database_module.db = test_db
    try:
        yield test_db, repo
    finally:
        database_module.db = original
        await test_db.disconnect()


def _run(body, tmp_path):
    async def main():
        async with _env(tmp_path) as (db, repo):
            return await body(db, repo)
    return asyncio.run(main())


def sop_config(stage_id="demo_draft", *, consumes=(), produces=(), skill_id=None):
    """模拟 workflow_composer.skill_to_stage 产出的 config。"""
    return {
        "skill_id": skill_id or stage_id.replace("_", "-"),
        "_stage_id": stage_id,
        "_success_status": f"{stage_id}_done",
        "_reject_status": f"{stage_id}_failed",
        "_consumes": list(consumes),
        "_produces": list(produces),
    }


def fake_outputs(repo: Path, *specs) -> list:
    """造出真实文件并返回 ArtifactOut 列表（模拟 SkillRunner 的回收结果）。"""
    outs = []
    for kind, filename, content in specs:
        d = repo / "scratch"
        d.mkdir(exist_ok=True)
        p = d / filename
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
        outs.append(ArtifactOut(
            rel_path=filename, abs_path=str(p), kind=kind,
            mime="", size=p.stat().st_size,
            is_binary=isinstance(content, bytes),
        ))
    return outs


# ════════════════════ 输入侧：_prepare_inputs ════════════════════

def test_prepare_inputs_creates_ticket_brief_when_wanted(tmp_path):
    """天然源必须被**主动创建**。

    ticket_brief 在 kinds.yaml 标了 builtin，组装器据此视为「已就绪」才没把
    以它为源的 skill 判缺源剔除。但没人会自动创建它 —— 不在这里补，
    第一个 skill 的 consumes 就落空，整条链从第一步就断。
    """
    async def body(db, repo):
        agent = SkillAgent()
        ctx = await agent._prepare_inputs(
            sop_config("demo_outline", consumes=[{"kind": "ticket_brief"}]),
            project_id=PROJECT_ID, ticket_id=TICKET_ID,
            requirement_id=REQ_ID, repo_path=str(repo),
        )
        entry = ctx["_artifacts"]["ticket_brief"]
        assert entry["path"].endswith("ticket_brief/brief.json")
        brief = json.loads(Path(entry["abs_path"]).read_text(encoding="utf-8"))
        assert brief["title"] == "写技术博客"
        assert brief["project_traits"] == ["pipeline:content"]
        assert ctx["_artifacts_missing"] == []
    _run(body, tmp_path)


def test_prepare_inputs_skips_brief_when_not_consumed(tmp_path):
    """不消费 ticket_brief 的 skill 不该被造一个无用文件。"""
    async def body(db, repo):
        await SkillAgent()._prepare_inputs(
            sop_config("demo_draft", consumes=[{"kind": "content_outline"}]),
            project_id=PROJECT_ID, ticket_id=TICKET_ID,
            requirement_id=REQ_ID, repo_path=str(repo),
        )
        rows = await db.fetch_all(
            "SELECT id FROM artifacts WHERE kind = 'ticket_brief'", ()
        )
        assert rows == []
    _run(body, tmp_path)


def test_prepare_inputs_injects_upstream_artifact(tmp_path):
    """上游 skill 的产出能被下游拿到 —— produces→consumes 通路的核心。"""
    async def body(db, repo):
        from artifacts.store import artifact_store
        await artifact_store.put(
            project_id=PROJECT_ID, ticket_id=TICKET_ID, requirement_id=REQ_ID,
            kind="content_outline", repo_path=str(repo),
            content="# 大纲\n- 一", filename="outline.md",
            produced_by="demo-outline",
        )
        ctx = await SkillAgent()._prepare_inputs(
            sop_config("demo_draft", consumes=[{"kind": "content_outline"}]),
            project_id=PROJECT_ID, ticket_id=TICKET_ID,
            requirement_id=REQ_ID, repo_path=str(repo),
        )
        entry = ctx["_artifacts"]["content_outline"]
        assert entry["produced_by"] == "demo-outline"
        assert "text" not in entry           # 默认 mode=path，不读内容
    _run(body, tmp_path)


def test_prepare_inputs_text_mode_reads_content(tmp_path):
    async def body(db, repo):
        from artifacts.store import artifact_store
        await artifact_store.put(
            project_id=PROJECT_ID, ticket_id=TICKET_ID, requirement_id=REQ_ID,
            kind="content_outline", repo_path=str(repo),
            content="# 大纲\n- 要点", filename="outline.md",
        )
        ctx = await SkillAgent()._prepare_inputs(
            sop_config("demo_draft",
                       consumes=[{"kind": "content_outline", "mode": "text"}]),
            project_id=PROJECT_ID, ticket_id=TICKET_ID,
            requirement_id=REQ_ID, repo_path=str(repo),
        )
        assert "要点" in ctx["_artifacts"]["content_outline"]["text"]
    _run(body, tmp_path)


def test_prepare_inputs_reports_missing_required(tmp_path):
    """缺必需产物时不 abort，而是让 LLM 在 prompt 里看到缺了什么。

    组装期的缺源检查已剔除无 producer 的 skill；运行期还缺通常意味着上游
    skipped 或失败 —— 此时「告诉 LLM」比直接中断更有用。
    """
    async def body(db, repo):
        ctx = await SkillAgent()._prepare_inputs(
            sop_config("demo_draft", consumes=[
                {"kind": "content_outline"},
                {"kind": "style_guide", "required": False},
            ]),
            project_id=PROJECT_ID, ticket_id=TICKET_ID,
            requirement_id=REQ_ID, repo_path=str(repo),
        )
        assert ctx["_artifacts"] == {}
        assert ctx["_artifacts_missing_required"] == ["content_outline"]
    _run(body, tmp_path)


def test_prepare_inputs_no_consumes_returns_empty(tmp_path):
    """老 skill（openspec-*）没有 _consumes → 不注入，不该报错。"""
    async def body(db, repo):
        assert await SkillAgent()._prepare_inputs(
            {"skill_id": "openspec-propose"},
            project_id=PROJECT_ID, ticket_id=TICKET_ID,
            requirement_id=REQ_ID, repo_path=str(repo),
        ) == {}
    _run(body, tmp_path)


def test_prepare_inputs_without_repo_path_returns_empty(tmp_path):
    """没有 repo_path 时产物总线无处落盘 —— 降级为不注入而非崩掉。"""
    async def body(db, repo):
        assert await SkillAgent()._prepare_inputs(
            sop_config("demo_draft", consumes=[{"kind": "content_outline"}]),
            project_id=PROJECT_ID, ticket_id=TICKET_ID,
            requirement_id=REQ_ID, repo_path="",
        ) == {}
    _run(body, tmp_path)


def test_prepare_inputs_degrades_on_store_failure(tmp_path, monkeypatch):
    """注入失败不该让 skill 跑不起来 —— 它是增强，不是前置条件。"""
    async def body(db, repo):
        import artifacts.injector as inj

        async def boom(*a, **kw):
            raise RuntimeError("DB 炸了")
        monkeypatch.setattr(inj, "build_consume_context", boom)

        assert await SkillAgent()._prepare_inputs(
            sop_config("demo_draft", consumes=[{"kind": "content_outline"}]),
            project_id=PROJECT_ID, ticket_id=TICKET_ID,
            requirement_id=REQ_ID, repo_path=str(repo),
        ) == {}
    _run(body, tmp_path)


# ════════════════════ 输出侧：_register_outputs ════════════════════

def test_register_outputs_writes_to_artifacts_table(tmp_path):
    async def body(db, repo):
        outs = fake_outputs(repo, ("draft_article", "draft.md", "# 正文"))
        result = SkillRunResult(status="success", outputs=outs, rounds=3)

        registered = await SkillAgent()._register_outputs(
            result, skill_id="demo-draft", project_id=PROJECT_ID,
            ticket_id=TICKET_ID, requirement_id=REQ_ID,
            repo_path=str(repo), rounds=3,
        )
        assert len(registered) == 1
        assert registered[0]["kind"] == "draft_article"

        row = await db.fetch_one(
            "SELECT * FROM artifacts WHERE kind = 'draft_article'", ()
        )
        assert row["produced_by"] == "demo-draft"
        assert row["content"] is None            # file 存储
        assert row["type"] == "draft_article"     # 双写，老查询可命中
        meta = json.loads(row["metadata"])
        assert meta["rounds"] == 3
    _run(body, tmp_path)


def test_register_outputs_skips_kindless_files(tmp_path, caplog):
    """没有 kind 的产出**不该走到 store**。

    openspec-* 这类老 skill 的四件套不在 x-workflow.produces 里，kind 为空。

    ⚠️ 只断言「registered 里没有它」是不够的：kind 为空时 `validate_kind("")`
    会 raise，被 `_register_outputs` 的 except 捕获，结果和「提前过滤」一样 ——
    实测注入「去掉过滤」后测试全绿，是个假绿。

    真实危害是**日志噪音**：每个老 skill 的每个产出都会触发一次失败的 put +
    一条 WARNING。openspec-propose 一次跑 4 个文件 = 4 条无意义警告，
    真问题会被淹掉。所以这里断言「没有产生任何登记失败的警告」。
    """
    import logging

    async def body(db, repo):
        outs = fake_outputs(
            repo,
            ("draft_article", "draft.md", "x"),
            ("", "proposal.md", "y"),            # 老 skill 的产出
        )
        with caplog.at_level(logging.WARNING, logger="skill_agent"):
            registered = await SkillAgent()._register_outputs(
                SkillRunResult(status="success", outputs=outs),
                skill_id="mixed", project_id=PROJECT_ID, ticket_id=TICKET_ID,
                requirement_id=REQ_ID, repo_path=str(repo), rounds=1,
            )
        assert [r["kind"] for r in registered] == ["draft_article"]
        noisy = [r for r in caplog.records if "登记产物失败" in r.getMessage()]
        assert noisy == [], (
            f"kind 为空的产出被送进了 store，产生 {len(noisy)} 条无意义警告"
        )
    _run(body, tmp_path)


def test_register_outputs_binary_stays_intact(tmp_path):
    """二进制产物字节完好 —— 这是整个产物总线改造的目标。"""
    png = b"\x89PNG\r\n\x1a\n" + bytes(range(256))

    async def body(db, repo):
        outs = fake_outputs(repo, ("cover_image", "cover.png", png))
        registered = await SkillAgent()._register_outputs(
            SkillRunResult(status="success", outputs=outs),
            skill_id="demo-cover", project_id=PROJECT_ID, ticket_id=TICKET_ID,
            requirement_id=REQ_ID, repo_path=str(repo), rounds=1,
        )
        assert registered[0]["mime"] == "image/png"
        row = await db.fetch_one(
            "SELECT path FROM artifacts WHERE kind = 'cover_image'", ()
        )
        assert (repo / row["path"]).read_bytes() == png
    _run(body, tmp_path)


def test_register_outputs_partial_failure_keeps_rest(tmp_path):
    """一个文件登记失败不该让其余的也丢掉。

    stage 的成败由 SkillRunner 的 status 决定，不该被产物登记的意外左右；
    缺失的记录会由下游 consumes 的 _artifacts_missing 自然暴露。
    """
    async def body(db, repo):
        outs = fake_outputs(repo, ("draft_article", "draft.md", "x"))
        # 再塞一个源文件不存在的（put 会 raise）
        outs.append(ArtifactOut(
            rel_path="ghost.md", abs_path=str(repo / "nope" / "ghost.md"),
            kind="content_outline",
        ))
        registered = await SkillAgent()._register_outputs(
            SkillRunResult(status="success", outputs=outs),
            skill_id="demo", project_id=PROJECT_ID, ticket_id=TICKET_ID,
            requirement_id=REQ_ID, repo_path=str(repo), rounds=1,
        )
        assert [r["kind"] for r in registered] == ["draft_article"]
    _run(body, tmp_path)


def test_register_outputs_empty_is_noop(tmp_path):
    async def body(db, repo):
        assert await SkillAgent()._register_outputs(
            SkillRunResult(status="success", outputs=[]),
            skill_id="x", project_id=PROJECT_ID, ticket_id=TICKET_ID,
            requirement_id=REQ_ID, repo_path=str(repo), rounds=0,
        ) == []
    _run(body, tmp_path)


# ════════════════════ 回传形状（orchestrator 的契约） ════════════════════

def test_skipped_result_carries_success_status():
    """availability 不满足时 orchestrator 要「直接跳到成功态，别卡流水线」。

    没有 success_status，orchestrator 只能靠 action 名反查 SOP —— 多一次
    compose_sop（53ms），且 skill 已被卸载时根本查不到。
    """
    r = SkillAgent()._skipped(sop_config("demo_draft"), "demo-draft", "不可用")
    assert r["status"] == "skipped"
    assert r["skill_status"] == "skipped"
    assert r["success_status"] == "demo_draft_done"
    assert r["sop_config"]["_stage_id"] == "demo_draft"


def test_execute_result_shape(tmp_path, monkeypatch):
    """走完整 _run_skill，检查回传字段齐全（orchestrator 分支的输入契约）。"""
    async def body(db, repo):
        from skills import runner as runner_mod
        from skills.executable_loader import ExecutableSkill

        outs = fake_outputs(repo, ("draft_article", "draft.md", "# 正文"))

        monkeypatch.setattr(
            runner_mod.SkillRunner, "is_available",
            lambda self, ctx: _true(),
        )
        monkeypatch.setattr(
            runner_mod.SkillRunner, "execute",
            lambda self, ctx, on_tool=None: _result(outs),
        )
        monkeypatch.setattr(
            "skills.executable_loader.load_executable_skill",
            lambda sid, repo_path="": ExecutableSkill(
                skill_id=sid, name=sid, description="", body="",
                source_path=Path("SKILL.md"),
            ),
        )

        res = await SkillAgent()._run_skill({
            "project_id": PROJECT_ID, "ticket_id": TICKET_ID,
            "requirement_id": REQ_ID, "repo_path": str(repo),
            "sop_config": sop_config(
                "demo_draft",
                consumes=[{"kind": "content_outline", "required": False}],
                produces=[{"kind": "draft_article", "glob": "draft.md"}],
            ),
        })

        assert res["status"] == "success"
        assert res["skill_status"] == "success"
        assert res["success_status"] == "demo_draft_done"
        assert res["skill_id"] == "demo-draft"
        assert res["outputs"] == ["draft.md"]
        assert len(res["artifacts"]) == 1
        assert res["artifacts"][0]["kind"] == "draft_article"
        assert res["sop_config"]["_stage_id"] == "demo_draft"
    _run(body, tmp_path)


async def _true():
    return True


async def _result(outs):
    return SkillRunResult(status="success", outputs=outs, rounds=2,
                          message="done")


def test_missing_skill_id_errors():
    """没有 skill_id 直接 error —— orchestrator 会据此标 blocked。"""
    res = asyncio.run(SkillAgent()._run_skill({"project_id": PROJECT_ID}))
    assert res["status"] == "error"
    assert "skill_id" in res["message"]
