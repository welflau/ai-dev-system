"""`TicketOrchestrator` 转发方法的接线测试。

重构方案 R2 第 3 步把 `TicketOrchestrator` 的一批方法搬到了 `orchestration/` 下按职责
分的模块里，类上留同名方法做转发（方案文档：docs/20261124_01_代码重构方案.md）。
函数体有没有搬错，由搬移核对脚本逐个比对语法树；这里测的是新写出来的那一层转发：

1. 新函数的参数表等于原方法的参数表，前面多一个 `orch`，读库的再多一个 `db`，
   名字、种类、默认值都一样；
2. 转发时每个参数落在同名的位置上，按位置传、按关键字传、只传必填三种调用方式都测；
3. `db` 取的是调用那一刻 `orchestrator` 模块里的 `db`。测试靠
   `monkeypatch.setattr(orchestrator, "db", ...)` 换库，转发时取别的对象就会写到真实库；
4. 返回值原样带回，协程方法仍然是协程方法；
5. 搬走的类常量和模块级函数，从原来的位置还能取到同一个对象。

`_seq_index` 是这一步里函数体有改动的方法（`TicketOrchestrator._STATUS_SUFFIXES`
改成读模块里的 `STATUS_SUFFIXES`），文件末尾给它单独补了特征测试，
搬之前先在原实现上跑过。

表里的行由搬移脚本生成，每搬一组加几行。
"""
import asyncio
import importlib
import inspect

import pytest

import orchestrator as orch_module
from orchestrator import TicketOrchestrator

# (方法名, 模块, 函数名, 种类, 是否传 db)
# --- table start ---
DELEGATES = [
    ("_resolve_phase_entry_status", "rewind", "resolve_phase_entry_status", "async", True),
    ("reset_phases", "rewind", "reset_phases", "async", True),
    ("_sop_status_sequence", "rewind", "sop_status_sequence", "async", True),
    ("_is_forward_jump", "rewind", "is_forward_jump", "async", False),
    ("_seq_index", "rewind", "seq_index", "static", False),
    ("_rewind_ticket_status", "rewind", "rewind_ticket_status", "async", True),
    ("_apply_status_rewind", "rewind", "apply_status_rewind", "async", True),
    ("_load_transition_rules", "sop_rules", "load_transition_rules", "sync", False),
    ("reload_sop", "sop_rules", "reload_sop", "sync", False),
    ("_is_noncode_ticket", "sop_rules", "is_noncode_ticket", "sync", False),
    ("_needs_design_stage", "sop_rules", "needs_design_stage", "sync", False),
    ("_get_rules_for_project", "sop_rules", "get_rules_for_project", "async", True),
    ("_sop_stage_for", "sop_rules", "sop_stage_for", "async", False),
    ("_sop_stages_for", "sop_rules", "sop_stages_for", "async", True),
    ("_sop_success_status_for", "sop_rules", "sop_success_status_for", "async", False),
    ("_invoke_stage_hook", "sop_rules", "invoke_stage_hook", "async", False),
    ("_apply_fragment_closeout", "sop_rules", "apply_fragment_closeout", "async", True),
    ("invalidate_project_rules", "sop_rules", "invalidate_project_rules", "sync", False),
    ("_get_all_actionable_statuses", "sop_rules", "get_all_actionable_statuses", "async", True),
    ("_status_is_executing", "sop_rules", "status_is_executing", "static", False),
]
# (类属性, 模块, 模块里的名字)
CONSTANTS = [
    ("PHASE_ORDER", "rewind", "PHASE_ORDER"),
    ("MAX_RESET_COUNT", "rewind", "MAX_RESET_COUNT"),
    ("_PHASE_ENTRY_STATUS", "rewind", "PHASE_ENTRY_STATUS"),
    ("_STATUS_SUFFIXES", "rewind", "STATUS_SUFFIXES"),
    ("_NONCODE_TICKET_KEYWORDS", "sop_rules", "NONCODE_TICKET_KEYWORDS"),
    ("_UI_KEYWORDS_CN", "sop_rules", "UI_KEYWORDS_CN"),
    ("_UI_KEYWORDS_EN", "sop_rules", "UI_KEYWORDS_EN"),
    ("_WORD_RE", "sop_rules", "WORD_RE"),
    ("_NON_UI_MODULES", "sop_rules", "NON_UI_MODULES"),
    ("_TERMINAL_STATUSES", "sop_rules", "TERMINAL_STATUSES"),
]
# (从 orchestrator 导入的名字, 模块)
REEXPORTS = [
    ("stage_hook_names", "sop_rules"),
    ("rewind_trigger", "sop_rules"),
    ("closeout_log_level", "sop_rules"),
    ("closeout_message", "sop_rules"),
    ("closeout_detail", "sop_rules"),
]
# --- table end ---

