"""
UECompileCheckAction — 调 UnrealBuildTool 编译项目 + 结构化错误解析（v0.18 Phase A）

输入 context:
    engine_path        : 引擎根目录（优先）。未给则从 uproject 自动解析（UEEngineResolver）
    uproject_path      : .uproject 绝对路径
    target_name        : 编译 Target（默认 <ProjectName>Editor）
    target_platform    : Win64 | Linux | Mac
    target_config      : Development | Debug | Shipping | Test
    timeout_seconds    : 超时秒（默认 600，首次可能要 2-5 分钟）
    sop_config         : 来自 SOP fragment 的 config dict，内含 timeout_seconds / max_retries

输出 data:
    {
      "status": "success" | "error",
      "exit_code": int,
      "duration_ms": int,
      "command": "...",           # 实际执行的命令
      "errors": [
        {
          "file": "path\\to\\file.h",
          "line": 42,
          "column": 10 | null,
          "code": "C2065" | "LNK2019" | "UHT" | null,
          "category": "compile" | "link" | "uht" | "ubt" | "unknown",
          "severity": "error",
          "msg": "..."
        }
      ],
      "warnings": [...同结构..],
      "raw_head": "stdout 开头 ~8KB",
      "raw_tail": "stdout 末尾 ~8KB",
      "products": [...],          # 编译产物（.dll/.exe）
      "engine_used": {path, version, type}
    }

降级：Agent 返回 status=error → orchestrator 已有的 BLOCKED + 自动诊断链接管。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from actions.base import ActionBase, ActionResult
from engines.ue_resolver import (
    UEEngineInfo,
    get_ubt_path,
    resolve_project_engine,
    verify_engine,
)

logger = logging.getLogger("actions.ue_compile_check")


# ==================== 错误解析 ====================

# MSVC C++ 编译错误：file(line): error CXXXX: msg
_RE_MSVC_COMPILE = re.compile(
    r"^(?P<file>[A-Za-z]:[\\/][^(]+?)\((?P<line>\d+)(?:,\s*(?P<col>\d+))?\)\s*:\s*"
    r"(?P<sev>error|warning|fatal error)\s+(?P<code>[A-Za-z]+\d+)\s*:\s*(?P<msg>.+)$"
)

# UHT / 通用 UE 构建错误：file(line): Error: msg  (无 code)
_RE_UHT_UBT = re.compile(
    r"^(?P<file>[A-Za-z]:[\\/][^(]+?)\((?P<line>\d+)\)\s*:\s*"
    r"(?P<sev>Error|Warning|FATAL)\s*:\s*(?P<msg>.+)$"
)

# C# 编译器消息（.Target.cs/.Build.cs）：file(line,col): warning CS0618: msg
_RE_CSHARP = re.compile(
    r"^(?P<file>[A-Za-z]:[\\/][^(]+?\.cs)\((?P<line>\d+),(?P<col>\d+)\)\s*:\s*"
    r"(?P<sev>error|warning)\s+(?P<code>CS\d+)\s*:\s*(?P<msg>.+)$"
)

# 链接器错误：无 file:line，形如 "foo.obj : error LNK2019: unresolved ..."
# 或 "error LNK1120: N unresolved externals"
_RE_LINKER = re.compile(
    r"(?P<file>\S+\.(?:obj|lib|exe|dll))?\s*:\s*"
    r"(?P<sev>error|fatal error)\s+(?P<code>LNK\d+)\s*:\s*(?P<msg>.+)$",
    re.IGNORECASE,
)

# UBT 自身错误（无文件位置）：ERROR: msg 或 UnrealBuildTool: ERROR: msg
_RE_UBT_GENERIC = re.compile(
    r"^(?:UnrealBuildTool:\s*)?(?P<sev>ERROR|Error)\s*:\s*(?P<msg>.+)$"
)


def _parse_ubt_output(text: str) -> Tuple[List[Dict], List[Dict]]:
    """扫 UBT 全部输出（stdout 合并 stderr），返回 (errors, warnings)。

    同一行可能被多条规则匹配，只接受第一条（规则顺序决定优先级）。
    """
    errors: List[Dict] = []
    warnings: List[Dict] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # C# 优先（.cs 扩展名明确，避免被 MSVC 通用正则抢走）
        m = _RE_CSHARP.match(line)
        if m:
            sev = m.group("sev").lower()
            entry = {
                "file": m.group("file"),
                "line": int(m.group("line")),
                "column": int(m.group("col")),
                "code": m.group("code"),
                "category": "csharp",
                "severity": sev,
                "msg": m.group("msg"),
            }
            (errors if entry["severity"] == "error" else warnings).append(entry)
            continue

        # MSVC C++ 编译
        m = _RE_MSVC_COMPILE.match(line)
        if m:
            sev = m.group("sev").lower()
            entry = {
                "file": m.group("file"),
                "line": int(m.group("line")),
                "column": int(m.group("col")) if m.group("col") else None,
                "code": m.group("code"),
                "category": "compile",
                "severity": "error" if "error" in sev else "warning",
                "msg": m.group("msg"),
            }
            (errors if entry["severity"] == "error" else warnings).append(entry)
            continue

        # UHT / 通用 UE 错误
        m = _RE_UHT_UBT.match(line)
        if m:
            sev = m.group("sev").lower()
            entry = {
                "file": m.group("file"),
                "line": int(m.group("line")),
                "column": None,
                "code": "UHT",
                "category": "uht",
                "severity": "error" if "error" in sev or "fatal" in sev else "warning",
                "msg": m.group("msg"),
            }
            (errors if entry["severity"] == "error" else warnings).append(entry)
            continue

        # 链接器
        m = _RE_LINKER.match(line)
        if m:
            entry = {
                "file": m.group("file") or None,
                "line": None,
                "column": None,
                "code": m.group("code"),
                "category": "link",
                "severity": "error",
                "msg": m.group("msg"),
            }
            errors.append(entry)
            continue

        # UBT 自身错误（放最后，兜底）
        m = _RE_UBT_GENERIC.match(line)
        if m:
            msg = m.group("msg")
            # 过滤掉 UE 自家日志的 "Error: some word is fine"（只收明显的错误语气）
            if len(msg) < 10:
                continue
            entry = {
                "file": None,
                "line": None,
                "column": None,
                "code": None,
                "category": "ubt",
                "severity": "error",
                "msg": msg,
            }
            errors.append(entry)
            continue

    return errors, warnings


# ==================== Action ====================


class UECompileCheckAction(ActionBase):
    """调 UBT 编译 UE 项目 + 解析错误"""

    available_for_traits = {"any_of": ["engine:ue5", "engine:ue4"]}

    @property
    def name(self) -> str:
        return "ue_compile_check"

    @property
    def description(self) -> str:
        return "调 UnrealBuildTool 编译 UE 项目，产出结构化编译错误列表"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        sop_cfg = context.get("sop_config") or {}
        timeout_seconds = int(
            context.get("timeout_seconds")
            or sop_cfg.get("timeout_seconds")
            or 600
        )

        uproject_path = context.get("uproject_path") or context.get("uproject")
        engine_path = context.get("engine_path") or context.get("ue_engine_path")

        # 未显式指定 uproject → 从项目 Git 仓库根扫 *.uproject 自动探测
        if not uproject_path:
            project_id = context.get("project_id")
            if project_id:
                try:
                    from git_manager import git_manager
                    repo_path = git_manager._repo_path(project_id)
                    if repo_path and Path(repo_path).is_dir():
                        found = sorted(Path(repo_path).glob("*.uproject"))
                        if found:
                            uproject_path = str(found[0])
                            logger.info("🔍 自动探测到 .uproject: %s", uproject_path)
                except Exception as e:
                    logger.warning("自动探测 .uproject 失败: %s", e)
        target_name = context.get("target_name") or context.get("ue_target_name")
        platform = (context.get("target_platform")
                    or context.get("ue_target_platform")
                    or "Win64")
        config_name = (context.get("target_config")
                       or context.get("ue_target_config")
                       or "Development")

        # 1. 解析引擎
        engine_info: Optional[UEEngineInfo] = None
        if engine_path:
            engine_info = verify_engine(engine_path)
        elif uproject_path:
            engine_info = resolve_project_engine(uproject_path)
        else:
            return _err("缺少 engine_path 和 uproject_path，无法定位 UE 引擎")

        if not engine_info or not engine_info.path:
            return _err(
                "无法定位 UE 引擎。请在项目设置里配置 ue_engine_path，或确保 "
                ".uproject 的 EngineAssociation 对应的版本已安装",
                detail={"uproject_path": uproject_path, "engine_path_tried": engine_path},
            )

        if not engine_info.has_ubt:
            return _err(
                f"引擎 {engine_info.path} 缺 UnrealBuildTool.exe。"
                f"若是自编译 build，需先运行 GenerateProjectFiles.bat + 编引擎",
                detail={"engine": engine_info.to_dict()},
            )

        ubt = get_ubt_path(engine_info.path)
        if not ubt:
            return _err(f"UBT 路径计算失败: {engine_info.path}")

        # 2. uproject 验证
        if not uproject_path:
            return _err("缺 uproject_path")
        up = Path(uproject_path)
        if not up.is_file():
            return _err(f".uproject 不存在: {up}")

        # 3. 推断 target_name
        if not target_name:
            target_name = _infer_target_name(up, prefer_editor=True)
            if not target_name:
                return _err(
                    "无法推断 target_name。请在项目设置里配置，或确保 "
                    f"Source/ 下有 <ProjectName>(Editor).Target.cs"
                )

        # 4. 组装命令
        cmd = [
            str(ubt),
            target_name,
            platform,
            config_name,
            str(up),
            "-waitmutex",
            "-NoHotReload",
        ]
        cmd_str = " ".join(f'"{c}"' if " " in c else c for c in cmd)
        logger.info("🔧 UBT 命令: %s", cmd_str)

        # 5. 执行
        t0 = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,   # 合并
            )
        except FileNotFoundError:
            return _err(f"启动 UBT 失败: {ubt} 不存在或权限不足")
        except Exception as e:
            return _err(f"启动 UBT 异常: {e}")

        try:
            stdout_bytes, _ = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            duration_ms = int((time.time() - t0) * 1000)
            return _err(
                f"UBT 超时（{timeout_seconds}s）",
                detail={"duration_ms": duration_ms, "command": cmd_str,
                        "engine_used": engine_info.to_dict()},
            )

        duration_ms = int((time.time() - t0) * 1000)
        text = stdout_bytes.decode("utf-8", errors="replace")
        exit_code = proc.returncode if proc.returncode is not None else -1

        # 6. 解析
        errors, warnings = _parse_ubt_output(text)

        # 7. 找产物
        products = _find_build_products(up.parent, target_name, platform, config_name)

        # 8. 打包结果
        head = text[:8192]
        tail = text[-8192:] if len(text) > 8192 else ""
        status = "success" if exit_code == 0 and not errors else "error"

        logger.info(
            "🔧 UBT done: exit=%d errors=%d warnings=%d duration=%.1fs",
            exit_code, len(errors), len(warnings), duration_ms / 1000.0,
        )

        data: Dict[str, Any] = {
            "status": status,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "command": cmd_str,
            "errors": errors,
            "warnings": warnings,
            "raw_head": head,
            "raw_tail": tail,
            "products": products,
            "engine_used": {
                "path": engine_info.path,
                "version": engine_info.version,
                "type": engine_info.type,
            },
            "target_name": target_name,
            "target_platform": platform,
            "target_config": config_name,
        }

        msg = (
            f"编译通过（耗时 {duration_ms // 1000}s）"
            if status == "success"
            else f"编译失败（{len(errors)} 个 error, {len(warnings)} 个 warning）"
        )
        return ActionResult(
            success=(status == "success"),
            data=data,
            message=msg,
        )


# ==================== 辅助 ====================


def _err(msg: str, detail: Optional[Dict] = None) -> ActionResult:
    data = {"status": "error", "errors": [], "warnings": [], "message": msg}
    if detail:
        data.update(detail)
    return ActionResult(success=False, data=data, message=msg, error=msg)


def _infer_target_name(uproject: Path, prefer_editor: bool = True) -> Optional[str]:
    """从 Source/ 里找 <Name>(Editor).Target.cs 推断默认 target。

    注意：.Target.cs 是双点后缀，Path.stem 只剥一层只能剩 '<Name>.Target'，
    必须手动剥 '.Target.cs' 才能拿到纯名字。
    """
    src = uproject.parent / "Source"
    if not src.is_dir():
        return None
    candidates: List[str] = []
    for f in src.glob("*.Target.cs"):
        name = f.name
        if name.endswith(".Target.cs"):
            candidates.append(name[: -len(".Target.cs")])

    if not candidates:
        return None
    # 优先 Editor target（开发态编译，支持热重载）
    if prefer_editor:
        for c in candidates:
            if c.endswith("Editor"):
                return c
    # 回退到第一个非 Editor target（Game/Client/Server）
    for c in candidates:
        if not c.endswith("Editor"):
            return c
    return candidates[0]


def _find_build_products(
    project_dir: Path,
    target_name: str,
    platform: str,
    config: str,
) -> List[str]:
    """扫常见产物位置，仅列出文件名供日志展示"""
    binaries = project_dir / "Binaries" / platform
    if not binaries.is_dir():
        return []
    # Editor build 的 .dll；Game build 的 .exe
    prods = []
    for p in binaries.glob(f"*{target_name}*"):
        if p.suffix.lower() in (".exe", ".dll", ".pdb"):
            prods.append(str(p.relative_to(project_dir)).replace("\\", "/"))
    return sorted(prods)[:10]
