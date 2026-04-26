"""
v0.19.1 ③ 仓库视图优化 —— smoke test

验证：
  1. git_manager.list_branches_enriched(pid) 对当前仓库可用（用当前项目自身作测试）
  2. git_manager.get_commit_detail(pid, sha) 解析 meta + files + patch
  3. 非法 sha 返回 None

用法：
    cd backend && python _test_v019_repo_views.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, ".")


def _banner(msg: str):
    print()
    print("=" * 70)
    print(f"  {msg}")
    print("=" * 70)


async def main():
    passed, failed = 0, 0

    def check(name: str, ok: bool, detail: str = ""):
        nonlocal passed, failed
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {name}" + (f"  -- {detail}" if detail else ""))
        if ok:
            passed += 1
        else:
            failed += 1

    from database import db
    from git_manager import git_manager
    from utils import generate_id, now_iso

    await db.connect()
    await db.init_tables()

    # 用 ai-dev-system 自身作测试仓库（项目根 = D:/A_Works/ai-dev-system）
    pid = generate_id("PRJ")
    repo_path = str(Path(__file__).resolve().parents[1])  # 项目根
    git_manager.set_project_path(pid, repo_path)
    await db.insert("projects", {
        "id": pid,
        "name": "RepoViewsSelfTest",
        "description": "",
        "status": "active",
        "tech_stack": "",
        "config": "{}",
        "git_repo_path": repo_path,
        "git_remote_url": "",
        "traits": "[]",
        "traits_confidence": "{}",
        "preset_id": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })

    # =========== 1. list_branches_enriched ===========
    _banner("1. list_branches_enriched 返回富分支信息")
    branches = await git_manager.list_branches_enriched(pid)
    check("返回非空", len(branches) > 0, f"count={len(branches)}")
    if branches:
        b0 = branches[0]
        check("含 name", bool(b0.get("name")))
        check("含 last_commit_sha", bool(b0.get("last_commit_sha")))
        check("含 last_commit_at", bool(b0.get("last_commit_at")))
        check("含 current 布尔", "current" in b0)
        check("含 ahead/behind 整数",
              isinstance(b0.get("ahead"), int) and isinstance(b0.get("behind"), int))
        # parent 可能为 None（根分支），只要存在即可
        check("parent 字段存在", "parent" in b0)

    # 至少一个分支是 current
    current_count = sum(1 for b in branches if b.get("current"))
    check("恰好 1 个分支 current=True", current_count == 1, f"current_count={current_count}")

    # =========== 2. get_commit_detail 最新一条 ===========
    _banner("2. get_commit_detail 对最新 commit 返回结构化信息")
    logs = await git_manager.get_log(pid, limit=1)
    check("至少一条 commit", len(logs) > 0, f"logs count={len(logs)}")
    if logs:
        sha = logs[0]["hash"]
        detail = await git_manager.get_commit_detail(pid, sha)
        check("detail 非空", detail is not None)
        if detail:
            check("sha 对齐", detail.get("sha") == sha)
            check("有 subject", bool(detail.get("subject")))
            check("有 author", bool(detail.get("author")))
            check("有 files list", isinstance(detail.get("files"), list))
            if detail.get("files"):
                f0 = detail["files"][0]
                check("file 含 path", bool(f0.get("path")))
                check("file 含 status", bool(f0.get("status")))
                check("file 含 additions (int)", isinstance(f0.get("additions"), int))
                check("file 含 deletions (int)", isinstance(f0.get("deletions"), int))
                check("file 含 binary (bool)", isinstance(f0.get("binary"), bool))
                check("file 含 patch (str)", isinstance(f0.get("patch"), str))

    # =========== 3. 非法 sha ===========
    _banner("3. 非法 sha 应返回 None")
    bogus = await git_manager.get_commit_detail(pid, "0" * 40)
    check("不存在的 sha 返回 None", bogus is None, f"got={bogus}")

    # =========== 4. 清理 ===========
    _banner("4. 清理测试数据")
    try:
        await db.execute("DELETE FROM projects WHERE id = ?", (pid,))
        print(f"  清理 project_id={pid}")
    except Exception as e:
        print(f"  清理失败: {e}")

    _banner("Summary")
    total = passed + failed
    print(f"  PASS {passed}/{total}  FAIL {failed}/{total}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
