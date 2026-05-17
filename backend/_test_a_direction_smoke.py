"""
A 方向改进冒烟测试
运行方式：python _test_a_direction_smoke.py
"""
import asyncio, sys, os
sys.path.insert(0, ".")

# 指向活跃 DB
if not os.environ.get("DB_PATH"):
    _db_candidate = os.path.join(os.path.dirname(__file__), "data", "ai_dev_system_new.db")
    if os.path.exists(_db_candidate):
        os.environ["DB_PATH"] = _db_candidate


async def run():
    results: list[tuple[str, bool, str]] = []

    # ── L5 Rules 注入 + L3 Cache 分区 ────────────────────────────────────────
    from agents.chat_assistant import ChatAssistantAgent
    agent = ChatAssistantAgent()
    prompt = await agent._build_system_prompt(
        {"id": "t", "name": "t", "description": ""},
        {"traits": "[]", "requirements_summary": "", "file_tree": ""},
    )
    ok = "CACHE_BOUNDARY" in prompt and len(prompt) > 500
    results.append(("L5 Rules 注入 + L3 Cache 分区", ok, "system_prompt 含 CACHE_BOUNDARY 标记"))

    # ── L1 Diminishing Returns ────────────────────────────────────────────────
    from query_engine.budget import Budget
    b = Budget(max_tokens=10_000, max_turns=50)
    b.consume(tokens=100, turns=1)
    b.consume(tokens=100, turns=1)
    b.consume(tokens=100, turns=1)
    ok = b.is_diminishing()
    results.append(("L1 Diminishing Returns", ok, "3 轮各 100 token < 阈值 500 → 触发"))

    # ── L9 Feature Flags ─────────────────────────────────────────────────────
    from actions.chat.set_session_flag import get_session_flag, _SESSION_FLAGS
    _SESSION_FLAGS["smoke"] = {"compaction": False}
    ok = (
        get_session_flag("smoke", "compaction") is False
        and get_session_flag("smoke", "nudge") is True  # default
    )
    results.append(("L9 Feature Flags", ok, "覆盖值生效 + 默认值兜底"))

    # ── L8 并行子任务 Action 注册 ─────────────────────────────────────────────
    found = any(c.__name__ == "DispatchParallelSubtasksAction" for c in ChatAssistantAgent.action_classes)
    results.append(("L8 DispatchParallelSubtasksAction", found, "已在 action_classes 中注册"))

    # ── L7 cost_usd 列 ────────────────────────────────────────────────────────
    from database import db
    await db.connect()
    cols = await db.fetch_all("PRAGMA table_info(llm_conversations)")
    has_cost = any(c["name"] == "cost_usd" for c in cols)
    results.append(("L7 cost_usd 列", has_cost, "llm_conversations.cost_usd 存在"))

    # ── L6 nudge_hook 已注册 ──────────────────────────────────────────────────
    from hooks.registry import hook_registry
    from hooks.builtin import register_builtin_hooks
    register_builtin_hooks()
    stats = hook_registry.get_stats()
    has_nudge = any("nudge" in s.get("name", "") for s in stats)
    results.append(("L6 nudge_hook 注册", has_nudge, "hook_registry stats 含 nudge"))

    # ── 输出结果 ──────────────────────────────────────────────────────────────
    print("\n=== A 方向冒烟测试 ===\n")
    all_pass = True
    for name, ok, note in results:
        status = "PASS" if ok else "FAIL"
        mark = "[PASS]" if ok else "[FAIL]"
        print(f"  {mark} {name:<40s}  {note}")
        if not ok:
            all_pass = False

    print()
    if all_pass:
        print("  结果：ALL PASS  (+2.0 分, 5.5 -> 7.5)")
    else:
        print("  结果：SOME FAILED — 请检查上方 [FAIL] 项")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run())
