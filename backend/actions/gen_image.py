"""GenImageAction — 给 SkillRunner 里的 LLM 用的生图工具。

## 为什么不复用 image_requests 那条异步流

`image_processor.process_image_request` 服务的是「文档先写、图后补」：
写一个 `[IMG_PENDING:id]` 占位符进文档 → 后台轮询 → 出图后回填占位符。

skill 链的语义是**产物必须在 stage 结束时就绪** —— 下一个 skill 的 consumes
会立刻去读文件。占位符那套会让下游拿到一个还没有图的路径。

所以这里只复用底层三个函数（`_create_lightai_task` / `_poll_lightai_task` /
`_download_image`），**阻塞等待直到出图**，不碰 image_requests 表。

## 为什么阻塞而不是返回 request_id 让 LLM 自己轮询

REACT 循环是单线程顺序推理。返回 request_id 会逼 LLM 自己写「查状态 → 没好
→ 再查」的循环，每次查询烧一轮 turn，而且很容易卡死在「再查一次」。

`_poll_lightai_task` 内部是 `await asyncio.sleep` 的非阻塞 IO，不卡事件循环。
代价是占 skill 的 `budget.max_seconds` —— 用 gen_image 的 skill 要把预算调到
600+。Budget.check() 只在轮与轮之间生效（query_engine/budget.py:39），所以
一次生图跑完回来下一轮开头就可能触发超时；orchestrator 的 SkillAgent 分支对
「超预算但 produces 齐全」做了豁免，见 `_skill_produces_satisfied`。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.7
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.gen_image")

# 与 image_processor._ENGINE_CONFIG 的 key 一致
_ENGINES = ("gemini", "gemini2", "jimeng", "midjourney")

# LightAI 只支持这几种比例（见 LightAI 公开技能文档）
_ASPECT_RATIOS = ("1:1", "16:9", "9:16", "4:3", "3:4", "2:3", "3:2", "21:9")

_SIZES = ("1K", "2K", "4K")

# 文件名白名单：只允许图片扩展名，且不含路径分隔符
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")

IMAGE_BLOCKED_MARKER = ".ads-image-blocked.json"
IMAGE_BLOCK_STOP = (
    "生图后端失败，已停止本 skill 的生图。"
    "禁止重试 gen_image，禁止 confirm_video_gate。"
    "写完已有文本后立即 done，工单转人工处理（检查 LIGHTAI_API_KEY / 引擎）。"
)


def write_image_blocked_marker(
    root: Path, error: str, extra: Optional[Dict[str, Any]] = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "image_gen_blocked",
        "image_blocked": True,
        "needs_human": True,
        "error": error,
        **(extra or {}),
    }
    path = root / IMAGE_BLOCKED_MARKER
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def read_image_blocked_marker(root: Optional[Path]) -> Optional[Dict[str, Any]]:
    if root is None:
        return None
    base = Path(root)
    paths = [base / IMAGE_BLOCKED_MARKER]
    if base.is_dir():
        paths.extend(sorted(base.glob(f"*/{IMAGE_BLOCKED_MARKER}")))
    for path in paths:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and (
            data.get("image_blocked") or data.get("needs_human")
        ):
            return data
    return None


def clear_image_blocked_markers(root: Optional[Path]) -> int:
    """恢复工单重跑 visual 前清掉生图阻塞标记，否则新一轮仍会拒绝 gen_image。"""
    if root is None:
        return 0
    base = Path(root)
    paths = [base / IMAGE_BLOCKED_MARKER]
    if base.is_dir():
        paths.extend(base.glob(f"*/{IMAGE_BLOCKED_MARKER}"))
    n = 0
    for path in paths:
        try:
            if path.is_file():
                path.unlink()
                n += 1
        except OSError:
            continue
    return n


class GenImageAction(ActionBase):
    """文生图。产出落在 skill 的 outputs.root 下，由 _collect_outputs 回收。"""

    def __init__(self, subdir: str = ""):
        # subdir 让 skill 能把图归到 outputs.root 下的子目录（如 images/），
        # 配合 `globs: ["images/*.png"]` 一次产出多张归同一 kind
        self._subdir = subdir.strip().strip("/")

    @property
    def name(self) -> str:
        return "gen_image"

    @property
    def description(self) -> str:
        return (
            "根据文字描述生成一张图片并保存到产出目录。"
            "单次调用耗时 30-300 秒（取决于引擎），会阻塞到出图为止，"
            "不要为同一张图重复调用。prompt 要具体：主体 + 风格 + 构图 + 光线。"
        )

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "图片描述（英文效果更好）。主体 + 风格 + 构图 + 光线",
                    },
                    "filename": {
                        "type": "string",
                        "description": "保存的文件名，须以 .png/.jpg/.webp 结尾，如 cover.png",
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "enum": list(_ASPECT_RATIOS),
                        "description": "画面比例，默认 16:9",
                    },
                    "image_size": {
                        "type": "string",
                        "enum": list(_SIZES),
                        "description": "分辨率档位，默认 2K",
                    },
                },
                "required": ["prompt", "filename"],
            },
        }

    # ──────────────────────── 参数校验 ────────────────────────

    def _resolve_dir(self, context: Dict[str, Any]) -> Optional[Path]:
        """产出目录 = skill 的 outputs.root（+ subdir）。

        与 WriteFileAction 共用 `_skill_output_root` 约定（runner.py:execute
        会把渲染好的 root 塞进 context）。没有它说明 skill 没声明 outputs.root，
        此时不该随便往仓库里写二进制文件。
        """
        root_raw = context.get("_skill_output_root")
        if not root_raw:
            return None
        root = Path(root_raw).resolve()
        return (root / self._subdir).resolve() if self._subdir else root

    @staticmethod
    def _safe_filename(raw: str) -> Optional[str]:
        """文件名来自 LLM，必须严格校验。

        只取 basename 不够 —— 还要挡住 `..`、路径分隔符、非图片扩展名。
        返回 None 表示拒绝（而不是悄悄改名，那会让 produces 的 glob 匹配不上，
        LLM 以为成功了但产物回收是空的）。
        """
        name = (raw or "").strip()
        if not name or "/" in name or "\\" in name or ".." in name:
            return None
        if not _SAFE_NAME_RE.match(name):
            return None
        if not name.lower().endswith(_IMAGE_EXTS):
            return None
        return name

    def _fail_blocked(
        self, out_dir: Path, error: str, extra: Optional[Dict[str, Any]] = None,
    ) -> ActionResult:
        data = {"image_blocked": True, "needs_human": True, **(extra or {})}
        try:
            write_image_blocked_marker(out_dir, error, extra)
            if self._subdir:
                write_image_blocked_marker(out_dir.parent, error, extra)
        except Exception as e:
            logger.warning("写入生图阻塞标记失败: %s", e)
        return ActionResult(success=False, error=error, data=data)

    # ──────────────────────── 执行 ────────────────────────

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        prompt = (context.get("prompt") or "").strip()
        if not prompt:
            return ActionResult(success=False, error="prompt 不能为空")

        filename = self._safe_filename(context.get("filename") or "")
        if not filename:
            return ActionResult(
                success=False,
                error=(f"filename 非法: {context.get('filename')!r}。"
                       f"只能是不含路径的图片文件名，如 cover.png"),
            )

        out_dir = self._resolve_dir(context)
        if out_dir is None:
            return ActionResult(
                success=False,
                error="缺少产出目录（skill 需在 x-runner.outputs.root 声明）",
            )

        from config import settings
        if not settings.LIGHTAI_API_KEY:
            # 明确报缺配置，而不是让 LightAI 返回 401 后变成「生成失败」
            return self._fail_blocked(out_dir, "LIGHTAI_API_KEY 未配置，无法生图")

        engine = str(context.get("engine")
                     or settings.LIGHTAI_IMAGE_ENGINE or "gemini")
        if engine not in _ENGINES:
            logger.warning("未知引擎 %s，回退 gemini", engine)
            engine = "gemini"

        aspect_ratio = str(context.get("aspect_ratio") or "16:9")
        if aspect_ratio not in _ASPECT_RATIOS:
            aspect_ratio = "16:9"
        image_size = str(context.get("image_size") or "2K")
        if image_size not in _SIZES:
            image_size = "2K"

        from image_processor import _create_and_poll, _download_image

        req = {
            "prompt": prompt,
            "engine": engine,
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
        }

        logger.info("🎨 gen_image 开始 engine=%s file=%s prompt=%.60s",
                    engine, filename, prompt)

        task_id, url = await _create_and_poll(req)
        extra = {"engine": engine, "filename": filename}
        if not task_id:
            # `_create_lightai_task` 把异常吞成 None，真实原因只在它的
            # logger.warning 里。给出可自查的方向 —— 常见的是 401（key 过期）
            # 或 429 重试耗尽（并发任务超时）。
            return self._fail_blocked(
                out_dir,
                f"LightAI 任务创建失败（engine={engine}）。常见原因："
                f"①LIGHTAI_API_KEY 无效或过期（HTTP 401）②网络不通 "
                f"③引擎 {engine} 不可用 ④并发任务等待超时（HTTP 429）。"
                f"精确错误见 image_processor 的 WARNING 日志",
                extra,
            )
        if not url:
            # 区分「超时」与「任务失败」对排查很重要，但 _poll_lightai_task
            # 两种情况都返回 None，只能在这里统一描述
            return self._fail_blocked(
                out_dir,
                f"LightAI 任务未产出图片（task={task_id}, engine={engine}）"
                f"—— 可能超时或被内容策略拒绝",
                extra,
            )

        saved = await _download_image(url, out_dir, filename)
        if not saved:
            return self._fail_blocked(
                out_dir, f"图片下载失败: {url[:120]}", extra,
            )

        path = Path(saved)
        size = path.stat().st_size if path.is_file() else 0
        if size == 0:
            # 下载成功但零字节 —— 让它失败，否则 _collect_outputs 会回收一个
            # 空文件当成功产出，下游 consumes 拿到坏图
            return self._fail_blocked(
                out_dir, f"下载的图片为空文件: {filename}", extra,
            )

        logger.info("🎨 gen_image 完成 %s (%d bytes)", filename, size)
        return ActionResult(
            success=True,
            data={"filename": filename, "size_bytes": size, "engine": engine},
            message=(f"已生成图片 {filename}（{size // 1024}KB, {engine}, "
                     f"{aspect_ratio}）。不要重复生成同一张图。"),
        )
