"""CI Strategy Loader——按项目 traits 匹配对应策略

逻辑跟 SOP fragment 匹配一致（any_of / all_of / none_of），区别：
  - SOP 是"把所有匹配的 fragment 都组合进去"（多选）
  - CIStrategy 是"按 priority 降序找第一个匹配的"（单选）

启动时扫 `strategies/*.py` 自动注册所有 CIStrategy 子类。
"""
from __future__ import annotations

import importlib
import json
import logging
import pkgutil
from typing import Dict, List, Optional, Set

from database import db

from ci.strategies.base import CIStrategy

logger = logging.getLogger("ci.loader")


class CIStrategyLoader:
    """扫描 strategies/ 目录 → 发现所有 CIStrategy 子类 → 按 priority 降序"""

    def __init__(self):
        self._strategies: List[CIStrategy] = []
        self._default: Optional[CIStrategy] = None  # 兜底策略（priority=0）
        self._loaded = False

    def load_all(self) -> None:
        """懒加载：首次调用时扫描 strategies/ 目录"""
        if self._loaded:
            return
        self._loaded = True

        seen_classes: set = set()

        # 扫描 strategies/*.py（不含 base.py / __init__.py）
        import ci.strategies as pkg
        for mod_info in pkgutil.iter_modules(pkg.__path__):
            name = mod_info.name
            if name in ("base", "__init__"):
                continue
            try:
                mod = importlib.import_module(f"ci.strategies.{name}")
            except Exception as e:
                logger.warning("加载 CI 策略模块 %s 失败: %s", name, e)
                continue
            for attr in dir(mod):
                cls = getattr(mod, attr)
                if (isinstance(cls, type) and issubclass(cls, CIStrategy)
                        and cls is not CIStrategy and not getattr(cls, "__abstractmethods__", None)):
                    # 只在"类定义所在模块 == 当前扫描模块"时才注册，
                    # 避免 default.py import WebCIStrategy 后 Web 被注册两次
                    if getattr(cls, "__module__", "") != mod.__name__:
                        continue
                    if cls in seen_classes:
                        continue
                    seen_classes.add(cls)
                    try:
                        inst = cls()
                    except Exception as e:
                        logger.warning("CI 策略 %s 实例化失败: %s", cls.__name__, e)
                        continue
                    if inst.name == "default":
                        self._default = inst
                    else:
                        self._strategies.append(inst)

        # 按 priority 降序
        self._strategies.sort(key=lambda s: s.priority, reverse=True)

        names = [f"{s.name}(p={s.priority})" for s in self._strategies]
        if self._default:
            names.append(f"{self._default.name}(default)")
        logger.info("🎯 CI 策略加载完成 (%d): %s", len(self._strategies), names)

    @staticmethod
    def _traits_match(traits: Set[str], required: Dict) -> bool:
        """跟 sop.loader._fragment_matches 的 traits 部分对齐"""
        if not required:
            return True
        all_of = required.get("all_of") or []
        any_of = required.get("any_of") or []
        none_of = required.get("none_of") or []
        if all_of and not all(t in traits for t in all_of):
            return False
        if any_of and not any(t in traits for t in any_of):
            return False
        if none_of and any(t in traits for t in none_of):
            return False
        return True

    async def pick_for_project(self, project_id: str) -> CIStrategy:
        """根据项目 traits 选择策略，按 priority 降序第一个匹配的"""
        self.load_all()

        proj = await db.fetch_one(
            "SELECT traits FROM projects WHERE id = ?", (project_id,)
        )
        traits_raw = (proj or {}).get("traits") or "[]"
        try:
            traits_list = json.loads(traits_raw) if isinstance(traits_raw, str) else list(traits_raw)
        except Exception:
            traits_list = []
        if not isinstance(traits_list, list):
            traits_list = []
        traits_set: Set[str] = {str(t).strip() for t in traits_list if str(t).strip()}

        for s in self._strategies:
            if self._traits_match(traits_set, s.required_traits or {}):
                logger.debug("项目 %s traits=%s → 策略 %s", project_id[:8], sorted(traits_set), s.name)
                return s

        # 兜底
        if self._default is None:
            raise RuntimeError(
                "无可用 CI 策略（连 default 都没注册）——检查 ci/strategies/default.py"
            )
        logger.debug("项目 %s traits=%s → 无策略命中，走 default", project_id[:8], sorted(traits_set))
        return self._default

    def all_strategies(self) -> List[CIStrategy]:
        """列出所有注册的策略（调试 / 管理 UI 用）"""
        self.load_all()
        out = list(self._strategies)
        if self._default:
            out.append(self._default)
        return out


# 全局单例
ci_loader = CIStrategyLoader()
