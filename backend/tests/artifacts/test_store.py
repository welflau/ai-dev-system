"""ArtifactStore 与 consumes injector 的单测。

两者是 `produces → consumes` 数据通路的两端，必须一起验证：
store 写得进去、injector 读得回来、两套存储形态（file / inline）都不漏。

测试用真实 SQLite（tmp_path 下）而非 mock —— COALESCE(kind, type) 这类
SQL 语义是本模块的核心正确性来源，mock 掉等于不测。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.6
"""
import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

import database as database_module
from artifacts.injector import build_consume_context, render_artifacts_prompt
from artifacts.kinds import KindRegistryError
from artifacts.store import (
    ArtifactStore,
    ArtifactStoreError,
    artifact_dir,
)
from database import SCHEMA_SQL, Database

PROJECT_ID = "P1"
REQ_ID = "REQ-20261015-aaa111"
TICKET_ID = "TK-20261015-bbb222"
# 路径里用的是 id 末 6 位
REQ_SHORT, TICKET_SHORT = "aaa111", "bbb222"


@asynccontextmanager
async def _env(tmp_path):
    """建库 + 建仓库目录 + 把全局 db 指到临时库。

    ArtifactStore 内部 `from database import db` 取的是模块级单例，
    所以必须替换 `database.db` 而不是传参。测试结束要还原，否则污染同进程
    其它测试（pytest 默认同进程跑完所有文件）。

    ⚠️ 这里的 try/finally 不只是整洁 —— aiosqlite 的 worker 线程是非守护线程，
    漏掉 disconnect 会让 pytest 进程在退出阶段挂死（无 traceback，见
    dev-notes/2026-10-15_04）。
    """
    db_file = tmp_path / "t.db"
    repo = tmp_path / "repo"
    repo.mkdir()

    conn = sqlite3.connect(db_file)
    conn.executescript(SCHEMA_SQL)
    conn.executescript(f"""
        INSERT INTO projects (id, name, traits, created_at, updated_at)
        VALUES ('{PROJECT_ID}', 'demo', '["pipeline:content"]',
                '2026-10-15T00:00:00Z', '2026-10-15T00:00:00Z');
        INSERT INTO requirements (id, project_id, title, description, created_at, updated_at)
        VALUES ('{REQ_ID}', '{PROJECT_ID}', '需求', '描述',
                '2026-10-15T00:00:00Z', '2026-10-15T00:00:00Z');
        INSERT INTO tickets (id, project_id, requirement_id, title, description,
                             type, module, status, created_at, updated_at)
        VALUES ('{TICKET_ID}', '{PROJECT_ID}', '{REQ_ID}', '写一篇技术博客',
                '讲讲产物总线', 'feature', 'content', 'pending',
                '2026-10-15T00:00:00Z', '2026-10-15T00:00:00Z');
    """)
    conn.commit()
    conn.close()

    original_db = database_module.db
    test_db = Database(db_path=str(db_file))
    await test_db.connect()
    database_module.db = test_db
    try:
        yield test_db, repo
    finally:
        database_module.db = original_db
        await test_db.disconnect()


def _run(coro_fn, tmp_path):
    """跑一个 async 测试体，签名 (db, repo) -> awaitable。"""
    async def main():
        async with _env(tmp_path) as (db, repo):
            return await coro_fn(db, repo)
    return asyncio.run(main())


# ──────────────────────────── 路径约定 ────────────────────────────

def test_artifact_dir_layout(tmp_path):
    """<repo>/artifacts/{req[-6:]}/{ticket[-6:]}/{kind}/"""
    d = artifact_dir(
        requirement_id=REQ_ID, ticket_id=TICKET_ID,
        kind="content_outline", repo_path=str(tmp_path),
    )
    assert d.parts[-4:] == ("artifacts", REQ_SHORT, TICKET_SHORT, "content_outline")


def test_artifact_dir_standalone_ticket(tmp_path):
    """无 requirement_id 的独立工单落到 standalone 段（与 orchestrator:3746 同约定）。"""
    d = artifact_dir(
        requirement_id="", ticket_id=TICKET_ID,
        kind="draft_article", repo_path=str(tmp_path),
    )
    # "standalone"[-6:] == "dalone"
    assert d.parts[-3] == "dalone"


# ──────────────────────────── put 基本行为 ────────────────────────────

