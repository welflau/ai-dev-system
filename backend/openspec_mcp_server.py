"""
OpenSpec MCP Server
将 openspec-cn CLI 封装为标准 MCP tools，供 CLI 模式的 Agent（codebuddy/claude）
以**命名工具**方式调用 —— 取代"让 LLM 用原生 Bash 拼 openspec-cn 命令"。

这样 CLI 模式下 skill 声明的 openspec 能力真正被命名调用：
时间轴显示 mcp__openspec__new_change 而非裸 Bash，安全边界回到本 server。

启动方式：python openspec_mcp_server.py
env：
  OPENSPEC_REPO  — 项目仓库根（openspec/ 所在目录），命令的 cwd
  OPENSPEC_CLI   — openspec CLI 命令名（openspec-cn / openspec），默认 openspec-cn

由 llm_client._build_settings_args 通过 --mcp-config 注入给 codebuddy。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("openspec")

_REPO = os.environ.get("OPENSPEC_REPO", "")
_CLI = os.environ.get("OPENSPEC_CLI", "") or (
    "openspec-cn" if shutil.which("openspec-cn") else ("openspec" if shutil.which("openspec") else "openspec-cn")
)

# 允许写入的四件套（write_artifact 白名单）
_ARTIFACTS = {"proposal", "specs", "design", "tasks"}


def _repo() -> Path | None:
    if not _REPO:
        return None
    p = Path(_REPO)
    return p if p.is_dir() else None


async def _run(args: list[str], timeout: int = 60) -> dict:
    """在 repo cwd 下跑 openspec-cn <args>，返回 {exit_code, output}。"""
    repo = _repo()
    if not repo:
        return {"exit_code": -1, "output": "OPENSPEC_REPO 未设置或不存在"}
    cmd = f"{_CLI} " + " ".join(args)
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(repo),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return {"exit_code": -1, "output": f"超时（>{timeout}s）: {cmd}"}
        text = out.decode("utf-8", errors="replace") if out else ""
        return {"exit_code": proc.returncode if proc.returncode is not None else -1,
                "output": text[:6000]}
    except Exception as e:
        return {"exit_code": -1, "output": f"执行异常: {e}"}


@mcp.tool()
async def new_change(change_id: str, description: str = "", goal: str = "") -> str:
    """创建一个新的 OpenSpec 变更（change）目录骨架。change_id 需以字母开头、用连字符。
    开始一个新提案时先调用一次。"""
    args = ["new", "change", change_id]
    if description:
        args += ["--description", json.dumps(description, ensure_ascii=False)]
    if goal:
        args += ["--goal", json.dumps(goal, ensure_ascii=False)]
    return json.dumps(await _run(args, 60), ensure_ascii=False)


@mcp.tool()
async def instructions(change_id: str, artifact: str) -> str:
    """获取某个产出物的写作要求，或 Apply 实现指令。
    artifact 取值：proposal / specs / design / tasks / apply。
    Propose 写每一件前先调对应 artifact；实现阶段传 apply。"""
    return json.dumps(await _run(["instructions", "--change", change_id, artifact, "--json"], 60),
                      ensure_ascii=False)


@mcp.tool()
async def instructions_apply(change_id: str) -> str:
    """获取 Apply 阶段实现指令（contextFiles、任务进度、动态 instruction）。开发前必调。"""
    return json.dumps(await _run(["instructions", "apply", "--change", change_id, "--json"], 60),
                      ensure_ascii=False)


@mcp.tool()
async def write_artifact(change_id: str, artifact: str, content: str) -> str:
    """把产出物内容写入 openspec/changes/<change_id>/<artifact>.md。
    artifact 取值：proposal / specs / design / tasks。content 为纯 Markdown（不要 ``` 围栏）。"""
    if artifact not in _ARTIFACTS:
        return json.dumps({"ok": False, "error": f"artifact 必须是 {sorted(_ARTIFACTS)}"}, ensure_ascii=False)
    repo = _repo()
    if not repo:
        return json.dumps({"ok": False, "error": "OPENSPEC_REPO 未设置"}, ensure_ascii=False)
    change_dir = repo / "openspec" / "changes" / change_id
    if not change_dir.is_dir():
        return json.dumps({"ok": False, "error": f"change 目录不存在，请先 new_change: {change_id}"},
                          ensure_ascii=False)
    # 去 ``` 围栏
    s = (content or "").strip()
    if s.startswith("```"):
        nl = s.find("\n")
        if nl > 0:
            s = s[nl + 1:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3].rstrip()
    try:
        (change_dir / f"{artifact}.md").write_text(s, encoding="utf-8")
        return json.dumps({"ok": True, "artifact": artifact, "bytes": len(s)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
async def validate(change_id: str) -> str:
    """校验该 change 的四件套是否完整、格式合规。四件写完后调用。"""
    return json.dumps(await _run(["validate", change_id, "--type", "change", "--no-interactive"], 60),
                      ensure_ascii=False)


@mcp.tool()
async def status(change_id: str) -> str:
    """查看该 change 各产出物（proposal/specs/design/tasks）的完成状态（JSON）。"""
    return json.dumps(await _run(["status", "--change", change_id, "--json"], 30),
                      ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
