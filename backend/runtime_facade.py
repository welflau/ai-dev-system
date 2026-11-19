"""L0 运行时门面 —— P2 拆主环（严格 DAG 的依赖倒置落点）。

背景
----
P1 后只剩一个 62 模块主环。图论实证：只要 ``orchestrator`` 的出边还指向
``agents``/``actions``，任何从它们**静态 import** 回 orchestrator（或回
``api.chat``）的边都会让 SCC 保持 > 1。方案 §3.4 给的解法是依赖倒置：
L1 只认 L0 契约，L3 单向注册，运行时按名字解析。

本模块就是那个最小的 L0 契约门面 —— 它刻意**不 import 任何项目内模块**，
因此在静态依赖图里是纯叶子，不参与成环。使用方只认本模块：

    from runtime_facade import get_orchestrator, chat_api
    orch = get_orchestrator()
    await orch.post_milestone_comment(...)          # 同步 await，时序不变
    await chat_api()._save_chat_message(...)        # 动态取模块属性，patch 兼容

为什么用 sys.modules / importlib 兜底
------------------------------------
提供方在模块加载末尾把自己注册进来；解析发生在运行时。若某进程只加载了
使用方（例如单测单独 import 某个 Agent），兜底按模块名解析，行为与原先
函数内 ``from orchestrator import orchestrator`` 完全一致。模块名以**变量**
传给 importlib，是因为这是运行时服务定位而非静态依赖声明 —— 守卫的静态
import 图不应把它记成一条边，否则环会原样回来（方案 §2.3 #7 的教训）：
静态依赖由 ``layers.toml`` 与 ``check_layers.py`` 判定，运行时查找不是依赖边。

灰度 / 回滚
-----------
``lazy_resolve``：置 False 时只查注册表与 sys.modules，不再强制 import，
用于排障时快速降级（调用方原有的 try/except 会兜住未解析的情况）。
它**不会「切回直连」** —— 直连静态 import 与 SCC=1 数学上不相容；
需要回滚请用 git revert 本阶段提交（方案 §7「逐文件 revert」）。
"""
from __future__ import annotations

import importlib
import sys
from typing import Any, Dict

_ORCHESTRATOR_MODULE = "orchestrator"
_CHAT_API_MODULE = "api.chat"

_handlers: Dict[str, Any] = {}

# 灰度开关：False = 不强制 import 未加载的提供方模块（排障降级用）
lazy_resolve = True


def register(name: str, value: Any) -> None:
    """提供方注册（也可用于单测注入替身）。"""
    _handlers[name] = value


def _resolve(name: str, module_name: str, attr: str | None = None):
    value = _handlers.get(name)
    if value is not None:
        return value
    mod = sys.modules.get(module_name)
    if mod is None and lazy_resolve:
        mod = importlib.import_module(module_name)
    if mod is None:
        return None
    return getattr(mod, attr, None) if attr else mod


def get_orchestrator():
    """返回 TicketOrchestrator 单例；未加载/未注册时返回 None。"""
    return _resolve("orchestrator", _ORCHESTRATOR_MODULE, "orchestrator")


def chat_api():
    """返回 api.chat 模块对象；调用方动态取属性（兼容 monkeypatch）。"""
    return _resolve("api.chat", _CHAT_API_MODULE)
