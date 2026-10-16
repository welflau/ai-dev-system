"""skill_io MCP server 的工具行为测试。

直接调 async 函数（不启 MCP stdio 协议）—— 被测的是**工具逻辑**，
协议层由 FastMCP 负责。

server 是独立进程、靠环境变量拿上下文，所以测试要在 import 前设好 env，
并且每个用例用独立的 module 实例（否则模块级常量会串）。
"""
import asyncio
import importlib.util
import json
import os
from pathlib import Path

import pytest

SERVER_PATH = Path(__file__).resolve().parents[2] / "skills" / "skill_io_mcp_server.py"

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(64))


def load_server(**env):
    """按给定 env 加载一份独立的 server 模块实例。

    模块级读 `os.environ`，所以必须先设 env 再 import。每次新建实例是为了
    让不同用例的 SKILL_OUTPUT_ROOT 互不干扰。
    """
    old = {k: os.environ.get(k) for k in (
        "SKILL_OUTPUT_ROOT", "SKILL_REPO", "SKILL_ALLOWED_EXTS",
        "SKILL_IMAGE_SUBDIR", "SKILL_BACKEND_DIR",
    )}
    os.environ.update({k: v for k, v in env.items() if v is not None})
    for k in old:
        if k not in env:
            os.environ.pop(k, None)
    try:
        spec = importlib.util.spec_from_file_location("skill_io_test", SERVER_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture
def env(tmp_path):
    """标准环境：产出目录 + 仓库 + 一个上游文件。"""
    out = tmp_path / "artifacts" / "aaa111" / "bbb222" / "content_outline"
    (tmp_path / "upstream").mkdir(parents=True)
    (tmp_path / "upstream" / "note.md").write_text(
        "# 上游内容\n要点 A", encoding="utf-8"
    )
    (tmp_path / "upstream" / "cover.png").write_bytes(PNG)
    mod = load_server(
        SKILL_OUTPUT_ROOT=str(out),
        SKILL_REPO=str(tmp_path),
        SKILL_ALLOWED_EXTS=".md",
    )
    return mod, out, tmp_path


def run(coro):
    return json.loads(asyncio.run(coro))


# ════════════════════ write_output ════════════════════

def test_write_lands_in_output_root(env):
    """**核心**：LLM 只给文件名，文件落在环境变量指定的产出目录。

    这正是原生 Write 做不到的 —— 它的相对路径基于 cwd(=仓库根)。
    """
    mod, out, repo = env
    r = run(mod.write_output("outline.md", "# 大纲\n- 一"))
    assert r["ok"] is True
    assert (out / "outline.md").read_text(encoding="utf-8") == "# 大纲\n- 一"
    # 不在仓库根
    assert not (repo / "outline.md").exists()


def test_write_creates_dir(env):
    """产出目录可能还不存在（skill 的第一个产出）。"""
    mod, out, _repo = env
    assert not out.exists()
    assert run(mod.write_output("outline.md", "x"))["ok"] is True
    assert out.is_dir()


def test_write_strips_code_fences(env):
    """LLM 爱给 Markdown 套 ```围栏，落盘前要去掉。"""
    mod, out, _ = env
    run(mod.write_output("outline.md", "```markdown\n# 大纲\n```"))
    assert (out / "outline.md").read_text(encoding="utf-8") == "# 大纲"


@pytest.mark.parametrize("bad", [
    "../../../etc/passwd.md",     # 路径穿越
    "sub/outline.md",             # 带目录
    "sub\\outline.md",            # Windows 分隔符
    "outline.exe",                # 扩展名不在白名单
    "outline",                    # 无扩展名
    "out line.md",                # 空格
    "",
])
def test_write_rejects_unsafe_filename(env, bad):
    """**拒绝而非改名**。

    改名会让 produces 的 glob 匹配不上，LLM 以为成功但 `_collect_outputs`
    回收到空 —— stage 判 partial 却看不出原因。
    """
    mod, _out, _repo = env
    r = run(mod.write_output(bad, "x"))
    assert r["ok"] is False
    assert "非法" in r["error"]


def test_write_respects_ext_whitelist(tmp_path):
    """白名单来自 skill 的 outputs.allowed_exts。"""
    out = tmp_path / "out"
    mod = load_server(SKILL_OUTPUT_ROOT=str(out), SKILL_ALLOWED_EXTS=".md,.json")
    assert run(mod.write_output("a.md", "x"))["ok"] is True
    assert run(mod.write_output("b.json", "{}"))["ok"] is True
    assert run(mod.write_output("c.txt", "x"))["ok"] is False


def test_write_defaults_to_md_only(tmp_path):
    """没声明 allowed_exts 时只允许 .md（与 WriteFileAction 的默认一致）。"""
    mod = load_server(SKILL_OUTPUT_ROOT=str(tmp_path / "out"))
    assert run(mod.write_output("a.md", "x"))["ok"] is True
    assert run(mod.write_output("a.json", "{}"))["ok"] is False


def test_write_without_output_root_errors(tmp_path):
    """没有产出目录时明确报错，而不是写到进程 cwd。"""
    mod = load_server(SKILL_REPO=str(tmp_path))
    r = run(mod.write_output("a.md", "x"))
    assert r["ok"] is False
    assert "SKILL_OUTPUT_ROOT" in r["error"]


# ════════════════════ read_repo_file ════════════════════

def test_read_upstream_artifact(env):
    """读上游产物 —— path 是 system prompt 里给的仓库相对路径。"""
    mod, _out, _repo = env
    r = run(mod.read_repo_file("upstream/note.md"))
    assert r["ok"] is True
    assert "要点 A" in r["content"]
    assert r["truncated"] is False


@pytest.mark.parametrize("bad", ["../outside.md", "/etc/passwd", ""])
def test_read_rejects_escape(env, bad):
    mod, _out, _repo = env
    assert run(mod.read_repo_file(bad))["ok"] is False


def test_read_missing_file(env):
    mod, _out, _repo = env
    r = run(mod.read_repo_file("upstream/ghost.md"))
    assert r["ok"] is False
    assert "不存在" in r["error"]


def test_read_binary_says_so(env):
    """二进制文件**明确报错**，不返回乱码。

    返回乱码的话 LLM 会以为自己读到了内容，然后基于垃圾数据往下做。
    """
    mod, _out, _repo = env
    r = run(mod.read_repo_file("upstream/cover.png"))
    assert r["ok"] is False
    assert "UTF-8" in r["error"]
    assert r["size"] == len(PNG)


def test_read_truncates_huge_file(env):
    """大文件截断 —— 不能把 50MB 的 log 塞进 LLM 上下文。"""
    mod, _out, repo = env
    (repo / "upstream" / "big.md").write_text("x" * 100_000, encoding="utf-8")
    r = run(mod.read_repo_file("upstream/big.md"))
    assert r["ok"] is True
    assert r["truncated"] is True
    assert len(r["content"]) < 100_000
    assert r["total_chars"] == 100_000


def test_read_without_repo_errors(tmp_path):
    mod = load_server(SKILL_OUTPUT_ROOT=str(tmp_path / "out"))
    assert run(mod.read_repo_file("a.md"))["ok"] is False


# ════════════════════ list_outputs ════════════════════

def test_list_outputs_after_writes(env):
    mod, out, _repo = env
    run(mod.write_output("a.md", "x"))
    run(mod.write_output("b.md", "yy"))
    r = run(mod.list_outputs())
    assert r["ok"] is True
    assert {f["path"] for f in r["files"]} == {"a.md", "b.md"}
    assert {f["bytes"] for f in r["files"]} == {1, 2}


def test_list_outputs_empty_dir(env):
    """目录还没建时返回空列表 + 说明，不报错。

    LLM 可能先 list 再决定写什么 —— 报错会让它以为出了问题。
    """
    mod, _out, _repo = env
    r = run(mod.list_outputs())
    assert r["ok"] is True
    assert r["files"] == []


# ════════════════════ gen_image ════════════════════

def test_gen_image_rejects_bad_filename(tmp_path):
    """参数校验在加载 GenImageAction 之前 —— 省掉一次无谓的 import。"""
    mod = load_server(SKILL_OUTPUT_ROOT=str(tmp_path / "out"))
    for bad in ("cover.exe", "../cover.png", "sub/cover.png", ""):
        r = run(mod.gen_image("a cat", bad))
        assert r["ok"] is False
        assert "非法" in r["error"]


def test_gen_image_rejects_empty_prompt(tmp_path):
    mod = load_server(SKILL_OUTPUT_ROOT=str(tmp_path / "out"))
    r = run(mod.gen_image("   ", "cover.png"))
    assert r["ok"] is False
    assert "prompt" in r["error"]


def test_gen_image_delegates_to_action(tmp_path, monkeypatch):
    """**复用 GenImageAction**，不在 MCP 侧重写一份参数校验与零字节检测。

    两份实现迟早漂 —— 这里只验证"确实委托了"，具体行为由
    tests/actions/test_gen_image.py 覆盖。
    """
    backend = str(Path(__file__).resolve().parents[2])
    out = tmp_path / "out"
    mod = load_server(
        SKILL_OUTPUT_ROOT=str(out),
        SKILL_IMAGE_SUBDIR="images",
        SKILL_BACKEND_DIR=backend,
    )

    import image_processor as ip
    calls = []

    async def create(req):
        calls.append(req)
        return "t1"

    async def poll(t, e):
        return "https://img/x.png"

    async def download(url, save_dir, filename):
        save_dir.mkdir(parents=True, exist_ok=True)
        (save_dir / filename).write_bytes(PNG)
        return str(save_dir / filename)

    monkeypatch.setattr(ip, "_create_lightai_task", create)
    monkeypatch.setattr(ip, "_poll_lightai_task", poll)
    monkeypatch.setattr(ip, "_download_image", download)
    from config import settings
    monkeypatch.setattr(settings, "LIGHTAI_API_KEY", "k", raising=False)

    r = run(mod.gen_image("a cat on a roof", "cover.png", "1:1", "4K"))
    assert r["ok"] is True
    # subdir 生效
    assert (out / "images" / "cover.png").read_bytes() == PNG
    # 参数透传
    assert calls[0]["aspect_ratio"] == "1:1"
    assert calls[0]["image_size"] == "4K"


def test_gen_image_without_backend_dir_reports_clearly(tmp_path):
    """拿不到 backend 时明说原因 —— 这是部署配置问题，不是生图失败。"""
    mod = load_server(SKILL_OUTPUT_ROOT=str(tmp_path / "out"),
                      SKILL_BACKEND_DIR="/nonexistent")
    r = run(mod.gen_image("a cat", "cover.png"))
    assert r["ok"] is False
    # 要么 import 失败，要么（本进程已有 backend 在 path 时）走到真实流程报缺 key
    assert "GenImageAction" in r["error"] or "LIGHTAI" in r["error"]


# ════════════════════ 返回格式 ════════════════════

def test_all_tools_return_json_with_ok_flag(env):
    """统一 `{"ok": bool, ...}` —— LLM 要能一眼看出成败。"""
    mod, _out, _repo = env
    for coro in (
        mod.write_output("a.md", "x"),
        mod.read_repo_file("upstream/note.md"),
        mod.list_outputs(),
        mod.write_output("bad.exe", "x"),
        mod.read_repo_file("ghost.md"),
    ):
        r = run(coro)
        assert isinstance(r, dict)
        assert "ok" in r
        if r["ok"] is False:
            assert r.get("error"), "失败时必须带 error"
