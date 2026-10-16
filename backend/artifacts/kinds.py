"""Artifact Kind 注册表 —— 加载 / 校验 kinds.yaml，给 skill 声明做 lint。

词表本身在同目录的 kinds.yaml，设计理由写在那个文件的头部注释里。
本模块只负责：加载 + 规范校验 + 对外暴露查询/lint 接口。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.2
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("artifacts.kinds")

KINDS_FILE = Path(__file__).resolve().parent / "kinds.yaml"

# kind 命名规范：小写蛇形。拒绝 Content-Outline / contentOutline / content.outline
_KIND_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# storage 合法取值，语义见 kinds.yaml 头部
_STORAGE_VALUES = ("file", "inline")


class KindRegistryError(Exception):
    """词表本身有结构性错误（命名不合规 / storage 非法 / 文件损坏）。

    这类错误不降级 —— 词表坏了意味着所有 kind 校验都不可信，
    继续跑等于关掉三道闸里的两道。
    """


@dataclass(frozen=True)
class KindSpec:
    kind: str
    description: str = ""
    mime: str = ""
    storage: str = "file"
    builtin: bool = False        # 天然源，无需 producer
    legacy: bool = False         # 老 Agent 路径产出，新 skill 不得 produces
    binary: bool = False
    produced_by: str = ""        # 老产物的产出方（仅文档价值）

    @property
    def is_inline(self) -> bool:
        return self.storage == "inline"


def _parse_kinds(raw: Dict[str, Any]) -> Dict[str, KindSpec]:
    kinds_raw = raw.get("kinds")
    if not isinstance(kinds_raw, dict) or not kinds_raw:
        raise KindRegistryError(f"{KINDS_FILE} 缺少非空的 kinds 映射")

    specs: Dict[str, KindSpec] = {}
    errors: List[str] = []

    for name, body in kinds_raw.items():
        if not _KIND_RE.match(str(name)):
            errors.append(f"kind '{name}' 不符合命名规范（小写蛇形 ^[a-z][a-z0-9_]*$）")
            continue
        body = body or {}
        if not isinstance(body, dict):
            errors.append(f"kind '{name}' 的定义必须是映射，实际是 {type(body).__name__}")
            continue

        storage = str(body.get("storage") or "file")
        if storage not in _STORAGE_VALUES:
            errors.append(
                f"kind '{name}' 的 storage='{storage}' 非法，只能是 {_STORAGE_VALUES}"
            )
            continue

        spec = KindSpec(
            kind=str(name),
            description=str(body.get("description") or "").strip(),
            mime=str(body.get("mime") or ""),
            storage=storage,
            builtin=bool(body.get("builtin")),
            legacy=bool(body.get("legacy")),
            binary=bool(body.get("binary")),
            produced_by=str(body.get("produced_by") or ""),
        )

        # builtin 的语义是「天然源」—— 框架自动产出，不该同时是老 Agent 的产物
        if spec.builtin and spec.legacy:
            errors.append(f"kind '{name}' 同时是 builtin 和 legacy，语义冲突")
            continue

        specs[spec.kind] = spec

    if errors:
        raise KindRegistryError(
            f"{KINDS_FILE} 存在 {len(errors)} 处问题:\n  - " + "\n  - ".join(errors)
        )
    return specs


@lru_cache(maxsize=1)
def load_kinds() -> Dict[str, KindSpec]:
    """加载并缓存词表。文件缺失或结构错误 → raise（不降级，见 KindRegistryError）。"""
    import yaml

    if not KINDS_FILE.is_file():
        raise KindRegistryError(f"kind 词表不存在: {KINDS_FILE}")
    try:
        raw = yaml.safe_load(KINDS_FILE.read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise KindRegistryError(f"解析 {KINDS_FILE} 失败: {e}") from e

    specs = _parse_kinds(raw)
    logger.info("📦 artifact kind 词表已加载: %d 个（builtin %d / legacy %d）",
                len(specs),
                sum(1 for s in specs.values() if s.builtin),
                sum(1 for s in specs.values() if s.legacy))
    return specs


def reload_kinds() -> Dict[str, KindSpec]:
    """清缓存重载。给测试和热更新用。"""
    load_kinds.cache_clear()
    return load_kinds()


def get_kind(kind: str) -> Optional[KindSpec]:
    return load_kinds().get(kind)


def is_registered(kind: str) -> bool:
    return kind in load_kinds()


def builtin_kinds() -> Set[str]:
    """天然源集合 —— 组装器视为「已就绪」，不需要任何 skill produces。"""
    return {k for k, s in load_kinds().items() if s.builtin}


def validate_kind(kind: str) -> KindSpec:
    """写入期闸门（第 2 道）。未注册直接 raise —— 不要降级成 warning。

    调用方是 ArtifactStore.put。此处失败意味着「某个 skill 产出了一个
    词表里没有的东西」，继续写入会让该产物永远不被任何 consumes 匹配到。
    """
    spec = get_kind(kind)
    if spec is None:
        known = ", ".join(sorted(load_kinds()))
        raise KindRegistryError(
            f"未注册的 artifact kind: '{kind}'。"
            f"请先在 {KINDS_FILE.name} 登记。已注册: {known}"
        )
    return spec


# ──────────────────────────── skill 声明 lint ────────────────────────────

@dataclass
class KindLintResult:
    """lint 结果。errors 非空 = 该 skill 不得参与组装。"""
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def lint_kind_refs(
    skill_id: str,
    consumes: List[str],
    produces: List[str],
) -> KindLintResult:
    """校验一个 skill 的 kind 引用。

    调用方：discover_workflow_skills（第 1 道闸）。errors 非空时该 skill 出局，
    并以 **ERROR** 级别打日志 —— 不是 warning。trait_taxonomy.yaml 的教训是
    「warning 没人看」，静默降级等于没有校验。

    规则：
      E1 未注册的 kind（consumes / produces 都查）
      E2 produces 了 inline kind —— ArtifactStore 只写文件，老读取方
         （`WHERE type='prd'` 取 content 列）拿不到，是静默断链
      E3 produces 了 builtin kind —— 天然源由框架产出，skill 覆盖它会让
         拓扑图出现「源头被改写」的歧义
      E4 同一 kind 既 consumes 又 produces —— 自环，拓扑排序必然检出环并
         导致整条链不组装。在这里拦下来报错更清楚
      W1 produces 为空 —— 合法（只读校验类 skill），但在链里是叶子节点，提示一下
    """
    res = KindLintResult()
    registry = load_kinds()

    for kind in consumes:
        if kind not in registry:
            res.errors.append(
                f"skill '{skill_id}' consumes 未注册的 kind '{kind}'"
            )

    for kind in produces:
        spec = registry.get(kind)
        if spec is None:
            res.errors.append(
                f"skill '{skill_id}' produces 未注册的 kind '{kind}'"
            )
            continue
        if spec.is_inline:
            res.errors.append(
                f"skill '{skill_id}' produces inline kind '{kind}' —— "
                f"inline 产物存在 artifacts.content 列（老 Agent 路径），"
                f"ArtifactStore 只写文件，下游 `WHERE type='{kind}'` 取 content 会落空"
            )
        if spec.builtin:
            res.errors.append(
                f"skill '{skill_id}' produces builtin kind '{kind}' —— "
                f"天然源由框架自动产出，skill 不得覆盖"
            )

    overlap = sorted(set(consumes) & set(produces))
    if overlap:
        res.errors.append(
            f"skill '{skill_id}' 的 {overlap} 既 consumes 又 produces —— "
            f"自环会让整条 skill 链因检出环而全部不组装"
        )

    if not produces:
        res.warnings.append(
            f"skill '{skill_id}' 未声明 produces —— 在依赖图里是叶子节点，"
            f"不会有任何下游消费它"
        )
    return res