P = inspect.Parameter


def _module(name):
    return importlib.import_module("orchestration." + name)


def _method_params(method):
    """原方法的参数，去掉 `self`。"""
    return list(inspect.signature(getattr(TicketOrchestrator, method)).parameters.values())[1:]


def _lead(uses_db):
    return ["orch", "db"] if uses_db else ["orch"]


def _call_with(method, module, func, kind, uses_db, monkeypatch, style):
    """用哨兵对象调一次转发方法，返回（新函数实际收到的参数, 期望收到的参数）。"""
    mod = _module(module)
    impl = getattr(mod, func)
    # 同一个测试里调第二次时，模块上已经是上一次换上去的记录函数
    sig = getattr(impl, "real_signature", None) or inspect.signature(impl)
    orch = TicketOrchestrator.__new__(TicketOrchestrator)
    fake_db, result, seen = object(), object(), {}

    def record(*args, **kwargs):
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        seen["args"] = dict(bound.arguments)
        return result

    async def record_async(*args, **kwargs):
        return record(*args, **kwargs)

    fake = record_async if kind == "async" else record
    fake.real_signature = sig
    monkeypatch.setattr(mod, func, fake)
    monkeypatch.setattr(orch_module, "db", fake_db, raising=False)

    args, kwargs, expect = [], {}, {"orch": orch}
    if uses_db:
        expect["db"] = fake_db
    for p in _method_params(method):
        value = object()
        if p.kind is P.VAR_POSITIONAL:
            if style == "required":
                expect[p.name] = ()
            else:
                args.append(value)
                expect[p.name] = (value,)
        elif p.kind is P.VAR_KEYWORD:
            if style == "required":
                expect[p.name] = {}
            else:
                kwargs["extra_keyword"] = value
                expect[p.name] = {"extra_keyword": value}
        elif style == "required" and p.default is not P.empty:
            expect[p.name] = p.default
        elif p.kind is P.KEYWORD_ONLY or (style == "keyword" and p.kind is P.POSITIONAL_OR_KEYWORD):
            kwargs[p.name] = value
            expect[p.name] = value
        else:
            args.append(value)
            expect[p.name] = value

    out = getattr(orch, method)(*args, **kwargs)
    if kind == "async":
        assert inspect.iscoroutine(out)
        out = asyncio.run(out)
    assert out is result
    return seen["args"], expect


FORWARDED = [row for row in DELEGATES if row[3] != "static"]
STATIC = [row for row in DELEGATES if row[3] == "static"]
_ids = lambda rows: [row[0] for row in rows]  # noqa: E731


def test_table_is_not_empty():
    assert len(DELEGATES) >= 7
    assert len({row[0] for row in DELEGATES}) == len(DELEGATES)


@pytest.mark.parametrize("method, module, func, kind, uses_db", FORWARDED, ids=_ids(FORWARDED))
def test_new_function_has_the_method_signature(method, module, func, kind, uses_db):
    impl = getattr(_module(module), func)
    params = list(inspect.signature(impl).parameters.values())
    lead = _lead(uses_db)
    assert [p.name for p in params[:len(lead)]] == lead
    assert all(p.kind is P.POSITIONAL_OR_KEYWORD and p.default is P.empty for p in params[:len(lead)])
    describe = lambda ps: [(p.name, p.kind, p.default) for p in ps]  # noqa: E731
    assert describe(params[len(lead):]) == describe(_method_params(method))
    is_async = kind == "async"
    assert inspect.iscoroutinefunction(impl) is is_async
    assert inspect.iscoroutinefunction(getattr(TicketOrchestrator, method)) is is_async


