"""artifacts —— 产物总线（kind 词表 + ArtifactStore + consumes 注入）。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.2 / §3.6
"""
from artifacts.injector import (  # noqa: F401
    build_consume_context,
    render_artifacts_prompt,
)
from artifacts.kinds import (  # noqa: F401
    KindLintResult,
    KindRegistryError,
    KindSpec,
    builtin_kinds,
    get_kind,
    is_registered,
    lint_kind_refs,
    load_kinds,
    reload_kinds,
    validate_kind,
)
from artifacts.store import (  # noqa: F401
    ArtifactRef,
    ArtifactStore,
    ArtifactStoreError,
    artifact_dir,
    artifact_store,
)

__all__ = [
    # kinds
    "KindLintResult",
    "KindRegistryError",
    "KindSpec",
    "builtin_kinds",
    "get_kind",
    "is_registered",
    "lint_kind_refs",
    "load_kinds",
    "reload_kinds",
    "validate_kind",
    # store
    "ArtifactRef",
    "ArtifactStore",
    "ArtifactStoreError",
    "artifact_dir",
    "artifact_store",
    # injector
    "build_consume_context",
    "render_artifacts_prompt",
]
