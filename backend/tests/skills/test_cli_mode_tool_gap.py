"""CLI 模式下 skill 工具的可用性 —— 缺陷与修复的完整记录。

## 缺陷（仍然存在于 QueryEngine）

`QueryEngine.run` 的 CLI 分支**根本不传 tools**：
  1. `LLMClient._call_cli_stream` 的签名里没有 tools
  2. CLI 分支（165 行）里 `tools` 出现 0 次
  3. `tools` 唯一的消费者是 API 分支的 `_call_anthropic_tools_stream`

这部分**没修**，也不打算在 QueryEngine 层修 —— CLI 的工具循环由 CLI 自己
控制（见 docs/20260802 §六.5），ADS 没法把 Python 侧的 callable 塞进去。

## 修复：skill_io MCP server

CLI 能命名调用的只有 MCP 工具。`skills/skill_io_mcp_server.py` 把 skill 的
builtin 工具（write_file / read_file / gen_image）包成 MCP，由
`llm_client._build_settings_args` 在 `_llm_ctx.skill_io` 非空时条件注入。

关键设计：**LLM 不碰路径**。产出目录通过 `SKILL_OUTPUT_ROOT` 环境变量传给
MCP server 进程，LLM 只给文件名。这正是原生 Write 出问题的地方 ——
它的相对路径基于 cwd(=仓库根)，而产出目录在 `artifacts/{req}/{ticket}/{kind}/`。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md
前作 §六.5：docs/20260802_01_通用Skill执行框架SkillRunner设计方案.md
"""
import inspect
import json
import re
from pathlib import Path

import pytest

from llm_client import LLMClient, _llm_ctx, set_skill_io_context
from query_engine.engine import QueryEngine
from skills.executable_loader import load_executable_skill
from skills.runner import SkillRunner

pytestmark = pytest.mark.real_builtin_skills

BACKEND = Path(__file__).resolve().parents[2]
MCP_SERVER = BACKEND / "skills" / "skill_io_mcp_server.py"


@pytest.fixture(autouse=True)
def _clean_skill_io():
    """每个用例前后清 skill_io 上下文。

    它是 contextvar，不清会串台 —— 一个用例设的产出目录会被下一个用例
    的 `_build_settings_args` 读到。
    """
    set_skill_io_context()
    yield
    set_skill_io_context()


def _cli_branch_source() -> str:
    src = inspect.getsource(QueryEngine.run)
    start = src.index('if getattr(self.llm, "api_format", "anthropic") == "cli":')
    return src[start:src.index("else:", start)]


def _settings_servers(cli_type="codebuddy", cwd="F:/fake-repo") -> dict:
    """跑一次 _build_settings_args，返回注入的 MCP server 配置。"""
    args, tmp = LLMClient._build_settings_args(cli_type, cwd)
    if not tmp:
        return {}
    try:
        cfg = json.loads(Path(tmp).read_text(encoding="utf-8"))
        return cfg.get("mcpServers") or cfg.get("mcp_servers") or {}
    finally:
        Path(tmp).unlink(missing_ok=True)


# ════════════════ 缺陷本身（未修，也不打算在此层修） ════════════════

def test_cli_stream_still_has_no_tools_param():
    """CLI 分支拿不到 tools —— 这是 MCP 方案存在的前提。

    若哪天它变了（CLI 支持了工具透传），skill_io MCP 就可以退役。
    """
    params = list(inspect.signature(LLMClient._call_cli_stream).parameters)
    assert "tools" not in params, (
        f"_call_cli_stream 现在收 tools 了（{params}）—— "
        f"skill_io MCP 可能不再必要，重新评估"
    )


def test_cli_branch_never_references_tools():
    assert len(re.findall(r"\btools\b", _cli_branch_source())) == 0


def test_tools_only_reach_api_branch():
    src = inspect.getsource(QueryEngine.run)
    assert "current_messages, tools, system" in src, "tools 的传递点变了"


# ════════════════ 修复：MCP server 本体 ════════════════

def test_mcp_server_exists_and_declares_tools():
    """server 文件在位，且声明了四个工具。"""
    assert MCP_SERVER.is_file()
    src = MCP_SERVER.read_text(encoding="utf-8")
    for tool in ("write_output", "read_repo_file", "gen_image", "list_outputs"):
        assert f"async def {tool}(" in src, f"缺工具 {tool}"
    assert src.count("@mcp.tool()") == 4