@pytest.mark.parametrize("style", ["positional", "keyword", "required"])
@pytest.mark.parametrize("method, module, func, kind, uses_db", FORWARDED, ids=_ids(FORWARDED))
def test_method_forwards_every_argument(method, module, func, kind, uses_db, style, monkeypatch):
    got, expect = _call_with(method, module, func, kind, uses_db, monkeypatch, style)
    assert set(got) == set(expect)
    for name, value in expect.items():
        if isinstance(value, (tuple, dict)) or name not in ("orch", "db"):
            assert got[name] == value, name
        else:
            assert got[name] is value, name


@pytest.mark.parametrize("method, module, func, kind, uses_db", FORWARDED, ids=_ids(FORWARDED))
def test_db_is_read_at_call_time(method, module, func, kind, uses_db, monkeypatch):
    """同一个实例先后两次调用，中间换了 `orchestrator.db`，第二次必须拿到新的。"""
    if not uses_db:
        got, _ = _call_with(method, module, func, kind, uses_db, monkeypatch, "positional")
        assert "db" not in got
        return
    first, _ = _call_with(method, module, func, kind, uses_db, monkeypatch, "positional")
    second, _ = _call_with(method, module, func, kind, uses_db, monkeypatch, "positional")
    assert first["db"] is not second["db"]
    assert second["db"] is orch_module.db


@pytest.mark.parametrize("method, module, func, kind, uses_db", STATIC, ids=_ids(STATIC))
def test_static_method_is_the_module_function(method, module, func, kind, uses_db):
    impl = getattr(_module(module), func)
    raw = inspect.getattr_static(TicketOrchestrator, method)
    assert isinstance(raw, staticmethod) and raw.__func__ is impl
    # 类上和实例上都能直接调，不绑定 self
    assert getattr(TicketOrchestrator, method) is impl
    assert getattr(TicketOrchestrator.__new__(TicketOrchestrator), method) is impl


@pytest.mark.parametrize("attr, module, name", CONSTANTS, ids=[row[0] for row in CONSTANTS])
def test_class_constant_is_the_module_object(attr, module, name):
    assert getattr(TicketOrchestrator, attr) is getattr(_module(module), name)


@pytest.mark.parametrize("name, module", REEXPORTS, ids=[row[0] for row in REEXPORTS])
def test_helper_still_importable_from_orchestrator(name, module):
    assert getattr(orch_module, name) is getattr(_module(module), name)


# ==================== `_seq_index` 特征测试 ====================

SEQ = [
    "pending", "planning_done", "architecture_in_progress", "architecture_done",
    "development_in_progress", "development_done", "acceptance_passed", "testing_done", "deployed",
]


@pytest.mark.parametrize("status, expected", [
    ("pending", 0),                       # 序列里有，直接取下标
    ("development_done", 5),
    ("deployed", 8),
    ("", None),                           # 空状态不参与判断
    (None, None),
    ("deploying", None),                  # 认不出后缀
    ("blocked", None),
    ("review_in_progress", None),         # 认得出后缀，序列里没有这个阶段
    ("acceptance_in_progress", 6),        # 序列里没有，按词根归到同阶段最早的位置
    ("acceptance_rejected", 6),
    ("testing_failed", 7),
    ("development_passed", 4),
    ("architecture_rejected", 2),
    ("planning_in_progress", 1),
    ("_done", None),                      # 词根为空，前缀成了 "_"
    ("deployed_done", 8),                 # 词根本身就是序列里的状态
])
def test_seq_index_current_behaviour(status, expected):
    assert TicketOrchestrator._seq_index(SEQ, status) == expected


def test_seq_index_empty_sequence():
    assert TicketOrchestrator._seq_index([], "development_done") is None
    assert TicketOrchestrator._seq_index([], "pending") is None


def test_seq_index_only_the_first_matching_suffix_is_stripped():
    # "x_done_failed" 先命中 "_failed"，词根是 "x_done"，归到以 "x_done_" 开头或等于 "x_done" 的最早位置
    assert TicketOrchestrator._seq_index(["a", "x_done", "x_done_extra"], "x_done_failed") == 1
    assert TicketOrchestrator._seq_index(["x_done_extra", "x"], "x_done_failed") == 0


def test_seq_index_suffix_table():
    assert TicketOrchestrator._STATUS_SUFFIXES == (
        "_in_progress", "_done", "_passed", "_failed", "_rejected",
    )


def test_seq_index_callable_from_an_instance():
    orch = TicketOrchestrator.__new__(TicketOrchestrator)
    assert orch._seq_index(SEQ, "acceptance_in_progress") == 6
