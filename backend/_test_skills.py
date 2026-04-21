"""
Skills 注入系统单元测试（不依赖 DB / 后端 server）

覆盖：
1. SkillLoader 加载 skills.json
2. DevAgent 聚合 react-dev + fastapi-dev + git-workflow 三个 skill（顺序按 priority）
3. TestAgent 只拿到 playwright-e2e
4. 未挂任何 skill 的 ArchitectAgent 返回空串
5. enabled=false 的 skill 被过滤
6. prompt.md 文件缺失时 log warning 不崩溃
7. ContextVar 注入 ActionNode._compile（有 skill 时 prompt 里含 "专业技能" 段）
8. ContextVar 在 BaseAgent.run_action 之后正确 reset

运行：cd backend && PYTHONIOENCODING=utf-8 python _test_skills.py
"""
import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch


def test_loader_reads_config():
    """SkillLoader 能读取 skills.json，4 个条目都启用"""
    from skills.loader import SkillLoader

    loader = SkillLoader()
    assert len(loader.skills) == 4, f"期望 4 个 skill，实际 {len(loader.skills)}"
    expected = {"react-dev", "fastapi-dev", "playwright-e2e", "git-workflow"}
    assert set(loader.skills.keys()) == expected

    enabled = loader.get_enabled_skills()
    assert len(enabled) == 4, "初始 4 个都应启用"
    print("✅ Test 1 加载 skills.json 通过")


def test_devagent_gets_three_skills():
    """DevAgent 拿到 react-dev + fastapi-dev + git-workflow（不含 playwright-e2e）"""
    from skills.loader import SkillLoader

    loader = SkillLoader()
    sids = loader.get_skills_for_agent("DevAgent")
    assert set(sids) == {"react-dev", "fastapi-dev", "git-workflow"}, \
        f"DevAgent 应拿 3 个 skill，实际 {sids}"

    # 按 priority 排序：high 在前（react, fastapi），medium 在后（git）
    git_idx = sids.index("git-workflow")
    assert git_idx == 2, "git-workflow 优先级 medium，应排最后"

    prompt = loader.build_prompt_for_agent("DevAgent")
    assert "react-dev" in prompt
    assert "fastapi-dev" in prompt
    assert "git-workflow" in prompt
    assert "playwright-e2e" not in prompt
    # 文件内容被读入
    assert "单文件" in prompt or "Hooks" in prompt  # react prompt 里的关键词
    print("✅ Test 2 DevAgent 聚合 3 个 skill 通过")


def test_testagent_gets_playwright_only():
    """TestAgent 只拿到 playwright-e2e"""
    from skills.loader import SkillLoader

    loader = SkillLoader()
    sids = loader.get_skills_for_agent("TestAgent")
    assert sids == ["playwright-e2e"], f"TestAgent 应只拿 playwright-e2e，实际 {sids}"

    prompt = loader.build_prompt_for_agent("TestAgent")
    assert "playwright-e2e" in prompt
    assert "react-dev" not in prompt  # 确认过滤生效
    print("✅ Test 3 TestAgent 过滤到 playwright-e2e 通过")


def test_architect_agent_empty():
    """没有 inject_to 包含 ArchitectAgent 的 skill → 返回空串"""
    from skills.loader import SkillLoader

    loader = SkillLoader()
    prompt = loader.build_prompt_for_agent("ArchitectAgent")
    assert prompt == "", "ArchitectAgent 当前没挂任何 skill，应返回空串"
    print("✅ Test 4 未挂 skill 的 Agent 返回空串通过")


def test_disabled_skill_filtered():
    """临时创建一份 enabled=false 的 skills.json，确认该 skill 不被拉入"""
    from skills.loader import SkillLoader

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        # 构造最小配置
        (base / "skills.json").write_text(json.dumps({
            "react-dev": {
                "name": "React",
                "prompt_file": "packs/react_dev/prompt.md",
                "inject_to": ["DevAgent"],
                "priority": "high",
                "enabled": False,  # 关掉
            },
            "fastapi-dev": {
                "name": "FastAPI",
                "prompt_file": "packs/fastapi_dev/prompt.md",
                "inject_to": ["DevAgent"],
                "priority": "high",
                "enabled": True,
            },
        }, ensure_ascii=False), encoding="utf-8")
        (base / "packs" / "react_dev").mkdir(parents=True)
        (base / "packs" / "react_dev" / "prompt.md").write_text("REACT CONTENT", encoding="utf-8")
        (base / "packs" / "fastapi_dev").mkdir(parents=True)
        (base / "packs" / "fastapi_dev" / "prompt.md").write_text("FASTAPI CONTENT", encoding="utf-8")

        loader = SkillLoader(base_dir=base)
        prompt = loader.build_prompt_for_agent("DevAgent")
        assert "FASTAPI CONTENT" in prompt
        assert "REACT CONTENT" not in prompt, "enabled=false 的 skill 不应被加载"
    print("✅ Test 5 enabled=false 过滤通过")


