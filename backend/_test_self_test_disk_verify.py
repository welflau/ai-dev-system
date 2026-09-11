"""
SelfTest 磁盘验证单元测试（盲审修复 P1）

5 用例：
1. flush + verify 全过（文件都在磁盘且大小合理）
2. 文件被删 → verify 失败并点名
3. 文件空（大小 0）但预期 >50 字节 → verify 失败
4. sop_config.verify_disk_files=false → 跳过磁盘验证
5. context 无 project_id → 跳过磁盘验证不崩

运行：cd backend && PYTHONIOENCODING=utf-8 python _test_self_test_disk_verify.py
"""
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch


def _make_fake_git_manager(tmp_root: Path):
    """构造一个假 git_manager，_repo_path 返回 tmp_root 下的子目录；write_file 直接写磁盘"""
    class FakeGitManager:
        def _repo_path(self, project_id: str):
            p = tmp_root / project_id
            p.mkdir(parents=True, exist_ok=True)
            return p

        async def write_file(self, project_id: str, path: str, content: str):
            full = self._repo_path(project_id) / path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")

    return FakeGitManager()


async def test_flush_then_verify_passes():
    from actions.self_test import SelfTestAction
    import git_manager as gm_module

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        fake = _make_fake_git_manager(tmp)
        with patch.object(gm_module, "git_manager", fake):
            action = SelfTestAction()
            files = {
                "index.html": "<html><body>hello world</body></html>" * 5,
                "main.py": "print('hi')\n" * 10,
            }
            await action._flush_files_to_repo("P-1", files)
            result = await action._verify_disk_files("P-1", files)
    assert result["ok"], f"should pass, got: {result}"
    assert "2 个文件已落盘" in result["detail"]
    print("✅ Test 1 flush + verify 全过通过")


async def test_missing_file_fails():
    from actions.self_test import SelfTestAction
    import git_manager as gm_module

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        fake = _make_fake_git_manager(tmp)
        with patch.object(gm_module, "git_manager", fake):
            action = SelfTestAction()
            files = {
                "index.html": "<html>" * 20,
                "ghost.py": "print('should not exist')",
            }
            # 只 flush 第一个
            await action._flush_files_to_repo("P-2", {"index.html": files["index.html"]})
            result = await action._verify_disk_files("P-2", files)
    assert not result["ok"]
    assert "ghost.py" in result["detail"]
    print("✅ Test 2 文件缺失 verify 失败通过")


async def test_empty_file_fails():
    from actions.self_test import SelfTestAction
    import git_manager as gm_module

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        fake = _make_fake_git_manager(tmp)
        with patch.object(gm_module, "git_manager", fake):
            action = SelfTestAction()
            # 正常落一个 + 手动放一个空文件
            files = {
                "normal.py": "print('a' * 200)" * 10,
                "empty.py": "x = 1\n# 这是一个" + "长" * 200 + " 的内容",  # 预期很长
            }
            await action._flush_files_to_repo("P-3", {"normal.py": files["normal.py"]})
            # empty.py 放到磁盘但内容空
            empty_path = fake._repo_path("P-3") / "empty.py"
            empty_path.write_text("", encoding="utf-8")
            result = await action._verify_disk_files("P-3", files)
    assert not result["ok"], f"empty file should fail, got: {result}"
    assert "empty.py" in result["detail"]
    print("✅ Test 3 空文件 verify 失败通过")


async def test_no_project_id_disk_verify_skipped():
    """run() 里如果 project_id 为空，应跳过磁盘 check 6（不调 _verify_disk_files）"""
    from actions.self_test import SelfTestAction

    action = SelfTestAction()
    result = await action.run({
        # 不传 project_id
        "_files": {"index.html": "<html><body>x</body></html>"},
        "ticket_title": "t",
        "module": "backend",  # 不触发截图
    })
    assert result.success
    checks = result.data["self_test"]["checks"]
    check_names = [c["name"] for c in checks]
    assert "磁盘落地" not in check_names, f"无 project_id 时不应跑磁盘检查，实际: {check_names}"
    print("✅ Test 4 无 project_id 跳过磁盘 check 通过")


async def test_opt_out_via_sop_config():
    """sop_config.verify_disk_files=false → 不跑磁盘 check"""
    from actions.self_test import SelfTestAction
    import git_manager as gm_module

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        fake = _make_fake_git_manager(tmp)
        with patch.object(gm_module, "git_manager", fake):
            action = SelfTestAction()
            result = await action.run({
                "project_id": "P-5",
                "_files": {"main.py": "print('hi')" * 10},
                "ticket_title": "t",
                "module": "backend",
                "sop_config": {"verify_disk_files": False},
            })
    assert result.success
    check_names = [c["name"] for c in result.data["self_test"]["checks"]]
    assert "磁盘落地" not in check_names, f"opt-out 时不应跑磁盘检查，实际: {check_names}"
    print("✅ Test 5 SOP opt-out 通过")


async def main():
    await test_flush_then_verify_passes()
    await test_missing_file_fails()
    await test_empty_file_fails()
    await test_no_project_id_disk_verify_skipped()
    await test_opt_out_via_sop_config()
    print("\n🎉 SelfTest 磁盘验证单测全部通过（5/5）")


if __name__ == "__main__":
    asyncio.run(main())
