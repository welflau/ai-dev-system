"""Skill IO MCP Server —— 让 CLI 模式的 Agent 能命名调用 skill 的 builtin 工具。

## 为什么需要它

`QueryEngine.run` 的 CLI 分支**根本不传 tools**（见
`tests/skills/test_cli_mode_tool_gap.py` 的三条证据）。于是 CLI 模式下：
  - skill 声明的 write_file / read_file / gen_image 对 LLM 不可见
  - CLI 用原生 Write，相对路径基于 cwd(=仓库根)，而 skill 的产出目录在
    `artifacts/{req}/{ticket}/{kind}/`
  - `_collect_outputs` 扫不到 → 一律 partial，且无任何报错

CLI 能命名调用的只有 MCP 工具（`mcp__<server>__<tool>`）。本 server 把
skill 的 builtin 工具包成 MCP，**LLM 只给文件名，路径由 server 用环境变量
自己拼** —— 和 `openspec_mcp_server.write_artifact` 同一套路数。

## 为什么 LLM 不该碰路径

`outputs.root` 是 SkillRunner 按模板渲染的（含 req_short / ticket_short），
LLM 既不知道也不该知道。让它传路径等于把「产出落在哪」的决定权交出去 ——
那正是 CLI 原生 Write 出问题的原因。

启动：python skills/skill_io_mcp_server.py
env：
  SKILL_OUTPUT_ROOT   产出目录绝对路径（write_output 的根，必填）
  SKILL_REPO          仓库根绝对路径（read_repo_file 的根）
  SKILL_ALLOWED_EXTS  写入扩展名白名单，逗号分隔，默认 .md
  SKILL_IMAGE_SUBDIR  gen_image 的子目录（对应 builtin_tools 的 gen_image:xxx）
  SKILL_BACKEND_DIR   backend 目录（import image_processor 用）

由 llm_client._build_settings_args 条件注入。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("skill_io")

_OUTPUT_ROOT = os.environ.get("SKILL_OUTPUT_ROOT", "")
_REPO = os.environ.get("SKILL_REPO", "")
_IMAGE_SUBDIR = (os.environ.get("SKILL_IMAGE_SUBDIR", "") or "").strip("/")
_BACKEND_DIR = os.environ.get("SKILL_BACKEND_DIR", "")
_KNOWLEDGE_ROOT = os.environ.get("SKILL_KNOWLEDGE_ROOT", "")
_WRITE_MODE = (os.environ.get("SKILL_WRITE_MODE") or "").strip().lower()
_SKILL_TOOLS = {
    t.split(":", 1)[0].strip()
    for t in (os.environ.get("SKILL_TOOLS") or "").split(",")
    if t.strip()
}
_KNOWLEDGE_PREFIX = "director-knowledge/"

_DEFAULT_EXTS = (".md",)
_ALLOWED_EXTS = tuple(
    e.strip().lower() for e in (os.environ.get("SKILL_ALLOWED_EXTS") or "").split(",")
    if e.strip()
) or _DEFAULT_EXTS

# 文件名白名单：不含路径分隔符，只允许常规字符
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")

# 读文件的大小上限 —— 超过就截断，避免把一个 50MB 的 log 塞进 LLM 上下文
_READ_MAX_CHARS = 60_000

# 生图后端一旦失败，本 MCP 进程内禁止再试 / 发确认卡
_IMAGE_BLOCKED_ERROR: str | None = None
_IMAGE_BLOCK_STOP = (
    "生图后端失败，已停止本 skill 的生图。"
    "禁止重试 gen_image，禁止 confirm_video_gate。"
    "写完已有文本后立即 done，工单转人工处理（检查 LIGHTAI_API_KEY / 引擎）。"
)


def _image_block_err() -> str | None:
    global _IMAGE_BLOCKED_ERROR
    if _IMAGE_BLOCKED_ERROR:
        return _IMAGE_BLOCKED_ERROR
    root = _output_root()
    if root is None:
        return None
    try:
        if _BACKEND_DIR and _BACKEND_DIR not in sys.path:
            sys.path.insert(0, _BACKEND_DIR)
        from actions.gen_image import read_image_blocked_marker
        hit = read_image_blocked_marker(root)
        if hit:
            _IMAGE_BLOCKED_ERROR = str(hit.get("error") or _IMAGE_BLOCK_STOP)
            return _IMAGE_BLOCKED_ERROR
    except Exception:
        return None
    return None


def _mark_image_blocked(error: str) -> None:
    global _IMAGE_BLOCKED_ERROR
    _IMAGE_BLOCKED_ERROR = error
    root = _output_root()
    if root is None:
        return
    try:
        if _BACKEND_DIR and _BACKEND_DIR not in sys.path:
            sys.path.insert(0, _BACKEND_DIR)
        from actions.gen_image import write_image_blocked_marker
        write_image_blocked_marker(root, error)
    except Exception:
        pass


def _err(msg: str, **extra) -> str:
    return json.dumps({"ok": False, "error": msg, **extra}, ensure_ascii=False)


def _ok(**data) -> str:
    return json.dumps({"ok": True, **data}, ensure_ascii=False)


def _output_root() -> Path | None:
    if not _OUTPUT_ROOT:
        return None
    return Path(_OUTPUT_ROOT).resolve()


def _safe_name(raw: str, exts: tuple) -> str | None:
    """文件名校验。**拒绝而非改名** —— 改名会让 produces 的 glob 匹配不上，
    LLM 以为成功了但产物回收是空的，整个 stage 判 partial 却看不出原因。"""
    name = (raw or "").strip()
    if not name or "/" in name or "\\" in name or ".." in name:
        return None
    if not _SAFE_NAME_RE.match(name):
        return None
    if not name.lower().endswith(exts):
        return None
    return name


def _strip_fences(text: str) -> str:
    """去掉 LLM 偶尔套的 ```lang ... ``` 围栏。

    与 `actions/write_file._strip_fences` 同语义，但本 server 是独立进程
    （MCP 走 stdio），不能 import backend 模块树 —— 所以这里重写一份简版。
    复杂的位置判断（content_sanitizer）留在 Action 侧。
    """
    s = (text or "").strip()
    if s.startswith("```"):
        nl = s.find("\n")
        if nl > 0:
            s = s[nl + 1:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3].rstrip()
    return s


# ════════════════════════ 工具 ════════════════════════

@mcp.tool()
async def write_output(filename: str, content: str) -> str:
    """把内容写入本次 skill 的产出目录。

    filename 只能是**不含路径**的文件名（如 outline.md）—— 产出目录由
    框架决定，不要自己拼路径、不要用原生 Write 工具。
    content 为纯文本（Markdown 等），不要加 ``` 围栏。
    """
    root = _output_root()
    if root is None:
        return _err("SKILL_OUTPUT_ROOT 未设置，本次 skill 未声明 outputs.root")

    name = _safe_name(filename, _ALLOWED_EXTS)
    if not name:
        return _err(
            f"filename 非法: {filename!r}。只能是不含路径的文件名，"
            f"且扩展名须是 {list(_ALLOWED_EXTS)}"
        )
    if content is None:
        return _err("content 不能为空")

    target = (root / name).resolve()
    try:
        target.relative_to(root)          # 兜底：root 本身是符号链接等情况
    except ValueError:
        return _err(f"路径越界: {name}")

    try:
        root.mkdir(parents=True, exist_ok=True)
        cleaned = _strip_fences(str(content))
        target.write_text(cleaned, encoding="utf-8")
        return _ok(filename=name, bytes=len(cleaned.encode("utf-8")))
    except Exception as e:
        return _err(f"写入失败: {e}", filename=name)


def _tool_enabled(name: str) -> bool:
    if not _SKILL_TOOLS:
        return True
    return name in _SKILL_TOOLS


def resolve_read_target(path: str) -> tuple[Path | None, str]:
    """解析 read_repo_file 路径。导演知识用 director-knowledge/ 前缀。

    返回 (target, error)。error 非空表示失败。
    """
    rel = (path or "").strip().replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return None, f"path 非法: {path!r}"
    if rel.startswith(_KNOWLEDGE_PREFIX):
        root_raw = _KNOWLEDGE_ROOT
        if not root_raw:
            return None, (
                "未配置导演知识目录。不要搜索 D:\\A_Works\\director 或 "
                "~/.codebuddy/projects，知识只走 director-knowledge/ 前缀。"
            )
        root = Path(root_raw).resolve()
        target = (root / rel[len(_KNOWLEDGE_PREFIX):]).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return None, f"路径越出知识目录: {rel}"
        return target, ""
    if not _REPO:
        return None, "SKILL_REPO 未设置"
    repo = Path(_REPO).resolve()
    if not repo.is_dir():
        return None, f"仓库目录不存在: {_REPO}"
    target = (repo / rel).resolve()
    try:
        target.relative_to(repo)
    except ValueError:
        return None, f"路径越出仓库: {rel}"
    return target, ""


def _ensure_backend_path() -> str:
    if _BACKEND_DIR and _BACKEND_DIR not in sys.path:
        sys.path.insert(0, _BACKEND_DIR)
    return _BACKEND_DIR


def _action_context(extra: dict | None = None) -> dict:
    ctx = {
        "repo_path": _REPO,
        "project_id": os.environ.get("SKILL_PROJECT_ID") or "",
        "ticket_id": os.environ.get("SKILL_TICKET_ID") or "",
        "ticket_title": os.environ.get("SKILL_TICKET_TITLE") or "",
        "requirement_id": os.environ.get("SKILL_REQUIREMENT_ID") or "",
        "session_id": os.environ.get("SKILL_SESSION_ID") or "",
        "skill_id": os.environ.get("SKILL_SKILL_ID") or os.environ.get("SKILL_ID") or "",
        "_skill_output_root": _OUTPUT_ROOT,
    }
    if extra:
        ctx.update(extra)
    return ctx


async def _ensure_db() -> None:
    """MCP 是独立进程，confirm_video_gate 写确认卡前要先连上同一份 DB。"""
    _ensure_backend_path()
    try:
        from database import db
        if getattr(db, "_db", None) is None:
            await db.connect()
    except Exception as e:
        logger = __import__("logging").getLogger("skill_io_mcp")
        logger.warning("skill_io 连接 DB 失败，确认卡可能写不进对话: %s", e)


async def _run_backend_action(name: str, extra: dict | None = None) -> str:
    if not _tool_enabled(name):
        return _err(f"本次 skill 未声明工具 {name}")
    _ensure_backend_path()
    await _ensure_db()
    try:
        from plugins.registry import create_action
        action = create_action(name)
    except Exception as e:
        return _err(f"无法加载 {name}（SKILL_BACKEND_DIR={_BACKEND_DIR}）: {e}")
    if action is None:
        return _err(f"未注册的工具: {name}")
    try:
        res = await action.run(_action_context(extra))
    except Exception as e:
        return _err(f"{name} 异常: {e}")
    if not res.success:
        return _err(res.error or f"{name} 失败", **(res.data or {}))
    payload = dict(res.data or {})
    if res.message:
        payload.setdefault("message", res.message)
    return _ok(**payload)


def _parse_path_list(raw: str) -> list[str]:
    s = (raw or "").strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            val = json.loads(s)
            if isinstance(val, list):
                return [str(x) for x in val if str(x).strip()]
        except Exception:
            pass
    return [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]


@mcp.tool()
async def read_repo_file(path: str) -> str:
    """读取仓库文件，或导演知识（path 以 director-knowledge/ 开头）。

    仓库文件：相对仓库根，如 artifacts/abc/def/content_outline/outline.md。
    导演知识：director-knowledge/modes/cinematic-drama/workflow.md
    不要搜索 D:\\A_Works\\director 或 ~/.codebuddy/projects。
    """
    rel = (path or "").strip().replace("\\", "/").lstrip("/")
    target, err = resolve_read_target(path)
    if err:
        return _err(err)
    assert target is not None
    if not target.is_file():
        return _err(f"文件不存在: {rel}")

    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return _err(
            f"{rel} 不是 UTF-8 文本（可能是图片/音视频），无法读取内容",
            size=target.stat().st_size,
        )
    except Exception as e:
        return _err(f"读取失败: {e}", path=rel)

    truncated = len(text) > _READ_MAX_CHARS
    return _ok(
        path=rel,
        content=text[:_READ_MAX_CHARS],
        truncated=truncated,
        total_chars=len(text),
    )


@mcp.tool()
async def gen_image(
    prompt: str,
    filename: str,
    aspect_ratio: str = "16:9",
    image_size: str = "2K",
) -> str:
    """根据文字描述生成一张图片，保存到产出目录。

    单次调用耗时 30-300 秒并且花钱，**不要为同一张图重复调用**。
    prompt 用英文，包含：主体 / 风格 / 构图 / 光线。
    filename 须以 .png / .jpg / .webp 结尾，不含路径。
    """
    blocked = _image_block_err()
    if blocked:
        return _err(f"{_IMAGE_BLOCK_STOP} {blocked}", image_blocked=True)

    root = _output_root()
    if root is None:
        return _err("SKILL_OUTPUT_ROOT 未设置")

    name = _safe_name(filename, _IMAGE_EXTS)
    if not name:
        return _err(
            f"filename 非法: {filename!r}。只能是不含路径的图片文件名，如 cover.png"
        )
    if not (prompt or "").strip():
        return _err("prompt 不能为空")

    # 复用 backend 的 GenImageAction —— 参数校验、零字节检测、引擎回退
    # 都在那里，不要在 MCP 侧重写一份（两份实现迟早漂）。
    if _BACKEND_DIR and _BACKEND_DIR not in sys.path:
        sys.path.insert(0, _BACKEND_DIR)
    try:
        from actions.gen_image import GenImageAction
    except Exception as e:
        return _err(f"无法加载 GenImageAction（SKILL_BACKEND_DIR={_BACKEND_DIR}）: {e}")

    try:
        res = await GenImageAction(subdir=_IMAGE_SUBDIR).run({
            "_skill_output_root": str(root),
            "prompt": prompt,
            "filename": name,
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
        })
    except Exception as e:
        return _err(f"生图异常: {e}")

    if not res.success:
        err = res.error or "生图失败"
        if (res.data or {}).get("image_blocked"):
            _mark_image_blocked(err)
            return _err(f"{_IMAGE_BLOCK_STOP} {err}", image_blocked=True)
        return _err(err)
    return _ok(**(res.data or {}), message=res.message)


@mcp.tool()
async def list_outputs() -> str:
    """列出产出目录里已有的文件。用于确认自己写了什么、避免重复产出。"""
    root = _output_root()
    if root is None:
        return _err("SKILL_OUTPUT_ROOT 未设置")
    if not root.is_dir():
        return _ok(files=[], note="产出目录尚未创建")
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            files.append({
                "path": p.relative_to(root).as_posix(),
                "bytes": p.stat().st_size,
            })
    return _ok(files=files)


if _WRITE_MODE == "repo":
    @mcp.tool()
    async def write_repo_file(path: str, content: str) -> str:
        """把内容写入仓库相对路径。导演 skill 用 works/<slug>/video_brief.json。

        不要用原生 Write。path 相对仓库根，禁止 ..。
        """
        if _WRITE_MODE and _WRITE_MODE != "repo":
            return _err("本次 skill 不是仓库写入模式，请用 write_output")
        if not _tool_enabled("write_file"):
            return _err("本次 skill 未声明 write_file")
        _ensure_backend_path()
        try:
            from actions.write_file import WriteFileAction
            res = await WriteFileAction(
                allowed_exts=list(_ALLOWED_EXTS) or None,
                write_mode="repo",
            ).run(_action_context({"path": path, "content": content}))
        except Exception as e:
            return _err(f"写入失败: {e}")
        if not res.success:
            return _err(res.error or "写入失败")
        return _ok(**(res.data or {}), message=res.message)


if _tool_enabled("init_work_package"):
    @mcp.tool()
    async def init_work_package(title: str = "", slug: str = "") -> str:
        """为当前片子创建 works/<slug>/ 工作包。已存在则复用，不覆盖。"""
        return await _run_backend_action("init_work_package", {
            "title": title, "slug": slug,
        })


if _tool_enabled("confirm_video_gate"):
    @mcp.tool()
    async def confirm_video_gate(
        title: str,
        summary: str = "",
        preview_paths: str = "",
        work_slug: str = "",
        mode: str = "",
        gate: str = "",
    ) -> str:
        """制作产物落盘后发出人审确认卡，然后停止。preview_paths 逗号分隔。"""
        blocked = _image_block_err()
        if blocked:
            return _err(f"{_IMAGE_BLOCK_STOP} {blocked}", image_blocked=True)
        return await _run_backend_action("confirm_video_gate", {
            "title": title,
            "summary": summary,
            "preview_paths": _parse_path_list(preview_paths),
            "work_slug": work_slug,
            "mode": mode,
            "gate": gate,
        })


if _tool_enabled("probe_backend"):
    @mcp.tool()
    async def probe_backend(backend: str = "") -> str:
        """探测 LightAI / LibTV / 即梦是否可用。不可用就停，不要换后端。"""
        return await _run_backend_action("probe_backend", {"backend": backend})


if _tool_enabled("gen_video"):
    @mcp.tool()
    async def gen_video(
        prompt: str,
        filename: str,
        duration: int = 15,
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
        backend: str = "",
        engine: str = "",
        work_slug: str = "",
        mode: str = "",
        first_frame: str = "",
        last_frame: str = "",
        ref_images: str = "",
    ) -> str:
        """生成一段视频并下载到 works/<slug>/video/。阻塞到完成，不要为同一段重复调用。"""
        extra = {
            "prompt": prompt,
            "filename": filename,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "work_slug": work_slug,
            "mode": mode,
            "first_frame": first_frame,
            "last_frame": last_frame,
            "ref_images": _parse_path_list(ref_images),
        }
        if backend:
            extra["backend"] = backend
        if engine:
            extra["engine"] = engine
        return await _run_backend_action("gen_video", extra)


if _tool_enabled("gen_video_batch"):
    @mcp.tool()
    async def gen_video_batch(
        clips: str,
        work_slug: str = "",
        backend: str = "",
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
    ) -> str:
        """按 shot_prompts 批量生成片段 2 及之后。clips 为 JSON 数组 [{filename, prompt, duration?}]。"""
        parsed = clips
        if isinstance(clips, str):
            try:
                parsed = json.loads(clips)
            except Exception:
                return _err("clips 必须是 JSON 数组")
        extra = {
            "clips": parsed,
            "work_slug": work_slug,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        }
        if backend:
            extra["backend"] = backend
        return await _run_backend_action("gen_video_batch", extra)


if _tool_enabled("download_video"):
    @mcp.tool()
    async def download_video(
        filename: str,
        url: str = "",
        task_id: str = "",
        work_slug: str = "",
    ) -> str:
        """平台已成功但本地文件丢失时，按 url 或 task_id 补下载。"""
        return await _run_backend_action("download_video", {
            "filename": filename, "url": url, "task_id": task_id, "work_slug": work_slug,
        })


if _tool_enabled("check_mode_assets"):
    @mcp.tool()
    async def check_mode_assets(
        gate: str = "", work_slug: str = "", mode: str = "",
    ) -> str:
        """按 Mode 检查当前工作包资产是否齐。"""
        return await _run_backend_action("check_mode_assets", {
            "gate": gate, "work_slug": work_slug, "mode": mode,
        })


@mcp.tool()
async def done(summary: str = "") -> str:
    """所有步骤已完成、产出文件都已写好时调用，结束本次 skill。"""
    return _ok(done=True, summary=summary or "")


if __name__ == "__main__":
    mcp.run()
