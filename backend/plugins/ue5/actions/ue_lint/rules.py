"""UE DevAgent 自测 Layer 1：7 条静态规则

每条规则独立函数，签名：
    rule_Rx(file_content, file_path_rel, repo_path, ctx) -> List[Issue]

主入口 `run_all_rules(files_written, repo_path, ctx)` 串起所有规则。

Issue 结构（跨规则统一）：
    {
        "rule": "R1",          # 稳定 id，前端 UI 用
        "file": "Source/X.h",  # 相对 repo 根的路径
        "line": 42 | None,
        "blocking": True,      # 阻塞就不能推进 stage
        "category": "uclass",  # 粗分类
        "msg": "...",          # 给 Reflexion prompt 用的人类可读说明
        "suggest": "...",      # 建议修法（可空）
    }
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from plugins.ue5.actions.ue_lint.data import (
    UE_PARENT_ONREP_METHODS,
    UE_INCLUDE_ORDER_VALID,
    UE_INCLUDE_ORDER_DEPRECATED,
    UE_TYPE_REQUIRED_HEADERS,
    all_known_modules_5_3,
)

logger = logging.getLogger("actions.ue_lint.rules")

Issue = Dict[str, Any]

# 默认按 5.3 跑；context 里有 ue_engine_version 时会覆盖
DEFAULT_ENGINE_MAJOR_MINOR = "5.3"


# ==================== 辅助函数 ====================


def _engine_major_minor(ctx: Dict[str, Any]) -> str:
    v = (ctx.get("ue_engine_version") or "").strip()
    if not v:
        return DEFAULT_ENGINE_MAJOR_MINOR
    m = re.match(r"^(\d+)\.(\d+)", v)
    if not m:
        return DEFAULT_ENGINE_MAJOR_MINOR
    return f"{m.group(1)}.{m.group(2)}"


def _module_root_for_file(repo_path: Path, file_path_rel: str) -> Optional[Path]:
    """给定 .h/.cpp 文件，返回其所属模块的 Source 根（含 Build.cs 的那级目录）"""
    p = (repo_path / file_path_rel).resolve()
    # 向上找到含 *.Build.cs 的第一级
    cur = p.parent
    root = repo_path.resolve()
    while cur != cur.parent and cur.is_relative_to(root):
        for child in cur.glob("*.Build.cs"):
            return cur
        cur = cur.parent
    return None


def _strip_line_comment(line: str) -> str:
    """粗暴去掉 // 开头的行注释（对 /* */ 不处理，不影响我们规则）"""
    idx = line.find("//")
    if idx >= 0:
        return line[:idx]
    return line


def _split_comment_stripped_lines(content: str) -> List[str]:
    return [_strip_line_comment(l) for l in content.splitlines()]


def _is_skipped_by_escape(line: str, rule_id: str) -> bool:
    """允许代码里 `// @ue-lint-skip R2` 逃生注释"""
    return f"@ue-lint-skip {rule_id}" in line


# ==================== R1: UCLASS / USTRUCT / UINTERFACE 必有 GENERATED_BODY ====================


_RE_UCLASS_DECL = re.compile(r"^\s*(UCLASS|USTRUCT|UINTERFACE)\s*(\(.*?\))?\s*$", re.MULTILINE)
_RE_GEN_BODY = re.compile(
    r"GENERATED_(BODY|UCLASS_BODY|USTRUCT_BODY|IINTERFACE_BODY|UINTERFACE_BODY)\s*\(\s*\)"
)
_RE_CLASS_BRACE = re.compile(r"^\s*(class|struct)\b")


def rule_R1_uclass_genbody(
    content: str, file_path_rel: str, repo_path: Path, ctx: Dict[str, Any]
) -> List[Issue]:
    """UCLASS / USTRUCT / UINTERFACE 声明后 N 行内必须有 GENERATED_BODY()"""
    if not file_path_rel.endswith(".h"):
        return []
    issues: List[Issue] = []
    lines = content.splitlines()

    for m in _RE_UCLASS_DECL.finditer(content):
        line_no = content[:m.start()].count("\n") + 1
        macro = m.group(1)
        # 检查宏声明之后最多 10 行内有没有 GENERATED_BODY 出现
        scan_end = min(line_no + 10, len(lines))
        block = "\n".join(lines[line_no - 1:scan_end])
        if _is_skipped_by_escape(block, "R1"):
            continue
        if not _RE_GEN_BODY.search(block):
            issues.append({
                "rule": "R1",
                "file": file_path_rel,
                "line": line_no,
                "blocking": True,
                "category": "uclass",
                "msg": f"{macro} 声明于 {file_path_rel}:{line_no}，但下面 10 行内未见 GENERATED_BODY()。UHT 会拒绝编译。",
                "suggest": "在 `class XXX : public YYY {` 之后紧跟一行 `GENERATED_BODY()`",
            })
    return issues


# ==================== R2: 子类 OnRep_* 不能有 UFUNCTION() 宏（父类已有该 OnRep 时）====================


# 匹配：class FOO_API AClassName : public AParentName {
_RE_CLASS_INHERIT = re.compile(
    r"class\s+(?:[A-Z_]+_API\s+)?[AUI]\w+\s*:\s*public\s+(A\w+|U\w+|I\w+)",
)
# 匹配 `UFUNCTION(...)` 紧跟 `void OnRep_XXX`
_RE_UFUNCTION_ONREP = re.compile(
    r"UFUNCTION\s*\([^)]*\)\s*\n\s*(?:virtual\s+)?void\s+(OnRep_\w+)\s*\(",
    re.MULTILINE,
)


def rule_R2_onrep_override(
    content: str, file_path_rel: str, repo_path: Path, ctx: Dict[str, Any]
) -> List[Issue]:
    """子类 override 父类 OnRep_* 时不能再加 UFUNCTION() 宏"""
    if not file_path_rel.endswith(".h"):
        return []
    # 找到第一个公共继承父类
    parent_match = _RE_CLASS_INHERIT.search(content)
    if not parent_match:
        return []
    parent = parent_match.group(1)
    # 父类 → 其 OnRep_* 方法白名单
    parent_onreps = set(UE_PARENT_ONREP_METHODS.get(parent, []))
    if not parent_onreps:
        return []

    issues: List[Issue] = []
    for m in _RE_UFUNCTION_ONREP.finditer(content):
        name = m.group(1)
        if name not in parent_onreps:
            continue
        # 看前面 1 行有没有 escape 注释
        line_no = content[:m.start()].count("\n") + 1
        # 检查代码片段里有没有 @ue-lint-skip R2
        snippet = content[max(0, m.start() - 100):m.end() + 20]
        if _is_skipped_by_escape(snippet, "R2"):
            continue
        issues.append({
            "rule": "R2",
            "file": file_path_rel,
            "line": line_no,
            "blocking": True,
            "category": "onrep-override",
            "msg": (
                f"{file_path_rel}:{line_no} 子类 {name}() 是 override 父类 {parent}::{name}，"
                f"不能加 UFUNCTION() 宏（UHT 会报 "
                f"'Override of UFUNCTION cannot have UFUNCTION() declaration above it'）"
            ),
            "suggest": f"把 `UFUNCTION()\\nvoid {name}();` 改成 `virtual void {name}() override;`",
        })
    return issues