def test_missing_prompt_file_graceful():
    """prompt.md 缺失：log warning，不崩溃，跳过该 skill"""
    from skills.loader import SkillLoader

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "skills.json").write_text(json.dumps({
            "ghost-skill": {
                "name": "Ghost",
                "prompt_file": "packs/not_exist/prompt.md",
                "inject_to": ["DevAgent"],
                "priority": "high",
                "enabled": True,
            },
        }, ensure_ascii=False), encoding="utf-8")

        loader = SkillLoader(base_dir=base)
        prompt = loader.build_prompt_for_agent("DevAgent")
        # 不崩溃即可，内容为空（唯一 skill 文件缺失）
        assert prompt == ""
    print("✅ Test 6 缺失 prompt 文件降级通过")


async def test_contextvar_injected_into_action_node():
    """BaseAgent.run_action 调用时，ActionNode._compile 能读到 skills"""
    from skills import _current_skills
    from actions.action_node import ActionNode
    from pydantic import BaseModel

    class FakeSchema(BaseModel):
        result: str = ""

    node = ActionNode(key="t", expected_type=FakeSchema, instruction="做某事")

    # 无 skills 时：不含 "专业技能" 段
    assert _current_skills.get() == ""
    prompt_no_skills = node._compile("context data")
    assert "专业技能" not in prompt_no_skills

    # 手动模拟 BaseAgent 的注入行为
    token = _current_skills.set("SKILL_TEXT_FOR_TEST")
    try:
        prompt_with_skills = node._compile("context data")
        assert "## 专业技能 (Skills)" in prompt_with_skills
        assert "SKILL_TEXT_FOR_TEST" in prompt_with_skills
        # 确保原指令和 schema 还在
        assert "做某事" in prompt_with_skills
        assert "result" in prompt_with_skills
    finally:
        _current_skills.reset(token)

    # reset 后回到空
    assert _current_skills.get() == ""
    print("✅ Test 7 ContextVar 注入 ActionNode._compile 通过")


async def test_run_action_sets_and_resets_contextvar():
    """BaseAgent.run_action 执行前设置 ContextVar，结束后自动 reset"""
    from agents.base import BaseAgent, ReactMode
    from actions.base import ActionBase, ActionResult
    from skills import _current_skills

    # 捕获 Action 运行时刻的 ContextVar 值
    captured = {}

    class CaptureAction(ActionBase):
        @property
        def name(self) -> str:
            return "capture"

        @property
        def description(self) -> str:
            return "capture contextvar"

        async def run(self, ctx):
            captured["during"] = _current_skills.get()
            return ActionResult(success=True, data={"ok": True})

    class FakeAgent(BaseAgent):
        action_classes = [CaptureAction]
        react_mode = ReactMode.SINGLE

        @property
        def agent_type(self) -> str:
            return "FakeAgent"

    # 手动塞一个 skills prompt（绕过 skills.json）
    agent = FakeAgent()
    agent._skills_prompt = "FAKE_SKILL_BLOCK"

    assert _current_skills.get() == ""  # 执行前为空
    await agent.run_action("capture", {})
    assert captured["during"] == "FAKE_SKILL_BLOCK", \
        f"Action 运行时应看到 skills，实际: {captured['during']!r}"
    assert _current_skills.get() == "", "run_action 结束后应 reset"
    print("✅ Test 8 run_action ContextVar set + reset 通过")


async def main():
    test_loader_reads_config()
    test_devagent_gets_three_skills()
    test_testagent_gets_playwright_only()
    test_architect_agent_empty()
    test_disabled_skill_filtered()
    test_missing_prompt_file_graceful()
    await test_contextvar_injected_into_action_node()
    await test_run_action_sets_and_resets_contextvar()
    print("\n🎉 Skills 单测全部通过（8/8）")


if __name__ == "__main__":
    asyncio.run(main())
