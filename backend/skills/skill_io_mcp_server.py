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


@mcp.tool()
async def read_repo_file(path: str) -> str:
    """读取仓库里的一个文本文件。

    path 是**相对仓库根**的路径（如 artifacts/abc/def/content_outline/outline.md）。
    上游产物的路径会在 system prompt 的「上游产物」小节给出，直接照抄即可。
    """
    if not _REPO:
        return _err("SKILL_REPO 未设置")
    repo = Path(_REPO).resolve()
    if not repo.is_dir():
        return _err(f"仓库目录不存在: {_REPO}")

    rel = (path or "").strip().replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return _err(f"path 非法: {path!r}")

    target = (repo / rel).resolve()
    try:
        target.relative_to(repo)
    except ValueError:
        return _err(f"路径越出仓库: {rel}")
    if not target.is_file():
        return _err(f"文件不存在: {rel}")

    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # 二进制文件没法给 LLM 看 —— 明说，而不是返回乱码
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
        return _err(res.error or "生图失败")
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


if __name__ == "__main__":
    mcp.run()