# ==================== R3: #include 路径可定位 ====================


_RE_INCLUDE_QUOTED = re.compile(r'^\s*#include\s+"([^"]+)"')

# 常见 UE Engine header（CoreMinimal 等）—— 项目里不一定有，也不要抓
# 先用启发：如果 path 含 `/` 且不是项目本地的已知形式，跳过（大概率是 Engine header）
# 项目级 header 模式：
#   - "MyFile.h"（同级）
#   - "Subdir/MyFile.h"（本模块子目录）
#   - "MyModule/Public/MyFile.h"（跨模块）

def rule_R3_include_paths(
    content: str, file_path_rel: str, repo_path: Path, ctx: Dict[str, Any]
) -> List[Issue]:
    """#include "XXX.h" 路径必须能在本模块或其他模块找到"""
    if not file_path_rel.endswith((".h", ".cpp")):
        return []

    issues: List[Issue] = []
    module_root = _module_root_for_file(repo_path, file_path_rel)
    if module_root is None:
        return []

    # 准备"同模块 .h 全路径索引" + "跨模块 Public 索引"
    module_headers: Dict[str, List[Path]] = {}   # basename → candidates
    for p in module_root.rglob("*.h"):
        module_headers.setdefault(p.name, []).append(p)

    cross_module_public: Dict[str, List[Path]] = {}
    source_root = repo_path / "Source"
    if source_root.is_dir():
        for p in source_root.rglob("Public/*.h"):
            cross_module_public.setdefault(p.name, []).append(p)
        for p in source_root.rglob("Public/**/*.h"):
            cross_module_public.setdefault(p.name, []).append(p)

    # 跨文件类型：.cpp 和 .h 的 include 都扫
    lines = content.splitlines()
    for i, raw in enumerate(lines, 1):
        stripped = _strip_line_comment(raw)
        m = _RE_INCLUDE_QUOTED.match(stripped)
        if not m:
            continue
        if _is_skipped_by_escape(raw, "R3"):
            continue
        inc = m.group(1)
        if "/" in inc:
            # 带路径的 include：只校验能不能在 cross_module_public 或 Engine 的 Components/ 等（我们不抓）
            # 简化：带路径就信任（大部分是 UE Engine 的 "Engine/World.h" / "Components/..."）
            continue
        # 无路径前缀的 include "Xxx.h" —— 看同模块能不能找
        header_name = inc
        # UE 自己的 CoreMinimal.h 也在此格式走，但 UE_IncludeMap 不好判；
        # 只要 header_name 不是 "CoreMinimal.h" / "Xxx.generated.h"，且本模块 / 跨模块都找不到 → blocking
        if header_name in ("CoreMinimal.h",):
            continue
        if header_name.endswith(".generated.h"):
            continue

        found_in_module = header_name in module_headers
        # 无路径前缀的 `#include "Xxx.h"` 何时合法，按 C++ / UBT 的实际解析顺序判：
        #   ① 引用方所在目录（quoted include 的相对查找）—— 永远命中
        #   ② UBT 加进 include 搜索路径的锚点：模块的 Public/ 与 Private/ 根
        # 模块根目录本身**不是**锚点（flat layout 也不是），见下方注释。
        if found_in_module:
            paths = module_headers[header_name]
            public = module_root / "Public"
            private = module_root / "Private"
            try:
                includer_dir = (repo_path / file_path_rel).resolve().parent
            except Exception:
                includer_dir = None
            ok = False
            for p in paths:
                # ① 与引用方同级 —— 相对查找直接命中。
                #
                # 这里曾经写的是「头文件位于模块根目录就放行」（理由：flat layout
                # 下 UBT 会把模块根加进 include 路径）。那个前提是错的：flat layout
                # 的同级引用能过，靠的是 quoted include 的相对查找，不是 include 路径。
                # 于是子目录引用方被误放行 —— Source/TestFPS/Tests/ 里写
                # #include "SprintComponent.h"（头在 Source/TestFPS/ 下）lint 报 0 issue，
                # 真编译 C1083。反过来同级的 Tests/Helper.h ← Tests/Foo.cpp 又被误报，
                # 且 suggest 与原文逐字相同，DevAgent 拿到无从下手，只能空转到 blocked。
                # 换成「与引用方同级」两头都对。
                try:
                    if includer_dir is not None and p.resolve().parent == includer_dir:
                        ok = True
                        break
                except Exception:
                    pass
                try:
                    # ② Public / Private 根目录下的直接文件 = OK
                    rel = p.resolve().relative_to(public.resolve()) if public.exists() else None
                    if rel is not None and rel.parent == Path("."):
                        ok = True
                        break
                except Exception:
                    pass
                try:
                    rel2 = p.resolve().relative_to(private.resolve()) if private.exists() else None
                    if rel2 is not None and rel2.parent == Path("."):
                        ok = True
                        break
                except Exception:
                    pass
            if not ok:
                # 头文件既不与引用方同级，也不在 Public/Private 根 → 给出可直接照抄的写法
                first = paths[0]
                suggest = None
                # 有 Public/Private 分层时，相对锚点的路径才是 UE 的惯用写法
                for anchor in (public, private):
                    if anchor.exists():
                        try:
                            suggest = first.resolve().relative_to(
                                anchor.resolve()).as_posix()
                            break
                        except Exception:
                            pass
                if suggest is None and includer_dir is not None:
                    # flat layout：给相对路径（如 "../SprintComponent.h"）。
                    # 不能退化成 first.name —— 那跟原文一模一样，等于没给建议。
                    try:
                        suggest = os.path.relpath(
                            str(first.resolve()), str(includer_dir),
                        ).replace("\\", "/")
                    except Exception:
                        pass
                if suggest is None:
                    suggest = first.name
                issues.append({
                    "rule": "R3",
                    "file": file_path_rel,
                    "line": i,
                    "blocking": True,
                    "category": "include-path",
                    "msg": (
                        f"{file_path_rel}:{i} #include \"{inc}\" 与引用方不同级，"
                        f"也不在模块 Public/ 或 Private/ 根下（UBT 的 include 锚点）；"
                        f"头文件实际位于 {first.relative_to(repo_path).as_posix()}"
                    ),
                    "suggest": f'应改成 #include "{suggest}"',
                })
            continue

        # 跨模块 Public
        if header_name in cross_module_public:
            # 跨模块的 include 必须带路径前缀，不带就找不到
            first = cross_module_public[header_name][0]
            # 找到该 header 所在 Public 下的相对路径
            rel = None
            for p in cross_module_public[header_name]:
                try:
                    for anchor in p.parents:
                        if anchor.name == "Public":
                            rel = p.resolve().relative_to(anchor.resolve()).as_posix()
                            break
                    if rel:
                        break
                except Exception:
                    pass
            issues.append({
                "rule": "R3",
                "file": file_path_rel,
                "line": i,
                "blocking": True,
                "category": "include-path-cross-module",
                "msg": f"{file_path_rel}:{i} #include \"{inc}\" 在本模块找不到；跨模块头需带路径",
                "suggest": f'应改成 #include "{rel or header_name}"（并在 Build.cs 加上对应模块依赖）',
            })
            continue

        # 彻底找不到 —— 但"找不到"只是"在项目 Source/ 里找不到"。
        # 引擎头（TimerManager.h）和插件头（EnhancedInputComponent.h 等）都不在
        # 项目里，UBT 靠模块 include 路径解析，无路径前缀的写法完全合法。
        # 实测 TestFPS：UBT 编译只报 2 个错，而这里曾误报 8 个 blocking，
        # 且全是引擎/插件头 —— 会把能编过的工单打回 fix_issues 空转到 blocked。
        # 判不了就别判：降级为 warning，交给下游 engine_compile 用真实编译定性。
        known_external = _is_known_engine_or_plugin_header(header_name)
        issues.append({
            "rule": "R3",
            "file": file_path_rel,
            "line": i,
            "blocking": False,
            "category": "include-not-found",
            "msg": (
                f"{file_path_rel}:{i} #include \"{inc}\" 在项目 Source/ 内找不到。"
                + ("已知的引擎/插件头，通常正常（需确认 Build.cs 有对应模块依赖）"
                   if known_external else
                   "若非引擎/插件头则可能是笔误；真实存在性由 engine_compile 阶段判定")
            ),
            "suggest": None,
        })

    return issues


