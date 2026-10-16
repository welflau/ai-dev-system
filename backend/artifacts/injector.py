"""consumes 注入 —— 把上游产物接到下游 skill 的执行上下文里。

这是 `produces → consumes` 数据通路的**消费端**：组装器按 kind 把 skill 排好序，
但「上一个 skill 产出的文件，下一个 skill 怎么拿到」要靠这里。

注入策略：**路径为主 + 提示自取**。
system prompt 里只给路径和大小，让 LLM 用 read_file 工具自己读。不把全文塞进去，
因为：
  - 二进制产物（图/音/视频）根本塞不进 prompt
  - 大文件会挤爆 token 预算，而 skill 往往只需要其中一部分
  - LLM 自己读能按需截取，比我们猜它要哪段准

mode=text 是例外（小文件且必读时用），上限 8000 字符。

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.6
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from artifacts.store import ArtifactRef, artifact_store

logger = logging.getLogger("artifacts.injector")

# mode=text 时单个产物注入 prompt 的字符上限
TEXT_INJECT_MAX_CHARS = 8000


def _norm_consume(spec: Any) -> Optional[Dict[str, Any]]:
    """归一化一条 consumes 声明。

    支持两种写法（x-workflow schema 的简写）：
        - content_outline                       → required=True, mode=path
        - {kind: ..., required: false, mode: text}
    """
    if isinstance(spec, str):
        return {"kind": spec, "required": True, "mode": "path"}
    if isinstance(spec, dict) and spec.get("kind"):
        mode = str(spec.get("mode") or "path")
        if mode not in ("path", "text", "both"):
            logger.warning("consumes mode 非法: %r，退回 path", mode)
            mode = "path"
        return {
            "kind": str(spec["kind"]),
            "required": bool(spec.get("required", True)),
            "mode": mode,
        }
    logger.warning("跳过无效 consumes 声明: %r", spec)
    return None


async def build_consume_context(
    consumes: List[Any],
    *,
    project_id: str,
    ticket_id: str,
    repo_path: str,
    requirement_id: str = "",
) -> Dict[str, Any]:
    """按 consumes 声明把上游产物查出来，组装成 context 片段。

    返回：
        {
          "_artifacts": {kind: {path, abs_path, mime, size, artifact_id,
                                created_at, text?}},
          "_artifacts_missing": [kind, ...],       # 含可选的
          "_artifacts_missing_required": [kind, ...],
        }

    **不因缺失而报错**。required 的缺失由调用方（SkillAgent）决定怎么办 ——
    组装期的「缺源」检查已经剔除了无 producer 的 skill，运行期还缺通常意味着
    上游 skipped 或失败，那时让 LLM 看到「缺什么」比直接 abort 更有用。
    """
    specs = [s for s in (_norm_consume(c) for c in consumes or []) if s]
    if not specs:
        return {"_artifacts": {}, "_artifacts_missing": [],
                "_artifacts_missing_required": []}

    wanted = [s["kind"] for s in specs]
    # 一次查完所有 kind，latest_per_kind 保证同 kind 多次产出取最新
    # （返工重跑会在同路径覆盖文件并插新行，created_at 倒序首条即当前有效版本）
    refs = await artifact_store.list(
        ticket_id=ticket_id, kinds=wanted, latest_per_kind=True,
        repo_path=repo_path,
    )
    by_kind: Dict[str, ArtifactRef] = {r.kind: r for r in refs}

    # 工单级没找到 → 退到需求级找（跨工单共享的产物，如 style_guide）
    still_missing = [k for k in wanted if k not in by_kind]
    if still_missing and requirement_id:
        req_refs = await artifact_store.list(
            requirement_id=requirement_id, kinds=still_missing,
            latest_per_kind=True, repo_path=repo_path,
        )
        for r in req_refs:
            by_kind.setdefault(r.kind, r)

    artifacts: Dict[str, Dict[str, Any]] = {}
    missing: List[str] = []
    missing_required: List[str] = []

    for spec in specs:
        kind = spec["kind"]
        ref = by_kind.get(kind)
        if ref is None:
            missing.append(kind)
            if spec["required"]:
                missing_required.append(kind)
            continue

        entry: Dict[str, Any] = {
            "artifact_id": ref.id,
            "path": ref.rel_path,
            "abs_path": ref.abs_path,
            "mime": ref.mime,
            "size": ref.size,
            "created_at": ref.created_at,
            "produced_by": ref.produced_by,
        }
        if spec["mode"] in ("text", "both"):
            entry["text"] = await artifact_store.read_text(
                ref, max_chars=TEXT_INJECT_MAX_CHARS
            )
        artifacts[kind] = entry

    if missing_required:
        logger.warning(
            "consumes 缺必需产物 ticket=%s kinds=%s —— skill 将在缺失状态下执行",
            ticket_id[:12], missing_required,
        )

    return {
        "_artifacts": artifacts,
        "_artifacts_missing": missing,
        "_artifacts_missing_required": missing_required,
    }


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n / 1024 / 1024:.1f}MB"


def render_artifacts_prompt(context: Dict[str, Any]) -> str:
    """把 `_artifacts` 渲染成 system prompt 片段。

    给 SkillRunner._build_system 调。没有产物时返回空串（不要留个空标题）。
    """
    artifacts = context.get("_artifacts") or {}
    missing = context.get("_artifacts_missing") or []
    if not artifacts and not missing:
        return ""

    lines: List[str] = []

    if artifacts:
        lines.append("## 上游产物（已就绪）")
        for kind, info in artifacts.items():
            lines.append(
                f"- `{kind}`: {info['path']} "
                f"({info.get('mime') or '?'}, {_fmt_size(info.get('size') or 0)})"
            )
            text = info.get("text")
            if text:
                lines.append(f"  内容：\n```\n{text}\n```")
            else:
                # 不内联内容时必须显式告诉 LLM 怎么拿 —— 否则它会凭空编造
                lines.append("  用 `read_file` 工具读取（path 相对仓库根）")

    if missing:
        required = set(context.get("_artifacts_missing_required") or [])
        lines.append("")
        lines.append("## 缺失的上游产物")
        for kind in missing:
            tag = "**必需，但上游未产出**" if kind in required else "可选，未产出"
            lines.append(f"- `{kind}`（{tag}）")
        if required:
            lines.append(
                "缺必需产物时不要编造内容；在 `done` 的 summary 里说明缺了什么。"
            )

    return "\n".join(lines)
