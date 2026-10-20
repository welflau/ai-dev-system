"""仓库文件过滤：按文件名/路径子串匹配，并且不钻进生成目录。"""
from pathlib import Path

from api.repos import _search_files


def test_search_matches_name_and_skips_generated_dirs(tmp_path: Path):
    (tmp_path / "Source").mkdir()
    (tmp_path / "Source" / "HeroCharacter.cpp").write_text("x", encoding="utf-8")
    (tmp_path / "Docs").mkdir()
    (tmp_path / "Docs" / "readme.md").write_text("x", encoding="utf-8")
    skipped = tmp_path / "Intermediate" / "Build"
    skipped.mkdir(parents=True)
    (skipped / "HeroCharacter.tmp").write_text("x", encoding="utf-8")

    hits, _partial, _scanned = _search_files(tmp_path, "hero")
    paths = [h["path"] for h in hits]
    assert "Source/HeroCharacter.cpp" in paths
    assert all("Intermediate" not in p for p in paths)


def test_search_matches_path_segment(tmp_path: Path):
    (tmp_path / "FeaturePacks" / "Fog").mkdir(parents=True)
    (tmp_path / "FeaturePacks" / "Fog" / "a.txt").write_text("x", encoding="utf-8")
    hits, _partial, _scanned = _search_files(tmp_path, "fog")
    paths = [h["path"] for h in hits]
    assert "FeaturePacks/Fog" in paths
    assert "FeaturePacks/Fog/a.txt" in paths
