"""对 Phaser / TS 仓库跑 ``tsc --noEmit``，并附 Phaser API 误用提示。

不自动 npm install，不启 Vite。缺 tsconfig / 缺 tsc 时返回 status=error。
类型错误返回 status=typecheck_failed（给 SOP reject_goto，不要 blocked）。
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.h5_typecheck")

_RE_TSC = re.compile(
    r"^(?P<file>.+?)\((?P<line>\d+),(?P<col>\d+)\):\s*"
    r"(?P<sev>error|warning)\s+(?P<code>TS\d+):\s*(?P<msg>.+)$"
)


def parse_tsc_output(raw: str) -> List[Dict[str, Any]]:
    errors: List[Dict[str, Any]] = []
    for line in (raw or "").splitlines():
        m = _RE_TSC.match(line.strip())
        if not m:
            continue
        errors.append({
            "file": m.group("file").replace("\\", "/"),
            "line": int(m.group("line")),
            "column": int(m.group("col")),
            "code": m.group("code"),
            "severity": m.group("sev"),
            "msg": m.group("msg").strip(),
        })
    return errors


def phaser_api_hints(errors: List[Dict[str, Any]]) -> List[str]:
    hints: List[str] = []
    seen: set = set()
    for err in errors:
        msg = err.get("msg") or ""
        code = err.get("code") or ""
        if "'on'" in msg and "TimerEvent" in msg and "TimerEvent.on" not in seen:
            seen.add("TimerEvent.on")
            hints.append(
                "TimerEvent 没有 .on()。用 this.time.delayedCall(ms, cb) "
                "或 this.time.addEvent({ delay, callback, loop })。"
            )
        if "createEmitter" in msg and "particles.createEmitter" not in seen:
            seen.add("particles.createEmitter")
            hints.append(
                "Phaser 3.60+ 粒子：this.add.particles(x, y, textureKey, config)，"
                "不要再用 createEmitter。"
            )
        if (
            "does not exist" in msg
            and ("Body | StaticBody" in msg or "Body | null" in msg)
            and "body-type" not in seen
        ):
            seen.add("body-type")
            hints.append("物理 body 在类里声明：body!: Phaser.Physics.Arcade.Body;")
        if "possibly 'null'" in msg and "keyboard" in msg and "keyboard-null" not in seen:
            seen.add("keyboard-null")
            hints.append("keyboard 可能为 null：this.input.keyboard!.createCursorKeys()")
        if (
            ("'save'" in msg or "'restore'" in msg)
            and "Graphics" in msg
            and "graphics-save" not in seen
        ):
            seen.add("graphics-save")
            hints.append("Phaser Graphics 没有 save()/restore()，直接 fillStyle。")
        if (
            code == "TS2415" or "not assignable to the same property" in msg
        ) and "ts2415" not in seen:
            seen.add("ts2415")
            hints.append(
                "TS2415：子类字段与 Phaser mixin 冲突（originX/alpha/visible 等），"
                "自定义字段加前缀。"
            )
        if "Cannot find module 'phaser'" in msg and "phaser-mod" not in seen:
            seen.add("phaser-mod")
            hints.append("找不到 phaser：在仓库根目录执行 npm install。")
    return hints


def resolve_tsc_cmd(repo: Path) -> Optional[List[str]]:
    bin_name = "tsc.cmd" if os.name == "nt" else "tsc"
    local = repo / "node_modules" / ".bin" / bin_name
    if local.is_file():
        return [str(local), "--noEmit", "-p", str(repo)]
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx:
        return [npx, "--yes", "tsc", "--noEmit", "-p", str(repo)]
    return None


class H5TypecheckAction(ActionBase):
    available_for_traits = {"any_of": ["framework:phaser"]}

    @property
    def name(self) -> str:
        return "h5_typecheck"

    @property
    def description(self) -> str:
        return "对 Phaser + TypeScript 仓库跑 tsc --noEmit，并给出常见 API 误用提示"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        repo = context.get("repo_path") or context.get("target_dir")
        if not repo:
            return ActionResult(
                success=False,
                data={"status": "error"},
                message="缺 repo_path",
                error="缺 repo_path",
            )
        root = Path(repo)
        if not (root / "tsconfig.json").is_file():
            return ActionResult(
                success=False,
                data={"status": "error"},
                message="仓库没有 tsconfig.json，先跑 instantiate_h5_template",
                error="仓库没有 tsconfig.json",
            )

        cmd = resolve_tsc_cmd(root)
        if not cmd:
            return ActionResult(
                success=False,
                data={"status": "error"},
                message="找不到 tsc / npx，请安装 Node.js 或在仓库执行 npm install",
                error="tsc not found",
            )

        timeout = int((context.get("sop_config") or {}).get("timeout_seconds") or
                      context.get("timeout_seconds") or 90)
        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            raw_b, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            return ActionResult(
                success=False,
                data={"status": "error", "command": cmd},
                message=f"tsc 超时（{timeout}s）",
                error="tsc timeout",
            )
        except FileNotFoundError:
            return ActionResult(
                success=False,
                data={"status": "error", "command": cmd},
                message="无法启动 tsc / npx",
                error="tsc spawn failed",
            )

        duration_ms = int((time.monotonic() - t0) * 1000)
        raw = (raw_b or b"").decode("utf-8", errors="replace")
        errors = [e for e in parse_tsc_output(raw) if e["severity"] == "error"]
        warnings = [e for e in parse_tsc_output(raw) if e["severity"] == "warning"]
        hints = phaser_api_hints(errors)
        data = {
            "exit_code": proc.returncode,
            "duration_ms": duration_ms,
            "command": cmd,
            "errors": errors[:40],
            "warnings": warnings[:20],
            "hints": hints,
            "raw_tail": raw[-4000:],
        }
        if proc.returncode == 0 and not errors:
            data["status"] = "success"
            return ActionResult(success=True, data=data, message="tsc 通过")

        data["status"] = "typecheck_failed"
        brief = "; ".join(
            f"{e['file']}:{e['line']} {e['code']} {e['msg'][:60]}"
            for e in errors[:3]
        ) or (raw[:200] if raw else "tsc 失败且无法解析错误")
        return ActionResult(
            success=False,
            data=data,
            message=f"tsc 失败 · {len(errors)} errors · {brief}",
            error=brief,
        )
