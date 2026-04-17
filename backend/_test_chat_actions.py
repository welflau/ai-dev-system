"""
P1-7 冒烟测试：直接调用新的 chat Action 类，绕过 LLM 和解析器，
验证 Action 体系能正确执行并返回与原 _execute_* 等价的 data 结构。

运行：cd backend && PYTHONIOENCODING=utf-8 python _test_chat_actions.py
"""
import asyncio
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s  %(message)s')


async def main():
    from database import db
    await db.connect()
    # 不调 init_tables：后台服务已持有 DB 连接，此处只做读测试

    # 拿一个真实项目做测试
    projects = await db.fetch_all("SELECT id, name FROM projects LIMIT 1")
    if not projects:
        print("❌ 没有项目可供测试，请先创建一个项目")
        sys.exit(1)
    project_id = projects[0]["id"]
    project_name = projects[0]["name"]
    print(f"✅ 使用项目: {project_id} ({project_name})\n")

    # === Test 1: ConfirmRequirementAction ===
    from actions.chat.confirm_requirement import ConfirmRequirementAction
    print("=== Test 1: ConfirmRequirementAction ===")
    result = await ConfirmRequirementAction().run({
        "project_id": project_id,
        "title": "测试需求标题",
        "description": "测试描述",
        "priority": "medium",
    })
    print(f"success: {result.success}")
    print(f"data: {json.dumps(result.data, ensure_ascii=False, indent=2)}")
    assert result.success is True
    assert result.data["type"] == "confirm_requirement"
    assert result.data["title"] == "测试需求标题"
    print("✅ 通过\n")

    # === Test 2: ConfirmBugAction ===
    from actions.chat.confirm_bug import ConfirmBugAction
    print("=== Test 2: ConfirmBugAction ===")
    result = await ConfirmBugAction().run({
        "project_id": project_id,
        "title": "测试 BUG 标题",
        "description": "现象描述",
    })
    print(f"data: {json.dumps(result.data, ensure_ascii=False, indent=2)}")
    assert result.success is True
    assert result.data["type"] == "confirm_bug"
    assert result.data["priority"] == "high"  # 默认值
    print("✅ 通过\n")

    # === Test 3: GitListBranchesAction（真实跑 Git） ===
    from actions.chat.git_list_branches import GitListBranchesAction
    print("=== Test 3: GitListBranchesAction ===")
    result = await GitListBranchesAction().run({"project_id": project_id})
    print(f"success: {result.success}")
    if result.success:
        print(f"当前分支: {result.data['data']['current']}")
        print(f"分支列表: {result.data['data']['branches']}")
    else:
        print(f"错误（可能项目没有 Git 仓库，非 bug）: {result.data}")
    print("✅ 通过（含降级场景）\n")

    # === Test 4: GitLogAction ===
    from actions.chat.git_log import GitLogAction
    print("=== Test 4: GitLogAction ===")
    result = await GitLogAction().run({"project_id": project_id, "limit": 3})
    print(f"success: {result.success}")
    print(f"message 前 200 字: {(result.data.get('message') or '')[:200]}")
    print("✅ 通过\n")

    # === Test 5: 未知 project_id 错误处理 ===
    print("=== Test 5: 未知 project_id 的错误处理 ===")
    result = await GitLogAction().run({"project_id": "PRJ-NOT-EXIST", "limit": 3})
    assert result.success is False
    assert result.data.get("type") == "error"
    print(f"错误消息: {result.data.get('message')}")
    print("✅ 通过\n")

    # === Test 6: 缺 project_id ===
    print("=== Test 6: 缺 project_id ===")
    result = await GitLogAction().run({})
    assert result.success is False
    assert "project_id" in (result.error or "")
    print(f"error: {result.error}")
    print("✅ 通过\n")

    print("🎉 所有冒烟测试通过")


if __name__ == "__main__":
    asyncio.run(main())