def _is_known_engine_or_plugin_header(header_name: str) -> bool:
    """该 header 是否为已知的引擎/插件头（出现在 R7 的类型→header 映射值里）。

    仅用于把 R3 的提示语说得更准，不影响 blocking 判定（一律 False）。
    """
    try:
        from plugins.ue5.actions.ue_lint.data import UE_TYPE_REQUIRED_HEADERS
    except Exception:
        return False
    for h in UE_TYPE_REQUIRED_HEADERS.values():
        if h == header_name or h.endswith("/" + header_name):
            return True
    return False


# ==================== R4: Build.cs 模块依赖有效 ====================


_RE_MODULE_DEPS = re.compile(
    r"(PublicDependencyModuleNames|PrivateDependencyModuleNames)\s*"
    r"\.\s*AddRange\s*\(\s*new\s+string\s*\[\s*\]\s*\{([^}]+)\}",
    re.DOTALL,
)
_RE_QUOTED_STR = re.compile(r'"([^"]+)"')


def rule_R4_build_cs_deps(
    content: str, file_path_rel: str, repo_path: Path, ctx: Dict[str, Any]
) -> List[Issue]:
    """Build.cs 里的模块依赖必须在白名单或本仓库 Source/ 下存在"""
    if not file_path_rel.endswith(".Build.cs"):
        return []

    # 收集本仓库所有本地模块名
    local_modules: Set[str] = set()
    source_root = repo_path / "Source"
    if source_root.is_dir():
        for p in source_root.rglob("*.Build.cs"):
            local_modules.add(p.stem)   # p.stem 对 "Foo.Build.cs" 是 "Foo.Build"
            # 更准确：去掉 .Build 后缀
            name = p.stem
            if name.endswith(".Build"):
                name = name[: -len(".Build")]
            local_modules.add(name)

    known = all_known_modules_5_3() | local_modules

    issues: List[Issue] = []
    for m in _RE_MODULE_DEPS.finditer(content):
        kind = m.group(1)
        body = m.group(2)
        for qm in _RE_QUOTED_STR.finditer(body):
            name = qm.group(1).strip()
            if not name:
                continue
            if name in known:
                continue
            line_no = content[:qm.start(1)].count("\n") + 1
            issues.append({
                "rule": "R4",
                "file": file_path_rel,
                "line": line_no,
                "blocking": False,   # 白名单不全，降级 warning 避免误报
                "category": "build-cs-unknown-module",
                "msg": (
                    f"{file_path_rel}:{line_no} {kind} 里的模块 \"{name}\" 不在 UE 5.3 "
                    f"内置模块 / 常见插件白名单，也不是本仓库本地模块。"
                    f"可能拼写错，或需要在 .uproject Plugins 启用对应插件"
                ),
                "suggest": None,
            })
    return issues


# ==================== R5: .uproject Modules ⊇ Source/ 模块 ====================


def rule_R5_uproject_modules(
    content: str, file_path_rel: str, repo_path: Path, ctx: Dict[str, Any]
) -> List[Issue]:
    """.uproject 的 Modules 数组必须覆盖 Source/ 下所有 *.Build.cs

    此规则每次 DevAgent 修改不触发（不依赖特定 file）——改在 run_all_rules 里兜底扫一次。
    """
    # 本函数入参的 content 其实用不上，我们直接扫仓库
    return []


