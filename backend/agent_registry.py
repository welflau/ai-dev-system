"""
Agent 注册中心 — 自动发现和注册 Agent
支持：装饰器注册 + 自动扫描 agents/custom/ 目录
"""
import importlib
import logging
from pathlib import Path
from typing import Dict, Type, Optional

logger = logging.getLogger("agent_registry")

# 全局 Agent 注册表
_REGISTRY: Dict[str, Type] = {}


def register_agent(name: str = None):
    """装饰器：注册 Agent 类

    用法:
        @register_agent("SecurityAgent")
        class SecurityAgent(BaseAgent):
            ...
    """
    def decorator(cls):
        agent_name = name or cls.__name__
        _REGISTRY[agent_name] = cls
        logger.debug("Agent 已注册: %s → %s", agent_name, cls.__name__)
        return cls
    return decorator


def get_registry() -> Dict[str, Type]:
    """获取所有注册的 Agent 类"""
    return dict(_REGISTRY)


def discover_agents():
    """自动发现并注册所有 Agent

    扫描顺序:
    1. 内置 agents/ 目录下的 Agent（通过 import）
    2. agents/custom/ 目录下的自定义 Agent
    """
    # 1. 注册内置 Agent
    _register_builtin_agents()

    # 2. 扫描自定义 Agent
    custom_dir = Path(__file__).parent / "agents" / "custom"
    if custom_dir.exists():
        _scan_custom_agents(custom_dir)

    logger.info("📦 Agent 注册完成: %d 个 (%s)",
                len(_REGISTRY), ", ".join(_REGISTRY.keys()))
    return _REGISTRY


def instantiate_agents() -> Dict[str, object]:
    """实例化所有注册的 Agent，返回 {name: instance}"""
    if not _REGISTRY:
        discover_agents()

    agents = {}
    for name, cls in _REGISTRY.items():
        try:
            agents[name] = cls()
        except Exception as e:
            logger.error("Agent 实例化失败: %s → %s", name, e)
    return agents


def _register_builtin_agents():
    """注册内置 Agent"""
    from agents.product import ProductAgent
    from agents.architect import ArchitectAgent
    from agents.dev import DevAgent
    from agents.test import TestAgent
    from agents.review import ReviewAgent
    from agents.deploy import DeployAgent

    builtin = {
        "ProductAgent": ProductAgent,
        "ArchitectAgent": ArchitectAgent,
        "DevAgent": DevAgent,
        "TestAgent": TestAgent,
        "ReviewAgent": ReviewAgent,
        "DeployAgent": DeployAgent,
    }
    for name, cls in builtin.items():
        if name not in _REGISTRY:
            _REGISTRY[name] = cls


def _scan_custom_agents(custom_dir: Path):
    """扫描 agents/custom/ 目录，自动加载自定义 Agent"""
    import sys

    for py_file in custom_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue

        module_name = f"agents.custom.{py_file.stem}"
        try:
            # 确保 agents/custom 在 path 中
            parent = str(custom_dir.parent.parent)
            if parent not in sys.path:
                sys.path.insert(0, parent)

            module = importlib.import_module(module_name)

            # 查找继承 BaseAgent 的类
            from agents.base import BaseAgent
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and issubclass(attr, BaseAgent)
                        and attr is not BaseAgent and attr_name not in _REGISTRY):
                    _REGISTRY[attr_name] = attr
                    logger.info("🔌 自定义 Agent 已加载: %s (from %s)", attr_name, py_file.name)

        except Exception as e:
            logger.warning("加载自定义 Agent 失败: %s → %s", py_file.name, e)
