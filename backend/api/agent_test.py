"""
Agent 健康检测 API — 供聊天框 /test 命令使用

每个 Agent 运行一个最小化测试用例，10 秒超时，返回 pass/fail/timeout/error
"""
import asyncio
import logging
import time
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from database import db

logger = logging.getLogger("api.agent_test")

router = APIRouter(prefix="/api/projects/{project_id}/agent-test", tags=["agent-test"])
global_router = APIRouter(prefix="/api/agent-test", tags=["agent-test"])


async def _run_with_timeout(coro, timeout: float = 10.0):
    """包装协程加超时，返回 (success, result, elapsed_ms)"""
    t0 = time.time()
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        return True, result, int((time.time() - t0) * 1000)
    except asyncio.TimeoutError:
        return False, {"error": f"超时（>{timeout}s）", "type": "timeout"}, int(timeout * 1000)
    except Exception as e:
        return False, {"error": str(e)[:200], "type": "error"}, int((time.time() - t0) * 1000)


# ==================== 各 Agent 测试函数 ====================

async def _test_chat_assistant(project_id: str) -> Dict:
    """ChatAssistant：发一条简短消息，检查能否返回回复"""
    from agents.chat_assistant import ChatAssistantAgent
    import agent_registry as _ar
    registry = _ar.get_registry() or {}
    if not registry:
        _ar.discover_agents()
        registry = _ar.get_registry()
    agent_cls = registry.get("ChatAssistant")
    if not agent_cls:
        raise RuntimeError("ChatAssistant 未注册")
    project = await db.fetch_one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not project:
        raise RuntimeError("项目不存在")
    agent = agent_cls()
    result = await agent.chat(
        user_message="你好，简单回复一个字",
        images=None, history=[], project=project, project_context="",
    )
    reply = result.get("reply", "")
    assert reply and len(reply) > 0, "回复为空"
    return {"reply_length": len(reply), "preview": reply[:40]}


async def _test_product_agent(project_id: str) -> Dict:
    """ProductAgent：分析一个最简需求"""
    from agents.product import ProductAgent
    agent = ProductAgent()
    context = {
        "project_id": project_id,
        "requirement_id": "TEST-REQ",
        "ticket_id": "TEST-TK",
        "requirement_title": "测试需求",
        "requirement_description": "添加一个显示 Hello World 的页面",
        "existing_files": {},
        "existing_code": "",
        "traits": [],
    }
    result = await agent.execute("develop", context)
    assert result.get("status") != "error", result.get("message", "未知错误")
    return {"status": result.get("status", "?"), "files": len(result.get("files", {}))}


async def _test_architect_agent(project_id: str) -> Dict:
    """ArchitectAgent：对简单需求做架构设计"""
    from agents.architect import ArchitectAgent
    agent = ArchitectAgent()
    context = {
        "project_id": project_id,
        "requirement_id": "TEST-REQ",
        "ticket_id": "TEST-TK",
        "requirement_title": "Hello World 页面",
        "requirement_description": "添加一个显示 Hello World 的静态页面",
        "existing_files": {},
        "traits": [],
    }
    result = await agent.execute("design_architecture", context)
    assert result.get("status") != "error", result.get("message", "未知错误")
    return {"status": result.get("status", "?"), "notes": str(result.get("notes", ""))[:80]}


async def _test_dev_agent(project_id: str) -> Dict:
    """DevAgent：生成一个最简单的文件"""
    from agents.dev import DevAgent
    agent = DevAgent()
    context = {
        "project_id": project_id,
        "requirement_id": "TEST-REQ",
        "ticket_id": "TEST-TK",
        "ticket_title": "创建 hello.txt",
        "ticket_description": "创建一个内容为 'Hello World' 的文本文件",
        "existing_files": {},
        "existing_code": "",
        "traits": [],
        "prior_insights": "",
    }
    result = await agent.execute("develop", context)
    assert result.get("status") != "error", result.get("message", "未知错误")
    return {"status": result.get("status", "?"), "files": len(result.get("files", {}))}


async def _test_review_agent(project_id: str) -> Dict:
    """ReviewAgent：审查一行代码"""
    from agents.review import ReviewAgent
    agent = ReviewAgent()
    context = {
        "project_id": project_id,
        "requirement_id": "TEST-REQ",
        "ticket_id": "TEST-TK",
        "ticket_title": "Hello World",
        "dev_result": {"files": {"hello.py": 'print("Hello World")'}},
        "traits": [],
    }
    result = await agent.execute("code_review", context)
    assert result.get("status") != "error", result.get("message", "未知错误")
    return {"status": result.get("status", "?"), "passed": result.get("passed")}


