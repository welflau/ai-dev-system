"""artifact kind 词表与 lint 的单测。

关注点：
  1. 词表自身的结构性约束（命名规范 / storage 合法 / builtin 与 legacy 互斥）
  2. 三道闸里的第 1、2 道（lint_kind_refs / validate_kind）确实会拦下来
  3. 与线上 artifacts.type 的覆盖关系（老产物都登记了，没有灰色地带）

第 3 道闸（扫 SKILL.md 的 CI 防漂测试）等 x-workflow 解析落地后另建文件。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.2
"""
import pytest

from artifacts.kinds import (
    KINDS_FILE,
    KindRegistryError,
    _KIND_RE,
    _parse_kinds,
    builtin_kinds,
    get_kind,
    is_registered,
    lint_kind_refs,
    load_kinds,
    reload_kinds,
    validate_kind,
)


# ──────────────────────── 词表自身的结构约束 ────────────────────────

def test_registry_loads():
    kinds = load_kinds()
    assert kinds, "词表为空"
    assert KINDS_FILE.is_file()


def test_all_kind_names_follow_naming_convention():
    """小写蛇形。拼写变体（Content-Outline / contentOutline）是 kind 漂移的主要来源。"""
    for name in load_kinds():
        assert _KIND_RE.match(name), f"kind '{name}' 不符合 ^[a-z][a-z0-9_]*$"


def test_every_kind_has_description():
    """没有描述的 kind 会被后来者重复发明一个同义词。"""
    for name, spec in load_kinds().items():
        assert spec.description, f"kind '{name}' 缺 description"


def test_exactly_one_builtin_source():
    """目前只有 ticket_brief 是天然源。

    多个 builtin 不是错误，但「源头有几个」是拓扑图的关键性质，
    新增时应当是一个有意识的决定，所以在这里钉住。
    """
    assert builtin_kinds() == {"ticket_brief"}


def test_builtin_kind_is_not_inline():
    """天然源由 ArtifactStore 产出 → 必须是 file 存储。"""
    for name in builtin_kinds():
        assert get_kind(name).storage == "file"


def test_legacy_kinds_are_all_inline():
    """老 Agent 路径的产物全部存在 artifacts.content 列。

    这条不变式是 lint 规则 E2 的前提：legacy ⟹ inline ⟹ 不得被 produces。
    """
    for name, spec in load_kinds().items():
        if spec.legacy:
            assert spec.is_inline, f"legacy kind '{name}' 应为 inline 存储"


def test_binary_kinds_are_file_storage():
    """二进制产物不可能塞进 TEXT 列。"""
    for name, spec in load_kinds().items():
        if spec.binary:
            assert spec.storage == "file", f"binary kind '{name}' 必须 file 存储"


def test_registry_is_cached():
    assert load_kinds() is load_kinds()
    reload_kinds()          # 清缓存不应报错
    assert load_kinds()


# ───────────────────── 解析期校验（词表写错要炸） ─────────────────────

def test_parse_rejects_bad_kind_name():
    with pytest.raises(KindRegistryError, match="命名规范"):
        _parse_kinds({"kinds": {"Content-Outline": {"description": "x"}}})


def test_parse_rejects_bad_storage():
    with pytest.raises(KindRegistryError, match="storage"):
        _parse_kinds({"kinds": {"foo": {"storage": "s3", "description": "x"}}})


def test_parse_rejects_builtin_legacy_conflict():
    """builtin（框架自动产出）与 legacy（老 Agent 产出）语义互斥。"""
    with pytest.raises(KindRegistryError, match="语义冲突"):
        _parse_kinds({
            "kinds": {"foo": {"builtin": True, "legacy": True, "description": "x"}}
        })


def test_parse_rejects_empty_registry():
    with pytest.raises(KindRegistryError, match="kinds"):
        _parse_kinds({})


def test_parse_reports_all_errors_at_once():
    """一次报全部问题，不要改一个发现一个。"""
    with pytest.raises(KindRegistryError) as ei:
        _parse_kinds({"kinds": {
            "BadName": {"description": "x"},
            "also_bad": {"storage": "nope", "description": "y"},
        }})
    assert "2 处问题" in str(ei.value)


# ─────────────────────── 第 2 道闸：写入期 validate ───────────────────────

def test_validate_kind_raises_on_unknown():
    with pytest.raises(KindRegistryError, match="未注册的 artifact kind"):
        validate_kind("totally_made_up")