def _run_R5_at_project_level(repo_path: Path, ctx: Dict[str, Any]) -> List[Issue]:
    import json as _json
    issues: List[Issue] = []

    up_files = list(repo_path.glob("*.uproject"))
    if not up_files:
        return []
    up_path = up_files[0]
    try:
        up_data = _json.loads(up_path.read_text(encoding="utf-8"))
    except Exception as e:
        return [{
            "rule": "R5", "file": up_path.name, "line": None, "blocking": True,
            "category": "uproject-parse",
            "msg": f".uproject 解析失败: {e}",
            "suggest": None,
        }]

    declared_modules = {m.get("Name", "") for m in (up_data.get("Modules") or []) if m.get("Name")}

    # 扫 Source/ 下的模块
    source_root = repo_path / "Source"
    if not source_root.is_dir():
        return []
    actual_modules: Set[str] = set()
    for p in source_root.rglob("*.Build.cs"):
        name = p.stem
        if name.endswith(".Build"):
            name = name[: -len(".Build")]
        actual_modules.add(name)

    # Source 有但 .uproject 没声明 → blocking
    missing = actual_modules - declared_modules
    for name in sorted(missing):
        issues.append({
            "rule": "R5",
            "file": up_path.name,
            "line": None,
            "blocking": True,
            "category": "uproject-missing-module",
            "msg": (
                f"Source/ 下有模块 \"{name}\"（{name}.Build.cs 存在）但 .uproject 里未声明。"
                f"UBT 不会编译该模块，相关 C++ 代码会找不到"
            ),
            "suggest": (
                f'在 {up_path.name} 的 "Modules" 数组里加入 '
                f'{{"Name": "{name}", "Type": "Runtime", "LoadingPhase": "Default"}}'
            ),
        })

    # R5b：插件与代码一致性——代码里 #include 了某插件头但 .uproject 没启用该插件
    # 只检查最常见的：StateTree / GameplayStateTree / EnhancedInput
    _PLUGIN_HEADER_MAP = {
        "StateTree": [
            "StateTree", "StateTreeExecutionContext", "StateTreeTaskBase",
            "StateTreeConditionBase", "StateTreeAIComponent",
        ],
        "GameplayStateTree": ["GameplayStateTree"],
        "EnhancedInput": [
            "EnhancedInputComponent", "EnhancedInputSubsystems",
            "InputAction", "InputMappingContext", "InputActionValue",
        ],
    }
    declared_plugins: Set[str] = {
        p.get("Name", "") for p in (up_data.get("Plugins") or [])
        if p.get("Enabled") is not False
    }
    for plugin_name, header_keywords in _PLUGIN_HEADER_MAP.items():
        if plugin_name in declared_plugins:
            continue
        # 扫 Source/ 下所有 .h/.cpp 的 #include 是否用到这些头
        used_in: List[str] = []
        for p in source_root.rglob("*.[ch]pp"):
            try:
                raw = p.read_text(encoding="utf-8", errors="replace")
                if any(kw in raw for kw in header_keywords):
                    used_in.append(str(p.relative_to(repo_path).as_posix()))
                    if len(used_in) >= 3:
                        break
            except Exception:
                pass
        if not source_root.rglob("*.[h]"):
            for p in source_root.rglob("*.h"):
                try:
                    raw = p.read_text(encoding="utf-8", errors="replace")
                    if any(kw in raw for kw in header_keywords):
                        used_in.append(str(p.relative_to(repo_path).as_posix()))
                        if len(used_in) >= 3:
                            break
                except Exception:
                    pass
        if used_in:
            issues.append({
                "rule": "R5b",
                "file": up_path.name,
                "line": None,
                "blocking": True,
                "category": "uproject-missing-plugin",
                "msg": (
                    f"代码里使用了 {plugin_name} 插件的头文件 "
                    f"（{used_in[0]} 等），但 .uproject 没有启用 {plugin_name} 插件。"
                    f"UBT 编译时找不到对应模块"
                ),
                "suggest": (
                    f'在 {up_path.name} 的 "Plugins" 数组里加入 '
                    f'{{"Name": "{plugin_name}", "Enabled": true}}'
                ),
            })
    return issues


# ==================== R6: Target.cs IncludeOrderVersion 兼容 ====================


_RE_INCLUDE_ORDER = re.compile(
    r"IncludeOrderVersion\s*=\s*EngineIncludeOrderVersion\.(\w+)"
)


def rule_R6_include_order(
    content: str, file_path_rel: str, repo_path: Path, ctx: Dict[str, Any]
) -> List[Issue]:
    """Target.cs 的 IncludeOrderVersion 必须跟引擎版本兼容"""
    if not file_path_rel.endswith(".Target.cs"):
        return []
    m = _RE_INCLUDE_ORDER.search(content)
    if not m:
        return []
    order = m.group(1)
    line_no = content[:m.start()].count("\n") + 1

    engine_ver = _engine_major_minor(ctx)
    valid = UE_INCLUDE_ORDER_VALID.get(engine_ver)
    if valid is None:
        return []   # 未知 UE 版本不校验

    deprecated = UE_INCLUDE_ORDER_DEPRECATED.get(engine_ver, set())

    issues: List[Issue] = []
    if order not in valid:
        issues.append({
            "rule": "R6",
            "file": file_path_rel,
            "line": line_no,
            "blocking": True,
            "category": "target-include-order",
            "msg": (
                f"{file_path_rel}:{line_no} IncludeOrderVersion=Unreal{order.replace('Unreal', '')} "
                f"在 UE {engine_ver} 已移除；合法值: {sorted(valid)}"
            ),
            "suggest": f"改为 EngineIncludeOrderVersion.Unreal{engine_ver.replace('.', '_')}",
        })
    elif order in deprecated:
        issues.append({
            "rule": "R6",
            "file": file_path_rel,
            "line": line_no,
            "blocking": False,
            "category": "target-include-order-deprecated",
            "msg": (
                f"{file_path_rel}:{line_no} IncludeOrderVersion=Unreal{order.replace('Unreal', '')} "
                f"在 UE {engine_ver} 已 deprecated，后续版本会移除"
            ),
            "suggest": f"升级到 EngineIncludeOrderVersion.Unreal{engine_ver.replace('.', '_')}",
        })
    return issues


# ==================== R7: 常用类型必需 header ====================


_RE_TYPE_USAGE_PATTERNS = [
    # NewObject<UCapsuleComponent>
    re.compile(r"NewObject\s*<\s*(\w+)\s*>"),
    # CreateDefaultSubobject<UCapsuleComponent>
    re.compile(r"CreateDefaultSubobject\s*<\s*(\w+)\s*>"),
    # Cast<UCapsuleComponent>
    re.compile(r"Cast\s*<\s*(\w+)\s*>"),
    # GetComponentByClass<UCapsuleComponent>
    re.compile(r"GetComponentByClass\s*<\s*(\w+)\s*>"),
]