def test_put_text_content(tmp_path):
    async def body(db, repo):
        store = ArtifactStore()
        ref = await store.put(
            project_id=PROJECT_ID, ticket_id=TICKET_ID, requirement_id=REQ_ID,
            kind="content_outline", repo_path=str(repo),
            content="# 大纲\n- 一\n- 二\n", filename="outline.md",
            produced_by="demo-outline",
        )
        assert ref.kind == "content_outline"
        assert ref.rel_path == f"artifacts/{REQ_SHORT}/{TICKET_SHORT}/content_outline/outline.md"
        assert Path(ref.abs_path).read_text(encoding="utf-8").startswith("# 大纲")
        assert ref.size > 0
        assert ref.mime == "text/markdown"       # 来自 kinds.yaml 而非扩展名推断

        row = await db.fetch_one("SELECT * FROM artifacts WHERE id = ?", (ref.id,))
        assert row["kind"] == "content_outline"
        assert row["type"] == "content_outline"   # 双写，老查询可命中
        assert row["content"] is None             # file 存储：内容不入库
        assert row["produced_by"] == "demo-outline"
        assert row["size_bytes"] == ref.size
    _run(body, tmp_path)


def test_put_binary_content(tmp_path):
    """二进制产物必须原样落盘 —— 这是改造前 SkillRunner 的核心缺陷。"""
    png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

    async def body(db, repo):
        store = ArtifactStore()
        ref = await store.put(
            project_id=PROJECT_ID, ticket_id=TICKET_ID, requirement_id=REQ_ID,
            kind="cover_image", repo_path=str(repo),
            content=png_header, filename="cover.png",
        )
        assert Path(ref.abs_path).read_bytes() == png_header
        assert ref.mime == "image/png"
        # read_text 对 binary kind 返回空串，而不是乱码
        assert await store.read_text(ref) == ""
    _run(body, tmp_path)


def test_read_text_respects_binary_kind_even_if_decodable(tmp_path):
    """binary 判定必须看 **kinds.yaml 的声明**，而不是「能不能 decode」。

    为什么单独写这条：上一条用的 PNG 魔数（0x89）不是合法 UTF-8，所以即便
    删掉 `spec.binary` 检查，也会被下面的 UnicodeDecodeError 兜底捕获而返回 ""
    —— 测试照样绿（实测注入验证过，是个假绿）。

    这里故意让 cover_image 的内容是**合法 UTF-8 的字节串**。少了声明检查，
    read_text 就会把它当文本返回，于是二进制内容被塞进 LLM 的 prompt。
    真实场景：小尺寸 GIF / 某些 WAV 头部恰好落在 ASCII 区间。
    """
    decodable_bytes = b"GIF89a" + b"pretend-image-bytes"

    async def body(db, repo):
        store = ArtifactStore()
        ref = await store.put(
            project_id=PROJECT_ID, ticket_id=TICKET_ID, requirement_id=REQ_ID,
            kind="cover_image", repo_path=str(repo),
            content=decodable_bytes, filename="cover.png",
        )
        # 前提：这些字节确实能 decode，所以 UnicodeDecodeError 兜底不会生效
        assert Path(ref.abs_path).read_bytes().decode("utf-8") == "GIF89apretend-image-bytes"
        assert await store.read_text(ref) == "", (
            "binary kind 的内容被当文本返回了 —— 声明优先于可解码性"
        )
    _run(body, tmp_path)


def test_put_from_src_path_outside_target_copies(tmp_path):
    async def body(db, repo):
        src = repo / "scratch.md"
        src.write_text("从别处搬来的", encoding="utf-8")
        store = ArtifactStore()
        ref = await store.put(
            project_id=PROJECT_ID, ticket_id=TICKET_ID, requirement_id=REQ_ID,
            kind="draft_article", repo_path=str(repo), src_path=str(src),
        )
        assert Path(ref.abs_path).is_file()
        assert src.is_file(), "源文件应保留（copy 而非 move）"
        assert ref.name == "scratch.md"
    _run(body, tmp_path)


def test_put_from_src_path_already_in_place_no_copy(tmp_path):
    """SkillRunner 的常规路径：x-runner.outputs.root 就渲染成目标目录，
    文件写出来已在位，put 只登记不搬运（避免自己 copy 到自己）。"""
    async def body(db, repo):
        target_dir = artifact_dir(
            requirement_id=REQ_ID, ticket_id=TICKET_ID,
            kind="draft_article", repo_path=str(repo),
        )
        target_dir.mkdir(parents=True)
        f = target_dir / "draft.md"
        f.write_text("就地产出", encoding="utf-8")

        store = ArtifactStore()
        ref = await store.put(
            project_id=PROJECT_ID, ticket_id=TICKET_ID, requirement_id=REQ_ID,
            kind="draft_article", repo_path=str(repo), src_path=str(f),
        )
        assert Path(ref.abs_path) == f.resolve()
        assert f.read_text(encoding="utf-8") == "就地产出"
    _run(body, tmp_path)


