"""SkillRunResult / ArtifactOut 与产出回收的单测。

核心关注点：**二进制产物不再被读成乱码**。

改造前 `_collect_outputs` 对每个命中文件做
`p.read_text(encoding="utf-8", errors="replace")`，PNG/MP3/MP4 会被逐字节替换成
U+FFFD 塞进内存。skill 链接入生图后每一轮都会踩这个坑。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.7
"""
from pathlib import Path

import pytest

from skills.executable_loader import ExecutableSkill
from skills.runner import ArtifactOut, SkillRunResult, SkillRunner, _TEXT_EXTS

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4


def _skill(globs, root="out") -> ExecutableSkill:
    return ExecutableSkill(
        skill_id="demo", name="demo", description="",
        body="", source_path=Path("SKILL.md"),
        outputs={"root": root, "globs": list(globs)},
    )


def _collect(tmp_path, globs, *, produces=None, root="out"):
    """跑一次 _collect_outputs。produces 走 sop_config._produces（kind 反查用）。"""
    runner = SkillRunner(_skill(globs, root))
    out_root = tmp_path / root
    ctx = {"sop_config": {"_produces": produces}} if produces else {}
    return runner._collect_outputs(ctx, out_root)


# ──────────────────────── ArtifactOut 自身 ────────────────────────

def test_artifact_out_name_from_rel_path():
    a = ArtifactOut(rel_path="images/cover.png", abs_path="/x/images/cover.png")
    assert a.name == "cover.png"
    b = ArtifactOut(rel_path="draft.md", abs_path="/x/draft.md")
    assert b.name == "draft.md"


def test_text_exts_covers_common_doc_formats():
    """skill 产出以 .md 为主；漏掉它会让 text_outputs 整个失效。"""
    for ext in (".md", ".txt", ".json", ".yaml", ".html"):
        assert ext in _TEXT_EXTS
    for ext in (".png", ".mp3", ".mp4", ".bin", ".zip"):
        assert ext not in _TEXT_EXTS


# ──────────────────────── 回收：基本行为 ────────────────────────

def test_collect_returns_list_not_dict(tmp_path):
    """破坏性变更的核心：outputs 的类型从 dict 变成 list。"""
    root = tmp_path / "out"
    root.mkdir()
    (root / "a.md").write_text("A", encoding="utf-8")

    outs = _collect(tmp_path, ["a.md"])
    assert isinstance(outs, list)
    assert len(outs) == 1
    assert isinstance(outs[0], ArtifactOut)


def test_collect_fills_metadata(tmp_path):
    root = tmp_path / "out"
    root.mkdir()
    (root / "draft.md").write_text("hello world", encoding="utf-8")

    out = _collect(tmp_path, ["draft.md"])[0]
    assert out.rel_path == "draft.md"
    assert Path(out.abs_path).is_file()
    assert out.mime == "text/markdown"
    assert out.size == len("hello world")
    assert out.is_binary is False


def test_collect_missing_root_returns_empty(tmp_path):
    """skill 一个文件都没写（或 root 模板渲染错）→ 空列表，不抛。"""
    assert _collect(tmp_path, ["a.md"]) == []


def test_collect_skips_directories(tmp_path):
    """glob 可能命中目录（如 `images/*` 里的子目录）。"""
    root = tmp_path / "out"
    (root / "images" / "sub").mkdir(parents=True)
    (root / "images" / "a.png").write_bytes(PNG_BYTES)

    outs = _collect(tmp_path, ["images/*"])
    assert [o.name for o in outs] == ["a.png"]


def test_collect_multiple_globs(tmp_path):
    root = tmp_path / "out"
    root.mkdir()
    for fn in ("proposal.md", "specs.md", "design.md", "tasks.md"):
        (root / fn).write_text(fn, encoding="utf-8")

    outs = _collect(tmp_path, ["proposal.md", "specs.md", "design.md", "tasks.md"])
    assert len(outs) == 4
    assert {o.rel_path for o in outs} == {
        "proposal.md", "specs.md", "design.md", "tasks.md"
    }


def test_collect_dedups_files_matched_by_multiple_globs(tmp_path):
    """`*.md` 和 `draft.md` 同时声明时，同一文件只登记一次。

    不去重的后果：expected_output_count 的 partial 判定会被虚高的计数骗过
    （声明 2 个 glob、实际只产出 1 个文件，却报「2 个产出，齐了」）。
    """
    root = tmp_path / "out"
    root.mkdir()
    (root / "draft.md").write_text("x", encoding="utf-8")

    outs = _collect(tmp_path, ["draft.md", "*.md"])
    assert len(outs) == 1


# ──────────────────── 二进制：本次改造的核心 ────────────────────

def test_collect_does_not_read_binary_content(tmp_path):
    """PNG 必须只登记元信息，内容原样留在磁盘。"""
    root = tmp_path / "out"
    root.mkdir()
    (root / "cover.png").write_bytes(PNG_BYTES)

    out = _collect(tmp_path, ["cover.png"])[0]
    assert out.is_binary is True
    assert out.mime == "image/png"
    assert out.size == len(PNG_BYTES)
    # 原始字节完好 —— 没有被 errors="replace" 破坏
    assert Path(out.abs_path).read_bytes() == PNG_BYTES