async def _test_test_agent(project_id: str) -> Dict:
    """TestAgent：对简单代码做验收测试"""
    from agents.test import TestAgent
    agent = TestAgent()
    context = {
        "project_id": project_id,
        "requirement_id": "TEST-REQ",
        "ticket_id": "TEST-TK",
        "ticket_title": "Hello World",
        "dev_result": {"files": {"hello.py": 'print("Hello World")'}},
        "traits": [],
    }
    result = await agent.execute("acceptance_review", context)
    assert result.get("status") != "error", result.get("message", "未知错误")
    return {"status": result.get("status", "?"), "passed": result.get("passed")}


async def _test_image_processor(project_id: str) -> Dict:
    """image_processor：检查 LightAI API 配置是否可达"""
    import httpx
    from config import settings
    if not settings.LIGHTAI_API_BASE:
        return {"status": "skip", "reason": "LIGHTAI_API_BASE 未配置"}
    url = f"{settings.LIGHTAI_API_BASE.rstrip('/')}/api/lightai/engines"
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {settings.LIGHTAI_API_KEY or ''}"})
    assert resp.status_code < 500, f"HTTP {resp.status_code}"
    return {"status": "reachable", "http": resp.status_code, "engines": len(resp.json() if resp.status_code == 200 else [])}


# ==================== 注册表 ====================

_AGENT_TESTS = {
    "ChatAssistant":    _test_chat_assistant,
    "ProductAgent":     _test_product_agent,
    "ArchitectAgent":   _test_architect_agent,
    "DevAgent":         _test_dev_agent,
    "ReviewAgent":      _test_review_agent,
    "TestAgent":        _test_test_agent,
    "ImageProcessor":   _test_image_processor,
}

AVAILABLE_AGENTS = list(_AGENT_TESTS.keys())


# ==================== 端点 ====================

@router.post("/{agent_name}")
async def test_agent(project_id: str, agent_name: str):
    """运行指定 Agent 的功能测试（10s 超时）"""
    project = await db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    if agent_name == "all":
        results = {}
        for name, fn in _AGENT_TESTS.items():
            ok, result, ms = await _run_with_timeout(fn(project_id))
            results[name] = {"passed": ok, "elapsed_ms": ms, **result}
        return {"results": results}

    fn = _AGENT_TESTS.get(agent_name)
    if not fn:
        raise HTTPException(400, f"未知 Agent：{agent_name}，可选：{AVAILABLE_AGENTS}")

    ok, result, ms = await _run_with_timeout(fn(project_id))
    return {"agent": agent_name, "passed": ok, "elapsed_ms": ms, **result}


@router.get("")
async def list_agents(project_id: str):
    """列出可测试的 Agent 列表"""
    return {"agents": AVAILABLE_AGENTS}


# ==================== 全局端点（无 project_id，自动借第一个项目）====================

async def _get_any_project_id() -> str:
    """获取任意一个可用项目 ID，用于全局测试"""
    row = await db.fetch_one(
        "SELECT id FROM projects WHERE id != '__global__' ORDER BY created_at DESC LIMIT 1"
    )
    if row:
        return row["id"]
    raise HTTPException(400, "没有可用项目，请先创建一个项目再运行 Agent 测试")


@global_router.post("/{agent_name}")
async def test_agent_global(agent_name: str):
    """全局 Agent 测试（不需要 project_id，自动借第一个可用项目）"""
    project_id = await _get_any_project_id()

    if agent_name == "all":
        results = {}
        for name, fn in _AGENT_TESTS.items():
            ok, result, ms = await _run_with_timeout(fn(project_id))
            results[name] = {"passed": ok, "elapsed_ms": ms, **result}
        return {"results": results, "project_id_used": project_id}

    fn = _AGENT_TESTS.get(agent_name)
    if not fn:
        raise HTTPException(400, f"未知 Agent：{agent_name}，可选：{AVAILABLE_AGENTS}")

    ok, result, ms = await _run_with_timeout(fn(project_id))
    return {"agent": agent_name, "passed": ok, "elapsed_ms": ms,
            "project_id_used": project_id, **result}


@global_router.get("")
async def list_agents_global():
    """列出可测试的 Agent 列表（全局）"""
    return {"agents": AVAILABLE_AGENTS}
