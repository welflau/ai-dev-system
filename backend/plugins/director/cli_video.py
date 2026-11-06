"""LibTV / dreamina CLI 执行。参数用 argv 列表，不走 shell 字符串。"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from plugins.director.backends import ProbeResult, probe_backend, which_binary

logger = logging.getLogger("plugins.director.cli_video")

_SUBMIT_RE = re.compile(
    r"(submit_id|task_id|taskId|nodeId|node_id)[\"'\s:=]+([A-Za-z0-9_-]+)",
    re.I,
)


async def run_cli(
    argv: Sequence[str],
    *,
    cwd: str = "",
    timeout: int = 120,
) -> Tuple[int, str, str]:
    """跑一条已解析的 argv。timeout 秒。不使用 shell=True。"""
    if not argv:
        return 1, "", "空命令"
    try:
        proc = await asyncio.create_subprocess_exec(
            *list(argv),
            cwd=cwd or None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return 124, "", f"CLI 超时 {timeout}s: {' '.join(argv[:4])}"
        out = (out_b or b"").decode("utf-8", errors="replace")
        err = (err_b or b"").decode("utf-8", errors="replace")
        return int(proc.returncode or 0), out, err
    except FileNotFoundError:
        return 127, "", f"找不到可执行文件: {argv[0]}"
    except Exception as e:
        return 1, "", str(e)


def _parse_submit_id(*texts: str) -> str:
    blob = "\n".join(texts)
    m = _SUBMIT_RE.search(blob)
    if m:
        return m.group(2)
    m2 = re.search(r"\b([0-9a-f]{8,}-[0-9a-f-]+)\b", blob, re.I)
    return m2.group(1) if m2 else ""


def _newest_mp4(folder: Path) -> Optional[Path]:
    files = [p for p in folder.glob("*.mp4") if p.is_file() and p.stat().st_size > 0]
    if not files:
        files = [p for p in folder.rglob("*.mp4") if p.is_file() and p.stat().st_size > 0]
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


async def generate_dreamina(
    *,
    dest: Path,
    prompt: str,
    duration: int,
    ratio: str,
    resolution: str,
    ref_images: List[str],
    ref_audio: List[str],
    session: str = "",
    model: str = "seedance2.0fast",
) -> Tuple[bool, Dict[str, Any], str]:
    probe: ProbeResult = probe_backend("dreamina")
    if not probe.available:
        return False, {"env_missing": True, "backend": "dreamina", "command": probe.command}, probe.hint

    binary = probe.binary or which_binary("dreamina")
    sub = "multimodal2video" if (ref_images or ref_audio) else "text2video"
    argv: List[str] = [
        binary, sub,
        f"--prompt={prompt}",
        f"--duration={int(duration)}",
        f"--video_resolution={resolution}",
        f"--model_version={model or 'seedance2.0fast'}",
        "--poll=30",
    ]
    if session:
        argv.append(f"--session={session}")
    if sub == "text2video" and ratio:
        argv.append(f"--ratio={ratio}")
    for img in ref_images:
        argv.extend(["--image", img])
    for aud in ref_audio:
        argv.extend(["--audio", aud])

    command = " ".join(argv[:6]) + " …"
    logger.info("🎬 dreamina 提交 %s → %s", sub, dest.name)
    code, out, err = await run_cli(argv, cwd=str(dest.parent), timeout=900)
    submit_id = _parse_submit_id(out, err)
    if code not in (0, 124) and not submit_id:
        return False, {
            "backend": "dreamina",
            "command": command,
            "task_id": "",
            "stderr": (err or out)[-1500:],
        }, err.strip() or out.strip() or f"dreamina 退出码 {code}"

    if submit_id:
        q = [
            binary, "query_result",
            f"--submit_id={submit_id}",
            f"--download_dir={str(dest.parent)}",
        ]
        qcode, qout, qerr = await run_cli(q, cwd=str(dest.parent), timeout=600)
        out += "\n" + qout
        err += "\n" + qerr
        if qcode != 0 and not _newest_mp4(dest.parent):
            return False, {
                "backend": "dreamina",
                "command": " ".join(q),
                "task_id": submit_id,
                "stderr": (qerr or qout)[-1500:],
            }, qerr.strip() or "dreamina query_result 失败"

    found = _newest_mp4(dest.parent)
    if found is None:
        return False, {
            "backend": "dreamina",
            "command": command,
            "task_id": submit_id,
        }, "dreamina 未下载到非空 mp4，不写空文件"

    if found.resolve() != dest.resolve():
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        shutil.move(str(found), str(dest))
    if dest.stat().st_size <= 0:
        dest.unlink(missing_ok=True)
        return False, {"backend": "dreamina", "command": command, "task_id": submit_id}, "下载文件为空"
    return True, {
        "backend": "dreamina",
        "command": command,
        "task_id": submit_id,
        "model": model or "seedance2.0fast",
        "path": str(dest),
        "bytes": dest.stat().st_size,
    }, ""


async def generate_libtv(
    *,
    dest: Path,
    prompt: str,
    project_uuid: str = "",
) -> Tuple[bool, Dict[str, Any], str]:
    """LibTV 画布节点流程依赖实时 schema。这里只探测 + 拒绝静默改后端。

    有 CLI 但没有 projectUuid 时停止，并给出下一步；不把历史 `libtv node`
    命令当唯一真相去硬跑。
    """
    probe = probe_backend("libtv")
    data = {"backend": "libtv", "command": probe.command, "env_missing": not probe.available}
    if not probe.available:
        return False, data, probe.hint

    code, out, err = await run_cli(
        [probe.binary, "version"], cwd=str(dest.parent), timeout=20,
    )
    data["probe_exit"] = code
    data["probe_out"] = (out or err)[:500]
    if not project_uuid:
        return False, data, (
            "LibTV 已安装，但未提供 libtv_project / projectUuid。"
            "画布未绑定不得生成，也不会改打 LightAI。"
            "请在本机按当前 `libtv --help` 绑定画布后再试，或改用 backend=lightai。"
        )
    return False, data, (
        "LibTV 生成必须按当前安装版本的实时 schema 建节点，"
        "本插件不代跑过期的 `libtv node` 快照。"
        f"已探测到 {probe.binary}（project={project_uuid}）。"
        "请在本机完成节点生成后用 download_video 拉回，或改用 dreamina / lightai。"
    )