def test_mcp_server_reads_root_from_env_not_from_llm():
    """**产出目录来自环境变量，不是 LLM 参数** —— 这是整个修复的核心。

    让 LLM 传路径等于把「产出落在哪」的决定权交出去，那正是原生 Write
    出问题的原因。检查 write_output 的签名里没有 path/dir 之类的参数。
    """
    src = MCP_SERVER.read_text(encoding="utf-8")
    assert 'os.environ.get("SKILL_OUTPUT_ROOT"' in src

    sig_line = next(
        l for l in src.splitlines() if l.startswith("async def write_output(")
    )
    for forbidden in ("path", "dir", "root", "output_dir"):
        assert forbidden not in sig_line, (
            f"write_output 的签名里出现了 {forbidden} —— LLM 不该碰路径"
        )
    assert "filename" in sig_line and "content" in sig_line


def test_mcp_server_is_standalone_process():
    """MCP server 走 stdio 独立进程，不能 import backend 模块树。

    唯一的例外是 gen_image —— 它在函数内部按 SKILL_BACKEND_DIR 延迟 import，
    为的是复用 GenImageAction 的参数校验与零字节检测（不想写第二份）。
    """
    src = MCP_SERVER.read_text(encoding="utf-8")
    module_level = src[: src.index("@mcp.tool()")]
    for forbidden in ("from actions", "from skills.", "from database",
                      "from config import"):
        assert forbidden not in module_level, (
            f"模块级 import 了 backend 模块（{forbidden}）—— "
            f"MCP server 是独立进程，启动时 sys.path 里没有 backend"
        )
    assert "SKILL_BACKEND_DIR" in src, "gen_image 需要它来延迟 import"


# ════════════════ 修复：条件注入 ════════════════

def test_not_injected_outside_skill_context():
    """没在跑 skill 时不注入 —— 普通聊天不该看到 write_output。"""
    servers = _settings_servers()
    assert "skill_io" not in servers
    assert "ads-data" in servers, "全局 server 应始终在"


def test_injected_when_skill_context_set():
    set_skill_io_context(
        output_root="F:/fake-repo/artifacts/aaa111/bbb222/content_outline",
        repo="F:/fake-repo",
        allowed_exts=[".md"],
        tools=["write_file"],
    )
    servers = _settings_servers()
    assert "skill_io" in servers
    env = servers["skill_io"]["env"]
    assert env["SKILL_OUTPUT_ROOT"].endswith("content_outline")
    assert env["SKILL_REPO"] == "F:/fake-repo"
    assert env["SKILL_ALLOWED_EXTS"] == ".md"
    assert Path(env["SKILL_BACKEND_DIR"]).name == "backend"


def test_image_subdir_passed_through():
    """`gen_image:images` 的子目录要传到 server，否则图落错位置。"""
    set_skill_io_context(
        output_root="F:/r/out", repo="F:/r", image_subdir="images",
        tools=["gen_image:images"],
    )
    env = _settings_servers()["skill_io"]["env"]
    assert env["SKILL_IMAGE_SUBDIR"] == "images"


def test_cleared_context_stops_injection():
    """清空后不再注入 —— contextvar 不会自动还原，必须显式清。"""
    set_skill_io_context(output_root="F:/r/out", repo="F:/r")
    assert "skill_io" in _settings_servers()
    set_skill_io_context()
    assert "skill_io" not in _settings_servers()


# ════════════════ 修复：SkillRunner 的进出 ════════════════

def test_runner_enters_and_exits_context():
    skill = load_executable_skill("demo-cover")
    runner = SkillRunner(skill)
    ctx = {"repo_path": "F:/r", "req_short": "aaa111", "ticket_short": "bbb222"}
    root = runner._output_root(ctx)

    runner._enter_skill_io_context(root, ctx)
    io = _llm_ctx.skill_io
    assert io is not None
    assert io["output_root"].replace("\\", "/").endswith("cover_image")
    assert io["image_subdir"] == "images", "gen_image:images 的子目录没解析出来"

    runner._exit_skill_io_context()
    assert _llm_ctx.skill_io is None


def test_runner_skips_context_without_output_root():
    """只读 skill（无 outputs.root）不需要 write_output，不该注入。"""
    runner = SkillRunner(load_executable_skill("openspec-validate"))
    runner._enter_skill_io_context(None, {"repo_path": "F:/r"})
    assert _llm_ctx.skill_io is None


