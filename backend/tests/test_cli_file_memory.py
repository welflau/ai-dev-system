"""CLI 用户目录记忆文件读取。"""
from pathlib import Path

from cli_file_memory import load_cli_file_memories, repo_path_to_cli_slug


def test_repo_path_to_cli_slug_windows():
    assert repo_path_to_cli_slug(r"F:\A_Works\Kinema") == "f-A_Works-Kinema"
    assert repo_path_to_cli_slug(r"D:\UEProjects\GASP58") == "d-UEProjects-GASP58"


def test_load_kinema_codebuddy_memory_if_present():
    repo = r"F:\A_Works\Kinema"
    mem_dir = Path.home() / ".codebuddy" / "projects" / "f-A_Works-Kinema" / "memory"
    if not mem_dir.is_dir():
        return  # 本机无该项目 CLI 记忆时跳过
    items = load_cli_file_memories(repo, limit=20)
    assert items, "应读到 CodeBuddy memory/*.md"
    assert all(i.get("source") == "codebuddy" for i in items)
    assert all(str(i["id"]).startswith("cli:codebuddy:") for i in items)
    titles = {i["title"] for i in items}
    assert any("GASP58" in t or "Bagins" in t for t in titles)


def test_type_filter_and_query(tmp_path, monkeypatch):
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_text("# Memory Index\n", encoding="utf-8")
    (mem / "foo.md").write_text(
        "---\nname: 引擎 fork\ntype: project\n---\n\n内容含 GASP58\n",
        encoding="utf-8",
    )
    (mem / "bar.md").write_text(
        "---\nname: 用户偏好\ntype: user\n---\n\n喜欢中文注释\n",
        encoding="utf-8",
    )

    def fake_discover(_repo):
        return [("codebuddy", mem)]

    monkeypatch.setattr("cli_file_memory.discover_cli_memory_dirs", fake_discover)
    all_items = load_cli_file_memories("dummy", limit=10)
    assert len(all_items) == 2
    assert load_cli_file_memories("dummy", type_filter="user_profile")[0]["title"] == "用户偏好"
    assert load_cli_file_memories("dummy", query="GASP58")[0]["title"] == "引擎 fork"