def test_text_outputs_skips_binary(tmp_path):
    """兼容属性只能看到文本文件。

    这正是它「安全」的地方，也是它不完整的地方 —— 新代码该用 outputs 本身。
    """
    root = tmp_path / "out"
    root.mkdir()
    (root / "draft.md").write_text("正文", encoding="utf-8")
    (root / "cover.png").write_bytes(PNG_BYTES)

    result = SkillRunResult(
        status="success", outputs=_collect(tmp_path, ["draft.md", "cover.png"])
    )
    assert len(result.outputs) == 2             # 两个都登记了
    assert set(result.output_paths) == {"draft.md", "cover.png"}
    assert set(result.text_outputs) == {"draft.md"}   # 但只读得到文本那个
    assert result.text_outputs["draft.md"] == "正文"


def test_text_outputs_tolerates_deleted_file(tmp_path):
    """登记后文件被删（人工清理）→ 跳过该条，不整体崩。"""
    root = tmp_path / "out"
    root.mkdir()
    (root / "a.md").write_text("A", encoding="utf-8")
    (root / "b.md").write_text("B", encoding="utf-8")

    result = SkillRunResult(status="success", outputs=_collect(tmp_path, ["*.md"]))
    Path(result.outputs[0].abs_path).unlink()

    texts = result.text_outputs
    assert len(texts) == 1


# ──────────────────────── kind 反查 ────────────────────────

def test_collect_maps_kind_from_produces_glob(tmp_path):
    """x-workflow.produces 的 glob → kind。"""
    root = tmp_path / "out"
    root.mkdir()
    (root / "outline.md").write_text("x", encoding="utf-8")
    (root / "cover.png").write_bytes(PNG_BYTES)

    outs = _collect(
        tmp_path, ["outline.md", "cover.png"],
        produces=[
            {"kind": "content_outline", "glob": "outline.md"},
            {"kind": "cover_image", "glob": "cover.png"},
        ],
    )
    by_name = {o.name: o for o in outs}
    assert by_name["outline.md"].kind == "content_outline"
    assert by_name["cover.png"].kind == "cover_image"


def test_collect_one_glob_many_files_share_kind(tmp_path):
    """`images/*.png` 命中 N 个文件 → 全归同一 kind。

    这是刻意的：一次产出 N 张图不该要求声明 N 条 produces。
    """
    root = tmp_path / "out" / "images"
    root.mkdir(parents=True)
    for i in range(3):
        (root / f"shot{i}.png").write_bytes(PNG_BYTES)

    outs = _collect(
        tmp_path, ["images/*.png"],
        produces=[{"kind": "cover_image", "glob": "images/*.png"}],
    )
    assert len(outs) == 3
    assert {o.kind for o in outs} == {"cover_image"}


def test_collect_kind_empty_without_produces(tmp_path):
    """没有 x-workflow 声明的老 skill（如 openspec-*）→ kind 为空串，不报错。"""
    root = tmp_path / "out"
    root.mkdir()
    (root / "proposal.md").write_text("x", encoding="utf-8")

    assert _collect(tmp_path, ["proposal.md"])[0].kind == ""


def test_collect_ignores_malformed_produces(tmp_path):
    """produces 里的坏条目不该让整次回收失败。"""
    root = tmp_path / "out"
    root.mkdir()
    (root / "a.md").write_text("x", encoding="utf-8")

    outs = _collect(
        tmp_path, ["a.md"],
        produces=[None, "not-a-dict", {"kind": "x"}, {"glob": "y"},
                  {"kind": "content_outline", "glob": "a.md"}],
    )
    assert outs[0].kind == "content_outline"


# ──────────────────────── partial 判定不受影响 ────────────────────────

def test_expected_output_count_still_drives_partial(tmp_path):
    """len(outputs) 的语义在 dict→list 之后不变，partial 判定照常。

    架构上这是 architect.py:197 `ok_count = len(result.outputs)` 能零改动的原因。
    """
    skill = _skill(["proposal.md", "specs.md", "design.md", "tasks.md"])
    assert skill.expected_output_count == 4

    root = tmp_path / "out"
    root.mkdir()
    (root / "proposal.md").write_text("x", encoding="utf-8")
    (root / "specs.md").write_text("x", encoding="utf-8")

    outs = SkillRunner(skill)._collect_outputs({}, root)
    assert len(outs) == 2 < skill.expected_output_count


# ──────────────────── system prompt 里的上游产物 ────────────────────

def test_build_system_renders_upstream_artifacts():
    """`_artifacts` 必须出现在 system 里，且带「用 read_file 自取」的指示。

    不渲染的话 SkillAgent 辛苦注入的上游产物对 LLM 完全不可见 —— 它只会
    按 skill body 凭空编造内容。这是 produces→consumes 通路的最后一环。
    """
    runner = SkillRunner(_skill(["draft.md"]))
    system = runner._build_system({
        "ticket_title": "写博客",
        "_artifacts": {
            "content_outline": {
                "path": "artifacts/aaa111/bbb222/content_outline/outline.md",
                "mime": "text/markdown", "size": 2048,
            }
        },
        "_artifacts_missing": ["style_guide"],
        "_artifacts_missing_required": [],
    })
    assert "上游产物" in system
    assert "outline.md" in system
    assert "read_file" in system
    assert "style_guide" in system


def test_build_system_without_artifacts_has_no_empty_section():
    """老 skill（openspec-*）没有 _artifacts → 不该被塞一个空标题。"""
    runner = SkillRunner(_skill(["proposal.md"]))
    system = runner._build_system({"ticket_title": "x"})
    assert "上游产物" not in system
    assert "缺失的上游产物" not in system
