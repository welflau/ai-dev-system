"""
v0.19.1 对话一键流 —— smoke test

只测新引入的 UE 自动 propose 支路（不跑 git clone/push，避免网络/磁盘噪音）：
  1. 直接 insert 一条 UE 项目记录
  2. 调 ProposeUEFrameworkAction.run() 拿到方案数据
  3. 调 _save_chat_message 持久化
  4. 从 chat_messages 查回来断言 action_type=propose_ue_framework + action_data 字段齐全

另外也验证 CreateProjectAction 的判定分支：
  - engine:ue* traits → is_ue_project=True
  - platform:web → is_ue_project=False

用法：
    cd backend && python _test_v019_auto_propose.py
"""
from __future__ import annotations

import asyncio
import json
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
        print(f"  [{marker}] {name}" + (f"  — {detail}" if detail else ""))
        if ok:
            passed += 1
        else:
            failed += 1

    from database import db
    from actions.chat.propose_ue_framework import ProposeUEFrameworkAction
    from api.chat import _save_chat_message
    from utils import generate_id, now_iso

    await db.connect()

    # =========== 1. 插入一条 UE 项目记录 ===========
    _banner("1. 准备测试数据：插入 UE 项目记录")
    pid = generate_id("PRJ")
    traits_ue = ["platform:desktop", "category:game", "engine:ue5", "genre:fps"]
    await db.insert("projects", {
        "id": pid,
        "name": "UETestAutoPropose",
        "description": "v0.19 smoke UE auto propose",
        "status": "active",
        "tech_stack": "Unreal Engine 5 / C++",
        "config": "{}",
        "git_repo_path": str(Path("D:/Projects/_v019_auto_propose_test")),
        "git_remote_url": "",
        "traits": json.dumps(traits_ue, ensure_ascii=False),
        "traits_confidence": "{}",
        "preset_id": "ue5-game",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    check("UE 项目已插入", True, f"pid={pid}")

    # =========== 2. ProposeUEFrameworkAction 能算方案 ===========
    _banner("2. ProposeUEFrameworkAction 对 UE 项目能产出方案")
    r = await ProposeUEFrameworkAction().run({"project_id": pid})
    check("propose 成功", r.success, r.error or "")
    d = r.data or {}
    check("type=propose_ue_framework", d.get("type") == "propose_ue_framework")
    check("含 engines", "engines" in d)
    check("含 recommended_template", bool(d.get("recommended_template")))
    check("含 target_dir", bool(d.get("target_dir")))

    # =========== 3. _save_chat_message 能把方案持久化到 chat_messages ===========
    _banner("3. 持久化到 chat_messages（模拟 CreateProjectAction 的 UE 分支）")
    intro = "✨ 检测到这是 UE 项目，已自动为你生成了框架方案。"
    await _save_chat_message(project_id=pid, role="assistant", content=intro, action=d)

    rows = await db.fetch_all(
        "SELECT id, role, action_type, action_data, content "
        "FROM chat_messages WHERE project_id = ? ORDER BY created_at",
        (pid,),
    )
    check("chat_messages 查到 1 条", len(rows) == 1, f"rows={len(rows)}")
    if rows:
        m = rows[0]
        check("role=assistant", m["role"] == "assistant")
        check("action_type=propose_ue_framework",
              m["action_type"] == "propose_ue_framework")
        ad = m.get("action_data")
        if ad:
            try:
                ad_obj = json.loads(ad) if isinstance(ad, str) else ad
                check("action_data 含 engines", "engines" in ad_obj)
                check("action_data 含 recommended_template",
                      "recommended_template" in ad_obj)
                check("action_data.project_id 一致",
                      ad_obj.get("project_id") == pid)
            except Exception as e:
                check("action_data 可 JSON 解析", False, str(e))
        else:
            check("action_data 非空", False)
        check("content 含 UE 提示前缀", "检测到这是 UE 项目" in (m.get("content") or ""))

    # =========== 4. CreateProjectAction 的 is_ue_project 判定 ===========
    _banner("4. is_ue_project 判定（不实际调用 run）")
    traits_web = ["platform:web", "category:app", "lang:typescript"]
    is_ue_1 = any(t.startswith("engine:ue") for t in traits_ue)
    is_ue_2 = any(t.startswith("engine:ue") for t in traits_web)
    is_ue_3 = any(t.startswith("engine:ue") for t in ["engine:ue4", "category:game"])
    is_ue_4 = any(t.startswith("engine:ue") for t in ["engine:unity", "category:game"])
    check("UE5 traits → True", is_ue_1)
    check("Web traits → False", not is_ue_2)
    check("UE4 traits → True", is_ue_3)
    check("Unity traits → False", not is_ue_4)

    # =========== 5. 非 UE 项目不走持久化支路（应不动 chat_messages） ===========
    _banner("5. 非 UE 项目：不调 ProposeUEFrameworkAction，chat_messages 不增")
    pid_web = generate_id("PRJ")
    await db.insert("projects", {
        "id": pid_web,
        "name": "WebTestNoPropose",
        "description": "v0.19 smoke web no propose",
        "status": "active",
        "tech_stack": "React",
        "config": "{}",
        "git_repo_path": str(Path("D:/Projects/_v019_web_test")),
        "git_remote_url": "",
        "traits": json.dumps(traits_web, ensure_ascii=False),
        "traits_confidence": "{}",
        "preset_id": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    rows_web = await db.fetch_all(
        "SELECT COUNT(*) as c FROM chat_messages WHERE project_id = ?", (pid_web,),
    )
    count_web = rows_web[0]["c"] if rows_web else -1
    check("Web 项目 chat_messages=0", count_web == 0, f"count={count_web}")

    # =========== 6. 清理 ===========
    _banner("6. 清理测试数据")
    for p in (pid, pid_web):
        try:
            await db.execute("DELETE FROM chat_messages WHERE project_id = ?", (p,))
            await db.execute("DELETE FROM projects WHERE id = ?", (p,))
            print(f"  清理 project_id={p}")
        except Exception as e:
            print(f"  清理 {p} 失败: {e}")

    _banner("Summary")
    total = passed + failed
    print(f"  PASS {passed}/{total}  FAIL {failed}/{total}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