def test_execute_clears_context_on_exception():
    """execute 抛异常也要清上下文。

    不清的后果：**同一个事件循环里**后续的调用会带着这个 skill 的产出目录，
    LLM 调 write_output 会把文件写进别的工单的产物目录。

    ⚠️ 断言必须在 **async 函数内部**做。`asyncio.run` 会为协程建一个独立的
    Context，退出后主线程读 contextvar 读到的是旧值 —— 在 run 之后断言
    `skill_io is None` 永远成立，哪怕 execute 真的泄漏了（实测注入
    「去掉 finally 清理」后测试全绿，是假绿）。

    真实场景里 SkillRunner.execute 和后续 LLM 调用在同一个循环里，
    所以污染是会传播的。
    """
    import asyncio

    runner = SkillRunner(load_executable_skill("demo-outline"))

    class BoomEngine:
        def __init__(self, *a, **kw):
            pass

        def run(self, *a, **kw):
            raise RuntimeError("boom")

    async def scenario():
        import query_engine
        original = query_engine.QueryEngine
        query_engine.QueryEngine = BoomEngine
        try:
            res = await runner.execute({
                "repo_path": "F:/fake-repo", "req_short": "aaa111",
                "ticket_short": "bbb222",
            })
        finally:
            query_engine.QueryEngine = original
        # 同一个循环、同一个 Context 里读 —— 这才是真实的污染路径
        return res.status, _llm_ctx.skill_io

    status, leaked = asyncio.run(scenario())
    assert status == "error"
    assert leaked is None, (
        f"异常路径没清 skill_io 上下文，泄漏了: {leaked}"
    )


def test_execute_clears_context_on_success():
    """正常结束同样要清 —— finally 覆盖两条路径。"""
    import asyncio

    runner = SkillRunner(load_executable_skill("demo-outline"))

    class EmptyEngine:
        def __init__(self, *a, **kw):
            pass

        async def run(self, *a, **kw):
            return
            yield          # 让它成为 async generator

    async def scenario():
        import query_engine
        original = query_engine.QueryEngine
        query_engine.QueryEngine = EmptyEngine
        try:
            await runner.execute({
                "repo_path": "F:/fake-repo", "req_short": "aaa111",
                "ticket_short": "bbb222",
            })
        finally:
            query_engine.QueryEngine = original
        return _llm_ctx.skill_io

    assert asyncio.run(scenario()) is None


# ════════════════ 修复：skill body 的 MCP 备选名 ════════════════

@pytest.mark.parametrize("skill_id,expected", [
    ("demo-outline", ["mcp__skill_io__write_output"]),
    ("demo-draft", ["mcp__skill_io__write_output"]),
    ("demo-cover", ["mcp__skill_io__gen_image", "mcp__skill_io__read_repo_file"]),
])
def test_demo_skills_mention_mcp_tool_names(skill_id, expected):
    """body 里要写 MCP 形式的工具名。

    LLM 看不到 ADS 的内部实现，只看 body。CLI 模式下它手里只有
    `mcp__skill_io__*`，body 里只提 `write_file` 会让它找不到工具而改用原生 Write。

    照 openspec-propose 的写法 —— 两种命名都列出来，覆盖 API / CLI 两种模式。
    """
    body = load_executable_skill(skill_id).body
    for name in expected:
        assert name in body, f"{skill_id} 的 body 缺 {name}"


@pytest.mark.parametrize("skill_id", ["demo-outline", "demo-draft", "demo-cover"])
def test_demo_skills_warn_against_native_write(skill_id):
    """body 里要明确禁止原生 Write/Bash。

    这是缺陷的直接后果：原生 Write 的相对路径基于仓库根，写出去的文件
    `_collect_outputs` 扫不到 —— 不警告的话 LLM 会"顺手"用它。
    """
    body = load_executable_skill(skill_id).body
    assert "原生 Write" in body or "原生 Write/Bash" in body, (
        f"{skill_id} 的 body 没警告原生 Write"
    )


def test_openspec_skill_keeps_its_warning():
    """openspec 的同类警告还在（它是本次修复的范本，别改坏了）。"""
    body = load_executable_skill("openspec-propose").body
    assert "Bash" in body
    assert "严禁" in body or "不要用" in body


# ════════════════ 路径落差（缺陷的根因，修复后仍需记住） ════════════════

def test_output_root_differs_from_cli_cwd():
    """skill 产出目录 ≠ CLI 的 cwd —— MCP 方案存在的理由。

    CLI 的 cwd = `projects.git_repo_path`（llm_client.py:1407）。
    原生 Write 写 `outline.md` 落在仓库根；产出目录在 artifacts/ 下三层。
    """
    repo = "F:/fake-repo"
    for skill_id, expect_prefix in (
        ("demo-outline", "artifacts"),
        ("openspec-propose", "openspec"),
    ):
        root = SkillRunner(load_executable_skill(skill_id))._output_root({
            "repo_path": repo, "req_short": "aaa111",
            "ticket_short": "bbb222", "change_id": "add-foo",
        })
        rel = str(root).replace("\\", "/").split("fake-repo/")[-1]
        assert rel.startswith(expect_prefix)
        assert "/" in rel, f"{skill_id} 的产出目录就在仓库根，落差不存在？"