# ──────────────────────────── put 的闸门 ────────────────────────────

def test_put_rejects_unregistered_kind(tmp_path):
    """第 2 道闸（kinds.py）。"""
    async def body(db, repo):
        with pytest.raises(KindRegistryError, match="未注册"):
            await ArtifactStore().put(
                project_id=PROJECT_ID, ticket_id=TICKET_ID,
                kind="made_up_kind", repo_path=str(repo), content="x",
            )
    _run(body, tmp_path)


def test_put_rejects_inline_kind(tmp_path):
    """inline kind 的内容该在 artifacts.content 列，不能走文件存储。

    不拦的后果：老读取方 `WHERE type='prd'` 取 content 会读到 NULL，
    表面「产出成功」实则下游拿不到任何东西。
    """
    async def body(db, repo):
        with pytest.raises(ArtifactStoreError, match="inline"):
            await ArtifactStore().put(
                project_id=PROJECT_ID, ticket_id=TICKET_ID,
                kind="prd", repo_path=str(repo), content="x",
            )
    _run(body, tmp_path)


def test_put_rejects_both_or_neither_source(tmp_path):
    async def body(db, repo):
        store = ArtifactStore()
        with pytest.raises(ArtifactStoreError, match="二选一|只能"):
            await store.put(
                project_id=PROJECT_ID, ticket_id=TICKET_ID,
                kind="content_outline", repo_path=str(repo),
            )
        with pytest.raises(ArtifactStoreError, match="二选一|只能"):
            await store.put(
                project_id=PROJECT_ID, ticket_id=TICKET_ID,
                kind="content_outline", repo_path=str(repo),
                content="x", src_path=str(repo / "a.md"),
            )
    _run(body, tmp_path)


def test_put_sanitizes_traversal_filename(tmp_path):
    """filename 来自 LLM（produces glob 命中的文件名），不可信。

    `../../etc/passwd` 必须被削成 `passwd` 落在目标目录内，
    而不是真的写到仓库外。
    """
    async def body(db, repo):
        ref = await ArtifactStore().put(
            project_id=PROJECT_ID, ticket_id=TICKET_ID, requirement_id=REQ_ID,
            kind="draft_article", repo_path=str(repo),
            content="x", filename="../../../etc/passwd",
        )
        assert ref.rel_path.startswith(f"artifacts/{REQ_SHORT}/{TICKET_SHORT}/")
        assert ref.rel_path.endswith("/passwd")
        assert ".." not in ref.rel_path
    _run(body, tmp_path)


def test_put_rejects_bad_repo_path(tmp_path):
    async def body(db, repo):
        with pytest.raises(ArtifactStoreError, match="repo_path"):
            await ArtifactStore().put(
                project_id=PROJECT_ID, ticket_id=TICKET_ID,
                kind="content_outline", repo_path=str(tmp_path / "nope"),
                content="x",
            )
    _run(body, tmp_path)


def test_put_rejects_missing_src_file(tmp_path):
    async def body(db, repo):
        with pytest.raises(ArtifactStoreError, match="源文件不存在"):
            await ArtifactStore().put(
                project_id=PROJECT_ID, ticket_id=TICKET_ID,
                kind="content_outline", repo_path=str(repo),
                src_path=str(repo / "ghost.md"),
            )
    _run(body, tmp_path)


# ──────────────────────────── list / get ────────────────────────────

def test_list_by_ticket_and_kind(tmp_path):
    async def body(db, repo):
        store = ArtifactStore()
        for kind, fn in (("content_outline", "o.md"), ("draft_article", "d.md")):
            await store.put(
                project_id=PROJECT_ID, ticket_id=TICKET_ID, requirement_id=REQ_ID,
                kind=kind, repo_path=str(repo), content="x", filename=fn,
            )
        all_refs = await store.list(ticket_id=TICKET_ID, repo_path=str(repo))
        assert {r.kind for r in all_refs} == {"content_outline", "draft_article"}

        one = await store.list(
            ticket_id=TICKET_ID, kinds=["draft_article"], repo_path=str(repo)
        )
        assert len(one) == 1 and one[0].kind == "draft_article"
    _run(body, tmp_path)