def rule_R7_type_headers(
    content: str, file_path_rel: str, repo_path: Path, ctx: Dict[str, Any]
) -> List[Issue]:
    """.cpp 里用到某 UE 类型的实例化调用但没 include 对应 header → blocking"""
    if not file_path_rel.endswith(".cpp"):
        return []

    # 已 include 的 header（只取 quoted include 的 basename 和带路径的）
    included_paths: Set[str] = set()
    included_names: Set[str] = set()
    for raw in content.splitlines():
        s = _strip_line_comment(raw)
        m = _RE_INCLUDE_QUOTED.match(s)
        if m:
            p = m.group(1)
            included_paths.add(p)
            included_names.add(Path(p).name)

    issues: List[Issue] = []
    seen_types: Set[str] = set()
    for pat in _RE_TYPE_USAGE_PATTERNS:
        for m in pat.finditer(content):
            tname = m.group(1)
            if tname in seen_types:
                continue
            required_header = UE_TYPE_REQUIRED_HEADERS.get(tname)
            if not required_header:
                continue
            header_name = Path(required_header).name
            # 已 include 了（全路径或 basename 任一匹配）
            if required_header in included_paths or header_name in included_names:
                continue
            seen_types.add(tname)
            line_no = content[:m.start()].count("\n") + 1
            snippet = content[max(0, m.start() - 100):m.end() + 50]
            if _is_skipped_by_escape(snippet, "R7"):
                continue
            # UE 的 SharedPCH 会预置 GameFramework/Engine 的核心类型，
            # 只看单文件 include 判不出真实可见性 —— 实测 TestFPS 的
            # FPSCharacter.cpp 未 include PlayerController.h 但编译通过，
            # 而 R7 判了 blocking。把 blocking 收窄到"PCH 覆盖不到"的类型，
            # 其余降级 warning，真值交给 engine_compile。
            is_pch_covered = tname in _PCH_LIKELY_COVERED_TYPES
            issues.append({
                "rule": "R7",
                "file": file_path_rel,
                "line": line_no,
                "blocking": not is_pch_covered,
                "category": "missing-type-header",
                "msg": (
                    f"{file_path_rel}:{line_no} 使用了 {tname} 但未 #include \"{required_header}\"。"
                    + ("该类型通常已由 SharedPCH 预置，多数情况可编过；"
                       "显式 include 更稳妥（IWYU）"
                       if is_pch_covered else "编译会报 C2027 (undefined type)")
                ),
                "suggest": f'文件顶部加 #include "{required_header}"',
            })
    return issues


# SharedPCH（CoreMinimal + Engine/UnrealEd PCH）通常已带进来的高频类型。
# 缺 include 属于 IWYU 风格问题，不该阻断流水线 —— 实测会把能编过的工单
# 打回 fix_issues 空转。真正的缺失由 UBT 编译报 C2027 定性。
_PCH_LIKELY_COVERED_TYPES: Set[str] = {
    "ACharacter", "APawn", "AActor", "APlayerController", "AController",
    "AGameMode", "AGameModeBase", "AGameState", "AGameStateBase", "APlayerState",
    "AHUD", "UWorld", "ULevel", "UGameInstance", "ULocalPlayer", "UEngine",
    "USceneComponent", "UActorComponent", "UPrimitiveComponent",
    "FTimerHandle", "FTimerManager",
}


# ==================== 主入口 ====================


def rule_R8_ue_file_types(
    content: str, file_path_rel: str, repo_path: Path, ctx: Dict[str, Any]
) -> List[Issue]:
    """UE 项目里不能写 Python/JS/Web 文件——防止 DevAgent 在修复循环里退化为 Web 代码

    常见场景：DevAgent fix_issues 第 N 次循环后"忘记"自己在 UE 项目里，
    开始生成 Python/Flask/JS 等非 UE 文件。Layer 1 立刻拦截。
    """
    _FORBIDDEN_EXTS = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".vue",
        ".json",   # 允许例外：.uproject / .uplugin 是 JSON，但它们不在 Source/ 里
        ".rb", ".go", ".java", ".php", ".rs",
    }
    _ALLOWED_JSON_PATTERNS = {".uproject", ".uplugin", ".json"}  # uasset 目录的 JSON 保留

    path = Path(file_path_rel)
    ext = path.suffix.lower()
    if ext not in _FORBIDDEN_EXTS:
        return []

    # .json 允许 .uproject / .uplugin 及 Config/ 目录
    if ext == ".json":
        name = path.name.lower()
        if name.endswith((".uproject", ".uplugin")):
            return []
        if "config" in str(path).lower() or "settings" in str(path).lower():
            return []

    # Python 特征加强判断：文件内容含 import flask / import django / def main() 等
    _PYTHON_MARKERS = [
        "import flask", "import django", "from flask", "from django",
        "import fastapi", "import uvicorn", "import requests",
        "#!/usr/bin/env python", "if __name__ == '__main__'",
    ]
    if ext == ".py":
        has_marker = any(m in content for m in _PYTHON_MARKERS)
    else:
        has_marker = True  # 其他禁止扩展名直接报

    if not has_marker and ext == ".py":
        # 纯 Python 脚本但没有 Web 框架迹象：降级为 warning（可能是 UE Python 工具）
        return [{
            "rule": "R8",
            "file": file_path_rel,
            "line": None,
            "blocking": False,
            "category": "wrong-file-type",
            "msg": (
                f"UE 项目里写了 Python 文件 {file_path_rel}。"
                f"如果是 UE 自动化工具脚本可以忽略，否则可能是 DevAgent 写错了代码类型"
            ),
            "suggest": "UE C++ 项目应输出 .h/.cpp/.Build.cs/.Target.cs 文件，不是 Python",
        }]

    return [{
        "rule": "R8",
        "file": file_path_rel,
        "line": None,
        "blocking": True,
        "category": "wrong-file-type",
        "msg": (
            f"UE 项目里写了 {ext} 文件（{file_path_rel}）。"
            f"DevAgent 可能在修复循环里退化为 Web/Python 开发模式，"
            f"忘记当前是 Unreal Engine C++ 项目"
        ),
        "suggest": (
            "请重新生成 C++ 文件（.h/.cpp）来修复编译错误，"
            "不要生成 Python/JavaScript/HTML 等非 UE 文件"
        ),
    }]


# ==================== R9: 委托配对（AddDynamic 应有 RemoveDynamic） ====================

# AddDynamic(UserObject, &Class::Func) / RemoveDynamic(UserObject, &Class::Func)
# 提取 (委托对象名, 回调函数名)。回调名兼容 &UClass::Func 与 Func 两种写法。
_RE_ADD_DYNAMIC = re.compile(
    r"(\w+)\s*\.\s*AddDynamic\s*\(\s*[^,]+,\s*(?:&\w+::)?(\w+)"
)
_RE_REMOVE_DYNAMIC = re.compile(
    r"(\w+)\s*\.\s*RemoveDynamic\s*\(\s*[^,]+,\s*(?:&\w+::)?(\w+)"
)

# 跨对象生命周期委托（需要 RemoveDynamic 解绑）。R9 只检查这些——
# UI 组件委托（OnClicked/OnCheckStateChanged 等）随 owning widget 销毁，无需 Remove，
# 一刀切检查会大量误报（UE UMG 最常见模式）。
_LIFECYCLE_DELEGATES = {
    "OnDestroyed",
    "OnEndPlay",
    "OnDeath",
    "OnDied",
    "OnActorBeginOverlap",
    "OnActorEndOverlap",
    "OnTakeAnyDamage",
    "OnTakePointDamage",
    "OnComponentBeginOverlap",
    "OnComponentEndOverlap",
    "OnComponentHit",
    "OnHealthChanged",
}


