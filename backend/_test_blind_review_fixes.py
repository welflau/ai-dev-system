"""
盲审修复 P0 单元测试（不依赖后端服务，mock LLM/DB）

4 用例：
1. DecomposeAction 接收 existing_files/existing_code 后，在 prompt 里能看到
2. ReviewAgent.execute("code_review", ctx) 路由到 CodeReviewAction，状态为 review_passed
3. ReviewAgent 低分（4/10）返回 review_passed 但 score 值保留（orchestrator 负责判 warning）
4. ReviewAgent 正常分（8/10）返回 review_passed

运行：cd backend && PYTHONIOENCODING=utf-8 python _test_blind_review_fixes.py
"""
import asyncio
import json
from unittest.mock import AsyncMock, patch


# ============================================================
# Test 1: DecomposeAction 收到代码上下文时，prompt 里有相应段落
# ============================================================
async def test_decompose_receives_code_context():
    from actions.decompose import DecomposeAction

    fake_json = json.dumps({
        "prd_summary": "在左上角加个红色按钮",
        "complexity": "simple",
        "tickets": [
            {"title": "加按钮", "description": "左上角", "type": "feature",
             "module": "frontend", "priority": 2, "estimated_hours": 1,
             "subtasks": ["写 CSS"], "dependencies": []},
        ],
    })
    captured_req = {}

    # 拦截 ActionNode.fill：确认传给它的 req 字符串里含代码上下文段
    from actions.action_node import ActionNode
    original_fill = ActionNode.fill

    async def capture_fill(self, req, llm, **kwargs):
        captured_req["value"] = req
        # mock LLM 返回：直接往 instruct_content 塞 DecomposeOutput 实例
        from actions.schemas import DecomposeOutput
        self.instruct_content = DecomposeOutput(**json.loads(fake_json))
        return self

    with patch.object(ActionNode, "fill", capture_fill):
        result = await DecomposeAction().run({
            "title": "加红色按钮",
            "description": "在左上角",
            "priority": "medium",
            "existing_files": ["index.html", "app.js", "styles.css"],
            "existing_code": {"index.html": "<html>...</html>"},
        })

    assert result.success
    req_text = captured_req.get("value", "")
    # 代码上下文段应出现
    assert "项目文件" in req_text, f"prompt 应含项目文件段，实际: {req_text[:500]}"
    assert "index.html" in req_text
    assert "app.js" in req_text
    print("✅ Test 1 decompose 收到代码上下文并注入 prompt 通过")


# ============================================================
# Test 2: ReviewAgent 路由 code_review 任务
# ============================================================
async def test_review_agent_routes_code_review():
    from agents.review import ReviewAgent

    agent = ReviewAgent()

    # mock CodeReviewAction.run 返回固定分数
    from actions.code_review import CodeReviewAction
    original_run = CodeReviewAction.run

    async def mock_run(self, context):
        from actions.base import ActionResult
        return ActionResult(
            success=True,
            data={"score": 8, "issues": [], "suggestions": []},
        )

    with patch.object(CodeReviewAction, "run", mock_run):
        result = await agent.execute("code_review", {
            "ticket_title": "加按钮",
            "dev_result": {"files": {"app.js": "console.log('hi')"}},
        })

    assert result.get("status") == "review_passed", f"应为 review_passed, 实际 {result.get('status')}"
    assert result.get("score") == 8
    print("✅ Test 2 ReviewAgent 路由 code_review 通过")


# ============================================================
# Test 3: 低分仍返回 review_passed（分数保留供 orchestrator 处理）
# ============================================================
async def test_review_agent_low_score_still_passes():
    from agents.review import ReviewAgent
    from actions.code_review import CodeReviewAction
    from actions.base import ActionResult

    async def mock_low(self, context):
        return ActionResult(
            success=True,
            data={"score": 4, "issues": ["命名太短", "无注释"], "suggestions": ["改名", "加注释"]},
        )

    with patch.object(CodeReviewAction, "run", mock_low):
        result = await ReviewAgent().execute("code_review", {"ticket_title": "t"})

    # 不阻塞：状态仍为 review_passed；分数保留
    assert result.get("status") == "review_passed"
    assert result.get("score") == 4
    assert len(result.get("issues", [])) == 2
    print("✅ Test 3 低分仍通过但分数保留 通过")


# ============================================================
# Test 4: 未知任务返回 error
# ============================================================
async def test_review_agent_unknown_task():
    from agents.review import ReviewAgent

    result = await ReviewAgent().execute("unknown_action", {})
    assert result.get("status") == "error"
    assert "未知任务" in result.get("message", "")
    print("✅ Test 4 未知任务返回 error 通过")


async def main():
    await test_decompose_receives_code_context()
    await test_review_agent_routes_code_review()
    await test_review_agent_low_score_still_passes()
    await test_review_agent_unknown_task()
    print("\n🎉 盲审修复 P0 单测全部通过（4/4）")


if __name__ == "__main__":
    asyncio.run(main())