def test_list_latest_per_kind_picks_newest(tmp_path):
    """返工重跑会在同路径覆盖文件并插新行 —— latest_per_kind 必须取最新那条。"""
    async def body(db, repo):
        store = ArtifactStore()
        first = await store.put(
            project_id=PROJECT_ID, ticket_id=TICKET_ID, requirement_id=REQ_ID,
            kind="draft_article", repo_path=str(repo),
            content="v1", filename="draft.md",
        )
        await db.update(
            "artifacts", {"created_at": "2026-10-15T00:00:00Z"},
            "id = ?", (first.id,),
        )
        second = await store.put(
            project_id=PROJECT_ID, ticket_id=TICKET_ID, requirement_id=REQ_ID,
            kind="draft_article", repo_path=str(repo),
            content="v2", filename="draft.md",
        )
        await db.update(
            "artifacts", {"created_at": "2026-10-15T09:00:00Z"},
            "id = ?", (second.id,),
        )

        assert len(await store.list(ticket_id=TICKET_ID, repo_path=str(repo))) == 2
        latest = await store.list(
            ticket_id=TICKET_ID, latest_per_kind=True, repo_path=str(repo)
        )
        assert len(latest) == 1
        assert latest[0].id == second.id
        assert await store.read_text(latest[0]) == "v2"
    _run(body, tmp_path)


def test_list_includes_legacy_inline_artifacts(tmp_path):
    """老产物 kind 列为 NULL —— 只查 kind 列会漏掉全部 2246 条存量。

    这是 `COALESCE(kind, type)` 存在的理由。
    """
    async def body(db, repo):
        await db.insert("artifacts", {
            "id": "ART-legacy", "project_id": PROJECT_ID,
            "requirement_id": REQ_ID, "ticket_id": TICKET_ID,
            "type": "prd", "name": "PRD - x",
            "content": json.dumps({"story": "作为用户…"}, ensure_ascii=False),
            "created_at": "2026-10-14T00:00:00Z",
        })
        store = ArtifactStore()

        refs = await store.list(
            ticket_id=TICKET_ID, kinds=["prd"], repo_path=str(repo)
        )
        assert len(refs) == 1
        ref = refs[0]
        assert ref.kind == "prd"            # 从 type 回退来的
        assert ref.is_inline
        text = await store.read_text(ref)
        assert "作为用户" in text

        # include_legacy=False 时应被排除
        assert await store.list(
            ticket_id=TICKET_ID, kinds=["prd"], repo_path=str(repo),
            include_legacy=False,
        ) == []
    _run(body, tmp_path)


def test_list_requires_a_scope(tmp_path):
    """没有任何过滤条件 = 全表扫描，必须拒绝。"""
    async def body(db, repo):
        with pytest.raises(ArtifactStoreError, match="至少需要"):
            await ArtifactStore().list()
    _run(body, tmp_path)


def test_get_returns_ref(tmp_path):
    async def body(db, repo):
        store = ArtifactStore()
        ref = await store.put(
            project_id=PROJECT_ID, ticket_id=TICKET_ID, requirement_id=REQ_ID,
            kind="content_outline", repo_path=str(repo), content="x",
            filename="o.md",
        )
        got = await store.get(ref.id, repo_path=str(repo))
        assert got is not None and got.id == ref.id and got.kind == ref.kind
        assert await store.get("ART-nope") is None
    _run(body, tmp_path)


def test_read_text_handles_missing_file(tmp_path):
    """DB 有索引但文件被删（人工清理 artifacts/ 目录）→ 返回空串不崩。"""
    async def body(db, repo):
        store = ArtifactStore()
        ref = await store.put(
            project_id=PROJECT_ID, ticket_id=TICKET_ID, requirement_id=REQ_ID,
            kind="content_outline", repo_path=str(repo), content="x",
            filename="o.md",
        )
        Path(ref.abs_path).unlink()
        assert await store.read_text(ref) == ""
    _run(body, tmp_path)


# ──────────────────────── ticket_brief（天然源） ────────────────────────