def rule_R9_delegate_pairing(
    content: str, file_path_rel: str, repo_path: Path, ctx: Dict[str, Any]
) -> List[Issue]:
    """跨生命周期委托的 AddDynamic 应有配对 RemoveDynamic（委托泄漏 / 悬挂指针）。

    保守策略：只报 warning（非 blocking）。只检查「跨对象生命周期委托」
    （OnDestroyed/OnActorBeginOverlap 等白名单），UI 组件委托（OnClicked 等）
    随 owning widget 销毁无需解绑，跳过。按「委托对象 + 回调函数」粒度在
    文件内检查，有 Add 无 Remove 的绑定对 → warning。
    """
    if not file_path_rel.endswith((".h", ".cpp")):
        return []

    add_pairs: Dict[Tuple[str, str], int] = {}   # (委托, 回调) -> 首个行号
    remove_pairs: Set[Tuple[str, str]] = set()

    for m in _RE_ADD_DYNAMIC.finditer(content):
        delegate = m.group(1)
        if delegate not in _LIFECYCLE_DELEGATES:
            continue  # 非跨生命周期委托（UI 组件等），跳过
        line_no = content[:m.start()].count("\n") + 1
        # 检查匹配点前 120 字符（含上一行的逃生注释），对齐 R2 的 snippet 做法
        snippet = content[max(0, m.start() - 120):m.end() + 20]
        if _is_skipped_by_escape(snippet, "R9"):
            continue
        add_pairs.setdefault((delegate, m.group(2)), line_no)

    for m in _RE_REMOVE_DYNAMIC.finditer(content):
        remove_pairs.add((m.group(1), m.group(2)))

    issues: List[Issue] = []
    for (delegate, callback), line_no in add_pairs.items():
        if (delegate, callback) in remove_pairs:
            continue
        issues.append({
            "rule": "R9",
            "file": file_path_rel,
            "line": line_no,
            "blocking": False,
            "category": "delegate-pairing",
            "msg": (
                f"{delegate}.AddDynamic 绑定了 {callback}，但文件内未见配对 RemoveDynamic。"
                f"对象销毁后可能悬挂指针"
            ),
            "suggest": (
                f"在析构函数 / EndPlay 里调用 {delegate}.RemoveDynamic 解绑；"
                f"若绑定到永久对象可加 @ue-lint-skip R9 逃生注释"
            ),
        })
    return issues


# ==================== R10: 交互回调空引用守卫（IsValid） ====================

# BindAction("Name", IE_Pressed, this, &Class::Func) → 回调名 Func
_RE_BIND_ACTION = re.compile(
    r"BindAction\s*\(\s*[^,]+,\s*[^,]+,\s*[^,]+,\s*(?:&\w+::)?(\w+)"
)


