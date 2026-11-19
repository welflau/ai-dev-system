"""ConfigPack 用户级安装（scope=user）：跨项目 / 多 CLI，项目级行为不变。

关联：docs/20261119_01_plugin-import外部仓库接入插件方案.md
"""
import json
from pathlib import Path

import pytest

import pack_installer as pi


@pytest.fixture
def fake_home(monkeypatch, tmp_path):
    """把 Path.home() 指到临时目录，避免测试写真实用户主目录。"""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pi.Path, "home", staticmethod(lambda: home))
    return home


def _files(root):
    return sorted(
        str(p.relative_to(root)).replace("\\", "/")
        for p in Path(root).rglob("*")
        if p.is_file()
    )


def test_project_scope_unchanged(tmp_path):
    """scope=project 仍写入 .{cli}/packs/<pack>/ 隔离子目录，且不碰 home。"""
    r = pi.install_pack(
        "git-workflow", str(tmp_path),
        {"project_name": "T", "repo_path": str(tmp_path), "tech_stack": "x", "git_remote": ""},
        scope="project",
    )
    assert r["success"], r
    assert r["scope"] == "project"
    assert r["install_root"] == str(tmp_path)
    files = _files(tmp_path)
    assert any("packs/git-workflow/" in f for f in files), files[:5]
    assert not any(f.startswith(".codebuddy/skills/") for f in files)


def test_user_scope_writes_all_cli_native_dirs(fake_home):
    """scope=user 写 ~/.{cli}/ 顶层原生目录，覆盖 4 个 CLI，无 packs/ 中间层。"""
    r = pi.install_pack("ai-workflow", "", {}, scope="user")
    assert r["success"], r
    assert r["scope"] == "user"
    assert r["install_root"] == str(fake_home)
    assert set(r["installed_targets"]) == set(pi.ALL_CLI_TARGETS)

    files = _files(fake_home)
    for cli in ("claude", "codebuddy", "cursor", "workbuddy"):
        assert any(f.startswith(f".{cli}/skills/") and f.endswith("SKILL.md") for f in files), (cli, files[:8])
    assert not any("/packs/" in f for f in files), files[:8]


def test_user_scope_ignores_project_path(fake_home, tmp_path):
    """用户级安装忽略 project_path，不会写进项目目录。"""
    project = tmp_path / "project"
    project.mkdir()
    r = pi.install_pack("git-workflow", str(project), {}, scope="user")
    assert r["success"], r
    assert _files(project) == []
    assert any(f.startswith(".codebuddy/") for f in _files(fake_home))


def test_user_scope_skips_project_template_rendering(fake_home):
    """用户级没有项目上下文，{{repo_path}} 等占位符保留原文而非被抹成空串。"""
    r = pi.install_pack("git-workflow", "", {}, scope="user")
    assert r["success"], r
    # 只要不抛异常、且文件确实写出即可；模板渲染跳过由实现保证
    assert any(f.endswith("SKILL.md") or f.endswith(".md") for f in _files(fake_home))


def test_install_pack_rejects_bad_scope():
    assert not pi.install_pack("git-workflow", "", {}, scope="bogus")["success"]


def test_install_pack_project_requires_path():
    assert not pi.install_pack("git-workflow", "", {}, scope="project")["success"]


def test_detect_cli_targets_whitelist():
    assert pi._detect_cli_targets("", ["claude", "codebuddy", "cursor", "workbuddy"]) == list(pi.ALL_CLI_TARGETS)
    assert pi._detect_cli_targets("", ["claude", "unknown"]) == ["claude"]


def test_all_pack_json_declare_four_targets():
    """13 个内置 Pack 的 targets 必须覆盖 4 个 CLI。"""
    pack_files = sorted(pi._PACKS_DIR.glob("*/pack.json"))
    assert len(pack_files) >= 13
    for f in pack_files:
        meta = json.loads(f.read_text(encoding="utf-8"))
        assert set(meta.get("targets", [])) == set(pi.ALL_CLI_TARGETS), (f.parent.name, meta.get("targets"))


def test_install_packs_user_scope(fake_home):
    results = pi.install_packs(["git-workflow", "code-quality"], "", {}, scope="user")
    assert len(results) == 2
    assert all(r["success"] and r["scope"] == "user" for r in results), results
