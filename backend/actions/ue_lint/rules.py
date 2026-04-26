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
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from actions.ue_lint.data import (
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
        # 如果在本模块根目录里（不是 Public/Private 子目录），UE 默认能 include
        # 如果在子目录里，必须写子目录前缀
        if found_in_module:
            paths = module_headers[header_name]
            # 把 module root 下的 Public/Private 视为"直接可 include"的锚点
            public = module_root / "Public"
            private = module_root / "Private"
            ok = False
            for p in paths:
                try:
                    # Public / Private 根目录下的直接文件 = OK
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
                # 头文件在 Public 或 Private 的**子目录**里 → 给出正确路径建议
                first = paths[0]
                # 相对 Public 或 Private 的子路径
                suggest = None
                for anchor in (module_root / "Public", module_root / "Private"):
                    if anchor.exists():
                        try:
                            rel = first.resolve().relative_to(anchor.resolve())
                            suggest = rel.as_posix()
                            break
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
                        f"{file_path_rel}:{i} #include \"{inc}\" 在本模块同级找不到；"
                        f"文件位于 {first.relative_to(repo_path).as_posix()}"
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

        # 彻底找不到
        issues.append({
            "rule": "R3",
            "file": file_path_rel,
            "line": i,
            "blocking": True,
            "category": "include-not-found",
            "msg": f"{file_path_rel}:{i} #include \"{inc}\" 找不到头文件",
            "suggest": None,
        })

    return issues


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
            issues.append({
                "rule": "R7",
                "file": file_path_rel,
                "line": line_no,
                "blocking": True,
                "category": "missing-type-header",
                "msg": (
                    f"{file_path_rel}:{line_no} 使用了 {tname} 但未 #include \"{required_header}\"。"
                    f"编译会报 C2027 (undefined type)"
                ),
                "suggest": f'文件顶部加 #include "{required_header}"',
            })
    return issues


# ==================== 主入口 ====================


_RULE_FUNCS = [
    rule_R1_uclass_genbody,
    rule_R2_onrep_override,
    rule_R3_include_paths,
    rule_R4_build_cs_deps,
    # R5 按"项目级"扫，在下面单独跑
    rule_R6_include_order,
    rule_R7_type_headers,
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