def test_put_ticket_brief_creates_source(tmp_path):
    """没有 ticket_brief，所有 consumes 它的 skill 都会因「缺源」被剔除，
    整条链直接空掉。"""
    async def body(db, repo):
        store = ArtifactStore()
        ref = await store.put_ticket_brief(
            project_id=PROJECT_ID, ticket_id=TICKET_ID,
            requirement_id=REQ_ID, repo_path=str(repo),
        )
        assert ref is not None and ref.kind == "ticket_brief"
        brief = json.loads(Path(ref.abs_path).read_text(encoding="utf-8"))
        assert brief["title"] == "写一篇技术博客"
        assert brief["description"] == "讲讲产物总线"
        assert brief["type"] == "feature"
        assert brief["project_traits"] == ["pipeline:content"]
    _run(body, tmp_path)


def test_put_ticket_brief_is_idempotent(tmp_path):
    """返工重跑时需求快照不应变化，也不该堆出一串重复行。"""
    async def body(db, repo):
        store = ArtifactStore()
        a = await store.put_ticket_brief(
            project_id=PROJECT_ID, ticket_id=TICKET_ID,
            requirement_id=REQ_ID, repo_path=str(repo),
        )
        b = await store.put_ticket_brief(
            project_id=PROJECT_ID, ticket_id=TICKET_ID,
            requirement_id=REQ_ID, repo_path=str(repo),
        )
        assert a.id == b.id
        rows = await db.fetch_all(
            "SELECT id FROM artifacts WHERE ticket_id = ? AND kind = 'ticket_brief'",
            (TICKET_ID,),
        )
        assert len(rows) == 1
    _run(body, tmp_path)


def test_put_ticket_brief_missing_ticket(tmp_path):
    async def body(db, repo):
        assert await ArtifactStore().put_ticket_brief(
            project_id=PROJECT_ID, ticket_id="TK-ghost", repo_path=str(repo),
        ) is None
    _run(body, tmp_path)


# ──────────────────────── injector：consumes 注入 ────────────────────────

def test_build_consume_context_path_mode(tmp_path):
    """默认 mode=path：只给路径，不读内容（省 token，且二进制也成立）。"""
    async def body(db, repo):
        store = ArtifactStore()
        await store.put(
            project_id=PROJECT_ID, ticket_id=TICKET_ID, requirement_id=REQ_ID,
            kind="content_outline", repo_path=str(repo),
            content="# 大纲", filename="outline.md", produced_by="demo-outline",
        )
        ctx = await build_consume_context(
            ["content_outline"],
            project_id=PROJECT_ID, ticket_id=TICKET_ID,
            repo_path=str(repo), requirement_id=REQ_ID,
        )
        entry = ctx["_artifacts"]["content_outline"]
        assert entry["path"].endswith("content_outline/outline.md")
        assert entry["produced_by"] == "demo-outline"
        assert "text" not in entry
        assert ctx["_artifacts_missing"] == []
    _run(body, tmp_path)


def test_build_consume_context_text_mode(tmp_path):
    async def body(db, repo):
        await ArtifactStore().put(
            project_id=PROJECT_ID, ticket_id=TICKET_ID, requirement_id=REQ_ID,
            kind="content_outline", repo_path=str(repo),
            content="# 大纲\n- 要点", filename="outline.md",
        )
        ctx = await build_consume_context(
            [{"kind": "content_outline", "mode": "text"}],
            project_id=PROJECT_ID, ticket_id=TICKET_ID,
            repo_path=str(repo), requirement_id=REQ_ID,
        )
        assert "要点" in ctx["_artifacts"]["content_outline"]["text"]
    _run(body, tmp_path)


def test_build_consume_context_distinguishes_required(tmp_path):
    """required 与可选的缺失要分开报 —— 前者是异常信号，后者是正常降级。"""
    async def body(db, repo):
        ctx = await build_consume_context(
            [
                "content_outline",                                  # 必需，缺
                {"kind": "style_guide", "required": False},          # 可选，缺
            ],
            project_id=PROJECT_ID, ticket_id=TICKET_ID,
            repo_path=str(repo), requirement_id=REQ_ID,
        )
        assert ctx["_artifacts"] == {}
        assert set(ctx["_artifacts_missing"]) == {"content_outline", "style_guide"}
        assert ctx["_artifacts_missing_required"] == ["content_outline"]
    _run(body, tmp_path)