def test_validate_kind_error_lists_known_kinds():
    """报错要带上已注册清单 —— 多数情况是拼错，给出候选能一眼看出。"""
    with pytest.raises(KindRegistryError) as ei:
        validate_kind("content_outlne")      # 少个 i
    assert "content_outline" in str(ei.value)


def test_validate_kind_returns_spec():
    assert validate_kind("ticket_brief").builtin is True


# ─────────────────────── 第 1 道闸：skill 声明 lint ───────────────────────

def test_lint_accepts_valid_declaration():
    res = lint_kind_refs("demo-draft", ["content_outline"], ["draft_article"])
    assert res.ok
    assert res.errors == []
    assert res.warnings == []


def test_lint_e1_unregistered_kind():
    """拼错的 kind 必须在扫描期就被拦下。

    不拦的后果：下游 consumes 找不到 producer → 静默出局 → 流水线少跑一步，
    没有任何报错。这是本词表存在的首要理由。
    """
    res = lint_kind_refs("x", ["content_outlne"], ["draft_articel"])
    assert not res.ok
    assert len(res.errors) == 2
    assert any("consumes 未注册" in e for e in res.errors)
    assert any("produces 未注册" in e for e in res.errors)


def test_lint_e2_cannot_produce_inline_kind():
    """produces 一个 inline kind 是静默断链。

    ArtifactStore 只写文件；老读取方（actions/write_ux_design.py:58 的
    `WHERE type='prd'` 取 content 列）会读到 NULL。表面上「产出成功」，
    实际下游什么都拿不到。
    """
    res = lint_kind_refs("x", [], ["prd"])
    assert not res.ok
    assert any("inline kind" in e for e in res.errors)


def test_lint_allows_consuming_inline_kind():
    """反向是允许的 —— 新 skill 读老产物（如内容 skill 参考 PRD）合理。

    injector 会从 content 列读 inline kind。
    """
    res = lint_kind_refs("x", ["prd", "ux_design"], ["content_outline"])
    assert res.ok


def test_lint_e3_cannot_produce_builtin_kind():
    """天然源被 skill 覆盖 → 拓扑图的源头出现歧义。"""
    res = lint_kind_refs("x", [], ["ticket_brief"])
    assert not res.ok
    assert any("builtin kind" in e for e in res.errors)


def test_lint_e4_self_loop():
    """同一 kind 既 consumes 又 produces = 自环。

    拓扑排序会检出环并让**整条 skill 链**不组装（方案的降级策略）。
    一个 skill 的笔误拖垮全链，所以在 lint 阶段单独报出来。
    """
    res = lint_kind_refs("x", ["content_outline"], ["content_outline"])
    assert not res.ok
    assert any("自环" in e for e in res.errors)


def test_lint_w1_empty_produces_is_warning_not_error():
    """只读校验类 skill 合法（参考 openspec-validate），但要提示它是叶子节点。"""
    res = lint_kind_refs("x", ["draft_article"], [])
    assert res.ok                      # 不阻止组装
    assert len(res.warnings) == 1
    assert "叶子节点" in res.warnings[0]


def test_lint_empty_declaration_is_ok():
    """完全不声明 kind 的 skill（纯副作用型）不报错。"""
    res = lint_kind_refs("x", [], [])
    assert res.ok


# ─────────────────── 与线上数据的覆盖关系（无灰色地带） ───────────────────

def test_all_observed_legacy_types_are_registered():
    """线上 artifacts.type 的全部取值都要在词表里。

    取值来源（2026-10-15 实测 data/ai_dev_system.db，2246 条）+ 代码里
    `db.insert("artifacts")` 写入的全部字面量。

    不登记的后果：新 skill 想 consumes 老产物时，lint 会把一个**真实存在**
    的 kind 判为「未注册」而让 skill 出局 —— 排查方向会完全跑偏。
    """
    observed = {
        # 库中实际有数据
        "deploy_config", "code", "code_review", "ux_design",
        "prd", "architecture", "art_design", "report",
        # 代码里会写但库中暂无
        "asset_manifest", "document", "html_prototype", "screenshot",
        "test", "ue_content",
    }
    missing = sorted(k for k in observed if not is_registered(k))
    assert missing == [], f"线上存在但词表未登记: {missing}"


def test_new_framework_kinds_are_file_storage():
    """新框架的产物一律落盘 —— 这是产物总线「文件为主 + DB 索引」的前提。"""
    for name in ("ticket_brief", "content_outline", "draft_article",
                 "cover_image", "style_guide"):
        spec = get_kind(name)
        assert spec is not None, f"{name} 未注册"
        assert spec.storage == "file", f"{name} 应为 file 存储"
        assert not spec.legacy