def _find_func_body(content: str, func_name: str) -> Optional[str]:
    """找到 `返回类型 类名::函数名(...)` 的定义体（从 { 到匹配 }）。找不到返回 None。"""
    pattern = re.compile(
        r"\w+\s+\w+::" + re.escape(func_name) + r"\s*\([^)]*\)\s*(?:const\s*)?(?:override\s*)?\{"
    )
    m = pattern.search(content)
    if not m:
        return None
    brace_start = content.index("{", m.start())
    depth = 0
    for i in range(brace_start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                return content[brace_start:i + 1]
    return None


def _collect_interaction_callbacks(content: str, rule_id: str) -> Dict[str, int]:
    """收集 AddDynamic / BindAction 绑定的交互回调名 → 绑定处行号。"""
    callbacks: Dict[str, int] = {}
    for m in _RE_ADD_DYNAMIC.finditer(content):
        line_no = content[:m.start()].count("\n") + 1
        snippet = content[max(0, m.start() - 120):m.end() + 20]
        if _is_skipped_by_escape(snippet, rule_id):
            continue
        callbacks.setdefault(m.group(2), line_no)
    for m in _RE_BIND_ACTION.finditer(content):
        line_no = content[:m.start()].count("\n") + 1
        snippet = content[max(0, m.start() - 120):m.end() + 20]
        if _is_skipped_by_escape(snippet, rule_id):
            continue
        callbacks.setdefault(m.group(1), line_no)
    return callbacks


def rule_R10_null_guard(
    content: str, file_path_rel: str, repo_path: Path, ctx: Dict[str, Any]
) -> List[Issue]:
    """交互回调（AddDynamic / BindAction 绑定的函数）访问其他对象指针时应有 IsValid 守卫。

    保守策略：只报 warning。只关心「非 this 的对象指针访问」——回调只访问 this
    成员（ClickCount++ 或 this->X）无空引用风险，跳过；访问其他对象指针
    （X->Y，X 非 this）时若无 IsValid → warning。
    """
    if not file_path_rel.endswith((".h", ".cpp")):
        return []

    callbacks = _collect_interaction_callbacks(content, "R10")
    if not callbacks:
        return []

    issues: List[Issue] = []
    for cb, line_no in sorted(callbacks.items(), key=lambda x: x[1]):
        body = _find_func_body(content, cb)
        if body is None:
            continue  # 回调定义不在本文件（跨文件），跳过
        # 提取所有 X-> 指针访问，排除 this->（this 成员无空引用风险）
        pointer_accesses = set(re.findall(r"(\w+)\s*->", body))
        non_this = pointer_accesses - {"this"}
        if not non_this:
            continue  # 只访问 this 成员，无空引用风险
        if "IsValid" in body:
            continue
        issues.append({
            "rule": "R10",
            "file": file_path_rel,
            "line": line_no,
            "blocking": False,
            "category": "null-guard",
            "msg": (
                f"交互回调 {cb}() 体内未发现 IsValid 空引用守卫。"
                f"回调里访问其他 Actor/对象前应检查 IsValid，防止对象已销毁导致崩溃"
            ),
            "suggest": (
                f"在 {cb}() 里访问其他对象前加 if (IsValid(X)) 守卫；"
                f"若确认无需守卫可加 @ue-lint-skip R10 逃生注释"
            ),
        })
    return issues


# ==================== R11: 交互回调递归（回调体内调用自身） ====================


def rule_R11_recursive_callback(
    content: str, file_path_rel: str, repo_path: Path, ctx: Dict[str, Any]
) -> List[Issue]:
    """交互回调（AddDynamic / BindAction 绑定）体内递归调用自身 → 无限递归风险。

    典型场景：OnClicked 回调里又触发一次 OnClicked（如按钮点击里模拟再次点击），
    可能导致无限递归 / 栈溢出。

    保守策略：只报 warning。仅检查「回调函数体内是否无参调用同名函数」，
    排除带参数的调用（函数重载）。
    """
    if not file_path_rel.endswith((".h", ".cpp")):
        return []

    callbacks = _collect_interaction_callbacks(content, "R11")
    if not callbacks:
        return []

    issues: List[Issue] = []
    for cb, line_no in sorted(callbacks.items(), key=lambda x: x[1]):
        body = _find_func_body(content, cb)
        if body is None:
            continue  # 回调定义不在本文件，跳过
        # body 从 { 开始不含函数签名，所以 body 里的 cb() 都是调用（含递归）。
        # 只匹配无参调用 \(\s*\)，排除带参数的同名调用（函数重载）。
        if re.search(r"\b" + re.escape(cb) + r"\s*\(\s*\)", body):
            issues.append({
                "rule": "R11",
                "file": file_path_rel,
                "line": line_no,
                "blocking": False,
                "category": "recursive-callback",
                "msg": (
                    f"交互回调 {cb}() 体内递归调用了自身，"
                    f"可能导致无限递归 / 栈溢出"
                ),
                "suggest": (
                    f"检查 {cb}() 里是否无意间再次触发了 {cb}；"
                    f"若为有意的有限递归可加 @ue-lint-skip R11 逃生注释"
                ),
            })
    return issues


# ==================== R12: Timer 配对（SetTimer 应有 ClearTimer） ====================

# SetTimer(TimerHandle, ...) / ClearTimer(TimerHandle)
_RE_SET_TIMER = re.compile(r"SetTimer\s*\(\s*(\w+)")
_RE_CLEAR_TIMER = re.compile(r"ClearTimer\s*\(\s*(\w+)")


def rule_R12_timer_pairing(
    content: str, file_path_rel: str, repo_path: Path, ctx: Dict[str, Any]
) -> List[Issue]:
    """SetTimer 应有配对 ClearTimer（Timer 泄漏 / 悬挂指针）。

    循环 Timer 若不在析构 / EndPlay 里 ClearTimer，对象销毁后 Timer 仍会触发，
    导致悬挂指针崩溃。保守策略：只报 warning——一次性 Timer 无需 Clear，
    且跨文件 Clear 合法，所以按 TimerHandle 名粒度在文件内检查。
    """
    if not file_path_rel.endswith((".h", ".cpp")):
        return []

    set_handles: Dict[str, int] = {}   # handle 名 -> 首个行号
    clear_handles: Set[str] = set()

    for m in _RE_SET_TIMER.finditer(content):
        handle = m.group(1)
        line_no = content[:m.start()].count("\n") + 1
        snippet = content[max(0, m.start() - 120):m.end() + 20]
        if _is_skipped_by_escape(snippet, "R12"):
            continue
        set_handles.setdefault(handle, line_no)

    for m in _RE_CLEAR_TIMER.finditer(content):
        clear_handles.add(m.group(1))

    issues: List[Issue] = []
    for handle, line_no in set_handles.items():
        if handle in clear_handles:
            continue
        issues.append({
            "rule": "R12",
            "file": file_path_rel,
            "line": line_no,
            "blocking": False,
            "category": "timer-pairing",
            "msg": (
                f"SetTimer({handle}) 未见配对 ClearTimer({handle})，"
                f"对象销毁后循环 Timer 可能悬挂触发导致崩溃"
            ),
            "suggest": (
                f"在析构函数 / EndPlay 里 ClearTimer({handle})；"
                f"若为一次性 Timer 或跨文件 Clear，可加 @ue-lint-skip R12 逃生注释"
            ),
        })
    return issues


# ==================== R13: 弱引用解引用守卫（TWeakObjectPtr） ====================

# TWeakObjectPtr<Type> VarName 声明
_RE_WEAK_DECL = re.compile(r"TWeakObjectPtr\s*<\s*[^>]+\s*>\s*(\w+)")


def rule_R13_weak_ptr_guard(
    content: str, file_path_rel: str, repo_path: Path, ctx: Dict[str, Any]
) -> List[Issue]:
    """TWeakObjectPtr 解引用（-> 访问）前应有 IsValid / Get() 判空守卫。

    TWeakObjectPtr 不阻止 GC，对象可能已被回收。直接 `WeakVar->` 解引用会崩溃，
    必须先 `WeakVar.IsValid()` / `IsValid(WeakVar)` / `WeakVar.Get()` 判空。

    保守策略：只报 warning。检查解引用点前 200 字符内是否有守卫。
    """
    if not file_path_rel.endswith((".h", ".cpp")):
        return []

    # 1. 收集 TWeakObjectPtr 变量名
    weak_vars: Set[str] = set()
    for m in _RE_WEAK_DECL.finditer(content):
        weak_vars.add(m.group(1))

    if not weak_vars:
        return []

    issues: List[Issue] = []
    for var in sorted(weak_vars):
        deref_re = re.compile(r"\b" + re.escape(var) + r"\s*->")
        for m in deref_re.finditer(content):
            line_no = content[:m.start()].count("\n") + 1
            # 解引用点前 200 字符，看有没有判空守卫
            snippet = content[max(0, m.start() - 200):m.start()]
            if _is_skipped_by_escape(snippet, "R13"):
                continue
            # 守卫模式：IsValid(var) / var.IsValid() / var.Get()
            if re.search(r"IsValid\s*\(\s*" + re.escape(var) + r"\s*\)", snippet):
                continue
            if re.search(re.escape(var) + r"\s*\.\s*IsValid\s*\(\s*\)", snippet):
                continue
            if re.search(re.escape(var) + r"\s*\.\s*Get\s*\(\s*\)", snippet):
                continue
            issues.append({
                "rule": "R13",
                "file": file_path_rel,
                "line": line_no,
                "blocking": False,
                "category": "weak-ptr-guard",
                "msg": (
                    f"TWeakObjectPtr {var} 解引用（->）前未见 IsValid / Get() 判空守卫，"
                    f"对象可能已被 GC 回收导致崩溃"
                ),
                "suggest": (
                    f"解引用前加 if ({var}.IsValid()) 或 if ({var}.Get()) 判空；"
                    f"若确认对象一定存活可加 @ue-lint-skip R13 逃生注释"
                ),
            })
    return issues


# ==================== R14: UObject 指针成员缺 UPROPERTY ====================

# UObject 指针成员声明：U/A 开头的类型 + 指针 + 变量名 + 分号
_RE_UOBJECT_PTR_DECL = re.compile(r"\b([UA][A-Za-z0-9_]*)\s*\*\s*(\w+)\s*;")


def rule_R14_uproperty_missing(
    content: str, file_path_rel: str, repo_path: Path, ctx: Dict[str, Any]
) -> List[Issue]:
    """UObject 指针成员（Uxxx* / Axxx*）缺 UPROPERTY() 宏 → GC 悬挂指针。

    UObject 裸指针成员没有 UPROPERTY() 时 GC 不知晓该引用，可能回收对象导致
    悬挂指针。保守策略：只报 warning，且只检查头文件（成员声明通常在 .h，
    .cpp 里的局部变量/参数不需要 UPROPERTY）。
    """
    if not file_path_rel.endswith(".h"):
        return []

    lines = content.splitlines()
    issues: List[Issue] = []
    for m in _RE_UOBJECT_PTR_DECL.finditer(content):
        var_type = m.group(1)
        var_name = m.group(2)
        line_no = content[:m.start()].count("\n") + 1
        snippet = content[max(0, m.start() - 300):m.start()]

        if _is_skipped_by_escape(snippet, "R14"):
            continue
        if "UPROPERTY" in snippet:
            continue
        # 函数参数/声明：同一行内声明前有未闭合 '('（如 void Foo(AActor* X);）
        line_text = lines[line_no - 1] if line_no - 1 < len(lines) else ""
        before = line_text[:line_text.find(var_name)] if var_name in line_text else ""
        if before.count("(") > before.count(")"):
            continue

        issues.append({
            "rule": "R14",
            "file": file_path_rel,
            "line": line_no,
            "blocking": False,
            "category": "uproperty-missing",
            "msg": (
                f"UObject 指针成员 {var_type}* {var_name} 缺 UPROPERTY() 宏，"
                f"GC 可能回收对象导致悬挂指针"
            ),
            "suggest": (
                f"在声明上方加 UPROPERTY()；"
                f"若确认无 GC 风险可加 @ue-lint-skip R14 逃生注释"
            ),
        })
    return issues


# ==================== R15: Cast 结果未判空直接解引用 ====================

# Cast<Type>(X)-> 直接解引用。CastChecked 的 'Checked' 使 \bCast\s*< 不命中，自动排除。
_RE_CAST_DEREF = re.compile(r"\bCast\s*<\s*[^>]+\s*>\s*\([^)]*\)\s*->")


def rule_R15_cast_null_guard(
    content: str, file_path_rel: str, repo_path: Path, ctx: Dict[str, Any]
) -> List[Issue]:
    """Cast<T>(X) 结果未判空直接解引用（->）→ 空指针 / 类型不符崩溃。

    Cast 类型不符时返回 nullptr，直接 -> 解引用会崩溃。安全写法是
    `if (Type* P = Cast<Type>(X)) { P->... }` 判空后再用。

    保守策略：只报 warning。正则只匹配 Cast 后紧跟 -> 的直接解引用，
    `if (Type* P = Cast<Type>(X))` 判空写法里 Cast 后是 `)`，不命中。
    """
    if not file_path_rel.endswith((".h", ".cpp")):
        return []

    issues: List[Issue] = []
    for m in _RE_CAST_DEREF.finditer(content):
        line_no = content[:m.start()].count("\n") + 1
        snippet = content[max(0, m.start() - 200):m.start()]
        if _is_skipped_by_escape(snippet, "R15"):
            continue
        issues.append({
            "rule": "R15",
            "file": file_path_rel,
            "line": line_no,
            "blocking": False,
            "category": "cast-null-guard",
            "msg": (
                "Cast 结果未判空直接解引用（->），类型不符或对象为空时崩溃"
            ),
            "suggest": (
                "改用 if (Type* P = Cast<Type>(X)) 判空后解引用；"
                "若确信类型匹配可用 CastChecked；或加 @ue-lint-skip R15 逃生注释"
            ),
        })
    return issues


_RULE_FUNCS = [
    rule_R8_ue_file_types,   # 最高优先：先拦退化行为
    rule_R1_uclass_genbody,
    rule_R2_onrep_override,
    rule_R3_include_paths,
    rule_R4_build_cs_deps,
    # R5 按"项目级"扫，在下面单独跑
    rule_R6_include_order,
    rule_R7_type_headers,
    rule_R9_delegate_pairing,
    rule_R10_null_guard,
    rule_R11_recursive_callback,
    rule_R12_timer_pairing,
    rule_R13_weak_ptr_guard,
    rule_R14_uproperty_missing,
    rule_R15_cast_null_guard,
]


def run_all_rules(
    files_written: List[str],
    repo_path: Path,
    ctx: Optional[Dict[str, Any]] = None,
) -> List[Issue]:
    """跑全部 7 条规则，返回 Issue 列表

    Args:
        files_written: DevAgent 本次写入的文件（相对 repo 的 POSIX 路径）
        repo_path: 项目 Git 仓库根
        ctx: 可选 context，含 ue_engine_version（"5.3.2"）等

    Returns:
        按 blocking 降序排序的 issue 列表
    """
    ctx = ctx or {}
    all_issues: List[Issue] = []

    # 逐文件跑 R1/R2/R3/R4/R6/R7
    for rel in files_written or []:
        rel_norm = rel.replace("\\", "/")
        abs_path = repo_path / rel_norm
        if not abs_path.is_file():
            continue
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.debug("读 %s 失败（忽略）: %s", rel_norm, e)
            continue
        for fn in _RULE_FUNCS:
            try:
                issues = fn(content, rel_norm, repo_path, ctx)
                all_issues.extend(issues)
            except Exception as e:
                logger.warning("规则 %s 在 %s 执行异常: %s", fn.__name__, rel_norm, e)

    # R5 项目级扫一次（独立于 files_written）
    try:
        all_issues.extend(_run_R5_at_project_level(repo_path, ctx))
    except Exception as e:
        logger.warning("R5 项目级扫异常: %s", e)

    # 按 blocking 降序排
    all_issues.sort(key=lambda i: (not i.get("blocking", False), i.get("file", ""), i.get("line") or 0))
    return all_issues


def summarize(issues: List[Issue]) -> Dict[str, int]:
    """统计：blocking / warnings / rule 分布"""
    b = sum(1 for i in issues if i.get("blocking"))
    w = sum(1 for i in issues if not i.get("blocking"))
    by_rule: Dict[str, int] = {}
    for i in issues:
        r = i.get("rule", "?")
        by_rule[r] = by_rule.get(r, 0) + 1
    return {"blocking": b, "warnings": w, "total": len(issues), "by_rule": by_rule}