def test_build_consume_context_falls_back_to_requirement_scope(tmp_path):
    """跨工单共享的产物（如 style_guide）挂在需求上，工单级查不到要回退。"""
    async def body(db, repo):
        other_ticket = "TK-20261015-ccc333"
        await db.insert("tickets", {
            "id": other_ticket, "project_id": PROJECT_ID,
            "requirement_id": REQ_ID, "title": "另一个工单",
            "description": "", "type": "feature", "status": "pending",
            "created_at": "2026-10-15T00:00:00Z",
            "updated_at": "2026-10-15T00:00:00Z",
        })
        await ArtifactStore().put(
            project_id=PROJECT_ID, ticket_id=other_ticket, requirement_id=REQ_ID,
            kind="style_guide", repo_path=str(repo),
            content="语气：克制", filename="style.md",
        )
        ctx = await build_consume_context(
            ["style_guide"],
            project_id=PROJECT_ID, ticket_id=TICKET_ID,     # 本工单没有
            repo_path=str(repo), requirement_id=REQ_ID,
        )
        assert "style_guide" in ctx["_artifacts"]
        assert ctx["_artifacts_missing"] == []
    _run(body, tmp_path)


def test_build_consume_context_consumes_legacy_inline(tmp_path):
    """新 skill 读老产物（如内容 skill 参考 PRD）—— lint 明确允许这个方向。"""
    async def body(db, repo):
        await db.insert("artifacts", {
            "id": "ART-prd1", "project_id": PROJECT_ID,
            "requirement_id": REQ_ID, "ticket_id": TICKET_ID,
            "type": "prd", "name": "PRD",
            "content": "## 用户故事\n作为读者…",
            "created_at": "2026-10-14T00:00:00Z",
        })
        ctx = await build_consume_context(
            [{"kind": "prd", "mode": "text"}],
            project_id=PROJECT_ID, ticket_id=TICKET_ID,
            repo_path=str(repo), requirement_id=REQ_ID,
        )
        assert "作为读者" in ctx["_artifacts"]["prd"]["text"]
    _run(body, tmp_path)


def test_build_consume_context_empty_declaration(tmp_path):
    async def body(db, repo):
        ctx = await build_consume_context(
            [], project_id=PROJECT_ID, ticket_id=TICKET_ID, repo_path=str(repo),
        )
        assert ctx == {"_artifacts": {}, "_artifacts_missing": [],
                       "_artifacts_missing_required": []}
    _run(body, tmp_path)


def test_build_consume_context_skips_malformed_specs(tmp_path):
    """坏声明不该让整个注入崩掉（x-workflow 解析期已 lint 过，这里是兜底）。"""
    async def body(db, repo):
        ctx = await build_consume_context(
            [None, 123, {"no_kind": 1}, "content_outline"],
            project_id=PROJECT_ID, ticket_id=TICKET_ID,
            repo_path=str(repo), requirement_id=REQ_ID,
        )
        assert ctx["_artifacts_missing"] == ["content_outline"]
    _run(body, tmp_path)


# ──────────────────────── prompt 渲染 ────────────────────────

def test_render_prompt_tells_llm_how_to_read():
    """不内联内容时**必须**告诉 LLM 用 read_file —— 否则它会凭空编造。"""
    text = render_artifacts_prompt({
        "_artifacts": {
            "content_outline": {
                "path": "artifacts/aaa111/bbb222/content_outline/outline.md",
                "mime": "text/markdown", "size": 2048,
            }
        },
        "_artifacts_missing": [],
    })
    assert "上游产物" in text
    assert "outline.md" in text
    assert "2.0KB" in text
    assert "read_file" in text


def test_render_prompt_inlines_text_when_present():
    text = render_artifacts_prompt({
        "_artifacts": {
            "content_outline": {
                "path": "p.md", "mime": "text/markdown", "size": 10,
                "text": "# 大纲内容",
            }
        },
        "_artifacts_missing": [],
    })
    assert "# 大纲内容" in text
    assert "read_file" not in text        # 已内联就不必再提示自取


def test_render_prompt_warns_on_missing_required():
    text = render_artifacts_prompt({
        "_artifacts": {},
        "_artifacts_missing": ["content_outline", "style_guide"],
        "_artifacts_missing_required": ["content_outline"],
    })
    assert "缺失的上游产物" in text
    assert "必需" in text
    assert "不要编造" in text


def test_render_prompt_empty_returns_blank():
    """没有产物时返回空串，不要往 system 里塞一个空标题。"""
    assert render_artifacts_prompt({}) == ""
    assert render_artifacts_prompt(
        {"_artifacts": {}, "_artifacts_missing": []}
    ) == ""
